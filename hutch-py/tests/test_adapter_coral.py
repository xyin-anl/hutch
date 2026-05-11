"""Tests for the CORAL multi-agent run adapter."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

from hutch.adapters import detect_format
from hutch.adapters.coral import detect, import_coral
from hutch.schema import EVENT_ADAPTER
from tests._coral_fixture import make_run


@pytest.fixture
def run_dir(tmp_path: Path) -> Path:
    return make_run(tmp_path / "coral-toy")


def test_detect_recognizes_run(run_dir: Path) -> None:
    assert detect(run_dir) is True
    adapter = detect_format(run_dir)
    assert adapter is not None
    assert adapter.name == "coral"


def test_detect_rejects_arbitrary_jsonl(tmp_path: Path) -> None:
    arbitrary = tmp_path / "iterations.jsonl"
    arbitrary.write_text('{"hello": "world"}\n', encoding="utf-8")
    assert detect(tmp_path) is False


def test_imports_run_envelope(run_dir: Path) -> None:
    events = list(import_coral(run_dir))
    assert events
    assert events[0].event_kind == "run_start"
    assert events[-1].event_kind == "run_end"


def test_event_kind_counts(run_dir: Path) -> None:
    """24 iterations + 4 heartbeats + 3 memory snapshots."""
    events = list(import_coral(run_dir))
    counts = Counter(e.event_kind for e in events)
    assert counts["individual"] == 24
    assert counts["fitness"] == 24
    assert counts["steering_command"] == 4
    assert counts["archive_snapshot"] == 3
    assert counts["run_start"] == 1
    assert counts["run_end"] == 1


def test_streams_split_per_agent(run_dir: Path) -> None:
    events = list(import_coral(run_dir))
    streams = {ev.stream_id for ev in events if ev.stream_id is not None}
    assert any(s.startswith("agent-researcher") for s in streams)
    assert any(s.startswith("agent-engineer") for s in streams)
    assert any(s.startswith("agent-analyst") for s in streams)


def test_heartbeats_emit_steering_commands(run_dir: Path) -> None:
    events = list(import_coral(run_dir))
    steering = [e for e in events if e.event_kind == "steering_command"]
    assert len(steering) == 4
    commands = {e.payload.command for e in steering}  # type: ignore[union-attr]
    assert commands.issubset({"pause_run", "resume_run", "inject_hint", "cancel_individual"})
    actors = {e.payload.actor for e in steering}  # type: ignore[union-attr]
    assert actors.issubset({"human", "policy"})


def test_memory_snapshots_emit_archive_snapshots(run_dir: Path) -> None:
    events = list(import_coral(run_dir))
    snapshots = [e for e in events if e.event_kind == "archive_snapshot"]
    assert len(snapshots) == 3
    for snap in snapshots:
        assert snap.payload.archive_id == "coral-shared-memory"  # type: ignore[union-attr]
        assert 0.0 <= snap.payload.coverage <= 1.0  # type: ignore[union-attr]
        assert snap.payload.size > 0  # type: ignore[union-attr]


def test_every_event_validates_against_schema(run_dir: Path) -> None:
    for ev in import_coral(run_dir):
        EVENT_ADAPTER.validate_python(ev.model_dump())


def test_explicit_run_id_is_honored(run_dir: Path) -> None:
    events = list(import_coral(run_dir, run_id="custom-coral"))
    assert {e.run_id for e in events} == {"custom-coral"}
