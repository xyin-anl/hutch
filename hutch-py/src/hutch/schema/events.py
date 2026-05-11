"""Canonical event envelope and the discriminated
union over all event variants.

Each variant pairs an ``event_kind`` literal with the matching payload model
from :mod:`hutch.schema.payloads`. The discriminator ``event_kind`` is what
Pydantic uses to dispatch deserialization in :data:`AnyEvent`.
"""

from __future__ import annotations

import time
from typing import Annotated, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from hutch.schema.payloads import (
    ArchiveSnapshotPayload,
    ArtifactPayload,
    ClaimPayload,
    DescriptorPayload,
    EvidencePayload,
    FitnessPayload,
    IndividualPayload,
    LineageEdgePayload,
    MigrationPayload,
    OperatorPayload,
    ParetoSnapshotPayload,
    ReviewPayload,
    RunEndPayload,
    RunStartPayload,
    SelfModPayload,
    SteeringCommandPayload,
    StreamEventPayload,
    TreeExpansionPayload,
)

_strict = ConfigDict(extra="forbid")


def _now_ns() -> int:
    return time.time_ns()


class _EventEnvelope(BaseModel):
    """Common envelope columns for every Hutch event."""

    model_config = _strict

    event_id: UUID = Field(default_factory=uuid4)
    run_id: str
    timestamp_ns: int = Field(default_factory=_now_ns, ge=0)
    stream_id: str | None = None
    worker_id: str | None = None
    span_id: str | None = None
    trace_id: str | None = None


class RunStartEvent(_EventEnvelope):
    event_kind: Literal["run_start"] = "run_start"
    payload: RunStartPayload


class RunEndEvent(_EventEnvelope):
    event_kind: Literal["run_end"] = "run_end"
    payload: RunEndPayload


class IndividualEvent(_EventEnvelope):
    event_kind: Literal["individual"] = "individual"
    payload: IndividualPayload


class OperatorEvent(_EventEnvelope):
    event_kind: Literal["operator"] = "operator"
    payload: OperatorPayload


class FitnessEvent(_EventEnvelope):
    event_kind: Literal["fitness"] = "fitness"
    payload: FitnessPayload


class DescriptorEvent(_EventEnvelope):
    event_kind: Literal["descriptor"] = "descriptor"
    payload: DescriptorPayload


class LineageEdgeEvent(_EventEnvelope):
    event_kind: Literal["lineage_edge"] = "lineage_edge"
    payload: LineageEdgePayload


class MigrationEvent(_EventEnvelope):
    event_kind: Literal["migration"] = "migration"
    payload: MigrationPayload


class SelfModEvent(_EventEnvelope):
    event_kind: Literal["self_mod"] = "self_mod"
    payload: SelfModPayload


class ArtifactEvent(_EventEnvelope):
    event_kind: Literal["artifact"] = "artifact"
    payload: ArtifactPayload


class ClaimEvent(_EventEnvelope):
    event_kind: Literal["claim"] = "claim"
    payload: ClaimPayload


class EvidenceEvent(_EventEnvelope):
    event_kind: Literal["evidence"] = "evidence"
    payload: EvidencePayload


class ReviewEvent(_EventEnvelope):
    event_kind: Literal["review"] = "review"
    payload: ReviewPayload


class StreamEventEvent(_EventEnvelope):
    event_kind: Literal["stream_event"] = "stream_event"
    payload: StreamEventPayload


class SteeringCommandEvent(_EventEnvelope):
    event_kind: Literal["steering_command"] = "steering_command"
    payload: SteeringCommandPayload


class TreeExpansionEvent(_EventEnvelope):
    event_kind: Literal["tree_expansion"] = "tree_expansion"
    payload: TreeExpansionPayload


class ArchiveSnapshotEvent(_EventEnvelope):
    event_kind: Literal["archive_snapshot"] = "archive_snapshot"
    payload: ArchiveSnapshotPayload


class ParetoSnapshotEvent(_EventEnvelope):
    event_kind: Literal["pareto_snapshot"] = "pareto_snapshot"
    payload: ParetoSnapshotPayload


AnyEvent = Annotated[
    RunStartEvent
    | RunEndEvent
    | IndividualEvent
    | OperatorEvent
    | FitnessEvent
    | DescriptorEvent
    | LineageEdgeEvent
    | MigrationEvent
    | SelfModEvent
    | ArtifactEvent
    | ClaimEvent
    | EvidenceEvent
    | ReviewEvent
    | StreamEventEvent
    | SteeringCommandEvent
    | TreeExpansionEvent
    | ArchiveSnapshotEvent
    | ParetoSnapshotEvent,
    Field(discriminator="event_kind"),
]
"""Discriminated union over every concrete event class.

Use :data:`EVENT_ADAPTER` to deserialize an arbitrary payload to the right
concrete subtype:

    >>> from hutch.schema import EVENT_ADAPTER
    >>> EVENT_ADAPTER.validate_python(some_dict)
"""

EVENT_ADAPTER: TypeAdapter[
    RunStartEvent
    | RunEndEvent
    | IndividualEvent
    | OperatorEvent
    | FitnessEvent
    | DescriptorEvent
    | LineageEdgeEvent
    | MigrationEvent
    | SelfModEvent
    | ArtifactEvent
    | ClaimEvent
    | EvidenceEvent
    | ReviewEvent
    | StreamEventEvent
    | SteeringCommandEvent
    | TreeExpansionEvent
    | ArchiveSnapshotEvent
    | ParetoSnapshotEvent
] = TypeAdapter(AnyEvent)
"""Cached :class:`pydantic.TypeAdapter` for the discriminated event union."""

EVENT_CLASSES: tuple[type[_EventEnvelope], ...] = (
    RunStartEvent,
    RunEndEvent,
    IndividualEvent,
    OperatorEvent,
    FitnessEvent,
    DescriptorEvent,
    LineageEdgeEvent,
    MigrationEvent,
    SelfModEvent,
    ArtifactEvent,
    ClaimEvent,
    EvidenceEvent,
    ReviewEvent,
    StreamEventEvent,
    SteeringCommandEvent,
    TreeExpansionEvent,
    ArchiveSnapshotEvent,
    ParetoSnapshotEvent,
)
"""Iteration helper — every concrete Event subclass."""
