"""OpenEvolve checkpoint adapter.

Reads OpenEvolve's on-disk checkpoint layout and emits canonical Hutch events.
The format is documented in
https://github.com/codelion/openevolve and on disk looks like::

    <checkpoint_path>/
        metadata.json          # islands, island_feature_maps, archive, ...
        programs/
            <program_id>.json  # one record per program (Program.to_dict())
        artifacts/
            <program_id>/      # optional large blobs

Per program the adapter emits, in order:

* :class:`IndividualEvent` (kind=``program``) with parent linkage, generation,
  island assignment, and OpenEvolve-specific metadata in the ``metadata`` dict.
* :class:`OperatorEvent` (kind=``refine``) when a parent is recorded — OpenEvolve
  doesn't preserve the original mutation/crossover label in checkpoints, so
  ``refine`` is the safest canonical choice; the LLM diff (if any) lands in
  the operator's ``metadata``.
* :class:`FitnessEvent` for each program with non-empty ``metrics``.
* :class:`DescriptorEvent` derived from ``island_feature_maps`` if both the
  cell key and the dimension hints are recoverable.

The adapter is permissive about missing fields per the project-wide
"render gracefully on partial data" rule — anything OpenEvolve didn't
serialize simply doesn't emit the corresponding event.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

from hutch.schema import (
    AnyEvent,
    DescriptorEvent,
    DescriptorPayload,
    FitnessEvent,
    FitnessPayload,
    IndividualEvent,
    IndividualPayload,
    OperatorEvent,
    OperatorPayload,
    RunEndEvent,
    RunEndPayload,
    RunStartEvent,
    RunStartPayload,
)

logger = logging.getLogger("hutch.adapters.openevolve")


def detect(path: Path) -> bool:
    """Return ``True`` when *path* looks like an OpenEvolve checkpoint."""
    return (path / "metadata.json").is_file() and (path / "programs").is_dir()


def import_openevolve(
    path: str | Path,
    *,
    run_id: str | None = None,
    project: str | None = None,
    finalize: bool = True,
) -> Iterator[AnyEvent]:
    """Yield canonical events for the OpenEvolve checkpoint at *path*."""
    root = Path(path)
    if not detect(root):
        raise ValueError(
            f"{root} doesn't look like an OpenEvolve checkpoint "
            f"(no metadata.json or programs/ directory)."
        )
    metadata = _load_metadata(root)
    programs = list(_load_programs(root))

    resolved_run_id = run_id or _derive_run_id(root)
    project = project or "openevolve"

    # ----- run_start -------------------------------------------------------
    started_at = _earliest_timestamp_ns(programs)
    yield RunStartEvent(
        run_id=resolved_run_id,
        timestamp_ns=started_at,
        payload=RunStartPayload(
            name=root.name,
            project=project,
            started_by="openevolve-importer",
            config={
                "last_iteration": metadata.get("last_iteration"),
                "best_program_id": metadata.get("best_program_id"),
                "num_islands": len(metadata.get("islands", [])),
                "checkpoint_path": str(root.resolve()),
            },
            # OpenEvolve's circle-packing benchmark uses sum_radii (max)
            # and compile_ms (min). We only declare what we observe in
            # the checkpoint so unknown metrics fall through to the UI's
            # name heuristic rather than getting mislabelled.
            score_directions=_score_directions_for(programs),
        ),
    )

    island_by_program = _invert_islands(metadata)
    descriptor_by_program = _invert_feature_maps(metadata)

    programs.sort(key=lambda p: (p.get("generation") or 0, p.get("timestamp") or ""))

    for prog in programs:
        prog_id = prog.get("id")
        if not isinstance(prog_id, str):
            logger.warning("skipping program with no id: %s", prog)
            continue
        ts = _parse_iso_ns(prog.get("timestamp"))
        parent_id = prog.get("parent_id")
        parents: list[str] = [parent_id] if isinstance(parent_id, str) else []
        is_seed = len(parents) == 0
        island_id = island_by_program.get(prog_id)

        # Promote island assignment to the envelope's stream_id so the
        # Operator-trace swimlane separates lanes per island. Falls back to
        # the default lane when the run doesn't use islands.
        stream_id = f"island-{island_id}" if island_id is not None else None

        yield IndividualEvent(
            run_id=resolved_run_id,
            timestamp_ns=ts,
            stream_id=stream_id,
            payload=IndividualPayload(
                id=prog_id,
                kind="program",
                parent_ids=parents,
                is_seed=is_seed,
                genome_lang=prog.get("language") or "python",
                generation_index=prog.get("generation"),
                island_id=island_id,
                metadata={
                    "changes_description": prog.get("changes_description"),
                    "iteration_found": prog.get("iteration_found"),
                    "complexity": prog.get("complexity"),
                    "diversity": prog.get("diversity"),
                },
            ),
        )

        if parents:
            yield OperatorEvent(
                run_id=resolved_run_id,
                timestamp_ns=ts,
                stream_id=stream_id,
                payload=OperatorPayload(
                    id=f"op-{prog_id}",
                    kind="refine",
                    parent_ids=parents,
                    child_id=prog_id,
                    metadata={
                        "changes_description": prog.get("changes_description"),
                        "iteration_found": prog.get("iteration_found"),
                    },
                ),
            )

        metrics = prog.get("metrics") or {}
        if isinstance(metrics, dict) and metrics:
            scores = {k: float(v) for k, v in metrics.items() if _is_number(v)}
            if scores:
                yield FitnessEvent(
                    run_id=resolved_run_id,
                    timestamp_ns=ts,
                    payload=FitnessPayload(
                        individual_id=prog_id,
                        evaluator_kind="deterministic_metric",
                        scores=scores,
                        composite=_composite_score(scores),
                    ),
                )

        descriptor = descriptor_by_program.get(prog_id)
        if descriptor is not None:
            island_idx, cell_id, coords = descriptor
            yield DescriptorEvent(
                run_id=resolved_run_id,
                timestamp_ns=ts,
                payload=DescriptorPayload(
                    individual_id=prog_id,
                    archive_id=f"openevolve-island-{island_idx}",
                    kind="grid",
                    coordinates=coords,
                    cell_id=cell_id,
                ),
            )

    # ----- run_end ---------------------------------------------------------
    if finalize:
        last_ts = _latest_timestamp_ns(programs)
        yield RunEndEvent(
            run_id=resolved_run_id,
            timestamp_ns=max(last_ts, started_at + 1),
            payload=RunEndPayload(
                status="finished",
                summary=f"imported {len(programs)} programs from {root.name}",
            ),
        )


# ---------- helpers --------------------------------------------------------


def _load_metadata(root: Path) -> dict[str, Any]:
    path = root / "metadata.json"
    parsed: Any = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(parsed, dict):
        raise ValueError(f"metadata.json at {path} is not a JSON object")
    return parsed


def _load_programs(root: Path) -> Iterator[dict[str, Any]]:
    pdir = root / "programs"
    for p in sorted(pdir.glob("*.json")):
        try:
            yield json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            logger.warning("skipping malformed program %s: %s", p.name, exc)


def _derive_run_id(root: Path) -> str:
    """Prefer a stable id derived from the checkpoint path; fall back to UUID."""
    name = root.name or root.parent.name or "openevolve"
    if not name:
        return f"openevolve-{uuid.uuid4().hex[:12]}"
    return f"oe-{name}"


def _invert_islands(metadata: dict[str, Any]) -> dict[str, str]:
    islands: Any = metadata.get("islands") or []
    out: dict[str, str] = {}
    if not isinstance(islands, list):
        return out
    for idx, prog_ids in enumerate(islands):
        if not isinstance(prog_ids, list):
            continue
        for pid in prog_ids:
            if isinstance(pid, str):
                out[pid] = str(idx)
    return out


def _invert_feature_maps(
    metadata: dict[str, Any],
) -> dict[str, tuple[int, str, list[float]]]:
    """Return ``{program_id: (island_idx, cell_key, coords)}``.

    OpenEvolve serializes per-island feature grids as ``{cell_key: program_id}``
    where ``cell_key`` is a string-encoded coordinate tuple. We try to parse
    floats out of the key; if we can't, we still emit the cell key but with
    empty coordinates (the descriptor is still useful for grouping).
    """
    # Annotated as ``Any`` rather than ``list[dict[str, str]]`` so the runtime
    # ``isinstance`` checks on JSON-parsed values stay reachable under mypy.
    feature_maps: Any = metadata.get("island_feature_maps") or []
    out: dict[str, tuple[int, str, list[float]]] = {}
    if not isinstance(feature_maps, list):
        return out
    for idx, fmap in enumerate(feature_maps):
        if not isinstance(fmap, dict):
            continue
        for cell_key, prog_id in fmap.items():
            if not isinstance(prog_id, str) or not isinstance(cell_key, str):
                continue
            coords = _parse_cell_key(cell_key)
            out[prog_id] = (idx, cell_key, coords)
    return out


_COORD_RE = re.compile(r"-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?")


def _parse_cell_key(key: str) -> list[float]:
    """Best-effort parse of OpenEvolve's cell-key strings into floats."""
    return [float(m) for m in _COORD_RE.findall(key)]


