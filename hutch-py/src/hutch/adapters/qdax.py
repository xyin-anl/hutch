"""QDax repertoire adapter.

QDax stores a MAP-Elites repertoire as a stack of arrays — centroids,
fitnesses, descriptors, optional genotypes. We accept the JSON export
form below rather than depending on JAX/numpy at the package level::

    {
      "centroids":   [[0.1, 0.2], [0.3, 0.4], …],   # one row per cell
      "fitnesses":   [0.51, -inf, 0.74, …],          # -inf marks empty
      "descriptors": [[0.12, 0.18], [...], …],       # actual descriptor
      "genotypes":   [[0.0, 1.5, …], [...], …],      # optional, flat
      "metadata": {
        "descriptor_dims": ["complexity", "speed"],
        "objective_name": "fitness",
        "name": "qd-toy",
        "kind": "grid"            # "grid" | "cvt" | "aurora"
      }
    }

Two-line conversion from a live QDax Repertoire::

    import json, numpy as np
    json.dump({
        "centroids":   r.centroids.tolist(),
        "fitnesses":   r.fitnesses.tolist(),
        "descriptors": r.descriptors.tolist(),
        "genotypes":   np.asarray(r.genotypes).reshape(r.fitnesses.shape[0], -1).tolist(),
        "metadata":    {"descriptor_dims": [...], "objective_name": "fitness"},
    }, open("repertoire.json", "w"))

Per filled cell the adapter emits:

* :class:`IndividualEvent` (kind=``program``).
* :class:`OperatorEvent` (kind=``mutate``) when a parent cell is recorded
  via the optional ``parents`` array (cell index of the parent).
* :class:`FitnessEvent` carrying the ``fitness`` score.
* :class:`DescriptorEvent` placing the cell in its archive.

A run-level :class:`ArchiveSnapshotEvent` summarises coverage, qd_score,
max_fitness, and size.
"""

from __future__ import annotations

