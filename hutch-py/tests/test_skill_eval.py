"""Real-LLM regression eval for ``SKILL.md``.

Drops ``SKILL.md`` into the system prompt, asks an OpenAI model to run a
small synthetic autoresearch scenario, and validates that the emitted
events parse cleanly through the canonical schema.

The M6 done-condition calls for ≥95% schema-valid
events. We track the rate across several scenarios.

The eval is opt-in: it skips silently when ``OPENAI_API_KEY`` isn't set.
Run it with::

    uv pip install -e ".[skill-eval]"
    # ... ensure OPENAI_API_KEY is in your .env
    pytest hutch-py/tests/test_skill_eval.py -q
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_PATH = REPO_ROOT / "hutch-skill" / "SKILL.md"
ENV_PATH = REPO_ROOT / ".env"

# The .env loader is provided by the skill-eval extra. Skip the whole module
# if either dependency is missing.
try:
    from dotenv import load_dotenv  # type: ignore[import-not-found]
    from openai import OpenAI

    load_dotenv(ENV_PATH)
    _DEPS_OK = True
except ImportError:  # pragma: no cover - the extra isn't installed
    _DEPS_OK = False

NEED_DEPS = pytest.mark.skipif(
    not _DEPS_OK,
    reason="install with `uv pip install -e .[skill-eval]` to enable",
)
NEED_KEY = pytest.mark.skipif(
    not os.environ.get("OPENAI_API_KEY"),
    reason="OPENAI_API_KEY not set; LLM eval is opt-in",
)


@dataclass(frozen=True)
class Scenario:
    name: str
    instruction: str
    min_events: int  # below this, the model under-produced and the run is invalid
    must_include: tuple[str, ...]  # event kinds that MUST appear


SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        name="linear-refine",
        instruction=(
            "Run a 3-step linear hypothesis-refinement loop on a toy task. "
            "Emit a run_start, then for each step a fresh Individual + Operator "
            "(refine) + Fitness, then one Claim with one Evidence, then "
            "run_end. Use the same run_id throughout (e.g. 'eval-linear')."
        ),
        min_events=8,
        must_include=("run_start", "individual", "operator", "fitness", "run_end"),
    ),
    Scenario(
        name="evolutionary-2islands",
        instruction=(
            "Run a 2-island, 2-generation evolutionary loop. Emit a run_start, "
            "one Individual+Fitness per seed (one per island), then for each "
            "generation one Individual+Operator(mutate)+Fitness per island. "
            "End with run_end. Use island_id='0' or '1' on the individuals "
            "and run_id 'eval-evo'."
        ),
        min_events=10,
        must_include=("run_start", "individual", "operator", "fitness", "run_end"),
    ),
    Scenario(
        name="self-improving",
        instruction=(
            "Run 2 iterations of agent self-modification on SWE-bench-mini. "
            "Emit run_start, one Individual for the parent agent + a fitness "
            "score, then for each iteration: a child Individual, an Operator "
            "(self_modify), a SelfMod event with overseer_verdict, and a "
            "Fitness for the child. End with run_end. Use run_id 'eval-self'."
        ),
        min_events=10,
        must_include=("run_start", "individual", "self_mod", "fitness", "run_end"),
    ),
)

MODEL = os.environ.get("HUTCH_SKILL_EVAL_MODEL", "gpt-4o")
"""Model to evaluate against. Default is OpenAI's gpt-4o; override via env."""


def _system_prompt(skill_text: str) -> str:
    return (
        "You log structured telemetry events for an autoresearch loop. "
        "Read the skill below, then run the scenario the user describes by "
        "emitting canonical Hutch events. Output ONE JSON object with the "
        'shape {"events": [<event>, <event>, ...]}. Do not include any text '
        "outside JSON. Every event must include `run_id`, `event_kind`, and "
        "a `payload` matching that event_kind. Use string ids (e.g. 'i-1'); "
        "do not invent UUIDs. Do not include trailing commentary.\n\n"
        "----- SKILL -----\n"
        f"{skill_text}\n"
        "----- END SKILL -----"
    )


def _validate_events(records: list[object]) -> tuple[int, int, list[str]]:
    """Return (valid_count, total_count, error_messages)."""
    from hutch.schema import EVENT_ADAPTER

    errors: list[str] = []
    valid = 0
    for i, rec in enumerate(records):
        try:
            EVENT_ADAPTER.validate_python(rec)
            valid += 1
        except Exception as exc:
            errors.append(f"event[{i}]: {exc}")
    return valid, len(records), errors


def _run_scenario(client: OpenAI, skill_text: str, scenario: Scenario) -> dict[str, object]:
    response = client.chat.completions.create(
        model=MODEL,
        response_format={"type": "json_object"},
        temperature=0.2,
        messages=[
            {"role": "system", "content": _system_prompt(skill_text)},
            {"role": "user", "content": scenario.instruction},
        ],
    )
    content = response.choices[0].message.content or "{}"
    parsed = json.loads(content)
    events = parsed.get("events", [])
    if not isinstance(events, list):
        events = []
    valid, total, errors = _validate_events(events)
    kinds = {rec["event_kind"] for rec in events if isinstance(rec, dict) and "event_kind" in rec}
    return {
        "scenario": scenario.name,
        "model": MODEL,
        "valid": valid,
        "total": total,
        "errors": errors,
        "kinds_seen": kinds,
        "scenario_min_events": scenario.min_events,
        "scenario_must_include": set(scenario.must_include),
    }


@NEED_DEPS
@NEED_KEY
def test_skill_produces_mostly_valid_events() -> None:
    """Aggregate ≥95% schema-valid pass rate across all scenarios."""
    skill_text = SKILL_PATH.read_text(encoding="utf-8")
    client = OpenAI()
    results = [_run_scenario(client, skill_text, s) for s in SCENARIOS]

    total = sum(int(r["total"]) for r in results)
    valid = sum(int(r["valid"]) for r in results)
    rate = valid / total if total > 0 else 0.0

    summary = "\n".join(
        f"  - {r['scenario']}: {r['valid']}/{r['total']} valid · kinds={sorted(r['kinds_seen'])}"
        for r in results
    )
    assert total > 0, f"no events produced across scenarios:\n{summary}"
    assert rate >= 0.95, (
        f"schema-validity rate {rate:.1%} below 0.95 target.\n"
        f"summary:\n{summary}\n"
        f"errors (first 10):\n  "
        + "\n  ".join(
            err
            for r in results
            for err in r["errors"][:5]  # type: ignore[index]
        )
    )


@NEED_DEPS
@NEED_KEY
@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.name)
def test_each_scenario_includes_required_event_kinds(scenario: Scenario) -> None:
    """Per-scenario: the model must produce the must-include event kinds.

    A 100% schema-valid run that's missing run_start or fitness still fails
    here — coverage matters as much as validity.
    """
    skill_text = SKILL_PATH.read_text(encoding="utf-8")
    client = OpenAI()
    result = _run_scenario(client, skill_text, scenario)

    missing = set(scenario.must_include) - set(result["kinds_seen"])  # type: ignore[arg-type]
    assert not missing, (
        f"{scenario.name}: missing required event kinds {missing}. "
        f"saw {sorted(result['kinds_seen'])}"  # type: ignore[arg-type]
    )
    assert int(result["total"]) >= scenario.min_events, (
        f"{scenario.name}: produced only {result['total']} events, expected ≥{scenario.min_events}"
    )
