"""Multi-operator evolutionary loop — mutation + crossover + selection.

Demonstrates that the dashboard differentiates the three classic
evolutionary operators (`mutate`, `crossover`, `select`) when an SDK-direct
loop emits them with the right kind labels. The Operator-trace view
color-codes each kind, the Phylogeny view dashes crossover edges (children
with two parents), and the Overview infers `evolutionary` from the
operator kinds.

Most evolutionary frameworks that ship publicly (OpenEvolve, AlphaEvolve)
don't preserve mutate-vs-crossover labels in their checkpoints — the
adapters fall back to ``refine``. To get the rich operator picture, log
events via the Hutch SDK directly (this example) or via a Skill-driven
agent that follows ``hutch-skill/SKILL.md``.

Usage::

    HUTCH_DB_PATH=/tmp/example06.duckdb python run.py
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

import hutch as h
from hutch.schema import IndividualPayload


@dataclass(frozen=True, slots=True)
class Genome:
    x: float
    y: float


def random_genome(rng: random.Random) -> Genome:
    return Genome(rng.uniform(-1, 1), rng.uniform(-1, 1))


def fitness(g: Genome) -> float:
    """Smooth bowl with a small ripple — peak near (0.4, 0.7)."""
    bowl = -((g.x - 0.4) ** 2 + (g.y - 0.7) ** 2)
    ripple = 0.05 * math.sin(5 * g.x) * math.sin(5 * g.y)
    return float(max(0.0, 1.0 + bowl + ripple))


def mutate_genome(g: Genome, rng: random.Random, sigma: float = 0.2) -> Genome:
    return Genome(
        max(-1, min(1, g.x + rng.gauss(0, sigma))),
        max(-1, min(1, g.y + rng.gauss(0, sigma))),
    )


def crossover_genome(a: Genome, b: Genome, rng: random.Random) -> Genome:
    """Whole-arithmetic crossover: child = α·a + (1-α)·b."""
    alpha = rng.uniform(0.2, 0.8)
    return Genome(alpha * a.x + (1 - alpha) * b.x, alpha * a.y + (1 - alpha) * b.y)


def main(
    num_islands: int = 4,
    generations: int = 8,
    population_size: int = 6,
    crossover_rate: float = 0.35,
    select_rate: float = 0.25,
) -> None:
    rng = random.Random(13)
    h.start_run(
        name="evo-multi-operator",
        project="hutch-examples",
        score_directions={"fitness": "higher"},
    )
    pop = h.start_population(name="bowl", kind="island", num_islands=num_islands)

    # Seed each island with `population_size` random genomes.
    islands: list[list[tuple[IndividualPayload, Genome]]] = []
    for island_idx in range(num_islands):
        seeded = []
        for _ in range(population_size):
            g = random_genome(rng)
            seed = h.log_individual(
                kind="program",
                island_id=str(island_idx),
                generation_index=0,
                population_id=pop.id,
                metadata={"genome": [g.x, g.y]},
            )
            h.log_fitness(individual=seed, scores={"fitness": fitness(g)})
            seeded.append((seed, g))
        islands.append(seeded)

    for gen in range(1, generations + 1):
        new_islands: list[list[tuple[IndividualPayload, Genome]]] = []
        for island_idx, parents in enumerate(islands):
            sorted_parents = sorted(parents, key=lambda pg: -fitness(pg[1]))
            top = sorted_parents[: max(2, len(sorted_parents) // 2)]
            children: list[tuple[IndividualPayload, Genome]] = []
            for _ in range(population_size):
                roll = rng.random()
                if roll < crossover_rate and len(top) >= 2:
                    a, b = rng.sample(top, 2)
                    child_genome = crossover_genome(a[1], b[1], rng)
                    child = h.log_individual(
                        kind="program",
                        parent_ids=[a[0].id, b[0].id],
                        island_id=str(island_idx),
                        generation_index=gen,
                        population_id=pop.id,
                        metadata={"genome": [child_genome.x, child_genome.y]},
                    )
                    h.log_operator(
                        kind="crossover",
                        parent_ids=[a[0].id, b[0].id],
                        child_id=child.id,
                    )
                elif roll < crossover_rate + select_rate and top:
                    chosen = rng.choice(top)
                    child = h.log_individual(
                        kind="program",
                        parent_ids=[chosen[0].id],
                        island_id=str(island_idx),
                        generation_index=gen,
                        population_id=pop.id,
                        metadata={"genome": [chosen[1].x, chosen[1].y]},
                    )
                    h.log_operator(
                        kind="select",
                        parent_ids=[chosen[0].id],
                        child_id=child.id,
                    )
                    child_genome = chosen[1]
                else:
                    parent = rng.choice(top or parents)
                    child_genome = mutate_genome(parent[1], rng)
                    child = h.log_individual(
                        kind="program",
                        parent_ids=[parent[0].id],
                        island_id=str(island_idx),
                        generation_index=gen,
                        population_id=pop.id,
                        metadata={"genome": [child_genome.x, child_genome.y]},
                    )
                    h.log_operator(
                        kind="mutate",
                        parent_ids=[parent[0].id],
                        child_id=child.id,
                    )
                h.log_fitness(individual=child, scores={"fitness": fitness(child_genome)})
                children.append((child, child_genome))
            new_islands.append(children)
        islands = new_islands

    h.end_run()
    print(
        f"finished: {num_islands} islands × {population_size} programs × "
        f"{generations + 1} generations"
    )


if __name__ == "__main__":
    main()
