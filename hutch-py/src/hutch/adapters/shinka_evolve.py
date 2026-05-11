"""ShinkaEvolve adapter.

ShinkaEvolve (Sakana AI) is an evolutionary system that searches over
LLM prompts and program candidates with explicit *meta-mutation* — the
search procedure itself evolves over time. The on-disk dump form we
support::

    shinka_run/
    ├── run.json                # name, project, started_at_ns
    ├── candidates.jsonl        # one candidate per line
    └── meta_mutations.jsonl    # optional: changes to the search procedure

``candidates.jsonl`` records::

    {
      "id":           "cand-42",
      "kind":         "prompt" | "program",
      "parents":      ["cand-37"],     # 0..N
      "operator":     "mutate" | "crossover" | "refine" | "diversify",
      "score":        0.71,             # or {"name": value, ...}
      "evaluator":    "shinka-eval",
      "generation":   3,
      "shinka_iteration": 17,           # internal step counter
      "timestamp_ns": ...
    }

``meta_mutations.jsonl`` records::

    {
      "id":           "meta-3",
      "parents":      ["meta-2"],       # the previous procedure version
      "description":  "increase mutation rate to 0.4",
      "timestamp_ns": ...
    }

Per candidate the adapter emits Individual + Operator (kind from
``operator`` field, defaulting to ``refine``) + Fitness. Meta-mutations
emit a separate Individual (kind=``skill`` per the schema's enum) plus
an OperatorEvent with kind=``meta_mutate``.
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
from hutch.schema.types import IndividualKind, OperatorKind

logger = logging.getLogger("hutch.adapters.shinka_evolve")

_CANDIDATES_NAME = "candidates.jsonl"
_META_NAME = "meta_mutations.jsonl"
_RUN_NAME = "run.json"

_VALID_OPERATOR_KINDS: frozenset[OperatorKind] = frozenset(
    {"mutate", "crossover", "refine", "diversify", "select", "propose", "distill"}
)
_VALID_INDIVIDUAL_KINDS: frozenset[IndividualKind] = frozenset(
    {"prompt", "program", "agent", "skill"}
)


def detect(path: Path) -> bool:
    """Return ``True`` for a directory containing ``candidates.jsonl``."""
    if not path.is_dir():
        return False
    p = path / _CANDIDATES_NAME
    if not p.is_file():
        return False
    try:
        with p.open("r", encoding="utf-8") as fh:
            head = fh.read(2048)
    except OSError:
        return False
    # The shinka_iteration field + operator field together are the giveaway.
    return '"shinka_iteration"' in head or ('"operator"' in head and '"generation"' in head)


def import_shinka_evolve(
    path: str | Path,
    *,
    run_id: str | None = None,
    project: str | None = None,
) -> Iterator[AnyEvent]:
    """Yield canonical events for a ShinkaEvolve dump at *path*."""
    root = Path(path)
    cand_path = root / _CANDIDATES_NAME
    if not cand_path.is_file():
        raise ValueError(f"{root} doesn't contain {_CANDIDATES_NAME}; not a ShinkaEvolve dump")

    metadata = _load_metadata(root)
    candidates = _load_jsonl(cand_path)
    meta_mutations = _load_jsonl(root / _META_NAME)
    if not candidates:
        raise ValueError(f"{cand_path} contains zero candidate records")

    candidates.sort(
        key=lambda r: (
            int(r.get("generation") or 0),
            int(r.get("shinka_iteration") or 0),
        )
    )

    resolved_run_id = run_id or _derive_run_id(root, metadata)
    project = project or "shinka-evolve"
    started_at = int(metadata.get("started_at_ns") or _earliest_ts(candidates) or time.time_ns())

    yield RunStartEvent(
        run_id=resolved_run_id,
        timestamp_ns=started_at,
        payload=RunStartPayload(
            name=str(metadata.get("name") or root.name or "shinka-evolve"),
            project=project,
            started_by="shinka-evolve-importer",
            config={
                "candidate_count": len(candidates),
                "meta_mutation_count": len(meta_mutations),
                "source_path": str(root.resolve()),
            },
        ),
    )

    seen: set[str] = set()

    # Meta-mutations (the search-procedure-itself entities) emit first so
    # candidates' lineage to a procedure version (if recorded) resolves.
    for meta in meta_mutations:
        meta_id = _str(meta.get("id"), "")
        if not meta_id:
            continue
        seen.add(meta_id)
        ts = _ts_for(meta, started_at, 0)
        meta_parents = _as_str_list(meta.get("parents"))
        yield IndividualEvent(
            run_id=resolved_run_id,
            timestamp_ns=ts,
            payload=IndividualPayload(
                id=meta_id,
                kind="skill",
                parent_ids=[p for p in meta_parents if p in seen],
                is_seed=not meta_parents,
                metadata={
                    "shinka_role": "meta_mutation",
                    "description": meta.get("description"),
                },
            ),
        )
        if meta_parents:
            yield OperatorEvent(
                run_id=resolved_run_id,
                timestamp_ns=ts,
                payload=OperatorPayload(
                    id=f"op-{meta_id}",
                    kind="meta_mutate",
                    parent_ids=[p for p in meta_parents if p in seen],
                    child_id=meta_id,
                    metadata={"shinka_role": "meta_mutation"},
                ),
            )

    for c_idx, c in enumerate(candidates):
        cand_id = _str(c.get("id"), f"shinka-{c_idx}")
        seen.add(cand_id)
        ts = _ts_for(c, started_at, c_idx)
        ind_kind = _coerce_individual_kind(c.get("kind"))
        op_kind = _coerce_operator_kind(c.get("operator"))
        parents = _as_str_list(c.get("parents"))

        yield IndividualEvent(
            run_id=resolved_run_id,
            timestamp_ns=ts,
            payload=IndividualPayload(
                id=cand_id,
                kind=ind_kind,
                parent_ids=parents,
                is_seed=len(parents) == 0,
                generation_index=_int(c.get("generation"), None),
                metadata={
                    "shinka_iteration": c.get("shinka_iteration"),
                    "evaluator": c.get("evaluator"),
                },
            ),
        )

        if parents:
            yield OperatorEvent(
                run_id=resolved_run_id,
                timestamp_ns=ts,
                payload=OperatorPayload(
                    id=f"op-{cand_id}",
                    kind=op_kind,
                    parent_ids=parents,
                    child_id=cand_id,
                    metadata={"shinka_iteration": c.get("shinka_iteration")},
                ),
            )

        scores = _scores_for(c)
        if scores:
            yield FitnessEvent(
                run_id=resolved_run_id,
                timestamp_ns=ts,
                payload=FitnessPayload(
                    individual_id=cand_id,
                    evaluator_id=_str(c.get("evaluator"), "") or None,
                    evaluator_kind="benchmark",
                    scores=scores,
                    composite=_composite(scores),
                ),
            )

    last_ts = max(
        _latest_ts(candidates) or 0,
        _latest_ts(meta_mutations) or 0,
        started_at + len(candidates),
    )
    yield RunEndEvent(
        run_id=resolved_run_id,
        timestamp_ns=last_ts + 1,
        payload=RunEndPayload(
            status="finished",
            summary=(
                f"imported {len(candidates)} ShinkaEvolve candidates "
                f"+ {len(meta_mutations)} meta-mutations"
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
            logger.warning("skipping malformed %s line %d: %s", p.name, line_no, exc)
            continue
        if isinstance(rec, dict):
            out.append(rec)
    return out


def _derive_run_id(root: Path, metadata: dict[str, Any]) -> str:
    explicit = metadata.get("run_id")
    if isinstance(explicit, str) and explicit:
        return explicit
    return f"shinka-{root.name or uuid.uuid4().hex[:12]}"


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


def _int(value: Any, default: int | None) -> int | None:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return default


def _as_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(v) for v in value if v is not None]


def _scores_for(rec: dict[str, Any]) -> dict[str, float]:
    raw = rec.get("score")
    if isinstance(raw, dict):
        return {
            str(k): float(v)
            for k, v in raw.items()
            if isinstance(v, (int, float)) and not isinstance(v, bool)
        }
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return {"score": float(raw)}
    return {}


def _composite(scores: dict[str, float]) -> float | None:
    if not scores:
        return None
    if "score" in scores:
        return scores["score"]
    return max(scores.values())


def _coerce_individual_kind(value: Any) -> IndividualKind:
    if isinstance(value, str) and value in _VALID_INDIVIDUAL_KINDS:
        return value
    return "program"


def _coerce_operator_kind(value: Any) -> OperatorKind:
    if isinstance(value, str) and value in _VALID_OPERATOR_KINDS:
        return value
    return "refine"
