"""Coverage tests for the literal-kind enums and the discriminated event union."""

from __future__ import annotations

from typing import get_args

from hutch.schema import (
    ALL_KINDS,
    EVENT_ADAPTER,
    EVENT_CLASSES,
    EventKind,
    IndividualEvent,
    IndividualPayload,
)


def test_event_classes_count_matches_event_kind_literal() -> None:
    """Every EventKind has exactly one concrete Event subclass."""
    kinds_in_classes = {cls.model_fields["event_kind"].default for cls in EVENT_CLASSES}
    kinds_in_literal = set(get_args(EventKind))
    assert kinds_in_classes == kinds_in_literal


def test_all_kinds_tuple_matches_event_kind_literal() -> None:
    """The runtime ALL_KINDS tuple mirrors the EventKind literal."""
    assert set(ALL_KINDS) == set(get_args(EventKind))
    assert len(ALL_KINDS) == len(set(ALL_KINDS))


def test_event_classes_unique_kinds() -> None:
    """No two Event subclasses claim the same event_kind."""
    kinds = [cls.model_fields["event_kind"].default for cls in EVENT_CLASSES]
    assert len(kinds) == len(set(kinds))


def test_event_adapter_dispatches_by_kind() -> None:
    """The TypeAdapter dispatches a generic dict to the right concrete class."""
    raw = {
        "run_id": "r1",
        "event_kind": "individual",
        "payload": {"id": "i1", "kind": "program", "is_seed": True},
    }
    parsed = EVENT_ADAPTER.validate_python(raw)
    assert isinstance(parsed, IndividualEvent)
    assert parsed.payload.id == "i1"


def test_event_adapter_rejects_unknown_kind() -> None:
    raw = {
        "run_id": "r1",
        "event_kind": "not_a_real_kind",
        "payload": {},
    }
    try:
        EVENT_ADAPTER.validate_python(raw)
    except Exception as exc:
        assert "discriminator" in str(exc) or "tag" in str(exc).lower()
    else:  # pragma: no cover
        raise AssertionError("expected ValidationError for unknown event_kind")


def test_default_timestamp_and_event_id() -> None:
    """Auto-defaults: timestamp_ns is positive, event_id is unique per call."""
    e1 = IndividualEvent(
        run_id="r1",
        payload=IndividualPayload(id="i1", kind="program", is_seed=True),
    )
    e2 = IndividualEvent(
        run_id="r1",
        payload=IndividualPayload(id="i2", kind="program", is_seed=True),
    )
    assert e1.timestamp_ns > 0
    assert e2.timestamp_ns > 0
    assert e1.event_id != e2.event_id
