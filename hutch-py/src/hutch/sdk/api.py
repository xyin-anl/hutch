"""User-facing logging API.

All functions are thin wrappers that:

1. Resolve the active run.
2. Build the matching Payload + Event from kwargs.
3. Send the event through the configured transport.
4. Return the payload so the caller can chain calls
   (``op = h.log_operator(..., child_id=ind.id)``).
"""

from __future__ import annotations

import uuid
from typing import Any

from hutch.schema import (
    AnyEvent,
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
    StreamEventEvent,
    StreamEventPayload,
    TreeExpansionEvent,
    TreeExpansionPayload,
)
from hutch.schema.types import (
    ArtifactKind,
    DescriptorArchiveKind,
    EvaluatorKind,
    EvidenceStance,
    IndividualKind,
    OperatorKind,
    PopulationKind,
    RunStatus,
    ScoreDirection,
    SelfModVerdict,
)
from hutch.sdk._state import (
    Population,
    RunHandle,
    active_run,
    clear_run,
    register_population,
    set_run,
    state,
)


def _new_id(prefix: str = "") -> str:
    short = uuid.uuid4().hex[:12]
    return f"{prefix}{short}" if prefix else short


def _send(event: AnyEvent) -> None:
    state().transport.send(event)


# ---------- run / population -------------------------------------------


def start_run(
    *,
    name: str | None = None,
    project: str | None = None,
    run_id: str | None = None,
    started_by: str | None = None,
    git_commit: str | None = None,
    config: dict[str, Any] | None = None,
    score_directions: dict[str, ScoreDirection] | None = None,
) -> RunHandle:
    """Open a run and emit a ``run_start`` event.

    *score_directions* — declare each fitness metric you'll log under
    ``log_fitness(scores=...)`` as either ``"higher"`` (higher is
    better) or ``"lower"`` (lower is better). The dashboard's Pareto
    frontier, best-composite aggregation, and any direction-aware
    consumer reads from here. Metrics you don't declare fall back to
    a name-based regex heuristic in the UI; declaring them is strictly
    more reliable.

    The returned handle is also installed as the *active run* for the
    process, so subsequent ``log_*`` calls don't need to pass ``run_id``.
    """
    handle = RunHandle(
        id=run_id or _new_id(prefix="run-"),
        name=name,
        project=project,
    )
    _send(
        RunStartEvent(
            run_id=handle.id,
            payload=RunStartPayload(
                name=name,
                project=project,
                started_by=started_by,
                git_commit=git_commit,
                config=config or {},
                score_directions=dict(score_directions or {}),
            ),
        )
    )
    set_run(handle)
    return handle


def end_run(*, status: RunStatus = "finished", summary: str | None = None) -> None:
    """Emit a ``run_end`` event for the active run and clear the active state."""
    handle = active_run()
    _send(
        RunEndEvent(
            run_id=handle.id,
            payload=RunEndPayload(status=status, summary=summary),
        )
    )
    clear_run()


def start_population(
    *,
    name: str,
    kind: PopulationKind,
    population_id: str | None = None,
    descriptor_dims: list[str] | None = None,
    num_islands: int | None = None,
    objectives: list[tuple[str, str]] | None = None,
) -> Population:
    """Register a population *handle*. Populations are pure metadata for v0
    and don't currently emit a canonical event; this hook reserves the API
    surface for when one lands."""
    pop = Population(
        id=population_id or _new_id(prefix="pop-"),
        name=name,
        kind=kind,
        descriptor_dims=list(descriptor_dims or []),
        objectives=list(objectives or []),
    )
    del num_islands
    register_population(pop)
    return pop


# ---------- per-event loggers ------------------------------------------


def log_individual(
    *,
    kind: IndividualKind,
    parent_ids: list[str] | None = None,
    is_seed: bool | None = None,
    individual_id: str | None = None,
    genome_uri: str | None = None,
    genome_hash: str | None = None,
    genome_lang: str | None = None,
    population_id: str | None = None,
    island_id: str | None = None,
    generation_index: int | None = None,
    metadata: dict[str, Any] | None = None,
    stream_id: str | None = None,
    worker_id: str | None = None,
) -> IndividualPayload:
    """Log one Individual. Returns the payload so callers can use ``ind.id``."""
    handle = active_run()
    parents = list(parent_ids or [])
    seed = is_seed if is_seed is not None else (len(parents) == 0)
    payload = IndividualPayload(
        id=individual_id or _new_id(prefix="ind-"),
        kind=kind,
        parent_ids=parents,
        is_seed=seed,
        genome_uri=genome_uri,
        genome_hash=genome_hash,
        genome_lang=genome_lang,
        population_id=population_id,
        island_id=island_id,
        generation_index=generation_index,
        metadata=metadata or {},
    )
    _send(
        IndividualEvent(
            run_id=handle.id,
            stream_id=stream_id,
            worker_id=worker_id,
            payload=payload,
        )
    )
    return payload


