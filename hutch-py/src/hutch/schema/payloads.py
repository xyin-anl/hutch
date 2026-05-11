"""Per-event payload models.

Each payload is paired with a single event-envelope variant in
:mod:`hutch.schema.events`. Payloads are intentionally permissive: most
fields are optional so an importer producing partial data still validates.
The minimum-required set per payload is what an *honest* producer cannot
omit without losing essential meaning.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from hutch.schema.types import (
    ArtifactKind,
    DescriptorArchiveKind,
    EvaluatorKind,
    EvidenceStance,
    IndividualKind,
    OperatorKind,
    RunStatus,
    ScoreDirection,
    SelfModVerdict,
    SteeringActor,
    SteeringCommandKind,
)

_strict = ConfigDict(extra="forbid")


class _PayloadBase(BaseModel):
    """Common payload base. Reject unknown fields by default; loose-mode
    payloads can override ``model_config`` if they ever need to."""

    model_config = _strict

    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Free-form extension dictionary. Adapters / SDKs use this for "
        "fields the canonical schema does not yet model.",
    )


class RunStartPayload(_PayloadBase):
    """Opens a run."""

    name: str | None = None
    project: str | None = None
    started_by: str | None = Field(
        default=None,
        description="Free-form actor identifier (user, CI job, agent id).",
    )
    git_commit: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    capabilities: dict[str, bool] = Field(
        default_factory=dict,
        description=(
            "Truthful dashboard capabilities declared by the producer. "
            "Common keys include `steering`, `llm_usage`, `live_updates`, and `audit`. "
            "Absent keys mean unsupported or not logged, never implicitly true."
        ),
    )
    score_directions: dict[str, ScoreDirection] = Field(
        default_factory=dict,
        description=(
            "Per-metric optimisation direction — `higher` (higher is better) "
            "or `lower` (lower is better). Used by the dashboard's Pareto "
            "frontier, best-composite aggregation, and any other consumer "
            "that needs to know which way is up. Declare every metric you "
            "log under `FitnessPayload.scores`. Unmatched metrics fall back "
            "to a name-based heuristic in the UI."
        ),
    )


class RunUpdatePayload(_PayloadBase):
    """Updates mutable run-level metadata for live/watch producers."""

    status: RunStatus | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    capabilities: dict[str, bool] = Field(default_factory=dict)
    score_directions: dict[str, ScoreDirection] = Field(default_factory=dict)
    source_counts: dict[str, int] = Field(default_factory=dict)
    watcher: dict[str, Any] = Field(default_factory=dict)


class RunEndPayload(_PayloadBase):
    """Closes a run."""

    status: RunStatus = "finished"
    summary: str | None = None


class IndividualPayload(_PayloadBase):
    """A single candidate Individual."""

    id: str
    kind: IndividualKind
    parent_ids: list[str] = Field(
        default_factory=list,
        description="Zero or more parent Individual ids. Empty iff ``is_seed`` is True.",
    )
    is_seed: bool = False
    genome_uri: str | None = None
    genome_hash: str | None = Field(
        default=None,
        pattern=r"^[0-9a-fA-F]{64}$",
        description="Optional SHA-256 hex digest for ``genome_uri`` content.",
    )
    genome_lang: str | None = None
    population_id: str | None = None
    island_id: str | None = None
    generation_index: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _seed_xor_parents(self) -> IndividualPayload:
        """§5.4 invariant: an Individual has at least one parent OR is a seed."""
        if self.is_seed and self.parent_ids:
            raise ValueError("Seed individuals must not declare parent_ids.")
        if not self.is_seed and not self.parent_ids:
            raise ValueError("Individual has no parent_ids; set is_seed=True to mark it as a seed.")
        return self


class OperatorPayload(_PayloadBase):
    """An event that produces a child Individual from zero or more parents."""

    id: str
    kind: OperatorKind
    parent_ids: list[str] = Field(default_factory=list)
    child_id: str
    prompt_template: str | None = None
    llm_id: str | None = None
    llm_temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    diff: str | None = Field(
        default=None,
        description="Inline diff text; for large diffs prefer ``diff_uri``.",
    )
    diff_uri: str | None = None
    cost_usd: float | None = Field(default=None, ge=0.0)
    tokens_in: int | None = Field(default=None, ge=0)
    tokens_out: int | None = Field(default=None, ge=0)


class FitnessPayload(_PayloadBase):
    """Multi-metric scalar evaluation of an Individual."""

    individual_id: str
    evaluator_id: str | None = None
    evaluator_kind: EvaluatorKind
    scores: dict[str, float] = Field(default_factory=dict)
    composite: float | None = None
    cascade_stage: int | None = Field(default=None, ge=0)
    is_pareto_front: bool | None = None
    dominates: list[str] = Field(default_factory=list)
    invalid_reason: str | None = Field(
        default=None,
        description="If set, this evaluation is considered failed; ``scores`` may be empty.",
    )

    @model_validator(mode="after")
    def _scores_or_invalid(self) -> FitnessPayload:
        if self.invalid_reason is None and not self.scores:
            raise ValueError(
                "FitnessPayload must contain at least one score, or set invalid_reason."
            )
        return self


class DescriptorPayload(_PayloadBase):
    """Locates an Individual in a behaviour archive (MAP-Elites / CVT / AURORA)."""

    individual_id: str
    archive_id: str
    kind: DescriptorArchiveKind
    dimensions: list[str] | None = None
    coordinates: list[float] = Field(default_factory=list)
    cell_id: str | None = None
    is_replaced: bool = False

    @model_validator(mode="after")
    def _coords_match_dims(self) -> DescriptorPayload:
        if self.dimensions is not None and self.coordinates:
            if len(self.dimensions) != len(self.coordinates):
                raise ValueError(
                    f"Descriptor has {len(self.coordinates)} coordinates but "
                    f"{len(self.dimensions)} dimensions."
                )
        return self


class LineageEdgePayload(_PayloadBase):
    """A single edge in the lineage DAG. Usually redundant with Operator events
    but used by importers that have edges without operator context."""

    parent_id: str
    child_id: str
    relation: str = "parent"


class MigrationPayload(_PayloadBase):
    """Inter-island migration of one or more Individuals."""

    population_id: str
    from_island: str
    to_island: str
    individual_ids: list[str]
    trigger: str | None = None


class SelfModPayload(_PayloadBase):
    """A self-modification proposal applied (or rejected) by an overseer."""

    parent_agent_id: str
    child_agent_id: str
    target_path: str | None = None
    diff_uri: str | None = None
    proposal: str | None = None
    overseer_id: str | None = None
    overseer_verdict: SelfModVerdict = "pending"
    benchmark: str | None = None
    score_before: float | None = None
    score_after: float | None = None


class ArtifactPayload(_PayloadBase):
    """Externally-stored content (genome blob, dataset, paper, …) referenced
    by URI + content hash."""

    id: str
    kind: ArtifactKind
    uri: str
    hash: str | None = Field(
        default=None,
        pattern=r"^[0-9a-fA-F]{64}$",
        description="Optional SHA-256 hex digest for ``uri`` content.",
    )
    format: str | None = None
    parent_artifact_id: str | None = None
    ara_layer: str | None = Field(
        default=None,
        description="Optional ARA-package layer label.",
    )


class ClaimPayload(_PayloadBase):
    """A claim derived from a run, optionally requiring reproduction."""

    id: str
    text: str
    supported_by: list[str] = Field(default_factory=list)
    requires_reproduction: bool = False


class EvidencePayload(_PayloadBase):
    """A piece of evidence weighing on a claim."""

    claim_id: str
    source_uri: str
    stance: EvidenceStance
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    source_quality: float | None = Field(default=None, ge=0.0, le=1.0)


class ReviewPayload(_PayloadBase):
    """An LLM-judge or human review of an Individual / claim / run."""

    target_id: str
    scorer: str
    scores: dict[str, float] = Field(default_factory=dict)
    concerns: list[str] = Field(default_factory=list)


class StreamEventPayload(_PayloadBase):
    """Open-ended log entry on a stream/worker swimlane (heartbeats, free-form
    annotations). Mostly used by the operator-trace view."""

    label: str
    text: str | None = None


class SteeringCommandPayload(_PayloadBase):
    """A write-back command from the dashboard."""

    command: SteeringCommandKind
    target_id: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    actor: SteeringActor


class TreeExpansionPayload(_PayloadBase):
    """An MCTS-style tree expansion event."""

    tree_id: str
    parent_node: str
    child_node: str
    visit_count: int = Field(default=0, ge=0)
    value_estimate: float | None = None
    virtual_loss: float | None = None


class ArchiveSnapshotPayload(_PayloadBase):
    """A periodic snapshot of an Archive's aggregate stats."""

    archive_id: str
    coverage: float = Field(ge=0.0, le=1.0)
    qd_score: float | None = None
    max_fitness: float | None = None
    size: int = Field(ge=0)
    snapshot_uri: str | None = None


class ParetoSnapshotPayload(_PayloadBase):
    """A periodic snapshot of a multi-objective Pareto front."""

    population_id: str
    front: list[str]
    objectives: list[str]
    hypervolume: float | None = None

    @model_validator(mode="after")
    def _front_non_empty(self) -> ParetoSnapshotPayload:
        if not self.front:
            raise ValueError("ParetoSnapshotPayload.front must contain at least one id.")
        return self
