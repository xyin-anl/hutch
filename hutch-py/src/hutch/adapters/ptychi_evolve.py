"""ptychi-evolve adapter.

ptychi-evolve (`AdvancedPhotonSource/ptychi-evolve
<https://arxiv.org/abs/2603.05696>`_) is an evolutionary coding system
that searches over X-ray ptychography reconstruction algorithms. Each
round of evolution produces a population of candidate reconstruction
implementations, scored on a metric that combines reconstruction
quality + wall-clock time.

We accept the JSONL-per-round dump form::

    ptychi_run/
    ├── run.json              # name, project, started_at_ns, dataset
    └── rounds.jsonl          # one round per line:
                                # {round, individuals: [
                                #   {id, parent, code, metrics: {nrmse, time_s, ...}}
                                # ]}

The metrics dict is flexible — any numeric fields go into the canonical
``FitnessPayload.scores``. ``nrmse`` (lower is better) and ``time_s``
(lower is better) are the two ptychi-evolve papers report.

Mapping:

* :class:`IndividualEvent` (kind=``program``) per individual, with
  ``parent_ids = [parent]`` when present (always at most one — ptychi
  uses simple mutation, no crossover).
* :class:`OperatorEvent` (kind=``mutate``) per non-seed individual.
* :class:`FitnessEvent` carrying every numeric metric.
* :class:`RunEndEvent` summarising counts.
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

logger = logging.getLogger("hutch.adapters.ptychi_evolve")

_ROUNDS_NAME = "rounds.jsonl"
_RUN_NAME = "run.json"


def detect(path: Path) -> bool:
    if not path.is_dir():
        return False
    p = path / _ROUNDS_NAME
    if not p.is_file():
        return False
    try:
        with p.open("r", encoding="utf-8") as fh:
            head = fh.read(2048)
    except OSError:
        return False
    # ``round`` + ``individuals`` + (nrmse OR ptychi keyword) is characteristic.
    if '"round"' not in head or '"individuals"' not in head:
        return False
    return '"nrmse"' in head or '"ptychi"' in head.lower() or '"reconstruction"' in head


def import_ptychi_evolve(
    path: str | Path,
    *,
    run_id: str | None = None,
    project: str | None = None,
) -> Iterator[AnyEvent]:
    """Yield canonical events for a ptychi-evolve dump at *path*."""
    root = Path(path)
    rounds_path = root / _ROUNDS_NAME
    if not rounds_path.is_file():
        raise ValueError(f"{root} doesn't contain {_ROUNDS_NAME}; not a ptychi-evolve dump")

    metadata = _load_metadata(root)
    rounds = _load_jsonl(rounds_path)
    if not rounds:
        raise ValueError(f"{rounds_path} contains zero round records")

    rounds.sort(key=lambda r: int(r.get("round") or 0))

    resolved_run_id = run_id or _derive_run_id(root, metadata)
    project = project or "ptychi-evolve"
    started_at = int(metadata.get("started_at_ns") or _earliest_ts(rounds) or time.time_ns())

    yield RunStartEvent(
        run_id=resolved_run_id,
        timestamp_ns=started_at,
        payload=RunStartPayload(
            name=str(metadata.get("name") or root.name or "ptychi-evolve"),
            project=project,
            started_by="ptychi-evolve-importer",
            config={
                "dataset": metadata.get("dataset"),
                "round_count": len(rounds),
                "source_path": str(root.resolve()),
            },
            # ptychi reports nrmse + time_s — both lower-better.
            score_directions=_score_directions_for(rounds),
        ),
    )

    seen_ids: set[str] = set()
    total_individuals = 0

    for r_idx, rnd in enumerate(rounds):
        round_idx = int(rnd.get("round") or r_idx)
        ts = _ts_for(rnd, started_at, r_idx)

        for ind in _as_dict_list(rnd.get("individuals")):
            ind_id = _str(ind.get("id"), "")
            if not ind_id:
                continue
            seen_ids.add(ind_id)
            parent_raw = ind.get("parent")
            parents: list[str] = []
            if isinstance(parent_raw, str) and parent_raw:
                parents = [parent_raw]
            elif isinstance(parent_raw, list):
                parents = [str(p) for p in parent_raw if isinstance(p, str)]

            yield IndividualEvent(
                run_id=resolved_run_id,
                timestamp_ns=ts,
                payload=IndividualPayload(
                    id=ind_id,
                    kind="program",
                    parent_ids=parents,
                    is_seed=len(parents) == 0,
                    genome_lang="python",
                    generation_index=round_idx,
                    metadata={
                        "code_length": len(ind.get("code") or ""),
                        "ptychi_round": round_idx,
                    },
                ),
            )
            total_individuals += 1

            if parents:
                yield OperatorEvent(
                    run_id=resolved_run_id,
                    timestamp_ns=ts,
                    payload=OperatorPayload(
                        id=f"op-{ind_id}",
                        kind="mutate",
                        parent_ids=parents,
                        child_id=ind_id,
                        metadata={"ptychi_round": round_idx},
                    ),
                )

            scores = _scores_for(ind.get("metrics"))
            if scores:
                yield FitnessEvent(
                    run_id=resolved_run_id,
                    timestamp_ns=ts,
                    payload=FitnessPayload(
                        individual_id=ind_id,
                        evaluator_id=str(metadata.get("dataset") or "ptychi-eval"),
                        evaluator_kind="deterministic_metric",
                        scores=scores,
                        composite=_composite(scores),
                    ),
                )

    last_ts = _latest_ts(rounds) or (started_at + len(rounds) + 1)
    yield RunEndEvent(
        run_id=resolved_run_id,
        timestamp_ns=max(last_ts, started_at + 1),
        payload=RunEndPayload(
            status="finished",
            summary=(
                f"imported {total_individuals} ptychi-evolve individuals "
                f"across {len(rounds)} rounds"
            ),
        ),
    )


# ---------- helpers --------------------------------------------------------


def _load_metadata(root: Path) -> dict[str, Any]:
    p = root / _RUN_NAME
    if not p.is_file():
        return {}
    try:
        parsed: Any = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _load_jsonl(p: Path) -> list[dict[str, Any]]:
    if not p.is_file():
        return []
    out: list[dict[str, Any]] = []
    text = p.read_text(encoding="utf-8")
    for line_no, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError as exc:
            logger.warning("skipping malformed line %d in %s: %s", line_no, p.name, exc)
            continue
        if isinstance(rec, dict):
            out.append(rec)
    return out


def _derive_run_id(root: Path, metadata: dict[str, Any]) -> str:
    explicit = metadata.get("run_id")
    if isinstance(explicit, str) and explicit:
        return explicit
    return f"ptychi-{root.name or uuid.uuid4().hex[:12]}"


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


def _str(value: Any, default: str) -> str:
    return value if isinstance(value, str) and value else default


def _as_dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [v for v in value if isinstance(v, dict)]


def _scores_for(value: Any) -> dict[str, float]:
    if not isinstance(value, dict):
        return {}
    return {
        str(k): float(v)
        for k, v in value.items()
        if isinstance(v, (int, float)) and not isinstance(v, bool)
    }


def _composite(scores: dict[str, float]) -> float | None:
    if not scores:
        return None
    # ptychi reports nrmse (lower is better); for a "higher is better"
    # composite we negate it. Otherwise fall back to max.
    if "nrmse" in scores:
        return -float(scores["nrmse"])
    return max(scores.values())


_PTYCHI_KNOWN_DIRECTIONS: dict[str, str] = {
    "nrmse": "lower",
    "rmse": "lower",
    "time_s": "lower",
    "time_ms": "lower",
    "iterations": "lower",
}


def _score_directions_for(rounds: list[dict[str, Any]]) -> dict[str, str]:
    seen: set[str] = set()
    for rnd in rounds:
        for ind in _as_dict_list(rnd.get("individuals")):
            metrics = ind.get("metrics") or {}
            if isinstance(metrics, dict):
                for k, v in metrics.items():
                    if (
                        isinstance(k, str)
                        and isinstance(v, (int, float))
                        and not isinstance(v, bool)
                    ):
                        seen.add(k)
    return {k: _PTYCHI_KNOWN_DIRECTIONS[k] for k in seen if k in _PTYCHI_KNOWN_DIRECTIONS}
