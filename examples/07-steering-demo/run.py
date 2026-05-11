"""Example 07 — Live steering demo.

A long-running loop that:

* logs one Individual + Fitness every iteration so the dashboard is alive,
* polls the Hutch steering channel between iterations,
* obeys ``pause_run`` / ``resume_run`` / ``cancel_individual`` /
  ``inject_hint`` commands.

Run it::

    # Terminal 1: start the daemon
    hutch serve --db /tmp/hutch-steering-demo.duckdb

    # Terminal 2: run the loop
    HUTCH_DAEMON_URL=http://127.0.0.1:7777 python run.py

    # Terminal 3 (or the UI): issue commands
    curl -X POST http://127.0.0.1:7777/steering/<run_id> \\
         -H 'content-type: application/json' \\
         -d '{"command":"pause_run","actor":"human"}'

In the dashboard, open the Steering tab on the run and use the "Issue
command" form — the loop will pick it up within ~1 second.
"""

from __future__ import annotations

import random
import time

import hutch as h
from hutch import steering


class LoopState:
    """Mutable container the steering handlers can poke at."""

    def __init__(self) -> None:
        self.paused = False
        self.cancelled_ids: set[str] = set()
        self.hint: str | None = None
        self.fork_target: str | None = None
        self.stop = False


def install_handlers(state: LoopState) -> None:
    @steering.handler("pause_run")
    def _on_pause(cmd: steering.SteeringCommand) -> str:
        state.paused = True
        return "paused"

    @steering.handler("resume_run")
    def _on_resume(cmd: steering.SteeringCommand) -> str:
        state.paused = False
        return "resumed"

    @steering.handler("cancel_individual")
    def _on_cancel(cmd: steering.SteeringCommand) -> str:
        if cmd.target_id is None:
            return "no target_id; cancel ignored"
        state.cancelled_ids.add(cmd.target_id)
        return f"will skip {cmd.target_id}"

    @steering.handler("inject_hint")
    def _on_hint(cmd: steering.SteeringCommand) -> str:
        text = str(cmd.params.get("text") or cmd.target_id or "")
        state.hint = text
        return f"hint stored: {text[:40]}"

    @steering.handler("fork_from")
    def _on_fork(cmd: steering.SteeringCommand) -> str:
        state.fork_target = cmd.target_id
        return f"will fork from {cmd.target_id}"


def evaluate(rng: random.Random, hint: str | None) -> dict[str, float]:
    """Toy evaluator. The hint, if present, biases the score upward to
    demonstrate that the steering channel is round-trip live."""
    base = round(0.3 + 0.5 * rng.random(), 3)
    if hint is not None:
        base = min(1.0, base + 0.2)
    return {"score": base, "noise": round(rng.random(), 3)}


def main(max_iterations: int = 60, sleep_s: float = 1.0) -> None:
    rng = random.Random(0)
    state = LoopState()
    install_handlers(state)

    run = h.start_run(name="steering-demo", project="hutch-examples")
    print(f"started run {run.id}")
    print(f"  open the dashboard at /run?id={run.id} and try the Steering tab")

    seed = h.log_individual(kind="hypothesis", metadata={"text": "seed candidate"})
    h.log_fitness(individual=seed, scores=evaluate(rng, None))

    parent_id = seed.id
    for i in range(max_iterations):
        # Drain the steering queue first.
        steering.poll()
        if state.stop:
            break

        # Pause loop: keep polling but emit no new work.
        if state.paused:
            time.sleep(sleep_s)
            continue

        # Honor a fork-from instruction once.
        if state.fork_target is not None:
            parent_id = state.fork_target
            state.fork_target = None
            print(f"  forked: parent_id <- {parent_id}")

        child = h.log_individual(
            kind="hypothesis",
            parent_ids=[parent_id],
            metadata={"step": i, "hint_in_effect": state.hint},
        )
        h.log_operator(
            kind="refine",
            parent_ids=[parent_id],
            child_id=child.id,
            llm_id="claude-sonnet-4-6",
            cost_usd=0.001,
        )

        if child.id in state.cancelled_ids:
            h.log_fitness(
                individual=child, scores={}, invalid_reason="cancelled by steering"
            )
            print(f"  step {i}: {child.id} cancelled before evaluation")
        else:
            scores = evaluate(rng, state.hint)
            h.log_fitness(individual=child, scores=scores)
            print(f"  step {i}: {child.id} -> {scores}")
            parent_id = child.id

        # Consume a one-shot hint after one iteration.
        if state.hint is not None:
            state.hint = None

        time.sleep(sleep_s)

    h.end_run(status="finished", summary=f"steering demo ran {i + 1} iterations")
    print(f"finished run {run.id}")


if __name__ == "__main__":
    main()
