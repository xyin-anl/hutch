"""Linear research loop — refine a single hypothesis over a few steps.

Demonstrates the minimum surface needed for a non-evolutionary loop:
RunStart, Individual, Operator(refine), Fitness, Claim, Evidence, RunEnd.

Run::

    HUTCH_DB_PATH=/tmp/skill-01.duckdb python 01_linear.py
"""

from __future__ import annotations

import random

import hutch as h


def evaluate_plausibility(text: str) -> float:
    rng = random.Random(hash(text) & 0xFFFF)
    return round(0.4 + 0.5 * rng.random(), 3)


def main() -> None:
    h.start_run(name="hypothesis-refine", project="hutch-skill-examples")
    seed = h.log_individual(
        kind="hypothesis",
        metadata={"text": "Increasing model temperature improves diversity."},
    )
    current = seed
    for step in range(5):
        score = evaluate_plausibility(str(current.metadata))
        h.log_fitness(individual=current, scores={"plausibility": score})
        refined = h.log_individual(
            kind="hypothesis",
            parent_ids=[current.id],
            metadata={"step": step + 1},
        )
        h.log_operator(
            kind="refine",
            parent_ids=[current.id],
            child_id=refined.id,
            llm_id="gpt-4o",
            cost_usd=0.012,
        )
        current = refined

    h.log_fitness(individual=current, scores={"plausibility": 0.78})
    claim = h.log_claim(
        text="The refined hypothesis attains plausibility ≥ 0.7.",
        supported_by=[current.id],
        requires_reproduction=True,
    )
    h.log_evidence(
        claim_id=claim.id,
        source_uri="arxiv:2026.00001",
        stance="supports",
        confidence=0.7,
    )
    h.end_run()


if __name__ == "__main__":
    main()
