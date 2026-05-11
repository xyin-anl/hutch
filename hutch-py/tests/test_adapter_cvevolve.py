"""Tests for the CVEvolve SQLite history adapter."""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hutch.adapters import REGISTRY, detect_format
from hutch.adapters.cvevolve import detect, import_cvevolve, is_complete
from hutch.daemon.app import create_app
from hutch.schema import EVENT_ADAPTER
from tests._cvevolve_fixture import make_session


@pytest.fixture
def session_dir(tmp_path: Path) -> Path:
    return make_session(tmp_path / "cvevolve-toy")


def test_detect_accepts_session_root_and_direct_db(session_dir: Path) -> None:
    db_path = session_dir / "history" / "search_history.sqlite"

    assert detect(session_dir) is True
    assert detect(db_path) is True

    adapter = detect_format(session_dir)
    assert adapter is not None
    assert adapter.name == "cvevolve"

    db_adapter = detect_format(db_path)
    assert db_adapter is not None
    assert db_adapter.name == "cvevolve"


def test_detect_rejects_empty_dir(tmp_path: Path) -> None:
    assert detect(tmp_path) is False
    assert detect_format(tmp_path) is None


def test_detect_rejects_arbitrary_sqlite_file(tmp_path: Path) -> None:
    db_path = tmp_path / "not_cvevolve.sqlite"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE unrelated (id INTEGER PRIMARY KEY, value TEXT)")
        conn.execute("INSERT INTO unrelated (value) VALUES ('hello')")

    assert detect(db_path) is False


def test_imports_run_envelope(session_dir: Path) -> None:
    events = list(import_cvevolve(session_dir))
    assert events
    assert events[0].event_kind == "run_start"
    assert events[-1].event_kind == "run_end"
    assert events[-1].payload.status == "finished"  # type: ignore[union-attr]


def test_finalize_false_suppresses_run_end(session_dir: Path) -> None:
    events = list(import_cvevolve(session_dir, finalize=False))
    assert events
    assert events[0].event_kind == "run_start"
    assert "run_end" not in {event.event_kind for event in events}


def test_active_session_import_emits_run_update_instead_of_run_end(session_dir: Path) -> None:
    db_path = session_dir / "history" / "search_history.sqlite"
    with sqlite3.connect(db_path) as conn:
        conn.execute("UPDATE session_state SET phase = 'round', status = 'running'")

    events = list(import_cvevolve(session_dir))

    assert "run_end" not in {event.event_kind for event in events}
    updates = [event for event in events if event.event_kind == "run_update"]
    assert len(updates) == 1
    assert updates[0].payload.status == "running"  # type: ignore[union-attr]
    assert updates[0].payload.source_counts["candidates"] == 5  # type: ignore[union-attr]


def test_active_then_completed_import_accepts_terminal_run_end(session_dir: Path) -> None:
    adapter = next(adapter for adapter in REGISTRY if adapter.name == "cvevolve")
    db_path = session_dir / "history" / "search_history.sqlite"

    with TestClient(create_app()) as client:
        with sqlite3.connect(db_path) as conn:
            conn.execute("UPDATE session_state SET phase = 'round', status = 'running'")
        active_events = [
            json.loads(event.model_dump_json())
            for event in adapter.iter_events(session_dir, run_id="cvevolve-active")
        ]
        active_response = client.post("/events", json=active_events)
        assert active_response.status_code == 200, active_response.text
        assert active_response.json()["accepted"] == len(active_events)
        assert client.get("/runs/cvevolve-active").json()["status"] == "running"

        with sqlite3.connect(db_path) as conn:
            conn.execute("UPDATE session_state SET phase = 'completed', status = 'completed'")
        completed_events = [
            json.loads(event.model_dump_json())
            for event in adapter.iter_events(session_dir, run_id="cvevolve-active")
        ]
        completed_response = client.post("/events", json=completed_events)
        assert completed_response.status_code == 200, completed_response.text
        assert completed_response.json()["accepted"] == 1
        assert client.get("/runs/cvevolve-active").json()["status"] == "finished"


def test_registry_iter_events_adds_stable_ids_and_source_metadata(session_dir: Path) -> None:
    adapter = next(adapter for adapter in REGISTRY if adapter.name == "cvevolve")

    first = list(adapter.iter_events(session_dir))
    second = list(adapter.iter_events(session_dir))

    assert [event.event_id for event in first] == [event.event_id for event in second]
    candidate = next(event for event in first if event.event_kind == "individual")
    assert candidate.payload.metadata["adapter"] == "cvevolve"  # type: ignore[union-attr]
    assert candidate.payload.metadata["source_path"] == str(session_dir.resolve())  # type: ignore[union-attr]
    assert candidate.payload.metadata["source_key"] == "individual:cand-baseline"  # type: ignore[union-attr]


def test_explicit_completion_state(session_dir: Path) -> None:
    db_path = session_dir / "history" / "search_history.sqlite"
    assert is_complete(session_dir) is True
    with sqlite3.connect(db_path) as conn:
        conn.execute("UPDATE session_state SET phase = 'round', status = 'running'")
    assert is_complete(session_dir) is False


def test_event_kind_counts(session_dir: Path) -> None:
    events = list(import_cvevolve(session_dir))
    counts = Counter(e.event_kind for e in events)
    assert counts["run_start"] == 1
    assert counts["run_end"] == 1
    assert counts["individual"] == 5
    assert counts["operator"] == 4
    assert counts["fitness"] == 8
    assert counts["stream_event"] == 1


