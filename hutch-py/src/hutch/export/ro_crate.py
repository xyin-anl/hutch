"""Workflow Run RO-Crate packager.

Builds a directory conforming to the Workflow Run RO-Crate profile
(`<https://www.researchobject.org/workflow-run-crate/>`_)::

    <output_dir>/
    ├── ro-crate-metadata.json    # the JSON-LD manifest
    └── data/
        └── events.jsonl          # the canonical event log

The manifest is a Schema.org / RO-Crate JSON-LD graph with one
``CreateAction`` per Operator, ``Dataset`` entries for the run + each
artifact, and the canonical ``conformsTo`` profile URLs.

Dep-free: RO-Crate is just JSON-LD; we hand-build the graph.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hutch import __version__
from hutch.schema import AnyEvent

logger = logging.getLogger("hutch.export.ro_crate")

RO_CRATE_PROFILE = (
    "https://w3id.org/ro/crate/1.1",
    "https://w3id.org/workflowhub/workflow-ro-crate/1.0",
    "https://w3id.org/ro/wfrun/process/0.5",
)
"""Profile URLs we declare ``conformsTo``. The Process Run Crate profile
v0.5 is the closest fit for an autoresearch run — it captures one
``CreateAction`` per executed step and supports nested objects."""


def export_ro_crate(
    *,
    run_id: str,
    events: Iterable[AnyEvent],
    output_dir: Path | str,
) -> Path:
    """Write an RO-Crate at *output_dir* and return the resolved path.

    The output directory is created if missing. Inside it:

    * ``ro-crate-metadata.json``  — the JSON-LD manifest (root)
    * ``data/events.jsonl``       — the run's canonical event log

    Returns the path to the created directory. The caller can zip it for
    distribution; we don't presume a packaging step.
    """
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    data_dir = target / "data"
    data_dir.mkdir(exist_ok=True)

    event_list = list(events)
    events_path = data_dir / "events.jsonl"
    with events_path.open("w", encoding="utf-8") as fh:
        for ev in event_list:
            fh.write(ev.model_dump_json() + "\n")

    manifest = _build_manifest(run_id=run_id, events=event_list)
    (target / "ro-crate-metadata.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=False) + "\n", encoding="utf-8"
    )
    return target


def _build_manifest(*, run_id: str, events: list[AnyEvent]) -> dict[str, Any]:
    started = _earliest_ts(events) or 0
    ended = _latest_ts(events) or started
    started_iso = _iso(started)
    ended_iso = _iso(ended)
    name = run_id
    description: str | None = None
    project: str | None = None
    started_by: str | None = None
    for ev in events:
        if ev.event_kind == "run_start":
            name_v = getattr(ev.payload, "name", None)
            if isinstance(name_v, str) and name_v:
                name = name_v
            project = getattr(ev.payload, "project", None)
            description = getattr(ev.payload, "started_by", None)  # rough
            started_by = getattr(ev.payload, "started_by", None)
        if ev.event_kind == "run_end":
            summary = getattr(ev.payload, "summary", None)
            if isinstance(summary, str) and summary:
                description = summary

    graph: list[dict[str, Any]] = []

    # Root: ro-crate-metadata.json descriptor
    graph.append(
        {
            "@id": "ro-crate-metadata.json",
            "@type": "CreativeWork",
            "conformsTo": [{"@id": p} for p in RO_CRATE_PROFILE],
            "about": {"@id": "./"},
        }
    )

    # Root dataset = the run itself
    root_part_ids: list[dict[str, str]] = [{"@id": "data/events.jsonl"}]
    has_part_ids: list[dict[str, str]] = list(root_part_ids)

    # Per-operator CreateAction entries.
    individuals_seen: dict[str, str] = {}
    for ev in events:
        if ev.event_kind == "individual":
            ind_id = ev.payload.id
            ind_iri = f"#ind/{ind_id}"
            individuals_seen[ind_id] = ind_iri
            graph.append(
                {
                    "@id": ind_iri,
                    "@type": "Dataset",
                    "name": ind_id,
                    "additionalType": ev.payload.kind,
                    "hutchKind": "Individual",
                    "isBasedOn": [
                        {"@id": individuals_seen.get(p, f"#ind/{p}")} for p in ev.payload.parent_ids
                    ],
                }
            )
            has_part_ids.append({"@id": ind_iri})

    op_iris: list[str] = []
    for ev in events:
        if ev.event_kind == "operator":
            op_id = ev.payload.id
            op_iri = f"#op/{op_id}"
            op_iris.append(op_iri)
            graph.append(
                {
                    "@id": op_iri,
                    "@type": "CreateAction",
                    "name": f"{ev.payload.kind} {op_id}",
                    "hutchOperatorKind": ev.payload.kind,
                    "object": [
                        {"@id": individuals_seen.get(p, f"#ind/{p}")} for p in ev.payload.parent_ids
                    ],
                    "result": [
                        {
                            "@id": individuals_seen.get(
                                ev.payload.child_id, f"#ind/{ev.payload.child_id}"
                            )
                        }
                    ],
                    **(
                        {"hutchCostUsd": ev.payload.cost_usd}
                        if isinstance(getattr(ev.payload, "cost_usd", None), (int, float))
                        else {}
                    ),
                    **(
                        {"instrument": {"@id": f"#agent/{ev.payload.llm_id}"}}
                        if isinstance(getattr(ev.payload, "llm_id", None), str)
                        and ev.payload.llm_id
                        else {}
                    ),
                    "endTime": _iso(ev.timestamp_ns),
                }
            )
            has_part_ids.append({"@id": op_iri})

    # Artifact entries.
    for ev in events:
        if ev.event_kind == "artifact":
            art_id = ev.payload.id
            art_iri = f"#art/{art_id}"
            graph.append(
                {
                    "@id": art_iri,
                    "@type": "Dataset",
                    "name": art_id,
                    "additionalType": ev.payload.kind,
                    "hutchKind": "Artifact",
                    "url": ev.payload.uri,
                    **(
                        {"identifier": ev.payload.hash} if getattr(ev.payload, "hash", None) else {}
                    ),
                }
            )
            has_part_ids.append({"@id": art_iri})

    # Agents (LLMs).
    seen_llms: set[str] = set()
    for ev in events:
        if ev.event_kind == "operator":
            llm = getattr(ev.payload, "llm_id", None)
            if isinstance(llm, str) and llm and llm not in seen_llms:
                seen_llms.add(llm)
                graph.append(
                    {
                        "@id": f"#agent/{llm}",
                        "@type": "SoftwareApplication",
                        "name": llm,
                    }
                )

    # Person entry for run.started_by.
    if isinstance(started_by, str) and started_by:
        graph.append(
            {
                "@id": f"#agent/{started_by}",
                "@type": "Person",
                "name": started_by,
            }
        )
        root_creator = [{"@id": f"#agent/{started_by}"}]
    else:
        root_creator = []

    # Root Dataset entry (the crate itself).
    root: dict[str, Any] = {
        "@id": "./",
        "@type": "Dataset",
        "name": name,
        "datePublished": ended_iso,
        "dateCreated": started_iso,
        "hutchRunId": run_id,
        "hutchSchemaVersion": __version__,
        "hasPart": has_part_ids,
    }
    if description:
        root["description"] = description
    if project:
        root["hutchProject"] = project
    if root_creator:
        root["creator"] = root_creator

    # The events.jsonl file as a File entity.
    graph.append(
        {
            "@id": "data/events.jsonl",
            "@type": "File",
            "name": "events.jsonl",
            "encodingFormat": "application/x-ndjson",
            "description": "Canonical Hutch event log for this run.",
        }
    )

    # Insert the root last so all #ind/#op/#art entries it points to exist.
    graph.insert(1, root)
    return {
        "@context": "https://w3id.org/ro/crate/1.1/context",
        "@graph": graph,
    }


# ---------- helpers --------------------------------------------------------


def _iter_ts(events: Iterable[AnyEvent]) -> list[int]:
    return [
        e.timestamp_ns for e in events if isinstance(e.timestamp_ns, int) and e.timestamp_ns > 0
    ]


def _earliest_ts(events: Iterable[AnyEvent]) -> int | None:
    seq = _iter_ts(events)
    return min(seq) if seq else None


def _latest_ts(events: Iterable[AnyEvent]) -> int | None:
    seq = _iter_ts(events)
    return max(seq) if seq else None


def _iso(ns: int) -> str:
    seconds, frac_ns = divmod(int(ns), 1_000_000_000)
    dt = datetime.fromtimestamp(seconds, tz=UTC)
    micros = frac_ns // 1000
    return dt.replace(microsecond=micros).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


__all__ = [
    "RO_CRATE_PROFILE",
    "export_ro_crate",
]
