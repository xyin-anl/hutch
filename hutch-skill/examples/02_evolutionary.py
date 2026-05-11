"""Evolutionary loop — multi-island, OpenEvolve-style.

Demonstrates a population-based search with islands, generations, and
mutation/crossover operators.
"""

from __future__ import annotations

import random

import hutch as h


def evaluate(individual_id: str) -> dict[str, float]:
    rng = random.Random(hash(individual_id) & 0xFFFF)
    return {"sum_radii": round(0.3 + 0.6 * rng.random(), 3)}


def main(num_islands: int = 3, generations: int = 4) -> None:
    h.start_run(name="circle-packing", project="hutch-skill-examples")
    pop = h.start_population(name="cp", kind="island", num_islands=num_islands)

    parents: list[list] = []
    for island_idx in range(num_islands):
        seed = h.log_individual(
            kind="program",
            island_id=str(island_idx),
            generation_index=0,
            population_id=pop.id,
        )
        h.log_fitness(individual=seed, scores=evaluate(seed.id))
        parents.append([seed])

    rng = random.Random(7)
    for gen in range(1, generations + 1):
        next_parents: list[list] = []
        for island_idx in range(num_islands):
            island_parents = parents[island_idx]
            children = []
            for parent in island_parents:
                child = h.log_individual(
                    kind="program",
                    parent_ids=[parent.id],
                    island_id=str(island_idx),
                    generation_index=gen,
                    population_id=pop.id,
                )
                h.log_operator(
                    kind="mutate", parent_ids=[parent.id], child_id=child.id
                )
                h.log_fitness(individual=child, scores=evaluate(child.id))
                children.append(child)

                # Occasional cross-island crossover.
                if rng.random() < 0.2 and num_islands >= 2:
                    other = rng.choice(
                        [
                            p
                            for j, ip in enumerate(parents)
                            if j != island_idx
                            for p in ip
                        ]
                    )
                    crossed = h.log_individual(
                        kind="program",
                        parent_ids=[parent.id, other.id],
                        island_id=str(island_idx),
                        generation_index=gen,
                        population_id=pop.id,
                    )
                    h.log_operator(
                        kind="crossover",
                        parent_ids=[parent.id, other.id],
                        child_id=crossed.id,
                    )
                    h.log_fitness(individual=crossed, scores=evaluate(crossed.id))
                    children.append(crossed)
            next_parents.append(children)
        parents = next_parents

    h.end_run()


if __name__ == "__main__":
    main()
