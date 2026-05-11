"""Synthetic CORAL run dump for tests + examples.

Mirrors the multi-agent / heartbeat / shared-memory structure described
in the CORAL paper (arXiv:2604.01658) without depending on the upstream
repo's specific serialiser.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

_AGENTS = ("researcher-0", "engineer-1", "analyst-2", "researcher-3")
_KINDS = ("propose", "edit", "review", "mutate")


def make_run(
    target_dir: Path,
    *,
    seed: int = 7,
    num_iterations: int = 24,
    num_heartbeats: int = 4,
    num_memory_snapshots: int = 3,
) -> Path:
    """Write a synthetic CORAL run rooted at *target_dir*. Returns the dir."""
    rng = random.Random(seed)
    target_dir.mkdir(parents=True, exist_ok=True)

    base_ts = 1_700_000_000_000_000_000

    iterations: list[dict] = []
    for i in range(num_iterations):
        agent = rng.choice(_AGENTS)
        kind = "propose" if i < len(_AGENTS) else rng.choice(_KINDS)
        parents: list[str] = []
        if i >= len(_AGENTS):
            # Pick one or two parents from any earlier iteration of the same agent
            # (or anyone, with smaller probability).
            same_agent = [it["id"] for it in iterations if it["agent"] == agent]
            pool = (
                same_agent if same_agent and rng.random() < 0.6 else [it["id"] for it in iterations]
            )
            if pool:
                if rng.random() < 0.18 and len(pool) >= 2:
                    parents = rng.sample(pool, 2)
                else:
                    parents = [rng.choice(pool)]
        iterations.append(
            {
                "id": f"iter-{i:03d}",
                "agent": agent,
                "kind": kind,
                "parents": parents,
                "code": f"# step {i} by {agent}",
                "score": round(0.4 + 0.5 * rng.random(), 4),
                "evaluator": "coral-eval",
                "timestamp_ns": base_ts + i * 1_000_000_000,
            }
        )

    iters_path = target_dir / "iterations.jsonl"
    with iters_path.open("w", encoding="utf-8") as fh:
        for it in iterations:
            fh.write(json.dumps(it) + "\n")

    # Heartbeats: a mix of pause/resume/inject_hint/cancel_individual.
    heartbeats: list[dict] = []
    commands_pool = ("pause_run", "resume_run", "inject_hint", "cancel_individual")
    for j in range(num_heartbeats):
        cmd = rng.choice(commands_pool)
        target_agent = rng.choice(_AGENTS) if cmd != "pause_run" else None
        params: dict = {}
        if cmd == "inject_hint":
            params = {"text": "consider the off-by-one case"}
        heartbeats.append(
            {
                "command": cmd,
                "agent": target_agent,
                "actor": rng.choice(("human", "policy")),
                "params": params,
                "timestamp_ns": base_ts + (num_iterations + j) * 1_000_000_000,
            }
        )
    hb_path = target_dir / "heartbeats.jsonl"
    with hb_path.open("w", encoding="utf-8") as fh:
        for hb in heartbeats:
            fh.write(json.dumps(hb) + "\n")

    # Shared-memory snapshots.
    snapshots: list[dict] = []
    for k in range(num_memory_snapshots):
        snapshots.append(
            {
                "archive_id": "coral-shared-memory",
                "size": 8 + 4 * k,
                "coverage": min(1.0, 0.3 + 0.2 * k),
                "qd_score": round(0.5 + 0.4 * rng.random(), 4),
                "max_fitness": round(0.7 + 0.2 * rng.random(), 4),
                "timestamp_ns": base_ts + (num_iterations + num_heartbeats + k) * 1_000_000_000,
            }
        )
    snap_path = target_dir / "memory_snapshots.jsonl"
    with snap_path.open("w", encoding="utf-8") as fh:
        for s in snapshots:
            fh.write(json.dumps(s) + "\n")

    (target_dir / "run.json").write_text(
        json.dumps(
            {
                "name": target_dir.name or "coral-toy",
                "project": "coral",
                "started_at_ns": base_ts,
                "agents": list(_AGENTS),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return target_dir
