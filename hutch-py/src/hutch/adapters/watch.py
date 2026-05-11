from __future__ import annotations

import hashlib
import json
import time
from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, cast

from hutch.adapters import CompletionPolicy
from hutch.adapters.support import decorate_adapter_event
from hutch.schema import AnyEvent, RunUpdateEvent, RunUpdatePayload
from hutch.sdk.transport import Transport


class WatchableAdapter(Protocol):
    name: str
    completion_policy: CompletionPolicy

    def is_complete(self, path: Path) -> bool | None: ...

    def iter_events(
        self,
        path: Path,
        *,
        run_id: str | None = None,
        project: str | None = None,
        finalize: bool = True,
        **importer_options: Any,
    ) -> Iterable[AnyEvent]: ...


ProgressCallback = Callable[[str], None]


@dataclass(frozen=True)
class WatchResult:
    adapter_name: str
    path: Path
    run_id: str | None
    polls: int
    events_sent: int
    completed: bool
    interrupted: bool = False


def watch_adapter(
    adapter: WatchableAdapter,
    path: Path,
    transport: Transport,
    *,
    run_id: str | None = None,
    project: str | None = None,
    poll_interval: float = 2.0,
    idle_complete_seconds: float = 60.0,
    adapter_options: Mapping[str, Any] | None = None,
    state_path: Path | None = None,
    progress: ProgressCallback | None = None,
) -> WatchResult:
    """Poll an adapter source and send only newly observed canonical events."""

    if poll_interval <= 0:
        raise ValueError("poll_interval must be greater than zero")
    if idle_complete_seconds <= 0:
        raise ValueError("idle_complete_seconds must be greater than zero")

    path = Path(path)
    seen_event_ids = _load_seen_event_ids(state_path)
    last_new_monotonic = time.monotonic()
    polls = 0
    sent = 0
    options = dict(adapter_options or {})

    def send_new(events: Iterable[AnyEvent]) -> int:
        sent_now = 0
        for event in events:
            event_id = str(event.event_id)
            if event_id in seen_event_ids:
                continue
            transport.send(event)
            seen_event_ids.add(event_id)
            sent_now += 1
        if sent_now:
            _save_seen_event_ids(state_path, seen_event_ids)
        return sent_now

    try:
        while True:
            polls += 1
            try:
                events = list(
                    adapter.iter_events(
                        path,
                        run_id=run_id,
                        project=project,
                        finalize=False,
                        **options,
                    )
                )
            except Exception as exc:
                if not _is_transient_source_error(exc):
                    raise
                if progress is not None:
                    progress(f"poll {polls}: source temporarily unreadable ({exc})")
                time.sleep(poll_interval)
                continue
            sent_now = send_new(events)
            update = _build_run_update(
                adapter=adapter,
                path=path,
                events=events,
                poll_index=polls,
            )
            if update is not None:
                sent_now += send_new([update])
            sent += sent_now

            if sent_now:
                last_new_monotonic = time.monotonic()
                if progress is not None:
                    progress(f"poll {polls}: sent {sent_now} new event(s)")

            complete_state = adapter.is_complete(path)
            if complete_state is True:
                final_events = list(
                    adapter.iter_events(
                        path,
                        run_id=run_id,
                        project=project,
                        finalize=True,
                        **options,
                    )
                )
                sent_final = send_new(final_events)
                sent += sent_final
                if progress is not None:
                    progress(f"completion detected; sent {sent_final} final event(s)")
                return WatchResult(
                    adapter_name=adapter.name,
                    path=path,
                    run_id=run_id,
                    polls=polls,
                    events_sent=sent,
                    completed=True,
                )

            idle_elapsed = time.monotonic() - last_new_monotonic
            if adapter.completion_policy == "idle" and idle_elapsed >= idle_complete_seconds:
                final_events = list(
                    adapter.iter_events(
                        path,
                        run_id=run_id,
                        project=project,
                        finalize=True,
                        **options,
                    )
                )
                sent_final = send_new(final_events)
                sent += sent_final
                if progress is not None:
                    progress(f"idle completion reached; sent {sent_final} final event(s)")
                return WatchResult(
                    adapter_name=adapter.name,
                    path=path,
                    run_id=run_id,
                    polls=polls,
                    events_sent=sent,
                    completed=True,
                )

            time.sleep(poll_interval)
    except KeyboardInterrupt:
        if progress is not None:
            progress("watch interrupted; leaving run open")
        return WatchResult(
            adapter_name=adapter.name,
            path=path,
            run_id=run_id,
            polls=polls,
            events_sent=sent,
            completed=False,
            interrupted=True,
        )


def _build_run_update(
    *,
    adapter: WatchableAdapter,
    path: Path,
    events: list[AnyEvent],
    poll_index: int,
) -> RunUpdateEvent | None:
    run_start = next((event for event in events if event.event_kind == "run_start"), None)
    if run_start is None:
        return None

    source_counts = Counter(event.event_kind for event in events)
    signature = _events_signature(events)
    timestamp_ns = max((event.timestamp_ns for event in events), default=time.time_ns())
    run_update = RunUpdateEvent(
        run_id=run_start.run_id,
        timestamp_ns=timestamp_ns,
        payload=RunUpdatePayload(
            status="running",
            config=dict(getattr(run_start.payload, "config", {}) or {}),
            capabilities={"live_updates": True},
            score_directions=dict(getattr(run_start.payload, "score_directions", {}) or {}),
            source_counts=dict(source_counts),
            watcher={
                "adapter": adapter.name,
                "poll_index": poll_index,
                "completion_policy": adapter.completion_policy,
            },
        ),
    )
    return cast(
        RunUpdateEvent,
        decorate_adapter_event(
            run_update,
            adapter_name=adapter.name,
            source_path=path,
            source_key=f"run_update:{signature}",
        ),
    )


def _events_signature(events: list[AnyEvent]) -> str:
    digest = hashlib.sha256()
    for event in sorted(events, key=lambda item: str(item.event_id)):
        digest.update(str(event.event_id).encode("utf-8"))
        digest.update(b":")
        digest.update(event.model_dump_json().encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()[:24]


def _is_transient_source_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return "database is locked" in text or "database is busy" in text or "locked" in text


def _load_seen_event_ids(state_path: Path | None) -> set[str]:
    if state_path is None or not state_path.is_file():
        return set()
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    raw_ids = data.get("event_ids") if isinstance(data, dict) else None
    if not isinstance(raw_ids, list):
        return set()
    return {str(value) for value in raw_ids if isinstance(value, str)}


def _save_seen_event_ids(state_path: Path | None, event_ids: set[str]) -> None:
    if state_path is None:
        return
    state_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = state_path.with_suffix(state_path.suffix + ".tmp")
    tmp_path.write_text(
        json.dumps({"event_ids": sorted(event_ids)}, sort_keys=True),
        encoding="utf-8",
    )
    tmp_path.replace(state_path)
