"""Tests for the DuckDB store and migration runner."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from hutch.schema import (
    FitnessEvent,
    FitnessPayload,
    IndividualEvent,
    IndividualPayload,
    OperatorEvent,
    OperatorPayload,
    RunStartEvent,
    RunStartPayload,
)
from hutch.store import (
    applied_versions,
    database,
    insert_event,
    migrate,
    open_and_migrate,
    open_db,
    read_events,
)


def test_migrate_creates_initial_schema_in_memory() -> None:
    conn = open_and_migrate()
    assert 1 in applied_versions(conn)


def test_migrate_is_idempotent() -> None:
    conn = open_and_migrate()
    second = migrate(conn)
    assert second == []


def test_migrate_persists_to_file(tmp_path: Path) -> None:
    db_path = tmp_path / "hutch.duckdb"
    conn = open_and_migrate(db_path)
    conn.close()

    # Reopen and confirm version 1 is recorded.
    conn2 = open_db(db_path)
    assert 1 in applied_versions(conn2)
    # Confirm we can run a SELECT on a created table.
    conn2.execute("SELECT * FROM events;")
    assert conn2.fetchall() == []


def test_failed_migration_rolls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = open_db()

    def broken_up(conn_) -> None:
        conn_.execute("CREATE TABLE migration_probe (id INTEGER);")
        raise RuntimeError("boom")

    monkeypatch.setattr(
        database,
        "_discover_migrations",
        lambda: [(99, SimpleNamespace(up=broken_up))],
    )

    with pytest.raises(RuntimeError, match="boom"):
        migrate(conn)
    assert 99 not in applied_versions(conn)
    with pytest.raises(Exception, match="migration_probe"):
        conn.execute("SELECT * FROM migration_probe;")


def test_insert_event_and_read_back_individual() -> None:
    conn = open_and_migrate()
    e = IndividualEvent(
        run_id="r1",
        payload=IndividualPayload(id="i1", kind="program", is_seed=True),
    )
    insert_event(conn, e)
    out = read_events(conn, "r1")
    assert len(out) == 1
    assert out[0] == e


def test_insert_multiple_kinds_and_read_in_order() -> None:
    conn = open_and_migrate()
    e1 = RunStartEvent(run_id="r1", timestamp_ns=100, payload=RunStartPayload(name="run1"))
    e2 = IndividualEvent(
        run_id="r1",
        timestamp_ns=200,
        payload=IndividualPayload(id="i1", kind="program", is_seed=True),
    )
    e3 = OperatorEvent(
        run_id="r1",
        timestamp_ns=300,
        payload=OperatorPayload(id="op1", kind="propose", parent_ids=[], child_id="i1"),
    )
    e4 = FitnessEvent(
        run_id="r1",
        timestamp_ns=400,
        payload=FitnessPayload(
            individual_id="i1",
            evaluator_kind="deterministic_metric",
            scores={"acc": 0.5},
        ),
    )
    for ev in (e3, e1, e4, e2):  # insert out of order
        insert_event(conn, ev)
    out = read_events(conn, "r1")
    assert [type(x).__name__ for x in out] == [
        "RunStartEvent",
        "IndividualEvent",
        "OperatorEvent",
        "FitnessEvent",
    ]


def test_read_events_filters_by_run_id() -> None:
    conn = open_and_migrate()
    insert_event(
        conn,
        IndividualEvent(
            run_id="alpha",
            payload=IndividualPayload(id="i1", kind="program", is_seed=True),
        ),
    )
    insert_event(
        conn,
        IndividualEvent(
            run_id="beta",
            payload=IndividualPayload(id="i2", kind="program", is_seed=True),
        ),
    )
    assert len(read_events(conn, "alpha")) == 1
    assert len(read_events(conn, "beta")) == 1
    assert read_events(conn, "gamma") == []


def test_duplicate_event_id_is_idempotent() -> None:
    """Duplicate event ids are ignored for at-least-once delivery."""
    conn = open_and_migrate()
    e = IndividualEvent(
        run_id="r1",
        payload=IndividualPayload(id="i1", kind="program", is_seed=True),
    )
    assert insert_event(conn, e) is True
    assert insert_event(conn, e) is False
    assert len(read_events(conn, "r1")) == 1


def test_read_events_filters_by_event_kind() -> None:
    conn = open_and_migrate()
    insert_event(
        conn,
        IndividualEvent(
            run_id="r1",
            payload=IndividualPayload(id="i1", kind="program", is_seed=True),
        ),
    )
    insert_event(
        conn,
        FitnessEvent(
            run_id="r1",
            payload=FitnessPayload(
                individual_id="i1",
                evaluator_kind="deterministic_metric",
                scores={"acc": 0.9},
            ),
        ),
    )
    assert [e.event_kind for e in read_events(conn, "r1", event_kind="fitness")] == ["fitness"]


def test_read_events_supports_since_and_limit() -> None:
    conn = open_and_migrate()
    for idx, ts in enumerate((100, 200, 300), start=1):
        insert_event(
            conn,
            IndividualEvent(
                run_id="r1",
                timestamp_ns=ts,
                payload=IndividualPayload(id=f"i{idx}", kind="program", is_seed=True),
            ),
        )
    out = read_events(conn, "r1", since_timestamp_ns=100, limit=1)
    assert len(out) == 1
    assert out[0].timestamp_ns == 200
