"""Synthetic ShinkaEvolve dump for tests + examples."""

from __future__ import annotations

import json
import random
from pathlib import Path

_OPERATORS = ("mutate", "crossover", "refine", "diversify")


def make_run(
    target_dir: Path,
    *,
    seed: int = 31,
    num_candidates: int = 20,
    num_generations: int = 4,
    num_meta_mutations: int = 2,
) -> Path:
    rng = random.Random(seed)
    target_dir.mkdir(parents=True, exist_ok=True)

    base_ts = 1_700_000_000_000_000_000

    # Meta-mutations chain: meta-0 (seed) -> meta-1 -> meta-2 ...
    meta_mutations: list[dict] = []
    for m in range(num_meta_mutations):
        meta_mutations.append(
            {
                "id": f"meta-{m}",
                "parents": [] if m == 0 else [f"meta-{m - 1}"],
                "description": f"adjust mutation rate (round {m})",
                "timestamp_ns": base_ts + m * 100_000_000,
            }
        )
    if meta_mutations:
        meta_path = target_dir / "meta_mutations.jsonl"
        with meta_path.open("w", encoding="utf-8") as fh:
            for m in meta_mutations:
                fh.write(json.dumps(m) + "\n")

    # Candidates: per generation, sample parents from the previous generation.
    candidates: list[dict] = []
    prev_gen_ids: list[str] = []
    per_gen = max(1, num_candidates // num_generations)

    for g in range(num_generations):
        new_gen_ids: list[str] = []
        for k in range(per_gen):
            cand_id = f"cand-{g}-{k:02d}"
            if g == 0 or not prev_gen_ids:
                parents: list[str] = []
                op = "refine"
            elif rng.random() < 0.18 and len(prev_gen_ids) >= 2:
                parents = rng.sample(prev_gen_ids, 2)
                op = "crossover"
            else:
                parents = [rng.choice(prev_gen_ids)]
                op = rng.choice(("mutate", "refine", "diversify"))
            kind = "program" if rng.random() < 0.65 else "prompt"
            candidates.append(
                {
                    "id": cand_id,
                    "kind": kind,
                    "operator": op,
                    "parents": parents,
                    "score": round(0.4 + 0.4 * rng.random(), 4),
                    "evaluator": "shinka-bench",
                    "generation": g,
                    "shinka_iteration": g * per_gen + k,
                    "timestamp_ns": base_ts + (g * per_gen + k + 1) * 100_000_000,
                }
            )
            new_gen_ids.append(cand_id)
        prev_gen_ids = new_gen_ids

    cand_path = target_dir / "candidates.jsonl"
    with cand_path.open("w", encoding="utf-8") as fh:
        for c in candidates:
            fh.write(json.dumps(c) + "\n")

    (target_dir / "run.json").write_text(
        json.dumps(
            {
                "name": target_dir.name or "shinka-toy",
                "project": "shinka-evolve",
                "started_at_ns": base_ts,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return target_dir
