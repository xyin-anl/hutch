"""POET environment-agent coevolution adapter.

POET (Wang et al., 2019; `uber-research/poet
<https://github.com/uber-research/poet>`_) coevolves a population of
environments (``BipedalWalker`` variants in the published work) and a
population of agents (neural-net policies). Each generation:

1. Every active environment-agent pair is evaluated; the agent's score
   on its environment becomes the pair's fitness.
2. Some environments mutate, producing new children with their own
   parent agents.
3. Agents periodically transfer between environments — the
   "transferring" operator that gives POET its name.

We accept a JSONL-per-generation dump that captures all of the above::

    poet_run/
    ├── run.json                # name, project, started_at_ns
    └── generations.jsonl       # one record per generation:
                                  # {generation, environments: [...],
                                  #  pairs: [{env_id, agent_id, score, parents}],
                                  #  transfers: [{from_env, to_env, agent_id}]}

The adapter emits one IndividualEvent per environment + per agent (each
gets its own canonical entity), one OperatorEvent for environment
mutations + agent transfers, and one FitnessEvent per evaluated pair.

Two distinct individual kinds are used to keep the dashboard's
phylogeny tidy: environments are ``environment``, agents are ``agent``.
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
    MigrationEvent,
    MigrationPayload,
    OperatorEvent,
    OperatorPayload,
    RunEndEvent,
    RunEndPayload,
    RunStartEvent,
    RunStartPayload,
)

logger = logging.getLogger("hutch.adapters.poet")

_GENERATIONS_NAME = "generations.jsonl"
_RUN_NAME = "run.json"


def detect(path: Path) -> bool:
    """Return ``True`` for a directory containing ``generations.jsonl``."""
    if not path.is_dir():
        return False
    p = path / _GENERATIONS_NAME
    if not p.is_file():
        return False
    try:
        with p.open("r", encoding="utf-8") as fh:
            head = fh.read(2048)
    except OSError:
        return False
    # POET's distinguishing fields: env_id + (transfers OR pairs) + generation.
    return '"generation"' in head and ('"env_id"' in head or '"environments"' in head)


def import_poet(
    path: str | Path,
    *,
    run_id: str | None = None,
    project: str | None = None,
    finalize: bool = True,
) -> Iterator[AnyEvent]:
    """Yield canonical events for a POET dump at *path*."""
    root = Path(path)
    gens_path = root / _GENERATIONS_NAME
    if not gens_path.is_file():
        raise ValueError(f"{root} doesn't contain {_GENERATIONS_NAME}; not a POET dump")

    metadata = _load_metadata(root)
    generations = _load_jsonl(gens_path)
    if not generations:
        raise ValueError(f"{gens_path} contains zero generation records")

    generations.sort(key=lambda r: int(r.get("generation") or 0))

    resolved_run_id = run_id or _derive_run_id(root, metadata)
    project = project or "poet"
    started_at = int(metadata.get("started_at_ns") or _earliest_ts(generations) or time.time_ns())

    yield RunStartEvent(
        run_id=resolved_run_id,
        timestamp_ns=started_at,
        payload=RunStartPayload(
            name=str(metadata.get("name") or root.name or "poet"),
            project=project,
            started_by="poet-importer",
            config={
                "generation_count": len(generations),
                "source_path": str(root.resolve()),
            },
        ),
    )

    seen_envs: set[str] = set()
    seen_agents: set[str] = set()
    population_id = "poet-population"

    for gen_idx, gen in enumerate(generations):
        gen_index = int(gen.get("generation") or gen_idx)
        ts = _ts_for(gen, started_at, gen_idx)

        # Emit environments first so subsequent agent + pair events can
        # reference them.
        for env in _as_dict_list(gen.get("environments")):
            env_id = _str(env.get("id"), "")
            if not env_id or env_id in seen_envs:
                continue
            seen_envs.add(env_id)
            parents = [p for p in _as_str_list(env.get("parents")) if p in seen_envs]
            yield IndividualEvent(
                run_id=resolved_run_id,
                timestamp_ns=ts,
                payload=IndividualPayload(
                    id=env_id,
                    kind="environment",
                    parent_ids=parents,
                    is_seed=len(parents) == 0,
                    population_id=population_id,
                    generation_index=gen_index,
                    metadata={"poet_role": "environment"},
                ),
            )
            if parents:
                yield OperatorEvent(
                    run_id=resolved_run_id,
                    timestamp_ns=ts,
                    payload=OperatorPayload(
                        id=f"op-env-{env_id}",
                        kind="mutate",
                        parent_ids=parents,
                        child_id=env_id,
                        metadata={"poet_role": "environment_mutation"},
                    ),
                )

        # Pairs — emit any new agent that appears, then a fitness event
        # per (env, agent) pair, scoped to the env via stream_id.
        for pair in _as_dict_list(gen.get("pairs")):
            env_id = _str(pair.get("env_id"), "")
            agent_id = _str(pair.get("agent_id"), "")
            if not env_id or not agent_id:
                continue
            if agent_id not in seen_agents:
                seen_agents.add(agent_id)
                agent_parents = [
                    p for p in _as_str_list(pair.get("agent_parents")) if p in seen_agents
                ]
                yield IndividualEvent(
                    run_id=resolved_run_id,
                    timestamp_ns=ts,
                    stream_id=f"env-{env_id}",
                    payload=IndividualPayload(
                        id=agent_id,
                        kind="agent",
                        parent_ids=agent_parents,
                        is_seed=len(agent_parents) == 0,
                        population_id=population_id,
                        island_id=env_id,
                        generation_index=gen_index,
                        metadata={"poet_role": "agent", "initial_env": env_id},
                    ),
                )
                if agent_parents:
                    yield OperatorEvent(
                        run_id=resolved_run_id,
                        timestamp_ns=ts,
                        stream_id=f"env-{env_id}",
                        payload=OperatorPayload(
                            id=f"op-agent-{agent_id}",
                            kind="mutate",
                            parent_ids=agent_parents,
                            child_id=agent_id,
                            metadata={"poet_role": "agent_mutation"},
                        ),
                    )

            score = pair.get("score")
            if isinstance(score, (int, float)) and not isinstance(score, bool):
                yield FitnessEvent(
                    run_id=resolved_run_id,
                    timestamp_ns=ts,
                    stream_id=f"env-{env_id}",
                    payload=FitnessPayload(
                        individual_id=agent_id,
                        evaluator_id=env_id,
                        evaluator_kind="simulator",
                        scores={"score": float(score)},
                        composite=float(score),
                    ),
                )

        # Transfers: agent X moves from env A to env B. Mirror the canonical
        # MigrationEvent (for the population) plus an OperatorEvent (for the
        # lineage edge — kind=migrate).
        for tr in _as_dict_list(gen.get("transfers")):
            from_env = _str(tr.get("from_env"), "")
            to_env = _str(tr.get("to_env"), "")
            agent_id = _str(tr.get("agent_id"), "")
            if not (from_env and to_env and agent_id):
                continue
            yield MigrationEvent(
                run_id=resolved_run_id,
                timestamp_ns=ts,
                payload=MigrationPayload(
                    population_id=population_id,
                    from_island=from_env,
                    to_island=to_env,
                    individual_ids=[agent_id],
                    trigger="poet_transfer",
                ),
            )

    if finalize:
        last_ts = _latest_ts(generations) or (started_at + len(generations) + 1)
        yield RunEndEvent(
            run_id=resolved_run_id,
            timestamp_ns=max(last_ts, started_at + 1),
            payload=RunEndPayload(
                status="finished",
                summary=(
                    f"imported {len(generations)} POET generations: "
                    f"{len(seen_envs)} environments, {len(seen_agents)} agents"
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
    return f"poet-{root.name or uuid.uuid4().hex[:12]}"


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


def _as_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(v) for v in value if v is not None]


def _as_dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [v for v in value if isinstance(v, dict)]


def _str(value: Any, default: str) -> str:
    return value if isinstance(value, str) and value else default
