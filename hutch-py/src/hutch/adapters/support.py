"""Shared helpers for hand-written adapters and live watch mode."""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

from hutch.schema import AnyEvent

_ADAPTER_EVENT_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "https://hutch.local/adapter-events")


def adapter_event_id(
    *,
    adapter_name: str,
    run_id: str,
    event_kind: str,
    source_key: str,
    version: str | None = None,
) -> uuid.UUID:
    """Return a stable UUID for an adapter-derived event."""
    raw = "\x1f".join([adapter_name, run_id, event_kind, source_key, version or ""])
    return uuid.uuid5(_ADAPTER_EVENT_NAMESPACE, raw)


def decorate_adapter_event(
    event: AnyEvent,
    *,
    adapter_name: str,
    source_path: str | Path,
    source_key: str | None = None,
    version: str | None = None,
) -> AnyEvent:
    """Attach source metadata and a deterministic event id to an adapter event."""
    resolved_source_key = source_key or default_source_key(event)
    event.payload.metadata.setdefault("adapter", adapter_name)
    event.payload.metadata.setdefault("source_path", str(Path(source_path).resolve()))
    event.payload.metadata.setdefault("source_key", resolved_source_key)
    event.event_id = adapter_event_id(
        adapter_name=adapter_name,
        run_id=event.run_id,
        event_kind=event.event_kind,
        source_key=resolved_source_key,
        version=version,
    )
    return event


def decorate_adapter_events(
    events: Iterable[AnyEvent],
    *,
    adapter_name: str,
    source_path: str | Path,
) -> Iterator[AnyEvent]:
    for event in events:
        yield decorate_adapter_event(
            event,
            adapter_name=adapter_name,
            source_path=source_path,
        )


def default_source_key(event: AnyEvent) -> str:
    """Best-effort stable source key for adapter events.

    Adapters can provide stronger keys in payload metadata via ``source_table`` /
    ``source_id`` or ``source_key``. This fallback keeps existing adapters live-
    watchable without forcing source-specific code into the watch runner.
    """
    metadata = event.payload.metadata
    explicit = metadata.get("source_key")
    if explicit is not None:
        return str(explicit)
    source_table = metadata.get("source_table")
    source_id = metadata.get("source_id")
    if source_table is not None and source_id is not None:
        return f"{source_table}:{source_id}"

    payload: Any = event.payload
    if event.event_kind == "run_start":
        return "run_start"
    if event.event_kind == "run_update":
        return "run_update"
    if event.event_kind == "run_end":
        return "run_end"
    if event.event_kind == "individual":
        return f"individual:{payload.id}"
    if event.event_kind == "operator":
        return f"operator:{payload.id}"
    if event.event_kind == "fitness":
        evaluator = payload.evaluator_id or payload.evaluator_kind
        score_names = ",".join(sorted(payload.scores))
        return f"fitness:{payload.individual_id}:{evaluator}:{score_names}"
    if event.event_kind == "descriptor":
        return (
            f"descriptor:{payload.individual_id}:{payload.archive_id}:"
            f"{payload.cell_id or json.dumps(payload.coordinates, sort_keys=True)}"
        )
    if event.event_kind == "self_mod":
        return f"self_mod:{payload.parent_agent_id}:{payload.child_agent_id}"
    if event.event_kind == "migration":
        ids = ",".join(payload.individual_ids)
        return f"migration:{payload.population_id}:{payload.from_island}:{payload.to_island}:{ids}"
    if event.event_kind == "archive_snapshot":
        return f"archive_snapshot:{payload.archive_id}:{event.timestamp_ns}"
    if event.event_kind == "pareto_snapshot":
        return f"pareto_snapshot:{payload.population_id}:{event.timestamp_ns}"
    if event.event_kind == "tree_expansion":
        return f"tree_expansion:{payload.tree_id}:{payload.parent_node}:{payload.child_node}"
    if event.event_kind == "claim":
        return f"claim:{payload.id}"
    if event.event_kind == "evidence":
        return f"evidence:{payload.claim_id}:{payload.source_uri}:{payload.stance}"
    if event.event_kind == "review":
        return f"review:{payload.target_id}:{payload.scorer}"
    if event.event_kind == "artifact":
        return f"artifact:{payload.id}"
    if event.event_kind == "lineage_edge":
        return f"lineage_edge:{payload.parent_id}:{payload.child_id}:{payload.relation}"
    if event.event_kind == "stream_event":
        return f"stream_event:{payload.label}:{event.timestamp_ns}:{payload.text or ''}"
    if event.event_kind == "steering_command":
        command_id = payload.metadata.get("command_id")
        return f"steering_command:{command_id or event.timestamp_ns}"
    return f"{event.event_kind}:{event.timestamp_ns}"  # type: ignore[unreachable]
