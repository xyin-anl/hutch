"""MAP-Elites on a toy 2D fitness landscape — Layer 2 demo.

50ish lines of MAP-Elites that exercise the full quality-diversity surface
of Hutch's schema: Individual, Operator(mutate), Fitness, Descriptor with
2D grid coordinates. Run this against ``hutch serve`` and the Archive view
will populate as the run progresses.

Real-world MAP-Elites runs would have a meaningful objective and meaningful
descriptors; this one uses a Rastrigin-like fitness with two random-projection
descriptors so the dashboard ends up with a colorful grid.

Usage::

    HUTCH_DB_PATH=/tmp/example05.duckdb python run.py
    # or, against a running daemon:
    hutch serve --db /tmp/example05.duckdb &
    python run.py
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

import hutch as h

GRID_RES = 16


@dataclass(frozen=True, slots=True)
class Genome:
    x: float
    y: float
    z: float


def random_genome(rng: random.Random) -> Genome:
    return Genome(rng.uniform(-1, 1), rng.uniform(-1, 1), rng.uniform(-1, 1))


def mutate(g: Genome, rng: random.Random, sigma: float = 0.2) -> Genome:
    return Genome(
        max(-1, min(1, g.x + rng.gauss(0, sigma))),
        max(-1, min(1, g.y + rng.gauss(0, sigma))),
        max(-1, min(1, g.z + rng.gauss(0, sigma))),
    )


def fitness(g: Genome) -> float:
    """Smooth bowl with a few peaks — high near (0.6, 0.6, 0.0)."""
    bowl = -(g.x - 0.6) ** 2 - (g.y - 0.6) ** 2 - (g.z * 0.5) ** 2
    ripple = 0.05 * math.cos(6 * g.x) * math.cos(6 * g.y)
    return float(max(0.0, 1.0 + bowl + ripple))


def descriptor(g: Genome) -> tuple[float, float]:
    """Two coarse behavioural descriptors in [0, 1]^2."""
    return ((g.x + 1) / 2, (g.y + 1) / 2)


def cell_id(coords: tuple[float, float]) -> str:
    return f"({int(coords[0] * GRID_RES)},{int(coords[1] * GRID_RES)})"


def main(steps: int = 200) -> None:
    rng = random.Random(11)
    # Archive: cell_id -> (parent_individual_id, parent_genome, fitness)
    archive: dict[str, tuple[str, Genome, float]] = {}

    h.start_run(
        name="map-elites-toy",
        project="hutch-examples",
        score_directions={"fitness": "higher"},
    )
    archive_id = "me-toy"

    for step in range(steps):
        parent_id: str | None = None
        if archive and rng.random() >= 0.1 and step >= 5:
            parent_id, parent_genome, _ = rng.choice(list(archive.values()))
            g = mutate(parent_genome, rng)
        else:
            g = random_genome(rng)

        ind = h.log_individual(
            kind="program",
            parent_ids=[parent_id] if parent_id else [],
            generation_index=step,
            metadata={"genome": [g.x, g.y, g.z]},
        )
        if parent_id is not None:
            h.log_operator(kind="mutate", parent_ids=[parent_id], child_id=ind.id)

        f = fitness(g)
        h.log_fitness(individual=ind, scores={"fitness": f})

        coords = descriptor(g)
        cid = cell_id(coords)
        h.log_descriptor(
            individual=ind,
            archive_id=archive_id,
            coordinates=list(coords),
            cell_id=cid,
            is_replaced=cid in archive and f > archive[cid][2],
        )
        if cid not in archive or f > archive[cid][2]:
            archive[cid] = (ind.id, g, f)

    h.end_run()
    print(f"finished MAP-Elites toy: {steps} samples, {len(archive)} cells filled.")


if __name__ == "__main__":
    main()
