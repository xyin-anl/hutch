"""Example 01 — Linear research loop.

A tiny `propose_hypothesis -> evaluate -> log_claim` loop using the Hutch SDK
directly. Demonstrates that even a non-evolutionary, single-chain research
loop populates the dashboard correctly.

Run it::

    # Embedded mode (no daemon required):
    HUTCH_DB_PATH=$PWD/example01.duckdb python run.py

    # Or, against a running daemon:
    hutch serve --db $PWD/example01.duckdb &   # in another shell
    python run.py                              # default daemon URL is :7777
"""

from __future__ import annotations

import random
from typing import cast

import hutch as h
from hutch.schema import IndividualPayload


def evaluate(hypothesis: IndividualPayload) -> dict[str, float]:
    """Toy evaluator: deterministic-ish plausibility + an evaluation latency.

    The two scores are deliberately of opposite signs (plausibility ↑ better,
    eval_seconds ↓ better) so the Pareto view's per-axis direction toggle
    has something to show.
    """
    rng = random.Random(hash(hypothesis.id) & 0xFFFF)
    plausibility = round(0.3 + 0.6 * rng.random(), 3)
    eval_seconds = round(0.05 + 0.2 * rng.random(), 3)
    return {"plausibility": plausibility, "eval_seconds": eval_seconds}


def main() -> None:
    run = h.start_run(
        name="linear-research-demo",
        project="hutch-examples",
        # plausibility ↑ better, eval_seconds ↓ better — declares the
        # canonical optimisation direction so the Pareto / Best-Composite
        # views don't have to guess.
        score_directions={"plausibility": "higher", "eval_seconds": "lower"},
    )
    print(f"started run {run.id}")

    seed = h.log_individual(
        kind="hypothesis",
        metadata={"text": "X improves Y under condition Z"},
    )
    print(f"  seeded hypothesis {seed.id}")

    current = seed
    for step in range(5):
        scores = evaluate(current)
        h.log_fitness(individual=current, scores=scores)
        print(f"  step {step}: scored {current.id} -> {scores}")

        # Refine once: the SDK's log_individual returns the new payload so we
        # can chain (note we hold the previous id for parent_ids).
        previous_id = current.id
        current = cast(
            IndividualPayload,
            h.log_individual(
                kind="hypothesis",
                parent_ids=[previous_id],
                metadata={"step": step + 1},
            ),
        )
        # ``cost_usd`` is the LLM-call cost — distinct from the toy
        # evaluator's ``eval_seconds`` reported as a fitness score.
        h.log_operator(
            kind="refine",
            parent_ids=[previous_id],
            child_id=current.id,
            llm_id="claude-sonnet-4-6",
            llm_temperature=0.7,
            cost_usd=0.012,
        )

    final_scores = evaluate(current)
    h.log_fitness(individual=current, scores=final_scores)

    # Two claims, each with a small evidence panel — exercises the
    # Evidence-Graph view with mixed stances + confidences.
    primary = h.log_claim(
        text="The refined hypothesis attains plausibility ≥ 0.6 across iterations.",
        supported_by=[current.id],
        requires_reproduction=True,
    )
    for src, stance, conf, qual in [
        ("arxiv:2026.00000", "supports", 0.78, 0.85),
        ("arxiv:2025.99902", "supports", 0.55, 0.62),
        ("blog:internal-replication", "contradicts", 0.40, 0.30),
        ("notebook:scratch-eval", "mentions", 0.50, 0.20),
    ]:
        h.log_evidence(
            claim_id=primary.id,
            source_uri=src,
            stance=stance,
            confidence=conf,
            source_quality=qual,
        )

    secondary = h.log_claim(
        text="The cost-per-claim of refine is ≤ $0.05 in the explored regime.",
        supported_by=[current.id],
        requires_reproduction=False,
    )
    for src, stance, conf, qual in [
        ("internal:cost-ledger", "supports", 0.92, 0.95),
        ("arxiv:2026.00000", "mentions", 0.30, 0.85),
    ]:
        h.log_evidence(
            claim_id=secondary.id,
            source_uri=src,
            stance=stance,
            confidence=conf,
            source_quality=qual,
        )

    h.end_run(status="finished", summary="5 refinement steps; final claim emitted.")
    print(f"finished run {run.id}; open the dashboard or query GET /runs/{run.id}")


if __name__ == "__main__":
    main()
