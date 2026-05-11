"""Self-improving agent loop — DGM/SICA-style.

Demonstrates a sequence of self-modifications with overseer verdicts.
Every iteration is one Individual (the new agent version) plus one SelfMod
event capturing the proposal, the verdict, and the before/after benchmark.
"""

from __future__ import annotations

import random

import hutch as h


def run_swe_bench(_agent_id: str) -> float:
    rng = random.Random(hash(_agent_id) & 0xFFFF)
    return round(0.35 + 0.4 * rng.random(), 3)


def main(iterations: int = 4) -> None:
    h.start_run(name="dgm-iteration", project="hutch-skill-examples")
    current = h.log_individual(kind="agent", individual_id="agent-v17")
    score = run_swe_bench("agent-v17")
    h.log_fitness(
        individual=current,
        scores={"swe_bench": score},
        evaluator_kind="benchmark",
    )

    for i in range(iterations):
        proposal = "Replace the BFS planner with A*"
        child_id = f"agent-v{18 + i}"
        score_after = run_swe_bench(child_id)
        accepted = score_after > score

        child = h.log_individual(
            kind="agent",
            individual_id=child_id,
            parent_ids=[current.id],
        )
        h.log_operator(
            kind="self_modify", parent_ids=[current.id], child_id=child.id
        )
        h.log_self_modification(
            parent_agent_id=current.id,
            child_agent_id=child.id,
            target_path="src/planner.py",
            proposal=proposal,
            overseer_id="claude-opus-4.7",
            overseer_verdict="accepted" if accepted else "rejected",
            benchmark="swe-bench-mini",
            score_before=score,
            score_after=score_after,
        )
        h.log_fitness(
            individual=child,
            scores={"swe_bench": score_after},
            evaluator_kind="benchmark",
        )
        if accepted:
            current = child
            score = score_after

    h.end_run()


if __name__ == "__main__":
    main()
