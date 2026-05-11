"""SDK tests in embedded mode (writes directly to DuckDB)."""

from __future__ import annotations

from pathlib import Path

import hutch as h
from hutch.schema import IndividualEvent, OperatorEvent
from hutch.sdk import SDKConfig
from hutch.store import open_db, read_events


def _embedded_config(tmp_path: Path) -> SDKConfig:
    return SDKConfig(mode="embedded", db_path=tmp_path / "hutch.duckdb")


def test_start_run_emits_run_start(tmp_path: Path) -> None:
    h.configure(_embedded_config(tmp_path))
    run = h.start_run(name="test-run", project="hutch")
    assert run.id.startswith("run-")

    conn = open_db(tmp_path / "hutch.duckdb")
    events = read_events(conn, run.id)
    conn.close()
    assert len(events) == 1
    assert events[0].event_kind == "run_start"
    assert events[0].payload.name == "test-run"  # type: ignore[union-attr]


def test_log_individual_seed_default(tmp_path: Path) -> None:
    h.configure(_embedded_config(tmp_path))
    run = h.start_run(name="r")
    seed = h.log_individual(kind="program")
    assert seed.is_seed is True
    assert seed.parent_ids == []

    conn = open_db(tmp_path / "hutch.duckdb")
    events = read_events(conn, run.id)
    conn.close()
    individuals = [e for e in events if isinstance(e, IndividualEvent)]
    assert len(individuals) == 1
    assert individuals[0].payload.id == seed.id


def test_full_linear_loop(tmp_path: Path) -> None:
    """Mini hypothesis → evaluate → claim loop, exercising the §6.1 surface."""
    h.configure(_embedded_config(tmp_path))
    run = h.start_run(name="linear")
    seed = h.log_individual(kind="hypothesis")
    refined = h.log_individual(kind="hypothesis", parent_ids=[seed.id])
    op = h.log_operator(kind="refine", parent_ids=[seed.id], child_id=refined.id)
    h.log_fitness(individual=refined, scores={"plausibility": 0.7})
    claim = h.log_claim(text="X improves Y by 12%", supported_by=[refined.id])
    h.log_evidence(claim_id=claim.id, source_uri="arxiv:1234", stance="supports")
    h.end_run(status="finished")

    conn = open_db(tmp_path / "hutch.duckdb")
    events = read_events(conn, run.id)
    conn.close()

    kinds = [e.event_kind for e in events]
    assert kinds == [
        "run_start",
        "individual",
        "individual",
        "operator",
        "fitness",
        "claim",
        "evidence",
        "run_end",
    ]
    # The operator's child_id matches the refined individual.
    op_event = next(e for e in events if isinstance(e, OperatorEvent))
    assert op_event.payload.child_id == refined.id
    assert op_event.payload.id == op.id


def test_active_run_required_outside_start_run(tmp_path: Path) -> None:
    h.configure(_embedded_config(tmp_path))
    import pytest

    with pytest.raises(RuntimeError, match="No active Hutch run"):
        h.log_individual(kind="program")


def test_explicit_run_id_round_trip(tmp_path: Path) -> None:
    h.configure(_embedded_config(tmp_path))
    h.start_run(name="r", run_id="custom-run")
    h.log_individual(kind="program", individual_id="my-seed")

    conn = open_db(tmp_path / "hutch.duckdb")
    events = read_events(conn, "custom-run")
    conn.close()
    assert any(getattr(e.payload, "id", None) == "my-seed" for e in events)


def test_start_population_returns_handle(tmp_path: Path) -> None:
    h.configure(_embedded_config(tmp_path))
    h.start_run(name="r")
    pop = h.start_population(
        name="circle-packing",
        kind="island",
        num_islands=4,
        objectives=[("sum_radii", "max"), ("compile_ms", "min")],
    )
    assert pop.id.startswith("pop-")
    assert pop.kind == "island"
    assert len(pop.objectives) == 2


def test_log_pareto_front(tmp_path: Path) -> None:
    h.configure(_embedded_config(tmp_path))
    run = h.start_run(name="r")
    pop = h.start_population(name="cp", kind="island")
    h.log_pareto_front(population=pop, front=["i1", "i2"], objectives=["x", "y"], hypervolume=0.9)
    conn = open_db(tmp_path / "hutch.duckdb")
    events = read_events(conn, run.id)
    conn.close()
    pareto = [e for e in events if e.event_kind == "pareto_snapshot"]
    assert len(pareto) == 1
    assert pareto[0].payload.front == ["i1", "i2"]  # type: ignore[union-attr]


def test_log_stream_event_and_archive_snapshot(tmp_path: Path) -> None:
    h.configure(_embedded_config(tmp_path))
    run = h.start_run(name="r")
    h.log_stream_event(label="heartbeat", text="worker alive", stream_id="worker-1")
    h.log_archive_snapshot(archive_id="grid", coverage=0.25, size=10, qd_score=3.5)

    conn = open_db(tmp_path / "hutch.duckdb")
    events = read_events(conn, run.id)
    conn.close()

    kinds = [e.event_kind for e in events]
    assert "stream_event" in kinds
    assert "archive_snapshot" in kinds
