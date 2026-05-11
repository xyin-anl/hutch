"""Generate a synthetic ASI-ARCH experiment dump for tests + examples.

Mimics the structure of records emitted by ASI-ARCH's MongoDB
``mongoexport``: one experiment per JSONL line with ``index`` / ``parent``
/ ``score`` / ``agent`` fields plus a few free-form text fields.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

_AGENTS = ("researcher", "engineer", "analyst")


def make_dump(
    target_path: Path,
    *,
    seed: int = 42,
    num_experiments: int = 30,
    branching_factor: int = 3,
) -> Path:
    """Write a synthetic ``experiments.jsonl`` dump to *target_path* and
    return the path. Generates a tree of architectures rooted at index 1
    so the lineage view has something interesting to render.
    """
    rng = random.Random(seed)
    target_path.parent.mkdir(parents=True, exist_ok=True)

    records: list[dict[str, object]] = []
    base_ts = 1_700_000_000_000_000_000
    for i in range(1, num_experiments + 1):
        if i == 1:
            parent = 0  # root
        else:
            # Pick a parent within the last `branching_factor` candidates so
            # the tree fans out a bit.
            recent = max(1, i - branching_factor * 2)
            parent = rng.randint(recent, i - 1)
        agent = _AGENTS[(i - 1) % len(_AGENTS)]
        score = round(0.4 + 0.5 * rng.random(), 4)
        loss = round(2.5 + 1.5 * rng.random(), 4)
        rec = {
            "index": i,
            "parent": parent,
            "name": f"Arch-{i:03d}",
            "agent": agent,
            "score": score,
            "loss": loss,
            "scores": {"score": score, "loss": loss},
            "timestamp_ns": base_ts + i * 60_000_000_000,
            "motivation": (
                f"Experiment {i} explores adjustments to layer-{rng.randint(1, 8)} "
                f"based on the parent's analysis of compute-vs-quality trade-offs."
            ),
            "analysis": (
                f"Score moved {'up' if rng.random() > 0.5 else 'down'} "
                f"by {rng.uniform(0.01, 0.1):.3f} relative to the parent."
            ),
            "verdict": rng.choice(["accepted", "rejected", "pending"]),
        }
        records.append(rec)

    with target_path.open("w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r) + "\n")
    return target_path
