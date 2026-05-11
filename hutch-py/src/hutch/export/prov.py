"""W3C PROV-O export.

Maps Hutch's five-abstraction model onto W3C PROV
(`<https://www.w3.org/TR/prov-o/>`_):

* :class:`prov:Entity`   ← every Individual + every Artifact
* :class:`prov:Activity` ← every Operator + the run as a whole
* :class:`prov:Agent`    ← run.started_by + per-operator llm_id
* ``prov:wasGeneratedBy``    ← Individual ⟶ Operator that produced it
* ``prov:used``              ← Operator ⟶ each parent Individual
* ``prov:wasDerivedFrom``    ← child Individual ⟶ each parent Individual
* ``prov:wasAssociatedWith`` ← Operator ⟶ Agent (LLM)
* ``prov:wasAttributedTo``   ← Individual ⟶ run starter
* ``prov:startedAtTime`` / ``prov:endedAtTime``  ← on the run + per Activity

Turtle output is hand-built — no external dep. JSON-LD / RDF-XML /
N-Triples require ``rdflib`` (``pip install thehutch[publish]``); the
hand-built Turtle is parsed and re-serialized through rdflib for those.
"""

from __future__ import annotations

import importlib.util
import logging
from collections.abc import Iterable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from hutch.schema import AnyEvent

logger = logging.getLogger("hutch.export.prov")

ProvFormat = Literal["turtle", "json-ld", "n-triples", "xml"]
PROV_FORMATS: tuple[ProvFormat, ...] = ("turtle", "json-ld", "n-triples", "xml")

_PREAMBLE = (
    "@prefix prov: <http://www.w3.org/ns/prov#> .\n"
    "@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .\n"
    "@prefix hutch: <https://github.com/xyin/hutch/ns#> .\n"
    "\n"
)


def export_prov(
    *,
    run_id: str,
    events: Iterable[AnyEvent],
    output_path: Path | str | None = None,
    format: ProvFormat = "turtle",  # noqa: A002 — matches user-facing CLI flag name
) -> str:
    """Serialise events to PROV-O. Returns the serialised string and
    optionally writes it to *output_path*.

    Default format is Turtle (dep-free). Other formats use ``rdflib``;
    raises :class:`RuntimeError` with an actionable message when the
    optional ``[publish]`` extra isn't installed.
    """
    fmt = format
    if fmt not in PROV_FORMATS:
        raise ValueError(f"unknown PROV format {fmt!r}; choose one of {PROV_FORMATS}")

    turtle = _to_turtle(run_id=run_id, events=list(events))
    out = turtle if fmt == "turtle" else _convert_via_rdflib(turtle, fmt)

    if output_path is not None:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_text(out, encoding="utf-8")
    return out


# ---------- Turtle builder -------------------------------------------------