def test_every_event_validates_against_schema(session_dir: Path) -> None:
    for ev in import_cvevolve(session_dir):
        EVENT_ADAPTER.validate_python(ev.model_dump())


def test_metric_directions_and_minimize_composite(session_dir: Path) -> None:
    events = list(import_cvevolve(session_dir))
    run_start = events[0]
    assert run_start.payload.score_directions["registration_error"] == "lower"  # type: ignore[union-attr]
    assert run_start.payload.score_directions["accuracy"] == "higher"  # type: ignore[union-attr]

    primary = next(
        ev
        for ev in events
        if ev.event_kind == "fitness"
        and ev.payload.individual_id == "cand-baseline"  # type: ignore[union-attr]
        and "registration_error" in ev.payload.scores  # type: ignore[union-attr]
    )
    assert primary.payload.composite == pytest.approx(-0.42)  # type: ignore[union-attr]


def test_operator_semantics(session_dir: Path) -> None:
    events = list(import_cvevolve(session_dir))
    operators = {
        ev.payload.child_id: ev.payload  # type: ignore[union-attr]
        for ev in events
        if ev.event_kind == "operator"
    }

    assert operators["cand-generate"].kind == "propose"
    assert operators["cand-generate"].parent_ids == []
    assert operators["cand-tune"].kind == "refine"
    assert operators["cand-tune"].parent_ids == ["cand-generate"]
    assert operators["cand-mut"].kind == "mutate"
    assert operators["cand-mut"].parent_ids == ["cand-tune"]
    assert operators["cand-cross"].kind == "crossover"
    assert operators["cand-cross"].parent_ids == ["cand-tune", "cand-mut"]


def test_seed_candidates_have_no_parents(session_dir: Path) -> None:
    events = list(import_cvevolve(session_dir))
    individuals = {
        ev.payload.id: ev.payload  # type: ignore[union-attr]
        for ev in events
        if ev.event_kind == "individual"
    }
    assert individuals["cand-baseline"].is_seed is True
    assert individuals["cand-baseline"].parent_ids == []
    assert individuals["cand-generate"].is_seed is True
    assert individuals["cand-generate"].parent_ids == []


def test_failure_becomes_stream_event(session_dir: Path) -> None:
    events = list(import_cvevolve(session_dir))
    failure = next(ev for ev in events if ev.event_kind == "stream_event")
    assert failure.payload.label == "candidate_failure"  # type: ignore[union-attr]
    assert failure.payload.text == "SyntaxError: invalid syntax"  # type: ignore[union-attr]
    assert failure.payload.metadata["parent_ids"] == ["cand-cross"]  # type: ignore[union-attr]


def test_audit_logs_are_opt_in(session_dir: Path) -> None:
    default_events = list(import_cvevolve(session_dir))
    default_stream_labels = {
        ev.payload.label  # type: ignore[union-attr]
        for ev in default_events
        if ev.event_kind == "stream_event"
    }
    assert "cvevolve_message" not in default_stream_labels
    assert "cvevolve_tool_call" not in default_stream_labels

    audit_events = list(import_cvevolve(session_dir, include_audit=True))
    assert audit_events[0].payload.capabilities == {"audit": True}  # type: ignore[union-attr]
    audit_streams = [
        ev
        for ev in audit_events
        if ev.event_kind == "stream_event"
        and ev.payload.label in {"cvevolve_message", "cvevolve_tool_call"}  # type: ignore[union-attr]
    ]
    labels = Counter(ev.payload.label for ev in audit_streams)  # type: ignore[union-attr]
    assert labels["cvevolve_message"] == 2
    assert labels["cvevolve_tool_call"] == 1
    assert all(
        ev.payload.metadata["audit_kind"] in {"message", "tool_call"} for ev in audit_streams
    )  # type: ignore[union-attr]
    for ev in audit_events:
        EVENT_ADAPTER.validate_python(ev.model_dump())


def test_audit_events_have_stable_ids_and_can_truncate(session_dir: Path) -> None:
    adapter = next(adapter for adapter in REGISTRY if adapter.name == "cvevolve")

    first = list(adapter.iter_events(session_dir, include_audit=True, audit_max_text_chars=12))
    second = list(adapter.iter_events(session_dir, include_audit=True, audit_max_text_chars=12))

    first_audit = [
        ev
        for ev in first
        if ev.event_kind == "stream_event"
        and ev.payload.label in {"cvevolve_message", "cvevolve_tool_call"}  # type: ignore[union-attr]
    ]
    second_audit = [
        ev
        for ev in second
        if ev.event_kind == "stream_event"
        and ev.payload.label in {"cvevolve_message", "cvevolve_tool_call"}  # type: ignore[union-attr]
    ]
    assert [ev.event_id for ev in first_audit] == [ev.event_id for ev in second_audit]
    assert first_audit[0].payload.metadata["source_key"] == "messages.message_events:1"  # type: ignore[union-attr]
    assert first_audit[0].payload.metadata["truncated"] is True  # type: ignore[union-attr]
    assert len(first_audit[0].payload.text or "") == 12  # type: ignore[union-attr]


def test_explicit_run_id_and_project_are_honored(session_dir: Path) -> None:
    events = list(import_cvevolve(session_dir, run_id="custom-cvevolve", project="science"))
    assert {e.run_id for e in events} == {"custom-cvevolve"}
    assert events[0].payload.project == "science"  # type: ignore[union-attr]
