"""Quality-Diversity / MAP-Elites loop.

Demonstrates Individual + Operator(mutate) + Fitness + Descriptor for a
2D MAP-Elites grid. The Archive view in the Hutch dashboard reads the
descriptor events to render the heat map.
"""

from __future__ import annotations

import random

import hutch as h


def cell_key(coords: tuple[float, float]) -> str:
    return f"({coords[0]:.2f},{coords[1]:.2f})"


def evaluate(seed: int) -> tuple[dict[str, float], tuple[float, float]]:
    rng = random.Random(seed)
    fitness = {"sum_radii": round(0.4 + 0.5 * rng.random(), 3)}
    descriptors = (round(rng.random(), 3), round(rng.random(), 3))
    return fitness, descriptors


def main(steps: int = 40) -> None:
    h.start_run(name="map-elites-toy", project="hutch-skill-examples")
    archive_id = "me-toy"

    population: list = []
    rng = random.Random(7)
    for step in range(steps):
        parent = rng.choice(population) if population else None
        ind = h.log_individual(
            kind="program",
            parent_ids=[parent.id] if parent else [],
        )
        if parent is not None:
            h.log_operator(
                kind="mutate", parent_ids=[parent.id], child_id=ind.id
            )
        fitness, descriptors = evaluate(step)
        h.log_fitness(individual=ind, scores=fitness)
        h.log_descriptor(
            individual=ind,
            archive_id=archive_id,
            coordinates=list(descriptors),
            cell_id=cell_key(descriptors),
        )
        population.append(ind)

    h.end_run()


if __name__ == "__main__":
    main()
