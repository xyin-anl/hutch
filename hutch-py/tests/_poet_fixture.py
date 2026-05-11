"""Synthetic POET coevolution dump for tests + examples."""

from __future__ import annotations

import json
import random
from pathlib import Path


def make_run(
    target_dir: Path,
    *,
    seed: int = 17,
    num_generations: int = 6,
    initial_envs: int = 3,
) -> Path:
    """Write a synthetic POET run rooted at *target_dir*. Returns the dir."""
    rng = random.Random(seed)
    target_dir.mkdir(parents=True, exist_ok=True)

    base_ts = 1_700_000_000_000_000_000
    env_ids: list[str] = [f"env-{i}" for i in range(initial_envs)]
    agent_ids: list[str] = [f"agent-{i}" for i in range(initial_envs)]

    generations: list[dict] = []

    # Generation 0: seed envs and one agent per env.
    generations.append(
        {
            "generation": 0,
            "environments": [{"id": eid, "parents": []} for eid in env_ids],
            "pairs": [
                {
                    "env_id": env_ids[i],
                    "agent_id": agent_ids[i],
                    "agent_parents": [],
                    "score": round(0.3 + 0.2 * rng.random(), 4),
                }
                for i in range(initial_envs)
            ],
            "transfers": [],
            "timestamp_ns": base_ts,
        }
    )

    next_env_idx = initial_envs
    next_agent_idx = initial_envs
    for g in range(1, num_generations):
        # Mutate one env (children environment).
        new_envs: list[dict] = []
        if rng.random() < 0.7:
            parent = rng.choice(env_ids)
            child = f"env-{next_env_idx}"
            next_env_idx += 1
            env_ids.append(child)
            new_envs.append({"id": child, "parents": [parent]})

        # Existing agents may also produce children.
        new_pairs: list[dict] = []
        for eid in env_ids:
            agent_for_env = next(
                (aid for aid in agent_ids if aid.endswith(eid.split("-")[-1])),
                rng.choice(agent_ids),
            )
            if rng.random() < 0.4:
                child_agent = f"agent-{next_agent_idx}"
                next_agent_idx += 1
                agent_ids.append(child_agent)
                new_pairs.append(
                    {
                        "env_id": eid,
                        "agent_id": child_agent,
                        "agent_parents": [agent_for_env],
                        "score": round(0.3 + 0.4 * rng.random(), 4),
                    }
                )
            else:
                new_pairs.append(
                    {
                        "env_id": eid,
                        "agent_id": agent_for_env,
                        "agent_parents": [],
                        "score": round(0.3 + 0.4 * rng.random(), 4),
                    }
                )

        # Occasionally transfer an agent.
        transfers: list[dict] = []
        if g >= 2 and len(env_ids) >= 2 and rng.random() < 0.6:
            from_env, to_env = rng.sample(env_ids, 2)
            transfers.append(
                {
                    "from_env": from_env,
                    "to_env": to_env,
                    "agent_id": rng.choice(agent_ids),
                }
            )

        generations.append(
            {
                "generation": g,
                "environments": new_envs,
                "pairs": new_pairs,
                "transfers": transfers,
                "timestamp_ns": base_ts + g * 1_000_000_000,
            }
        )

    gens_path = target_dir / "generations.jsonl"
    with gens_path.open("w", encoding="utf-8") as fh:
        for gen in generations:
            fh.write(json.dumps(gen) + "\n")

    (target_dir / "run.json").write_text(
        json.dumps(
            {
                "name": target_dir.name or "poet-toy",
                "project": "poet",
                "started_at_ns": base_ts,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return target_dir