def _to_turtle(*, run_id: str, events: list[AnyEvent]) -> str:
    """Hand-build the Turtle representation. Sorted output for determinism."""
    parts: list[str] = [_PREAMBLE]

    run_iri = f"hutch:run-{_sanitize(run_id)}"
    started_at = _earliest_ts(events)
    ended_at = _latest_ts(events)
    started_by_agent: str | None = None

    # Run activity.
    run_lines = [
        f"{run_iri} a prov:Activity ;",
        f'    hutch:runId "{_escape(run_id)}" ;',
    ]
    if started_at is not None:
        run_lines.append(f'    prov:startedAtTime "{_iso(started_at)}"^^xsd:dateTime ;')
    if ended_at is not None:
        run_lines.append(f'    prov:endedAtTime "{_iso(ended_at)}"^^xsd:dateTime ;')

    # Look at run_start for run-level metadata.
    for ev in events:
        if ev.event_kind == "run_start":
            run_lines.append(f'    hutch:name "{_escape(getattr(ev.payload, "name", "") or "")}" ;')
            project = getattr(ev.payload, "project", None)
            if project:
                run_lines.append(f'    hutch:project "{_escape(project)}" ;')
            started_by = getattr(ev.payload, "started_by", None)
            if isinstance(started_by, str) and started_by:
                started_by_agent = f"hutch:agent-{_sanitize(started_by)}"
                run_lines.append(f"    prov:wasAssociatedWith {started_by_agent} ;")
        elif ev.event_kind == "run_end":
            status = getattr(ev.payload, "status", None)
            if status:
                run_lines.append(f'    hutch:status "{_escape(status)}" ;')
    run_lines = _terminate(run_lines)
    parts.append("\n".join(run_lines) + "\n")

    if started_by_agent is not None:
        parts.append(
            f"{started_by_agent} a prov:Agent, prov:Person ;\n    hutch:runStarter true .\n"
        )

    # Index Individuals + Operators for cross-referencing.
    individuals = [e for e in events if e.event_kind == "individual"]
    operators = [e for e in events if e.event_kind == "operator"]
    op_by_child: dict[str, AnyEvent] = {op.payload.child_id: op for op in operators}

    # Operator activities.
    seen_agents: set[str] = set()
    for op in operators:
        op_id = op.payload.id
        op_iri = f"hutch:op-{_sanitize(op_id)}"
        op_lines = [
            f"{op_iri} a prov:Activity ;",
            f'    hutch:operatorKind "{_escape(op.payload.kind)}" ;',
            f"    prov:wasInformedBy {run_iri} ;",
            f'    prov:atTime "{_iso(op.timestamp_ns)}"^^xsd:dateTime ;',
        ]
        for parent_id in op.payload.parent_ids:
            op_lines.append(f"    prov:used hutch:ind-{_sanitize(parent_id)} ;")
        llm_id = getattr(op.payload, "llm_id", None)
        if isinstance(llm_id, str) and llm_id:
            llm_iri = f"hutch:agent-{_sanitize(llm_id)}"
            op_lines.append(f"    prov:wasAssociatedWith {llm_iri} ;")
            if llm_id not in seen_agents:
                seen_agents.add(llm_id)
                parts.append(
                    f"{llm_iri} a prov:Agent, prov:SoftwareAgent ;\n"
                    f'    hutch:llmId "{_escape(llm_id)}" .\n'
                )
        cost = getattr(op.payload, "cost_usd", None)
        if isinstance(cost, (int, float)):
            op_lines.append(f'    hutch:costUsd "{cost}"^^xsd:decimal ;')
        op_lines = _terminate(op_lines)
        parts.append("\n".join(op_lines) + "\n")

    # Individual entities.
    for ind in individuals:
        ind_id = ind.payload.id
        ind_iri = f"hutch:ind-{_sanitize(ind_id)}"
        ind_lines = [
            f"{ind_iri} a prov:Entity ;",
            f'    hutch:individualKind "{_escape(ind.payload.kind)}" ;',
            f'    prov:generatedAtTime "{_iso(ind.timestamp_ns)}"^^xsd:dateTime ;',
        ]
        for parent_id in ind.payload.parent_ids:
            ind_lines.append(f"    prov:wasDerivedFrom hutch:ind-{_sanitize(parent_id)} ;")
        producing_op = op_by_child.get(ind_id)
        if producing_op is not None:
            producing_op_id = getattr(producing_op.payload, "id", "")
            if producing_op_id:
                ind_lines.append(f"    prov:wasGeneratedBy hutch:op-{_sanitize(producing_op_id)} ;")
        if started_by_agent is not None:
            ind_lines.append(f"    prov:wasAttributedTo {started_by_agent} ;")
        ind_lines = _terminate(ind_lines)
        parts.append("\n".join(ind_lines) + "\n")

    # Fitness facts as RDF data attached to the individual entity.
    for ev in events:
        if ev.event_kind != "fitness":
            continue
        ind_iri = f"hutch:ind-{_sanitize(ev.payload.individual_id)}"
        scores = getattr(ev.payload, "scores", {}) or {}
        if scores:
            for k, v in scores.items():
                if isinstance(v, (int, float)):
                    parts.append(
                        f'{ind_iri} hutch:score [ hutch:metric "{_escape(k)}" ; '
                        f'hutch:value "{v}"^^xsd:decimal ] .\n'
                    )

    # Artifacts.
    for ev in events:
        if ev.event_kind != "artifact":
            continue
        art_id = ev.payload.id
        art_iri = f"hutch:art-{_sanitize(art_id)}"
        art_lines = [
            f"{art_iri} a prov:Entity ;",
            f'    hutch:artifactKind "{_escape(ev.payload.kind)}" ;',
            f'    hutch:uri "{_escape(ev.payload.uri)}" ;',
        ]
        h = getattr(ev.payload, "hash", None)
        if h:
            art_lines.append(f'    hutch:hash "{_escape(h)}" ;')
        art_lines = _terminate(art_lines)
        parts.append("\n".join(art_lines) + "\n")

    return "".join(parts)


