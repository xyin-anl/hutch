"""Synthetic ptychi-evolve dump for tests + examples."""

from __future__ import annotations

import json
import random
from pathlib import Path


def make_run(
    target_dir: Path,
    *,
    seed: int = 23,
    num_rounds: int = 5,
    pop_size: int = 6,
) -> Path:
    rng = random.Random(seed)
    target_dir.mkdir(parents=True, exist_ok=True)

    base_ts = 1_700_000_000_000_000_000
    rounds: list[dict] = []
    prev_pop_ids: list[str] = []
    next_id = 0

    for r in range(num_rounds):
        pop = []
        for _ in range(pop_size):
            ind_id = f"recon-{next_id:03d}"
            next_id += 1
            parent = rng.choice(prev_pop_ids) if prev_pop_ids and rng.random() > 0.05 else None
            pop.append(
                {
                    "id": ind_id,
                    "parent": parent,
                    "code": f"# reconstruction algo at round {r}",
                    "metrics": {
                        # Lower is better for both; ptychi-evolve treats them as
                        # the search objective.
                        "nrmse": round(0.30 - 0.04 * r + rng.uniform(-0.02, 0.05), 4),
                        "time_s": round(2.0 - 0.2 * r + rng.uniform(-0.3, 0.5), 3),
                    },
                }
            )
        rounds.append(
            {
                "round": r,
                "individuals": pop,
                "timestamp_ns": base_ts + r * 1_000_000_000,
            }
        )
        prev_pop_ids = [p["id"] for p in pop]

    rounds_path = target_dir / "rounds.jsonl"
    with rounds_path.open("w", encoding="utf-8") as fh:
        for rnd in rounds:
            fh.write(json.dumps(rnd) + "\n")

    (target_dir / "run.json").write_text(
        json.dumps(
            {
                "name": target_dir.name or "ptychi-toy",
                "project": "ptychi-evolve",
                "started_at_ns": base_ts,
                "dataset": "siemens-star-toy",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return target_dir
