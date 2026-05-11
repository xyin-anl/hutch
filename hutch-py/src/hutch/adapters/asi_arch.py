"""ASI-ARCH experiments adapter.

ASI-ARCH (`GAIR-NLP/ASI-Arch
<https://github.com/GAIR-NLP/ASI-Arch>`_) stores its experiment trail in
MongoDB. We accept the natural ``mongoexport`` output: a JSONL file with
one experiment record per line, OR a single JSON file containing an
array of records (``experiments.json``).

Each record is a permissive dict; we look for these fields::

    {
      "index": 17,                    # required: stable per-run integer id
      "parent": 12,                   # 0 / null / missing => seed
      "name":   "ConvAttention-XL",
      "score":  0.713,
      "loss":   3.21,
      "motivation": "...",            # one paragraph; goes to metadata
      "analysis":   "...",
      "agent":      "researcher",     # researcher|engineer|analyst (stream)
      "timestamp_ns": 1714514400_000_000_000,   # optional; we synthesize one if absent
      "verdict":    "accepted",       # optional analyst verdict
      "scores":     { "accuracy": 0.71, "loss": 3.21 }   # optional richer metrics
    }

Per record the adapter emits:

* :class:`IndividualEvent` (kind=``architecture``) with ``parent_ids``
  resolved through the index→id map. The agent (Researcher/Engineer/
  Analyst) lands as ``stream_id`` so the Operator-trace swimlane lays
  them out per role.
* :class:`OperatorEvent` (kind=``propose`` by default; ``edit_diff`` for
  the engineer agent; ``review`` for the analyst).
* :class:`FitnessEvent` with the LLM-judge or benchmark scores.
* :class:`ReviewEvent` for non-empty analyst comments.

Anything not recoverable simply doesn't emit the corresponding event —
the project's "render gracefully on partial data" rule.
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
    ReviewEvent,
    ReviewPayload,
    RunEndEvent,
    RunEndPayload,
    RunStartEvent,
    RunStartPayload,
)
from hutch.schema.types import OperatorKind

logger = logging.getLogger("hutch.adapters.asi_arch")

_AGENT_TO_OP_KIND: dict[str, OperatorKind] = {
    "researcher": "propose",
    "engineer": "edit_diff",
    "analyst": "review",
}


def detect(path: Path) -> bool:
    """Return ``True`` when *path* points at an ASI-ARCH dump."""
    candidates = _candidate_files(path)
    if not candidates:
        return False
    for candidate in candidates:
        try:
            with candidate.open("r", encoding="utf-8") as fh:
                head = fh.read(2048)
        except OSError:
            continue
        # Both index/parent and the agent vocabulary are characteristic.
        if '"index"' in head and ('"parent"' in head or '"motivation"' in head):
            return True
    return False


def import_asi_arch(
    path: str | Path,
    *,
    run_id: str | None = None,
    project: str | None = None,
) -> Iterator[AnyEvent]:
    """Yield canonical events for an ASI-ARCH experiment dump at *path*."""
    p = Path(path)
    candidates = _candidate_files(p)
    if not candidates:
        raise ValueError(
            f"{p} doesn't look like an ASI-ARCH dump "
            "(expected experiments.jsonl, experiments.json, or a JSON/JSONL file)"
        )
    records = _load_records(candidates[0])
    if not records:
        raise ValueError(f"{candidates[0]} contains zero ASI-ARCH experiment records")

    # Sort by index when present so children come after their parents.
    records.sort(key=lambda r: _coerce_int(r.get("index"), default=10**9) or 10**9)

    resolved_run_id = run_id or _derive_run_id(p, records[0])
    project = project or "asi-arch"

    started_at = _earliest_ts(records) or time.time_ns()
    yield RunStartEvent(
        run_id=resolved_run_id,
        timestamp_ns=started_at,
        payload=RunStartPayload(
            name=p.name or "asi-arch",
            project=project,
            started_by="asi-arch-importer",
            config={
                "experiment_count": len(records),
                "source_path": str(candidates[0].resolve()),
            },
            # ASI-ARCH benchmarks lean on accuracy (higher) + loss (lower) +
            # perplexity (lower).
            score_directions=_score_directions_for(records),
        ),
    )

    index_to_id: dict[int, str] = {}

    for rec_idx, rec in enumerate(records):
        idx = _coerce_int(rec.get("index"))
        ind_id = _individual_id(rec, idx)
        if idx is not None:
            index_to_id[idx] = ind_id

        parent_idx = _coerce_int(rec.get("parent"))
        parent_ids: list[str] = []
        if parent_idx is not None and parent_idx != 0 and parent_idx in index_to_id:
            parent_ids = [index_to_id[parent_idx]]

        agent_raw = rec.get("agent") or rec.get("role") or "researcher"
        agent = str(agent_raw).strip().lower() if isinstance(agent_raw, str) else "researcher"
        stream_id = f"agent-{agent}" if agent else None
        op_kind: OperatorKind = _AGENT_TO_OP_KIND.get(agent, "propose")

        ts = _ts_for(rec, started_at, rec_idx)

        yield IndividualEvent(
            run_id=resolved_run_id,
            timestamp_ns=ts,
            stream_id=stream_id,
            payload=IndividualPayload(
                id=ind_id,
                kind="architecture",
                parent_ids=parent_ids,
                is_seed=len(parent_ids) == 0,
                generation_index=idx,
                metadata={
                    "asi_arch_index": idx,
                    "asi_arch_parent": parent_idx,
                    "name": rec.get("name"),
                    "agent": agent,
                    "motivation": _truncate(rec.get("motivation"), 1000),
                    "analysis": _truncate(rec.get("analysis"), 1000),
                    "verdict": rec.get("verdict"),
                },
            ),
        )

        if parent_ids:
            yield OperatorEvent(
                run_id=resolved_run_id,
                timestamp_ns=ts,
                stream_id=stream_id,
                payload=OperatorPayload(
                    id=f"op-{ind_id}",
                    kind=op_kind,
                    parent_ids=parent_ids,
                    child_id=ind_id,
                    metadata={"agent": agent},
                ),
            )

        scores = _scores_for(rec)
        if scores:
            yield FitnessEvent(
                run_id=resolved_run_id,
                timestamp_ns=ts,
                stream_id=stream_id,
                payload=FitnessPayload(
                    individual_id=ind_id,
                    evaluator_kind="llm_judge" if agent == "analyst" else "benchmark",
                    scores=scores,
                    composite=_composite(scores),
                ),
            )

        analyst_text = rec.get("analysis") if agent == "analyst" else None
        if isinstance(analyst_text, str) and analyst_text.strip():
            yield ReviewEvent(
                run_id=resolved_run_id,
                timestamp_ns=ts,
                stream_id=stream_id,
                payload=ReviewPayload(
                    target_id=ind_id,
                    scorer="asi-arch-analyst",
                    scores=scores or {},
                    concerns=_concerns_from(rec),
                ),
            )

    last_ts = _latest_ts(records) or (started_at + len(records) + 1)
    yield RunEndEvent(
        run_id=resolved_run_id,
        timestamp_ns=max(last_ts, started_at + 1),
        payload=RunEndPayload(
            status="finished",
            summary=f"imported {len(records)} ASI-ARCH experiments",
        ),
    )


# ---------- helpers --------------------------------------------------------


def _candidate_files(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    if not path.is_dir():
        return []
    out: list[Path] = []
    for name in ("experiments.jsonl", "experiments.json", "asi_arch_dump.jsonl"):
        candidate = path / name
        if candidate.is_file():
            out.append(candidate)
    return out


def _load_records(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8")
    text = text.strip()
    if not text:
        return []
    out: list[dict[str, Any]] = []
    if text.startswith("["):
        parsed: Any = json.loads(text)
        if isinstance(parsed, list):
            for item in parsed:
                if isinstance(item, dict):
                    out.append(item)
        return out
    # Fallback: NDJSON / JSONL.
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError as exc:
            logger.warning("skipping malformed line in %s: %s", path.name, exc)
            continue
        if isinstance(rec, dict):
            out.append(rec)
    return out


def _individual_id(rec: dict[str, Any], idx: int | None) -> str:
    explicit = rec.get("id") or rec.get("_id")
    if isinstance(explicit, str) and explicit:
        return explicit
    if idx is not None:
        return f"asi-{idx}"
    return f"asi-{uuid.uuid4().hex[:12]}"


def _coerce_int(value: Any, *, default: int | None = None) -> int | None:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.lstrip("-").isdigit():
        return int(value)
    return default


def _ts_for(rec: dict[str, Any], started_at: int, rec_idx: int) -> int:
    explicit = rec.get("timestamp_ns")
    if isinstance(explicit, (int, float)):
        return int(explicit)
    explicit_s = rec.get("timestamp")
    if isinstance(explicit_s, (int, float)):
        return int(float(explicit_s) * 1_000_000_000)
    return started_at + rec_idx


def _earliest_ts(records: list[dict[str, Any]]) -> int | None:
    candidates = [_coerce_int(r.get("timestamp_ns")) for r in records]
    candidates_clean = [c for c in candidates if c is not None and c > 0]
    if candidates_clean:
        return min(candidates_clean)
    return None


def _latest_ts(records: list[dict[str, Any]]) -> int | None:
    candidates = [_coerce_int(r.get("timestamp_ns")) for r in records]
    candidates_clean = [c for c in candidates if c is not None and c > 0]
    if candidates_clean:
        return max(candidates_clean)
    return None


def _derive_run_id(path: Path, first: dict[str, Any]) -> str:
    explicit = first.get("run_id")
    if isinstance(explicit, str) and explicit:
        return explicit
    name = path.parent.name if path.is_file() else path.name
    if not name:
        name = "asi-arch"
    return f"asi-{name}"


def _scores_for(rec: dict[str, Any]) -> dict[str, float]:
    out: dict[str, float] = {}
    s = rec.get("scores")
    if isinstance(s, dict):
        for k, v in s.items():
            if isinstance(k, str) and _is_number(v):
                out[k] = float(v)
    for fallback_key in ("score", "loss", "accuracy", "perplexity"):
        v = rec.get(fallback_key)
        if isinstance(v, (int, float)) and not isinstance(v, bool) and fallback_key not in out:
            out[fallback_key] = float(v)
    return out


def _composite(scores: dict[str, float]) -> float | None:
    if not scores:
        return None
    if "score" in scores:
        return scores["score"]
    return max(scores.values())


def _truncate(value: Any, n: int) -> str | None:
    if not isinstance(value, str):
        return None
    return value if len(value) <= n else value[:n] + "…"


def _concerns_from(rec: dict[str, Any]) -> list[str]:
    raw = rec.get("concerns")
    if isinstance(raw, list):
        return [str(x) for x in raw if isinstance(x, str)]
    return []


def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


_ASI_KNOWN_DIRECTIONS: dict[str, str] = {
    "score": "higher",
    "accuracy": "higher",
    "f1": "higher",
    "loss": "lower",
    "perplexity": "lower",
    "ppl": "lower",
}


def _score_directions_for(records: list[dict[str, Any]]) -> dict[str, str]:
    seen: set[str] = set()
    for rec in records:
        for k in _scores_for(rec):
            seen.add(k)
    return {k: _ASI_KNOWN_DIRECTIONS[k] for k in seen if k in _ASI_KNOWN_DIRECTIONS}
