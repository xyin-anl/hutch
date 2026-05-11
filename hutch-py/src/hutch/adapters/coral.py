"""CORAL multi-agent run adapter.

CORAL (`Human-Agent-Society/CORAL
<https://github.com/Human-Agent-Society/CORAL>`_, arXiv:2604.01658) is
a multi-agent autonomous self-evolution framework with three
distinguishing features that map cleanly onto the canonical schema:

* **Multi-agent streams** — one CORAL agent per worker, each emitting
  proposals and edits in parallel. We surface them as Hutch
  ``stream_id`` swimlanes.
* **Heartbeats** — CORAL's intervention mechanism, where the user (or
  a policy) can interrupt an agent mid-iteration with cancel / pause /
  inject_hint commands. We mirror them as ``steering_command`` events
  for the Steering panel + audit trail.
* **Shared memory** — a persistent across-agent store of patterns
  + reusable artifacts. We surface as :class:`ArchiveSnapshotEvent`
  per snapshot.

We accept the natural directory dump CORAL can produce::

    coral_run/
    ├── run.json                # name, project, started_at_ns, agents
    ├── iterations.jsonl        # one record per agent iteration
    ├── heartbeats.jsonl        # optional intervention log
    └── memory_snapshots.jsonl  # optional shared-memory snapshots

``iterations.jsonl`` records have these fields::

    {
      "id":         "iter-42",
      "agent":      "researcher-3",
      "parents":    ["iter-37"],         # zero or more
      "kind":       "edit",               # propose / edit / review / mutate
      "code":       "...",                # optional
      "score":      0.71,                 # or {"metric": value, ...}
      "evaluator":  "benchmark-X",        # optional
      "timestamp_ns": 1714514400_000_000_000
    }

``heartbeats.jsonl`` records mirror Hutch's
:class:`SteeringCommandPayload`::

    {
      "command":    "pause_run",
      "agent":      "engineer-1",          # optional target
      "params":     { ... },               # optional
      "actor":      "human" | "agent" | "policy",
      "timestamp_ns": ...
    }

The dump may have any subset of those three files; missing ones simply
don't emit the corresponding events.
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
    ArchiveSnapshotEvent,
    ArchiveSnapshotPayload,
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
    SteeringCommandEvent,
    SteeringCommandPayload,
)
from hutch.schema.types import OperatorKind, SteeringActor

logger = logging.getLogger("hutch.adapters.coral")

_ITERATIONS_NAME = "iterations.jsonl"
_HEARTBEATS_NAME = "heartbeats.jsonl"
_MEMORY_NAME = "memory_snapshots.jsonl"
_RUN_NAME = "run.json"

_KIND_TO_OP: dict[str, OperatorKind] = {
    "propose": "propose",
    "edit": "edit_diff",
    "edit_diff": "edit_diff",
    "review": "review",
    "mutate": "mutate",
    "refine": "refine",
    "diversify": "diversify",
    "self_modify": "self_modify",
}

_VALID_COMMANDS: frozenset[str] = frozenset(
    {
        "cancel_individual",
        "freeze_island",
        "fork_from",
        "override_param",
        "pause_run",
        "resume_run",
        "cancel_self_mod",
        "approve_hitl",
        "inject_hint",
    }
)


def detect(path: Path) -> bool:
    """Return ``True`` for a directory that smells like a CORAL dump."""
    if not path.is_dir():
        return False
    iters = path / _ITERATIONS_NAME
    if not iters.is_file():
        return False
    try:
        with iters.open("r", encoding="utf-8") as fh:
            head = fh.read(2048)
    except OSError:
        return False
    # ``agent`` + ``kind`` (with one of the CORAL operator labels) is a strong signal.
    return '"agent"' in head and any(
        f'"kind": "{k}"' in head or f'"kind":"{k}"' in head for k in _KIND_TO_OP
    )


def import_coral(
    path: str | Path,
    *,
    run_id: str | None = None,
    project: str | None = None,
    finalize: bool = True,
) -> Iterator[AnyEvent]:
    """Yield canonical events for a CORAL dump at *path*."""
    root = Path(path)
    iters_path = root / _ITERATIONS_NAME
    if not iters_path.is_file():
        raise ValueError(f"{root} doesn't contain {_ITERATIONS_NAME}; not a CORAL dump")

    metadata = _load_metadata(root)
    iterations = _load_jsonl(iters_path)
    heartbeats = _load_jsonl(root / _HEARTBEATS_NAME)
    snapshots = _load_jsonl(root / _MEMORY_NAME)

    if not iterations:
        raise ValueError(f"{iters_path} contains zero iteration records")

    iterations.sort(key=lambda r: _ts_for(r, 0, 0))

    resolved_run_id = run_id or _derive_run_id(root, metadata)
    project = project or "coral"
    started_at = int(metadata.get("started_at_ns") or _earliest_ts(iterations) or time.time_ns())

    yield RunStartEvent(
        run_id=resolved_run_id,
        timestamp_ns=started_at,
        payload=RunStartPayload(
            name=str(metadata.get("name") or root.name or "coral"),
            project=project,
            started_by="coral-importer",
            config={
                "agent_count": _count_agents(iterations),
                "iteration_count": len(iterations),
                "heartbeat_count": len(heartbeats),
                "memory_snapshot_count": len(snapshots),
                "source_path": str(root.resolve()),
            },
        ),
    )

    seen_ids: set[str] = set()

    for rec_idx, rec in enumerate(iterations):
        ind_id = _str(rec.get("id"), f"coral-{rec_idx}")
        seen_ids.add(ind_id)
        agent = _str(rec.get("agent"), "agent-0")
        stream_id = f"agent-{agent}"

        parents = [p for p in (_as_str_list(rec.get("parents"))) if p in seen_ids]
        # If a parent isn't yet seen (forward ref) we still keep it so
        # the lineage edge survives — schema allows arbitrary string ids.
        for p in _as_str_list(rec.get("parents")):
            if p not in seen_ids and p not in parents:
                parents.append(p)

        ts = _ts_for(rec, started_at, rec_idx)
        op_kind = _KIND_TO_OP.get(_str(rec.get("kind"), "propose"), "propose")

        yield IndividualEvent(
            run_id=resolved_run_id,
            timestamp_ns=ts,
            stream_id=stream_id,
            payload=IndividualPayload(
                id=ind_id,
                kind="program",
                parent_ids=parents,
                is_seed=len(parents) == 0,
                metadata={
                    "coral_kind": rec.get("kind"),
                    "coral_agent": agent,
                    "code_length": len(rec.get("code") or ""),
                    "evaluator": rec.get("evaluator"),
                },
            ),
        )

        if parents:
            yield OperatorEvent(
                run_id=resolved_run_id,
                timestamp_ns=ts,
                stream_id=stream_id,
                payload=OperatorPayload(
                    id=f"op-{ind_id}",
                    kind=op_kind,
                    parent_ids=parents,
                    child_id=ind_id,
                    metadata={"coral_agent": agent},
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
                    evaluator_id=_str(rec.get("evaluator"), None),
                    evaluator_kind="benchmark",
                    scores=scores,
                    composite=_composite(scores),
                ),
            )

    for hb in heartbeats:
        cmd = _str(hb.get("command"), "")
        if cmd not in _VALID_COMMANDS:
            logger.debug("dropping heartbeat with unknown command: %r", cmd)
            continue
        actor: SteeringActor = _coerce_actor(hb.get("actor"))
        params = hb.get("params")
        if not isinstance(params, dict):
            params = {}
        yield SteeringCommandEvent(
            run_id=resolved_run_id,
            timestamp_ns=_ts_for(hb, started_at, 0),
            payload=SteeringCommandPayload(
                command=cmd,
                target_id=_str(hb.get("agent") or hb.get("target_id"), None),
                params={k: v for k, v in params.items() if isinstance(k, str)},
                actor=actor,
            ),
        )

    for snap in snapshots:
        archive_id = _str(snap.get("archive_id") or snap.get("memory_id"), "coral-shared-memory")
        size = snap.get("size")
        if not isinstance(size, int):
            size = len(snap.get("entries") or []) or 0
        coverage = snap.get("coverage")
        if not isinstance(coverage, (int, float)):
            coverage = 0.0
        yield ArchiveSnapshotEvent(
            run_id=resolved_run_id,
            timestamp_ns=_ts_for(snap, started_at, 0),
            payload=ArchiveSnapshotPayload(
                archive_id=archive_id,
                coverage=max(0.0, min(1.0, float(coverage))),
                size=int(size),
                qd_score=(
                    float(snap["qd_score"])
                    if isinstance(snap.get("qd_score"), (int, float))
                    else None
                ),
                max_fitness=(
                    float(snap["max_fitness"])
                    if isinstance(snap.get("max_fitness"), (int, float))
                    else None
                ),
            ),
        )

    if finalize:
        last_ts = max(
            _latest_ts(iterations) or 0,
            _latest_ts(heartbeats) or 0,
            _latest_ts(snapshots) or 0,
            started_at + len(iterations),
        )
        yield RunEndEvent(
            run_id=resolved_run_id,
            timestamp_ns=last_ts + 1,
            payload=RunEndPayload(
                status="finished",
                summary=(
                    f"imported {len(iterations)} CORAL iterations, "
                    f"{len(heartbeats)} heartbeats, {len(snapshots)} memory snapshots"
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
    return f"coral-{root.name or uuid.uuid4().hex[:12]}"


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


def _str(value: Any, default: str | None) -> str:
    if isinstance(value, str) and value:
        return value
    return default if default is not None else ""


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


def _count_agents(iterations: list[dict[str, Any]]) -> int:
    return len({_str(it.get("agent"), "agent-0") for it in iterations})


def _coerce_actor(value: Any) -> SteeringActor:
    if isinstance(value, str) and value in {"human", "agent", "policy"}:
        return value  # type: ignore[return-value]
    return "human"
