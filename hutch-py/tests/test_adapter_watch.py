from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from uuid import UUID

from hutch.adapters.watch import watch_adapter
from hutch.schema import (
    EVENT_ADAPTER,
    AnyEvent,
    IndividualEvent,
    IndividualPayload,
    RunEndEvent,
    RunEndPayload,
    RunStartEvent,
    RunStartPayload,
)
from hutch.sdk.transport import Transport


class _Sink(Transport):
    def __init__(self) -> None:
        self.events: list[AnyEvent] = []

    def send(self, event: AnyEvent) -> None:
        self.events.append(event)

    def close(self) -> None:
        return


class _ExplicitFakeAdapter:
    name = "fake"
    completion_policy = "explicit"

    def __init__(self) -> None:
        self.polls = 0

    def iter_events(
        self,
        path: Path,
        *,
        run_id: str | None = None,
        project: str | None = None,
        finalize: bool = True,
    ) -> Iterator[AnyEvent]:
        del path
        self.polls += 1
        resolved_run_id = run_id or "run-live"
        yield RunStartEvent(
            event_id=UUID("00000000-0000-0000-0000-000000000001"),
            run_id=resolved_run_id,
            timestamp_ns=1,
            payload=RunStartPayload(name="fake", project=project),
        )
        yield _individual(resolved_run_id, "a", 2)
        if self.polls >= 2:
            yield _individual(resolved_run_id, "b", 3)
        if finalize:
            yield RunEndEvent(
                event_id=UUID("00000000-0000-0000-0000-000000000004"),
                run_id=resolved_run_id,
                timestamp_ns=4,
                payload=RunEndPayload(status="finished"),
            )

    def is_complete(self, path: Path) -> bool | None:
        del path
        return self.polls >= 2


class _IdleFakeAdapter:
    name = "idle_fake"
    completion_policy = "idle"

    def iter_events(
        self,
        path: Path,
        *,
        run_id: str | None = None,
        project: str | None = None,
        finalize: bool = True,
    ) -> Iterator[AnyEvent]:
        del path
        resolved_run_id = run_id or "run-idle"
        yield RunStartEvent(
            event_id=UUID("00000000-0000-0000-0000-000000000011"),
            run_id=resolved_run_id,
            timestamp_ns=1,
            payload=RunStartPayload(name="idle", project=project),
        )
        yield _individual(resolved_run_id, "a", 2)
        if finalize:
            yield RunEndEvent(
                event_id=UUID("00000000-0000-0000-0000-000000000013"),
                run_id=resolved_run_id,
                timestamp_ns=3,
                payload=RunEndPayload(status="finished"),
            )

    def is_complete(self, path: Path) -> bool | None:
        del path
        return None


def test_watch_dedupes_repeated_polls_and_sends_new_records(tmp_path: Path) -> None:
    adapter = _ExplicitFakeAdapter()
    sink = _Sink()

    result = watch_adapter(
        adapter,
        tmp_path,
        sink,
        run_id="watched",
        poll_interval=0.01,
        idle_complete_seconds=1.0,
    )

    assert result.completed is True
    assert [event.event_kind for event in sink.events] == [
        "run_start",
        "individual",
        "run_update",
        "individual",
        "run_update",
        "run_end",
    ]
    assert [event.payload.id for event in sink.events if event.event_kind == "individual"] == [  # type: ignore[union-attr]
        "a",
        "b",
    ]
    assert all(
        event.payload.capabilities == {"live_updates": True}  # type: ignore[union-attr]
        for event in sink.events
        if event.event_kind == "run_update"
    )
    for event in sink.events:
        EVENT_ADAPTER.validate_python(event.model_dump())


def test_watch_idle_completion_sends_run_end(tmp_path: Path) -> None:
    sink = _Sink()

    result = watch_adapter(
        _IdleFakeAdapter(),
        tmp_path,
        sink,
        poll_interval=0.01,
        idle_complete_seconds=0.01,
    )

    assert result.completed is True
    assert [event.event_kind for event in sink.events].count("run_end") == 1


def test_watch_state_checkpoint_suppresses_restart_replay(tmp_path: Path) -> None:
    state_path = tmp_path / "watch-state.json"
    first_sink = _Sink()
    first = watch_adapter(
        _ExplicitFakeAdapter(),
        tmp_path,
        first_sink,
        run_id="watched",
        poll_interval=0.01,
        idle_complete_seconds=1.0,
        state_path=state_path,
    )
    assert first.completed is True
    assert first.events_sent > 0
    assert state_path.is_file()

    second_sink = _Sink()
    second = watch_adapter(
        _ExplicitFakeAdapter(),
        tmp_path,
        second_sink,
        run_id="watched",
        poll_interval=0.01,
        idle_complete_seconds=1.0,
        state_path=state_path,
    )
    assert second.completed is True
    assert second.events_sent == 0
    assert second_sink.events == []


def _individual(run_id: str, individual_id: str, timestamp_ns: int) -> IndividualEvent:
    suffix = 2 if individual_id == "a" else 3
    return IndividualEvent(
        event_id=UUID(f"00000000-0000-0000-0000-00000000000{suffix}"),
        run_id=run_id,
        timestamp_ns=timestamp_ns,
        payload=IndividualPayload(
            id=individual_id,
            kind="program",
            parent_ids=[],
            is_seed=True,
        ),
    )
