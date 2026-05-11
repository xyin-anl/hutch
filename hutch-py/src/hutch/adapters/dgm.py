"""DGM checkpoint adapter.

Reads the on-disk format produced by the [DGM](https://github.com/jennyzzt/dgm)
implementation and emits canonical Hutch events. The format is documented
informally; we read what we find:

::

    output_dgm/
        <commit_id>/
            metadata.json   # parent_commit, accuracy_score, overall_performance,
                            # overseer_verdict, proposal, generation, …
        <commit_id>/...
    dgm_metadata.jsonl       # one record per generation: {generation, archive,
                            # children, children_compiled, …}

Per agent the adapter emits:

* :class:`IndividualEvent` (kind=``agent``) with parent linkage.
* :class:`OperatorEvent` (kind=``self_modify``) when a parent_commit is set.
* :class:`SelfModEvent` carrying the proposal, overseer verdict, and the
  before/after benchmark scores.
* :class:`FitnessEvent` over whichever scalar metrics the agent recorded.

Anything we can't find is left empty per the project-wide "permissive about
missing fields" rule.
"""

from __future__ import annotations

import json
import logging
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
    SelfModEvent,
    SelfModPayload,
)
from hutch.schema.types import SelfModVerdict

logger = logging.getLogger("hutch.adapters.dgm")


def detect(path: Path) -> bool:
    """A DGM run dir contains either ``output_dgm/`` or a sibling
    ``dgm_metadata.jsonl``."""
    if not path.is_dir():
        return False
    has_output = (path / "output_dgm").is_dir() or path.name == "output_dgm"
    has_meta = (path / "dgm_metadata.jsonl").is_file()
    return has_output or has_meta


def import_dgm(
    path: str | Path,
    *,
    run_id: str | None = None,
    project: str | None = None,
) -> Iterator[AnyEvent]:
    """Yield canonical events for the DGM run at *path*."""
    root = Path(path)
    if not detect(root):
        raise ValueError(
            f"{root} doesn't look like a DGM run "
            f"(no output_dgm/ subdirectory or dgm_metadata.jsonl)."
        )
    output_dgm = root if root.name == "output_dgm" else root / "output_dgm"
    if not output_dgm.is_dir():
        # fall back: maybe the user pointed at output_dgm/ already
        output_dgm = root
    agents = list(_load_agents(output_dgm))
    generations = _load_generations(root)

    resolved_run_id = run_id or f"dgm-{root.name}"
    project = project or "dgm"

    started_at = _earliest_ctime_ns(agents)
    yield RunStartEvent(
        run_id=resolved_run_id,
        timestamp_ns=started_at,
        payload=RunStartPayload(
            name=root.name,
            project=project,
            started_by="dgm-importer",
            config={
                "num_agents": len(agents),
                "generations": len(generations),
                "checkpoint_path": str(root.resolve()),
            },
        ),
    )

    # Sort agents by generation, then by ctime for stable ordering.
    agents.sort(key=lambda a: (a.get("generation") or 0, a.get("ctime_ns") or 0, a.get("id") or ""))

    parent_score: dict[str, float | None] = {}
    for agent in agents:
        agent_id = agent["id"]
        parent_id = agent.get("parent_commit")
        is_seed = parent_id is None
        ts = int(agent.get("ctime_ns") or 0)
        score = _agent_main_score(agent)
        scores = _agent_scores(agent)

        yield IndividualEvent(
            run_id=resolved_run_id,
            timestamp_ns=ts,
            payload=IndividualPayload(
                id=agent_id,
                kind="agent",
                parent_ids=[parent_id] if parent_id else [],
                is_seed=is_seed,
                generation_index=agent.get("generation"),
                metadata={
                    "proposal": agent.get("proposal"),
                    "compiled": agent.get("compiled"),
                    "raw_metadata_path": agent.get("path"),
                },
            ),
        )

        if parent_id:
            yield OperatorEvent(
                run_id=resolved_run_id,
                timestamp_ns=ts,
                payload=OperatorPayload(
                    id=f"op-{agent_id}",
                    kind="self_modify",
                    parent_ids=[parent_id],
                    child_id=agent_id,
                    metadata={"proposal": agent.get("proposal")},
                ),
            )
            yield SelfModEvent(
                run_id=resolved_run_id,
                timestamp_ns=ts,
                payload=SelfModPayload(
                    parent_agent_id=parent_id,
                    child_agent_id=agent_id,
                    target_path=agent.get("target_path"),
                    diff_uri=agent.get("diff_uri"),
                    proposal=agent.get("proposal"),
                    overseer_id=agent.get("overseer_id"),
                    overseer_verdict=_normalize_verdict(agent.get("overseer_verdict")),
                    benchmark=agent.get("benchmark"),
                    score_before=parent_score.get(parent_id),
                    score_after=score,
                ),
            )

        if scores:
            yield FitnessEvent(
                run_id=resolved_run_id,
                timestamp_ns=ts,
                payload=FitnessPayload(
                    individual_id=agent_id,
                    evaluator_kind="benchmark",
                    scores=scores,
                    composite=score,
                ),
            )
        parent_score[agent_id] = score

    last_ts = _latest_ctime_ns(agents)
    yield RunEndEvent(
        run_id=resolved_run_id,
        timestamp_ns=max(last_ts, started_at + 1),
        payload=RunEndPayload(
            status="finished",
            summary=f"imported {len(agents)} agents from {root.name}",
        ),
    )