def log_operator(
    *,
    kind: OperatorKind,
    child_id: str,
    parent_ids: list[str] | None = None,
    operator_id: str | None = None,
    prompt_template: str | None = None,
    llm_id: str | None = None,
    llm_temperature: float | None = None,
    diff: str | None = None,
    diff_uri: str | None = None,
    cost_usd: float | None = None,
    tokens_in: int | None = None,
    tokens_out: int | None = None,
    metadata: dict[str, Any] | None = None,
    stream_id: str | None = None,
    worker_id: str | None = None,
) -> OperatorPayload:
    handle = active_run()
    payload = OperatorPayload(
        id=operator_id or _new_id(prefix="op-"),
        kind=kind,
        parent_ids=list(parent_ids or []),
        child_id=child_id,
        prompt_template=prompt_template,
        llm_id=llm_id,
        llm_temperature=llm_temperature,
        diff=diff,
        diff_uri=diff_uri,
        cost_usd=cost_usd,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        metadata=metadata or {},
    )
    _send(
        OperatorEvent(
            run_id=handle.id,
            stream_id=stream_id,
            worker_id=worker_id,
            payload=payload,
        )
    )
    return payload


def log_fitness(
    *,
    individual: IndividualPayload | str,
    scores: dict[str, float] | None = None,
    evaluator_kind: EvaluatorKind = "deterministic_metric",
    evaluator_id: str | None = None,
    composite: float | None = None,
    cascade_stage: int | None = None,
    is_pareto_front: bool | None = None,
    dominates: list[str] | None = None,
    invalid_reason: str | None = None,
    metadata: dict[str, Any] | None = None,
    stream_id: str | None = None,
) -> FitnessPayload:
    handle = active_run()
    individual_id = individual.id if isinstance(individual, IndividualPayload) else individual
    payload = FitnessPayload(
        individual_id=individual_id,
        evaluator_id=evaluator_id,
        evaluator_kind=evaluator_kind,
        scores=dict(scores or {}),
        composite=composite,
        cascade_stage=cascade_stage,
        is_pareto_front=is_pareto_front,
        dominates=list(dominates or []),
        invalid_reason=invalid_reason,
        metadata=metadata or {},
    )
    _send(FitnessEvent(run_id=handle.id, stream_id=stream_id, payload=payload))
    return payload


def log_descriptor(
    *,
    individual: IndividualPayload | str,
    archive_id: str,
    coordinates: list[float] | None = None,
    cell_id: str | None = None,
    kind: DescriptorArchiveKind = "grid",
    dimensions: list[str] | None = None,
    is_replaced: bool = False,
    metadata: dict[str, Any] | None = None,
) -> DescriptorPayload:
    handle = active_run()
    individual_id = individual.id if isinstance(individual, IndividualPayload) else individual
    payload = DescriptorPayload(
        individual_id=individual_id,
        archive_id=archive_id,
        kind=kind,
        dimensions=dimensions,
        coordinates=list(coordinates or []),
        cell_id=cell_id,
        is_replaced=is_replaced,
        metadata=metadata or {},
    )
    _send(DescriptorEvent(run_id=handle.id, payload=payload))
    return payload


