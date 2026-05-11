"""FunSearch programs-database adapter.

FunSearch (Romera-Paredes et al., Nature 2024;
`google-deepmind/funsearch <https://github.com/google-deepmind/funsearch>`_)
runs an LLM-driven evolutionary search over Python programs scoring on
a benchmark (cap-set, online bin packing, …). The repo's primary
serialised state is a pickled ``programs_database`` plus per-iteration
JSON logs of the best programs.

We accept the natural JSON-export form rather than depending on the
upstream pickle format, which requires importing the original
benchmark module to round-trip::

    funsearch_dump/
    ├── runs.json           # optional: name, problem, started_at_ns
    └── programs.jsonl      # one program per line:
                              #   {id, code, score, parents, island_id,
                              #    generation, evaluator}

Per program the adapter emits:

* :class:`IndividualEvent` (kind=``program``) with ``parent_ids``
  derived from the integer ``parents`` array (mapped to canonical
  string ids so the schema's ``parent_ids: list[str]`` is happy).
* :class:`OperatorEvent` (kind=``mutate`` for fanout 1, ``crossover``
  for fanout ≥ 2) when parents are recorded.
* :class:`FitnessEvent` with the score(s); the ``evaluator`` field
  becomes the ``evaluator_id`` so the dashboard can filter per
  benchmark.

Permissive on missing fields per the project-wide rule.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from hutch.schema import (
    AnyEvent,
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
from hutch.schema.types import OperatorKind

logger = logging.getLogger("hutch.adapters.funsearch")

_PROGRAMS_NAME = "programs.jsonl"
_RUN_META_NAME = "runs.json"


def detect(path: Path) -> bool:
    """Return ``True`` for a directory containing ``programs.jsonl``."""
    if not path.is_dir():
        return False
    candidate = path / _PROGRAMS_NAME
    if not candidate.is_file():
        return False
    try:
        with candidate.open("r", encoding="utf-8") as fh:
            head = fh.read(4096)
    except OSError:
        return False
    # Discriminate against AIDE / DGM / openevolve files that also use jsonl.
    return '"score"' in head and ('"island_id"' in head or '"generation"' in head)


def import_funsearch(
    path: str | Path,
    *,
    run_id: str | None = None,
    project: str | None = None,
    finalize: bool = True,
) -> Iterator[AnyEvent]:
    """Yield canonical events for a FunSearch dump at *path*."""
    root = Path(path)
    programs_path = root / _PROGRAMS_NAME
    if not programs_path.is_file():
        raise ValueError(f"{root} doesn't contain {_PROGRAMS_NAME}; not a FunSearch dump")

    metadata = _load_metadata(root)
    records = _load_programs(programs_path)
    if not records:
        raise ValueError(f"{programs_path} contains zero program records")

    # Sort for stable lineage replay.
    records.sort(key=lambda r: (_int(r.get("generation"), 0), _int(r.get("id"), 0)))

    resolved_run_id = run_id or _derive_run_id(root, metadata)
    project = project or "funsearch"
    started_at = int(metadata.get("started_at_ns") or _earliest_ts(records) or time.time_ns())
    problem_name = str(metadata.get("problem") or _infer_problem(records) or "unknown")

    yield RunStartEvent(
        run_id=resolved_run_id,
        timestamp_ns=started_at,
        payload=RunStartPayload(
            name=str(metadata.get("name") or root.name or "funsearch"),
            project=project,
            started_by="funsearch-importer",
            config={
                "problem": problem_name,
                "program_count": len(records),
                "source_path": str(root.resolve()),
            },
        ),
    )

    int_to_str: dict[int, str] = {}

    for rec_idx, rec in enumerate(records):
        raw_id = rec.get("id")
        prog_id = _coerce_id(raw_id, rec_idx)
        if isinstance(raw_id, int):
            int_to_str[raw_id] = prog_id

        parent_ints = _as_int_list(rec.get("parents"))
        parent_ids: list[str] = []
        for p in parent_ints:
            if p in int_to_str:
                parent_ids.append(int_to_str[p])
            else:
                # Forward-reference or out-of-order; emit as opaque id.
                parent_ids.append(f"fs-{p}")

        ts = _ts_for(rec, started_at, rec_idx)
        island_id = _str_or_none(rec.get("island_id"))

        yield IndividualEvent(
            run_id=resolved_run_id,
            timestamp_ns=ts,
            stream_id=f"island-{island_id}" if island_id is not None else None,
            payload=IndividualPayload(
                id=prog_id,
                kind="program",
                parent_ids=parent_ids,
                is_seed=len(parent_ids) == 0,
                genome_lang="python",
                generation_index=_int(rec.get("generation"), None),
                island_id=island_id,
                metadata={
                    "funsearch_id": raw_id,
                    "code_length": len(rec.get("code") or ""),
                    "evaluator": rec.get("evaluator"),
                },
            ),
        )

        if parent_ids:
            op_kind: OperatorKind = "crossover" if len(parent_ids) >= 2 else "mutate"
            yield OperatorEvent(
                run_id=resolved_run_id,
                timestamp_ns=ts,
                stream_id=f"island-{island_id}" if island_id is not None else None,
                payload=OperatorPayload(
                    id=f"op-{prog_id}",
                    kind=op_kind,
                    parent_ids=parent_ids,
                    child_id=prog_id,
                    metadata={"funsearch_id": raw_id},
                ),
            )

        scores = _scores_for(rec)
        if scores:
            yield FitnessEvent(
                run_id=resolved_run_id,
                timestamp_ns=ts,
                payload=FitnessPayload(
                    individual_id=prog_id,
                    evaluator_id=str(rec.get("evaluator") or problem_name),
                    evaluator_kind="benchmark",
                    scores=scores,
                    composite=_composite(scores),
                ),
            )

    if finalize:
        last_ts = _latest_ts(records) or (started_at + len(records) + 1)
        yield RunEndEvent(
            run_id=resolved_run_id,
            timestamp_ns=max(last_ts, started_at + 1),
            payload=RunEndPayload(
                status="finished",
                summary=f"imported {len(records)} FunSearch programs ({problem_name})",
            ),
        )


# ---------- helpers --------------------------------------------------------


def _load_metadata(root: Path) -> dict[str, Any]:
    p = root / _RUN_META_NAME
    if not p.is_file():
        return {}
    try:
        parsed: Any = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        logger.warning("malformed %s: %s", p, exc)
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _load_programs(p: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    text = p.read_text(encoding="utf-8")
    for line_no, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError as exc:
            logger.warning("skipping malformed program on line %d: %s", line_no, exc)
            continue
        if isinstance(rec, dict):
            out.append(rec)
    return out


def _derive_run_id(root: Path, metadata: dict[str, Any]) -> str:
    explicit = metadata.get("run_id")
    if isinstance(explicit, str) and explicit:
        return explicit
    return f"fs-{root.name or uuid.uuid4().hex[:12]}"


def _coerce_id(raw: Any, fallback_idx: int) -> str:
    if isinstance(raw, int):
        return f"fs-{raw}"
    if isinstance(raw, str) and raw:
        return raw
    return f"fs-{fallback_idx}"


def _as_int_list(value: Any) -> list[int]:
    if not isinstance(value, list):
        return []
    out: list[int] = []
    for v in value:
        if isinstance(v, bool):
            continue
        if isinstance(v, int):
            out.append(v)
        elif isinstance(v, float) and v.is_integer():
            out.append(int(v))
    return out


def _int(value: Any, default: int | None) -> int | None:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return default


def _str_or_none(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _ts_for(rec: dict[str, Any], started_at: int, rec_idx: int) -> int:
    explicit = rec.get("timestamp_ns")
    if isinstance(explicit, (int, float)):
        return int(explicit)
    return started_at + rec_idx


def _earliest_ts(records: list[dict[str, Any]]) -> int | None:
    seq = [
        int(r["timestamp_ns"]) for r in records if isinstance(r.get("timestamp_ns"), (int, float))
    ]
    return min(seq) if seq else None


def _latest_ts(records: list[dict[str, Any]]) -> int | None:
    seq = [
        int(r["timestamp_ns"]) for r in records if isinstance(r.get("timestamp_ns"), (int, float))
    ]
    return max(seq) if seq else None


def _scores_for(rec: dict[str, Any]) -> dict[str, float]:
    raw = rec.get("score")
    if isinstance(raw, dict):
        return {
            str(k): float(v)
            for k, v in raw.items()
            if isinstance(v, (int, float)) and not isinstance(v, bool)
        }
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        evaluator = rec.get("evaluator")
        key = str(evaluator) if isinstance(evaluator, str) and evaluator else "score"
        return {key: float(raw)}
    return {}


def _composite(scores: dict[str, float]) -> float | None:
    if not scores:
        return None
    if len(scores) == 1:
        return next(iter(scores.values()))
    return max(scores.values())


def _infer_problem(records: list[dict[str, Any]]) -> str | None:
    for rec in records:
        evaluator = rec.get("evaluator")
        if isinstance(evaluator, str) and evaluator:
            return evaluator
    return None
