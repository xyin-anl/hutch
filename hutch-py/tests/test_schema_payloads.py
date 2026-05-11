"""Happy-path construction + selected negative cases for every payload kind."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from hutch.schema import (
    ArchiveSnapshotEvent,
    ArchiveSnapshotPayload,
    ArtifactEvent,
    ArtifactPayload,
    ClaimEvent,
    ClaimPayload,
    DescriptorEvent,
    DescriptorPayload,
    EvidenceEvent,
    EvidencePayload,
    FitnessEvent,
    FitnessPayload,
    IndividualEvent,
    IndividualPayload,
    LineageEdgeEvent,
    LineageEdgePayload,
    MigrationEvent,
    MigrationPayload,
    OperatorEvent,
    OperatorPayload,
    ParetoSnapshotEvent,
    ParetoSnapshotPayload,
    ReviewEvent,
    ReviewPayload,
    RunEndEvent,
    RunEndPayload,
    RunStartEvent,
    RunStartPayload,
    SelfModEvent,
    SelfModPayload,
    SteeringCommandEvent,
    SteeringCommandPayload,
    StreamEventEvent,
    StreamEventPayload,
    TreeExpansionEvent,
    TreeExpansionPayload,
)

RUN = "test-run"


def test_run_start_payload_minimal() -> None:
    e = RunStartEvent(run_id=RUN, payload=RunStartPayload())
    assert e.event_kind == "run_start"
    assert e.payload.config == {}


def test_run_end_payload_default_status() -> None:
    e = RunEndEvent(run_id=RUN, payload=RunEndPayload())
    assert e.payload.status == "finished"


def test_individual_payload_seed() -> None:
    p = IndividualPayload(id="i1", kind="program", is_seed=True)
    e = IndividualEvent(run_id=RUN, payload=p)
    assert e.payload.parent_ids == []


def test_individual_payload_with_parents() -> None:
    p = IndividualPayload(id="i2", kind="program", parent_ids=["i1"])
    assert not p.is_seed
    assert p.parent_ids == ["i1"]


def test_individual_payload_orphan_rejected() -> None:
    with pytest.raises(ValidationError):
        IndividualPayload(id="i1", kind="program")


def test_individual_payload_seed_with_parents_rejected() -> None:
    with pytest.raises(ValidationError):
        IndividualPayload(id="i1", kind="program", is_seed=True, parent_ids=["i0"])


def test_individual_genome_hash_must_be_sha256_hex() -> None:
    IndividualPayload(id="i1", kind="program", is_seed=True, genome_hash="a" * 64)
    with pytest.raises(ValidationError):
        IndividualPayload(id="i1", kind="program", is_seed=True, genome_hash="../not-a-hash")


def test_operator_payload_propose_no_parents() -> None:
    p = OperatorPayload(id="op1", kind="propose", child_id="i1")
    e = OperatorEvent(run_id=RUN, payload=p)
    assert e.payload.parent_ids == []


def test_operator_payload_crossover_two_parents() -> None:
    p = OperatorPayload(id="op2", kind="crossover", parent_ids=["a", "b"], child_id="c")
    assert len(p.parent_ids) == 2


def test_operator_payload_distill_n_parents() -> None:
    """§5.4: parent_ids supports arbitrary fanout."""
    parents = [f"a{i}" for i in range(7)]
    p = OperatorPayload(id="op3", kind="distill", parent_ids=parents, child_id="c")
    assert len(p.parent_ids) == 7


def test_operator_temperature_range() -> None:
    with pytest.raises(ValidationError):
        OperatorPayload(id="op", kind="mutate", parent_ids=["a"], child_id="c", llm_temperature=3.0)


def test_fitness_happy() -> None:
    p = FitnessPayload(
        individual_id="i1",
        evaluator_kind="deterministic_metric",
        scores={"accuracy": 0.9, "cost": 0.3},
    )
    FitnessEvent(run_id=RUN, payload=p)


def test_fitness_invalid_reason_allows_empty_scores() -> None:
    p = FitnessPayload(
        individual_id="i1",
        evaluator_kind="unit_test",
        invalid_reason="timeout",
    )
    assert p.scores == {}


def test_fitness_empty_scores_rejected_when_no_invalid_reason() -> None:
    with pytest.raises(ValidationError):
        FitnessPayload(individual_id="i1", evaluator_kind="benchmark")


def test_descriptor_grid() -> None:
    p = DescriptorPayload(
        individual_id="i1",
        archive_id="a1",
        kind="grid",
        dimensions=["complexity", "diversity"],
        coordinates=[0.3, 0.7],
        cell_id="(3,7)",
    )
    DescriptorEvent(run_id=RUN, payload=p)


def test_descriptor_dim_mismatch_rejected() -> None:
    with pytest.raises(ValidationError):
        DescriptorPayload(
            individual_id="i1",
            archive_id="a1",
            kind="grid",
            dimensions=["x", "y", "z"],
            coordinates=[0.1, 0.2],
        )


def test_lineage_edge() -> None:
    p = LineageEdgePayload(parent_id="p", child_id="c")
    LineageEdgeEvent(run_id=RUN, payload=p)


def test_migration_event() -> None:
    p = MigrationPayload(
        population_id="pop1",
        from_island="3",
        to_island="4",
        individual_ids=["i1", "i2"],
    )
    MigrationEvent(run_id=RUN, payload=p)


def test_self_mod() -> None:
    p = SelfModPayload(
        parent_agent_id="v17",
        child_agent_id="v18",
        target_path="src/agent.py",
        score_before=0.41,
        score_after=0.43,
    )
    SelfModEvent(run_id=RUN, payload=p)
    assert p.overseer_verdict == "pending"


def test_artifact() -> None:
    p = ArtifactPayload(id="art1", kind="program", uri="hutch+local://abc123")
    ArtifactEvent(run_id=RUN, payload=p)


def test_artifact_hash_must_be_sha256_hex() -> None:
    ArtifactPayload(id="art1", kind="program", uri="hutch+local://abc123", hash="f" * 64)
    with pytest.raises(ValidationError):
        ArtifactPayload(id="art1", kind="program", uri="hutch+local://abc123", hash="bad")


def test_claim() -> None:
    p = ClaimPayload(id="c1", text="X improves Y by 12%.", supported_by=["i1"])
    ClaimEvent(run_id=RUN, payload=p)


def test_evidence_confidence_range() -> None:
    EvidencePayload(claim_id="c1", source_uri="arxiv:1234", stance="supports", confidence=0.7)
    with pytest.raises(ValidationError):
        EvidencePayload(claim_id="c1", source_uri="x", stance="mentions", confidence=1.5)


def test_evidence_event() -> None:
    p = EvidencePayload(claim_id="c1", source_uri="arxiv:1234", stance="contradicts")
    EvidenceEvent(run_id=RUN, payload=p)


def test_review() -> None:
    p = ReviewPayload(target_id="i1", scorer="claude-4", scores={"novelty": 6.0})
    ReviewEvent(run_id=RUN, payload=p)


def test_stream_event() -> None:
    p = StreamEventPayload(label="heartbeat")
    StreamEventEvent(run_id=RUN, stream_id="s1", payload=p)


def test_steering_command() -> None:
    p = SteeringCommandPayload(
        command="cancel_individual",
        target_id="i1",
        actor="human",
    )
    SteeringCommandEvent(run_id=RUN, payload=p)


def test_tree_expansion() -> None:
    p = TreeExpansionPayload(
        tree_id="t1",
        parent_node="n1",
        child_node="n2",
        visit_count=4,
        value_estimate=0.7,
    )
    TreeExpansionEvent(run_id=RUN, payload=p)


def test_archive_snapshot_coverage_range() -> None:
    p = ArchiveSnapshotPayload(archive_id="a1", coverage=0.42, size=128)
    ArchiveSnapshotEvent(run_id=RUN, payload=p)
    with pytest.raises(ValidationError):
        ArchiveSnapshotPayload(archive_id="a1", coverage=1.2, size=128)
    with pytest.raises(ValidationError):
        ArchiveSnapshotPayload(archive_id="a1", coverage=-0.1, size=128)


def test_pareto_snapshot() -> None:
    p = ParetoSnapshotPayload(
        population_id="pop1",
        front=["i1", "i7"],
        objectives=["sum_radii", "compile_ms"],
    )
    ParetoSnapshotEvent(run_id=RUN, payload=p)


def test_pareto_empty_front_rejected() -> None:
    with pytest.raises(ValidationError):
        ParetoSnapshotPayload(population_id="pop1", front=[], objectives=["x"])


def test_metadata_extension_dict_allowed_everywhere() -> None:
    """Every payload accepts a free-form metadata dict."""
    p = IndividualPayload(
        id="i1",
        kind="program",
        is_seed=True,
        metadata={"experimenter": "xyin", "rng_seed": 42},
    )
    assert p.metadata["rng_seed"] == 42