def log_archive_snapshot(
    *,
    archive_id: str,
    coverage: float,
    size: int,
    qd_score: float | None = None,
    max_fitness: float | None = None,
    snapshot_uri: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> ArchiveSnapshotPayload:
    handle = active_run()
    payload = ArchiveSnapshotPayload(
        archive_id=archive_id,
        coverage=coverage,
        qd_score=qd_score,
        max_fitness=max_fitness,
        size=size,
        snapshot_uri=snapshot_uri,
        metadata=metadata or {},
    )
    _send(ArchiveSnapshotEvent(run_id=handle.id, payload=payload))
    return payload


def log_island_migration(
    *,
    population_id: str,
    from_island: str,
    to_island: str,
    individual_ids: list[str],
    trigger: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> MigrationPayload:
    handle = active_run()
    payload = MigrationPayload(
        population_id=population_id,
        from_island=from_island,
        to_island=to_island,
        individual_ids=list(individual_ids),
        trigger=trigger,
        metadata=metadata or {},
    )
    _send(MigrationEvent(run_id=handle.id, payload=payload))
    return payload


def log_self_modification(
    *,
    parent_agent_id: str,
    child_agent_id: str,
    target_path: str | None = None,
    diff_uri: str | None = None,
    proposal: str | None = None,
    overseer_id: str | None = None,
    overseer_verdict: SelfModVerdict = "pending",
    benchmark: str | None = None,
    score_before: float | None = None,
    score_after: float | None = None,
    metadata: dict[str, Any] | None = None,
) -> SelfModPayload:
    handle = active_run()
    payload = SelfModPayload(
        parent_agent_id=parent_agent_id,
        child_agent_id=child_agent_id,
        target_path=target_path,
        diff_uri=diff_uri,
        proposal=proposal,
        overseer_id=overseer_id,
        overseer_verdict=overseer_verdict,
        benchmark=benchmark,
        score_before=score_before,
        score_after=score_after,
        metadata=metadata or {},
    )
    _send(SelfModEvent(run_id=handle.id, payload=payload))
    return payload


def log_artifact(
    *,
    kind: ArtifactKind,
    uri: str,
    artifact_id: str | None = None,
    hash: str | None = None,
    format: str | None = None,
    parent_artifact_id: str | None = None,
    ara_layer: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> ArtifactPayload:
    handle = active_run()
    payload = ArtifactPayload(
        id=artifact_id or _new_id(prefix="art-"),
        kind=kind,
        uri=uri,
        hash=hash,
        format=format,
        parent_artifact_id=parent_artifact_id,
        ara_layer=ara_layer,
        metadata=metadata or {},
    )
    _send(ArtifactEvent(run_id=handle.id, payload=payload))
    return payload


def log_pareto_front(
    *,
    population: Population | str,
    front: list[str],
    objectives: list[str],
    hypervolume: float | None = None,
    metadata: dict[str, Any] | None = None,
) -> ParetoSnapshotPayload:
    handle = active_run()
    population_id = population.id if isinstance(population, Population) else population
    payload = ParetoSnapshotPayload(
        population_id=population_id,
        front=list(front),
        objectives=list(objectives),
        hypervolume=hypervolume,
        metadata=metadata or {},
    )
    _send(ParetoSnapshotEvent(run_id=handle.id, payload=payload))
    return payload


def log_tree_expansion(
    *,
    tree_id: str,
    parent_node: str,
    child_node: str,
    visit_count: int = 0,
    value_estimate: float | None = None,
    virtual_loss: float | None = None,
    metadata: dict[str, Any] | None = None,
) -> TreeExpansionPayload:
    handle = active_run()
    payload = TreeExpansionPayload(
        tree_id=tree_id,
        parent_node=parent_node,
        child_node=child_node,
        visit_count=visit_count,
        value_estimate=value_estimate,
        virtual_loss=virtual_loss,
        metadata=metadata or {},
    )
    _send(TreeExpansionEvent(run_id=handle.id, payload=payload))
    return payload


def log_stream_event(
    *,
    label: str,
    text: str | None = None,
    stream_id: str | None = None,
    worker_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> StreamEventPayload:
    handle = active_run()
    payload = StreamEventPayload(label=label, text=text, metadata=metadata or {})
    _send(
        StreamEventEvent(
            run_id=handle.id,
            stream_id=stream_id,
            worker_id=worker_id,
            payload=payload,
        )
    )
    return payload


def log_claim(
    *,
    text: str,
    supported_by: list[str] | None = None,
    requires_reproduction: bool = False,
    claim_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> ClaimPayload:
    handle = active_run()
    payload = ClaimPayload(
        id=claim_id or _new_id(prefix="claim-"),
        text=text,
        supported_by=list(supported_by or []),
        requires_reproduction=requires_reproduction,
        metadata=metadata or {},
    )
    _send(ClaimEvent(run_id=handle.id, payload=payload))
    return payload


def log_evidence(
    *,
    claim_id: str,
    source_uri: str,
    stance: EvidenceStance,
    confidence: float | None = None,
    source_quality: float | None = None,
    metadata: dict[str, Any] | None = None,
) -> EvidencePayload:
    handle = active_run()
    payload = EvidencePayload(
        claim_id=claim_id,
        source_uri=source_uri,
        stance=stance,
        confidence=confidence,
        source_quality=source_quality,
        metadata=metadata or {},
    )
    _send(EvidenceEvent(run_id=handle.id, payload=payload))
    return payload


def log_review(
    *,
    target_id: str,
    scorer: str,
    scores: dict[str, float] | None = None,
    concerns: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> ReviewPayload:
    handle = active_run()
    payload = ReviewPayload(
        target_id=target_id,
        scorer=scorer,
        scores=dict(scores or {}),
        concerns=list(concerns or []),
        metadata=metadata or {},
    )
    _send(ReviewEvent(run_id=handle.id, payload=payload))
    return payload