def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _composite_score(scores: dict[str, float]) -> float | None:
    if not scores:
        return None
    return max(scores.values())


def _parse_iso_ns(value: Any) -> int:
    """Parse an ISO-8601 timestamp string to nanoseconds since epoch.

    Accepts ``None`` / unknown formats and returns ``0`` so the schema's
    ``timestamp_ns >= 0`` validator still passes; the caller bumps to a
    monotone-increasing value when needed.
    """
    if isinstance(value, (int, float)):
        # Already an epoch-seconds value.
        return int(float(value) * 1_000_000_000)
    if not isinstance(value, str):
        return 0
    try:
        # OpenEvolve uses ISO-8601 with optional 'Z' or offset.
        normalized = value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
        return int(dt.timestamp() * 1_000_000_000)
    except ValueError:
        return 0


def _earliest_timestamp_ns(programs: list[dict[str, Any]]) -> int:
    candidates = [_parse_iso_ns(p.get("timestamp")) for p in programs]
    candidates = [c for c in candidates if c > 0]
    return min(candidates) if candidates else 0


def _latest_timestamp_ns(programs: list[dict[str, Any]]) -> int:
    candidates = [_parse_iso_ns(p.get("timestamp")) for p in programs]
    candidates = [c for c in candidates if c > 0]
    return max(candidates) if candidates else 0


# Metric-name → direction mapping for OpenEvolve's published benchmarks.
# We only emit directions for metrics we actually observe in the checkpoint.
_OE_KNOWN_DIRECTIONS: dict[str, str] = {
    # circle-packing
    "sum_radii": "higher",
    "compile_ms": "lower",
    "compile_time_ms": "lower",
    # commonly-seen in other OpenEvolve runs
    "score": "higher",
    "accuracy": "higher",
    "correctness": "higher",
    "loss": "lower",
    "runtime_s": "lower",
    "runtime_ms": "lower",
    "ms": "lower",
}


def _score_directions_for(programs: list[dict[str, Any]]) -> dict[str, str]:
    seen_metrics: set[str] = set()
    for prog in programs:
        metrics = prog.get("metrics") or {}
        if isinstance(metrics, dict):
            for k, v in metrics.items():
                if isinstance(k, str) and _is_number(v):
                    seen_metrics.add(k)
    return {k: _OE_KNOWN_DIRECTIONS[k] for k in seen_metrics if k in _OE_KNOWN_DIRECTIONS}