import json
import logging
import math
import time
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from hutch.schema import (
    AnyEvent,
    ArchiveSnapshotEvent,
    ArchiveSnapshotPayload,
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
from hutch.schema.types import DescriptorArchiveKind

logger = logging.getLogger("hutch.adapters.qdax")


def detect(path: Path) -> bool:
    """Return ``True`` when *path* looks like a QDax JSON export."""
    if path.is_file() and path.suffix == ".json":
        return _looks_like_qdax(path)
    if path.is_dir():
        candidate = path / "repertoire.json"
        if candidate.is_file():
            return _looks_like_qdax(candidate)
    return False


def import_qdax(
    path: str | Path,
    *,
    run_id: str | None = None,
    project: str | None = None,
    finalize: bool = True,
) -> Iterator[AnyEvent]:
    """Yield canonical events from a QDax JSON repertoire export at *path*.

    *path* may point at the JSON file directly or at a directory containing
    ``repertoire.json``.
    """
    p = Path(path)
    if p.is_dir():
        p = p / "repertoire.json"
    if not p.is_file():
        raise ValueError(f"{p} does not exist; expected a QDax repertoire.json export")

    data = _load(p)
    centroids = _as_list_of_floats(data.get("centroids") or [])
    fitnesses = _as_list_of_scalars(data.get("fitnesses") or [])
    descriptors = _as_list_of_floats(data.get("descriptors") or centroids)
    parents_raw = data.get("parents")
    parents: list[int | None] = _as_optional_int_list(parents_raw)
    metadata = data.get("metadata") or {}
    if not isinstance(metadata, dict):
        metadata = {}

    if not fitnesses:
        raise ValueError(f"{p} contains no fitnesses array; nothing to import")

    archive_kind: DescriptorArchiveKind = _archive_kind(metadata.get("kind"))
    archive_id = str(metadata.get("archive_id") or "qdax-archive")
    objective_name = str(metadata.get("objective_name") or "fitness")
    descriptor_dims_raw = metadata.get("descriptor_dims")
    descriptor_dims: list[str] | None
    if isinstance(descriptor_dims_raw, list) and all(
        isinstance(x, str) for x in descriptor_dims_raw
    ):
        descriptor_dims = list(descriptor_dims_raw)
    else:
        descriptor_dims = None

    resolved_run_id = run_id or _derive_run_id(p, metadata)
    project = project or "qdax"

    started_at = int(metadata.get("started_at_ns") or time.time_ns())
    yield RunStartEvent(
        run_id=resolved_run_id,
        timestamp_ns=started_at,
        payload=RunStartPayload(
            name=str(metadata.get("name") or p.parent.name or p.stem),
            project=project,
            started_by="qdax-importer",
            config={
                "num_cells": len(fitnesses),
                "archive_id": archive_id,
                "descriptor_dims": descriptor_dims,
                "objective_name": objective_name,
                "source_path": str(p.resolve()),
            },
        ),
    )

    cell_id_to_individual: dict[int, str] = {}
    filled = 0
    qd_score = 0.0
    max_fitness = -math.inf

    for cell_idx, fit in enumerate(fitnesses):
        if not _cell_filled(fit):
            continue
        filled += 1
        ind_id = f"qd-{cell_idx}"
        cell_id_to_individual[cell_idx] = ind_id

        # Lineage: optional ``parents`` array maps cell_idx → parent cell_idx.
        parent_cell = parents[cell_idx] if cell_idx < len(parents) else None
        parent_ids: list[str] = []
        if parent_cell is not None and parent_cell in cell_id_to_individual:
            parent_ids = [cell_id_to_individual[parent_cell]]

        ts = started_at + cell_idx  # monotone but tightly packed
        yield IndividualEvent(
            run_id=resolved_run_id,
            timestamp_ns=ts,
            payload=IndividualPayload(
                id=ind_id,
                kind="program",
                parent_ids=parent_ids,
                is_seed=len(parent_ids) == 0,
                generation_index=int(cell_idx),
                metadata={
                    "qdax_cell_idx": cell_idx,
                    "centroid": centroids[cell_idx] if cell_idx < len(centroids) else None,
                },
            ),
        )

        if parent_ids:
            yield OperatorEvent(
                run_id=resolved_run_id,
                timestamp_ns=ts,
                payload=OperatorPayload(
                    id=f"op-{ind_id}",
                    kind="mutate",
                    parent_ids=parent_ids,
                    child_id=ind_id,
                    metadata={"qdax_cell_idx": cell_idx},
                ),
            )

        score = float(fit)
        max_fitness = max(max_fitness, score)
        qd_score += score
        yield FitnessEvent(
            run_id=resolved_run_id,
            timestamp_ns=ts,
            payload=FitnessPayload(
                individual_id=ind_id,
                evaluator_kind="deterministic_metric",
                scores={objective_name: score},
                composite=score,
            ),
        )

        coords = descriptors[cell_idx] if cell_idx < len(descriptors) else []
        yield DescriptorEvent(
            run_id=resolved_run_id,
            timestamp_ns=ts,
            payload=DescriptorPayload(
                individual_id=ind_id,
                archive_id=archive_id,
                kind=archive_kind,
                dimensions=descriptor_dims,
                coordinates=list(coords),
                cell_id=str(cell_idx),
            ),
        )

    coverage = filled / len(fitnesses) if fitnesses else 0.0
    yield ArchiveSnapshotEvent(
        run_id=resolved_run_id,
        timestamp_ns=started_at + len(fitnesses) + 1,
        payload=ArchiveSnapshotPayload(
            archive_id=archive_id,
            coverage=coverage,
            qd_score=qd_score if filled else None,
            max_fitness=max_fitness if filled else None,
            size=filled,
        ),
    )

    if finalize:
        yield RunEndEvent(
            run_id=resolved_run_id,
            timestamp_ns=started_at + len(fitnesses) + 2,
            payload=RunEndPayload(
                status="finished",
                summary=(
                    f"imported {filled} filled cells of {len(fitnesses)} "
                    f"(coverage={coverage:.2%}) from {p.name}"
                ),
            ),
        )


# ---------- helpers --------------------------------------------------------


def _looks_like_qdax(path: Path) -> bool:
    try:
        with path.open("r", encoding="utf-8") as fh:
            head = fh.read(4096)
    except OSError:
        return False
    # Cheap shape probe — avoid full JSON parse for big files.
    return '"fitnesses"' in head and ('"centroids"' in head or '"descriptors"' in head)


def _load(path: Path) -> dict[str, Any]:
    parsed: Any = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(parsed, dict):
        raise ValueError(f"{path} is not a JSON object at the top level")
    return parsed


def _as_list_of_floats(values: Any) -> list[list[float]]:
    out: list[list[float]] = []
    if not isinstance(values, list):
        return out
    for row in values:
        if isinstance(row, list):
            out.append([float(x) for x in row if _is_number(x)])
        elif _is_number(row):
            out.append([float(row)])
    return out


def _as_list_of_scalars(values: Any) -> list[float]:
    if not isinstance(values, list):
        return []
    out: list[float] = []
    for v in values:
        if v is None:
            out.append(float("-inf"))
        elif _is_number(v):
            out.append(float(v))
        elif isinstance(v, str) and v.lower() in {"-inf", "-infinity", "null"}:
            out.append(float("-inf"))
        else:
            out.append(float("-inf"))
    return out


def _as_optional_int_list(values: Any) -> list[int | None]:
    if not isinstance(values, list):
        return []
    out: list[int | None] = []
    for v in values:
        if isinstance(v, int) and v >= 0:
            out.append(v)
        elif isinstance(v, float) and v.is_integer() and v >= 0:
            out.append(int(v))
        else:
            out.append(None)
    return out


def _cell_filled(fit: float) -> bool:
    return math.isfinite(fit)


def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _archive_kind(value: Any) -> DescriptorArchiveKind:
    if isinstance(value, str) and value in ("grid", "cvt", "aurora"):
        return value  # type: ignore[return-value]
    return "grid"


def _derive_run_id(path: Path, metadata: dict[str, Any]) -> str:
    explicit = metadata.get("run_id")
    if isinstance(explicit, str) and explicit:
        return explicit
    name = metadata.get("name") or path.parent.name or path.stem
    if isinstance(name, str) and name:
        return f"qd-{name}"
    return f"qd-{uuid.uuid4().hex[:12]}"
