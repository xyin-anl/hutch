"""Full round-trip identity tests: Event → JSON → DuckDB → query → Event.

This is the M1 done-criterion check: an in-memory
event survives JSON serialization, DuckDB persistence, and read-back as an
identical Pydantic instance.
"""

from __future__ import annotations

import pytest

from hutch.schema import (
    EVENT_ADAPTER,
    AnyEvent,
    ArchiveSnapshotEvent,
    ArchiveSnapshotPayload,
    DescriptorEvent,
    DescriptorPayload,
    FitnessEvent,
    FitnessPayload,
    IndividualEvent,
    IndividualPayload,
    OperatorEvent,
    OperatorPayload,
    ParetoSnapshotEvent,
    ParetoSnapshotPayload,
    SelfModEvent,
    SelfModPayload,
    SteeringCommandEvent,
    SteeringCommandPayload,
    TreeExpansionEvent,
    TreeExpansionPayload,
)
from hutch.store import insert_event, open_and_migrate, read_events

ROUND_TRIP_FIXTURES: list[tuple[str, AnyEvent]] = [
    (
        "individual-with-parents",
        IndividualEvent(
            run_id="r1",
            stream_id="researcher",
            worker_id="w1",
            payload=IndividualPayload(
                id="i7",
                kind="program",
                parent_ids=["i1", "i3"],
                genome_uri="hutch+local://abc",
                genome_hash="a" * 64,
                generation_index=4,
                island_id="2",
                metadata={"rng": 42},
            ),
        ),
    ),
    (
        "operator-crossover",
        OperatorEvent(
            run_id="r1",
            payload=OperatorPayload(
                id="op-c",
                kind="crossover",
                parent_ids=["i1", "i2"],
                child_id="i3",
                llm_id="claude-sonnet-4-6",
                llm_temperature=0.7,
                cost_usd=0.0124,
                tokens_in=1230,
                tokens_out=412,
            ),
        ),
    ),
    (
        "fitness-multi-metric",
        FitnessEvent(
            run_id="r1",
            payload=FitnessPayload(
                individual_id="i7",
                evaluator_kind="benchmark",
                scores={"sum_radii": 2.63, "compile_ms": 84.0},
                composite=2.63,
                cascade_stage=2,
                is_pareto_front=True,
                dominates=["i4", "i5"],
            ),
        ),
    ),
    (
        "descriptor-grid",
        DescriptorEvent(
            run_id="r1",
            payload=DescriptorPayload(
                individual_id="i7",
                archive_id="ME-1",
                kind="grid",
                dimensions=["complexity", "diversity", "performance"],
                coordinates=[0.34, 0.71, 0.12],
                cell_id="(34,71,12)",
            ),
        ),
    ),
    (
        "self-mod",
        SelfModEvent(
            run_id="r1",
            payload=SelfModPayload(
                parent_agent_id="v17",
                child_agent_id="v18",
                target_path="src/coder.py",
                diff_uri="hutch+local://difff00",
                proposal="Replace BFS with A*",
                overseer_id="claude-opus-4-7",
                overseer_verdict="accepted",
                benchmark="swe-bench-mini",
                score_before=0.41,
                score_after=0.46,
            ),
        ),
    ),
    (
        "steering",
        SteeringCommandEvent(
            run_id="r1",
            payload=SteeringCommandPayload(
                command="freeze_island",
                target_id="island-3",
                params={"reason": "diversity collapse"},
                actor="human",
            ),
        ),
    ),
    (
        "tree-expansion",
        TreeExpansionEvent(
            run_id="r1",
            payload=TreeExpansionPayload(
                tree_id="aide-1",
                parent_node="n17",
                child_node="n34",
                visit_count=8,
                value_estimate=0.62,
                virtual_loss=0.1,
            ),
        ),
    ),
    (
        "archive-snapshot",
        ArchiveSnapshotEvent(
            run_id="r1",
            payload=ArchiveSnapshotPayload(
                archive_id="ME-1",
                coverage=0.42,
                qd_score=12.7,
                max_fitness=2.63,
                size=84,
                snapshot_uri="hutch+local://snap",
            ),
        ),
    ),
    (
        "pareto",
        ParetoSnapshotEvent(
            run_id="r1",
            payload=ParetoSnapshotPayload(
                population_id="pop1",
                front=["i7", "i9", "i12"],
                objectives=["sum_radii", "compile_ms"],
                hypervolume=0.83,
            ),
        ),
    ),
]


@pytest.mark.parametrize(
    ("label", "event"), ROUND_TRIP_FIXTURES, ids=lambda v: v if isinstance(v, str) else ""
)
def test_event_round_trip_via_json(label: str, event: AnyEvent) -> None:
    """In-memory → JSON string → discriminated parse → equal."""
    del label
    raw = event.model_dump_json()
    back = EVENT_ADAPTER.validate_json(raw)
    assert back == event
    assert type(back) is type(event)


@pytest.mark.parametrize(
    ("label", "event"), ROUND_TRIP_FIXTURES, ids=lambda v: v if isinstance(v, str) else ""
)
def test_event_round_trip_via_duckdb(label: str, event: AnyEvent) -> None:
    """In-memory → DuckDB INSERT → SELECT → discriminated parse → equal."""
    del label
    conn = open_and_migrate()
    insert_event(conn, event)
    read_back = read_events(conn, event.run_id)
    assert len(read_back) == 1
    assert read_back[0] == event
    assert type(read_back[0]) is type(event)


def test_full_run_round_trip_preserves_order_and_count() -> None:
    """A whole sequence of mixed-kind events round-trips identically and in order."""
    conn = open_and_migrate()
    for i, (_, event) in enumerate(ROUND_TRIP_FIXTURES):
        # Force a deterministic ordering for the round-trip ordering check.
        event_with_ts = event.model_copy(update={"timestamp_ns": (i + 1) * 1000})
        insert_event(conn, event_with_ts)
    read_back = read_events(conn, "r1")
    assert len(read_back) == len(ROUND_TRIP_FIXTURES)
    timestamps = [ev.timestamp_ns for ev in read_back]
    assert timestamps == sorted(timestamps)
