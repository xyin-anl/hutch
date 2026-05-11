"""AIDE-style tree-search loop.

Demonstrates Individual + Operator(tree_expand) + TreeExpansion + Fitness.
The dashboard's Phylogeny view renders the tree and the Operator-trace
view shows the expansion sequence; a dedicated Tree-search view lands
in M7.
"""

from __future__ import annotations

import random

import hutch as h


def evaluate_node(node_id: str) -> float:
    rng = random.Random(hash(node_id) & 0xFFFF)
    return round(0.4 + 0.5 * rng.random(), 3)


def main(expansions: int = 12) -> None:
    h.start_run(name="aide-tree", project="hutch-skill-examples")
    root = h.log_individual(
        kind="experiment_plan",
        individual_id="root",
        generation_index=0,
    )
    h.log_fitness(individual=root, scores={"val_acc": evaluate_node(root.id)})

    frontier: list[tuple[str, int]] = [(root.id, 1)]
    rng = random.Random(11)
    for _ in range(expansions):
        if not frontier:
            break
        parent_id, depth = frontier.pop(rng.randrange(len(frontier)))
        child = h.log_individual(
            kind="experiment_plan",
            parent_ids=[parent_id],
            generation_index=depth,
        )
        h.log_operator(
            kind="tree_expand", parent_ids=[parent_id], child_id=child.id
        )
        h.log_tree_expansion(
            tree_id="aide",
            parent_node=parent_id,
            child_node=child.id,
            visit_count=1,
            value_estimate=evaluate_node(child.id),
        )
        h.log_fitness(individual=child, scores={"val_acc": evaluate_node(child.id)})
        if depth < 4:
            frontier.append((child.id, depth + 1))

    h.end_run()


if __name__ == "__main__":
    main()