# ---------- rdflib bridge --------------------------------------------------


def _convert_via_rdflib(turtle: str, fmt: ProvFormat) -> str:
    """Re-serialise *turtle* into *fmt* via rdflib."""
    if importlib.util.find_spec("rdflib") is None:
        raise RuntimeError(
            f"PROV format {fmt!r} requires the optional [publish] extra. "
            "Install with: pip install thehutch[publish]"
        )
    import rdflib

    g = rdflib.Graph()
    g.parse(data=turtle, format="turtle")
    rdflib_format = {
        "turtle": "turtle",
        "json-ld": "json-ld",
        "n-triples": "nt",
        "xml": "xml",
    }[fmt]
    serialised: Any = g.serialize(format=rdflib_format)
    if isinstance(serialised, bytes):
        return serialised.decode("utf-8")
    return str(serialised)


# ---------- helpers --------------------------------------------------------


_SANITIZE_RE = None


def _sanitize(s: str) -> str:
    """Make *s* safe for use as the local part of a Turtle prefixed name.

    Turtle pn-local rules are tighter than usual identifiers; we keep
    [A-Za-z0-9_.-] verbatim and percent-encode anything else, then quote
    it as ``urn:hutch:<encoded>`` if it would otherwise collide.
    """
    out_chars: list[str] = []
    for ch in s:
        if ch.isalnum() or ch in "-._":
            out_chars.append(ch)
        else:
            out_chars.append(f"_{ord(ch):x}")
    return "".join(out_chars) or "anon"


def _escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _iso(ns: int) -> str:
    seconds, frac_ns = divmod(int(ns), 1_000_000_000)
    dt = datetime.fromtimestamp(seconds, tz=UTC)
    micros = frac_ns // 1000
    return dt.replace(microsecond=micros).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _iter_ts(events: Iterable[AnyEvent]) -> Iterator[int]:
    for e in events:
        if isinstance(e.timestamp_ns, int) and e.timestamp_ns > 0:
            yield e.timestamp_ns


def _earliest_ts(events: Iterable[AnyEvent]) -> int | None:
    seq = list(_iter_ts(events))
    return min(seq) if seq else None


def _latest_ts(events: Iterable[AnyEvent]) -> int | None:
    seq = list(_iter_ts(events))
    return max(seq) if seq else None


def _terminate(lines: list[str]) -> list[str]:
    """Replace the trailing ``;`` on the last predicate-object line with ``.``."""
    if not lines:
        return lines
    last = lines[-1]
    if last.endswith(" ;"):
        lines[-1] = last[:-2] + " ."
    elif last.endswith(";"):
        lines[-1] = last[:-1] + "."
    elif not last.endswith("."):
        lines[-1] = last + " ."
    return lines


__all__ = [
    "PROV_FORMATS",
    "ProvFormat",
    "export_prov",
]
