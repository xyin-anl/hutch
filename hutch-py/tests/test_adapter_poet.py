"""Tests for the POET coevolution adapter."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

from hutch.adapters import detect_format
from hutch.adapters.poet import detect, import_poet
from hutch.schema import EVENT_ADAPTER
from tests._poet_fixture import make_run


@pytest.fixture
def run_dir(tmp_path: Path) -> Path:
    return make_run(tmp_path / "poet-toy")


def test_detect_recognizes_run(run_dir: Path) -> None:
    assert detect(run_dir) is True
    adapter = detect_format(run_dir)
    assert adapter is not None
    assert adapter.name == "poet"


def test_imports_run_envelope(run_dir: Path) -> None:
    events = list(import_poet(run_dir))
    assert events
    assert events[0].event_kind == "run_start"
    assert events[-1].event_kind == "run_end"


def test_environments_and_agents_emit_distinct_individuals(run_dir: Path) -> None:
    events = list(import_poet(run_dir))
    individuals = [e for e in events if e.event_kind == "individual"]
    envs = [e for e in individuals if e.payload.kind == "environment"]  # type: ignore[union-attr]
    agents = [e for e in individuals if e.payload.kind == "agent"]  # type: ignore[union-attr]
    assert envs, "expected at least one environment Individual"
    assert agents, "expected at least one agent Individual"
    # Disjoint id spaces.
    env_ids = {e.payload.id for e in envs}  # type: ignore[union-attr]
    agent_ids = {e.payload.id for e in agents}  # type: ignore[union-attr]
    assert env_ids.isdisjoint(agent_ids)


def test_pair_evaluation_emits_fitness_with_env_as_evaluator(run_dir: Path) -> None:
    """Agents are scored on environments → evaluator_id = env id."""
    events = list(import_poet(run_dir))
    fits = [e for e in events if e.event_kind == "fitness"]
    assert fits
    sample = fits[0].payload
    assert sample.evaluator_kind == "simulator"  # type: ignore[union-attr]
    assert sample.evaluator_id is not None  # type: ignore[union-attr]
    assert sample.evaluator_id.startswith("env-")  # type: ignore[union-attr]
    # The fitness's individual_id is the agent.
    assert sample.individual_id.startswith("agent-")  # type: ignore[union-attr]


def test_transfers_emit_migrations(run_dir: Path) -> None:
    events = list(import_poet(run_dir))
    migrations = [e for e in events if e.event_kind == "migration"]
    if migrations:  # the fixture is probabilistic; assert shape if any present
        m = migrations[0].payload
        assert m.from_island.startswith("env-")  # type: ignore[union-attr]
        assert m.to_island.startswith("env-")  # type: ignore[union-attr]
        assert m.trigger == "poet_transfer"  # type: ignore[union-attr]


def test_event_streams_split_per_environment(run_dir: Path) -> None:
    events = list(import_poet(run_dir))
    streams = {ev.stream_id for ev in events if ev.stream_id is not None}
    # Every stream is "env-..." because both agents and pairs are
    # surfaced under the env's swimlane.
    assert all(s.startswith("env-") for s in streams)
    assert len(streams) >= 1


def test_every_event_validates_against_schema(run_dir: Path) -> None:
    for ev in import_poet(run_dir):
        EVENT_ADAPTER.validate_python(ev.model_dump())


def test_explicit_run_id_is_honored(run_dir: Path) -> None:
    events = list(import_poet(run_dir, run_id="custom-poet"))
    assert {e.run_id for e in events} == {"custom-poet"}


def test_event_kind_distribution(run_dir: Path) -> None:
    """At minimum: run_start + N individuals + M fitness + run_end. Migrations
    are probabilistic in the fixture."""
    events = list(import_poet(run_dir))
    counts = Counter(e.event_kind for e in events)
    assert counts["run_start"] == 1
    assert counts["run_end"] == 1
    assert counts["individual"] >= 4  # 3 seeds + at least one mutation
    assert counts["fitness"] >= 4
