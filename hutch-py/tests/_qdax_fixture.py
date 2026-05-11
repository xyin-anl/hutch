"""Generate a synthetic QDax-shaped JSON repertoire for tests + examples."""

from __future__ import annotations

import json
import math
import random
from pathlib import Path
from typing import Any


def make_repertoire(
    target_path: Path,
    *,
    seed: int = 11,
    grid_side: int = 8,
    fill_fraction: float = 0.45,
    descriptor_dims: tuple[str, str] = ("complexity", "speed"),
    objective_name: str = "fitness",
) -> Path:
    """Write a synthetic ``repertoire.json`` to *target_path*.

    The grid is ``grid_side**2`` cells with ``fill_fraction`` of them filled
    by a toy fitness gradient. Roughly half of the filled cells declare a
    ``parent`` cell so the lineage graph in the dashboard isn't all seeds.
    """
    rng = random.Random(seed)
    target_path.parent.mkdir(parents=True, exist_ok=True)

    num_cells = grid_side * grid_side
    fitnesses: list[float] = [float("-inf")] * num_cells
    centroids: list[list[float]] = []
    descriptors: list[list[float]] = []
    parents: list[int | None] = [None] * num_cells

    for idx in range(num_cells):
        cx = (idx % grid_side) / grid_side
        cy = (idx // grid_side) / grid_side
        centroids.append([cx, cy])
        descriptors.append([cx + rng.uniform(-0.01, 0.01), cy + rng.uniform(-0.01, 0.01)])

    filled_indices = rng.sample(range(num_cells), int(num_cells * fill_fraction))
    for fill_idx, cell_idx in enumerate(filled_indices):
        cx, cy = centroids[cell_idx]
        # Toy fitness landscape: peak near (0.7, 0.4), noisy elsewhere.
        peak = 1.0 - math.hypot(cx - 0.7, cy - 0.4)
        noise = rng.uniform(-0.1, 0.1)
        fitnesses[cell_idx] = max(0.0, peak + noise)

        # Roughly half the filled cells point at a previously-filled parent.
        if fill_idx > 0 and rng.random() < 0.55:
            parents[cell_idx] = filled_indices[rng.randrange(fill_idx)]

    payload: dict[str, Any] = {
        "centroids": centroids,
        "fitnesses": [float(f) if math.isfinite(f) else None for f in fitnesses],
        "descriptors": descriptors,
        "parents": parents,
        "metadata": {
            "name": target_path.parent.name or "qdax-toy",
            "archive_id": "qdax-grid",
            "kind": "grid",
            "objective_name": objective_name,
            "descriptor_dims": list(descriptor_dims),
        },
    }
    target_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return target_path
