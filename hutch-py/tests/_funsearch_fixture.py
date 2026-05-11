"""Synthetic FunSearch programs.jsonl dump for tests + examples."""

from __future__ import annotations

import json
import random
from pathlib import Path


def make_dump(
    target_dir: Path,
    *,
    seed: int = 13,
    num_programs: int = 24,
    num_islands: int = 3,
    problem: str = "cap_set",
) -> Path:
    """Write a synthetic FunSearch dump rooted at *target_dir*. Returns the dir."""
    rng = random.Random(seed)
    target_dir.mkdir(parents=True, exist_ok=True)

    base_ts = 1_700_000_000_000_000_000
    programs: list[dict] = []

    # Seed each island with a distinct generation-0 program.
    for island in range(num_islands):
        programs.append(
            {
                "id": island,
                "code": f"def priority_{island}(x): return x[0]",
                "score": round(0.4 + 0.05 * island + rng.random() * 0.05, 4),
                "parents": [],
                "island_id": island,
                "generation": 0,
                "evaluator": problem,
                "timestamp_ns": base_ts + island * 1_000_000_000,
            }
        )

    # Subsequent generations sample one parent per program (occasionally two).
    for i in range(num_islands, num_programs):
        island = rng.randrange(num_islands)
        # Pick parent(s) from same island.
        same_island = [p["id"] for p in programs if p["island_id"] == island]
        parents: list[int]
        if not same_island:
            parents = []
        elif rng.random() < 0.18 and len(same_island) >= 2:
            parents = rng.sample(same_island, 2)
        else:
            parents = [rng.choice(same_island)]
        gen = max((p["generation"] for p in programs if p["id"] in parents), default=0) + 1
        programs.append(
            {
                "id": i,
                "code": f"def priority_{i}(x): return x[0] + {i}",
                "score": round(0.4 + 0.4 * rng.random(), 4),
                "parents": parents,
                "island_id": island,
                "generation": gen,
                "evaluator": problem,
                "timestamp_ns": base_ts + (i + 1) * 1_000_000_000,
            }
        )

    programs_path = target_dir / "programs.jsonl"
    with programs_path.open("w", encoding="utf-8") as fh:
        for p in programs:
            fh.write(json.dumps(p) + "\n")

    runs_path = target_dir / "runs.json"
    runs_path.write_text(
        json.dumps(
            {
                "name": target_dir.name or "funsearch-toy",
                "problem": problem,
                "started_at_ns": base_ts,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return target_dir