# ---------- helpers --------------------------------------------------------


def _load_agents(output_dgm: Path) -> Iterator[dict[str, Any]]:
    if not output_dgm.is_dir():
        return
    for child in sorted(output_dgm.iterdir()):
        if not child.is_dir():
            continue
        meta = child / "metadata.json"
        if not meta.is_file():
            continue
        try:
            data = json.loads(meta.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            logger.warning("skipping unreadable metadata at %s: %s", meta, exc)
            continue
        if not isinstance(data, dict):
            continue
        data["id"] = data.get("commit_id") or child.name
        data["path"] = str(meta)
        if isinstance(data.get("ctime"), (int, float)):
            data["ctime_ns"] = int(float(data["ctime"]) * 1_000_000_000)
        yield data


def _load_generations(root: Path) -> list[dict[str, Any]]:
    p = root / "dgm_metadata.jsonl"
    if not p.is_file():
        return []
    out: list[dict[str, Any]] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(rec, dict):
            out.append(rec)
    return out


def _agent_scores(agent: dict[str, Any]) -> dict[str, float]:
    scores: dict[str, float] = {}
    for key in (
        "accuracy_score",
        "overall_performance",
        "compile_rate",
        "polyglot_score",
        "swe_bench",
    ):
        value = agent.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            scores[key] = float(value)
    return scores


def _agent_main_score(agent: dict[str, Any]) -> float | None:
    for key in ("overall_performance", "accuracy_score", "swe_bench"):
        v = agent.get(key)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return float(v)
    return None


def _normalize_verdict(value: Any) -> SelfModVerdict:
    if isinstance(value, str):
        v = value.strip().lower()
        if v in {"accepted", "accept", "approved"}:
            return "accepted"
        if v in {"rejected", "reject", "denied"}:
            return "rejected"
    return "pending"


def _earliest_ctime_ns(agents: list[dict[str, Any]]) -> int:
    candidates = [int(a.get("ctime_ns") or 0) for a in agents]
    candidates = [c for c in candidates if c > 0]
    return min(candidates) if candidates else 0


def _latest_ctime_ns(agents: list[dict[str, Any]]) -> int:
    candidates = [int(a.get("ctime_ns") or 0) for a in agents]
    candidates = [c for c in candidates if c > 0]
    return max(candidates) if candidates else 0
