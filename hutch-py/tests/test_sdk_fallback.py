"""Tests for the JSONL fallback queue."""

from __future__ import annotations

from pathlib import Path

import httpx

from hutch.schema import IndividualEvent, IndividualPayload
from hutch.sdk import fallback
from hutch.sdk.config import SDKConfig
from hutch.sdk.transport import DaemonTransport


def _make_event(seed_id: str = "i1") -> IndividualEvent:
    return IndividualEvent(
        run_id="r1",
        payload=IndividualPayload(id=seed_id, kind="program", is_seed=True),
    )


def test_append_and_iter_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "fb.jsonl"
    e1 = _make_event("a")
    e2 = _make_event("b")
    fallback.append_event(path, e1)
    fallback.append_event(path, e2)
    out = list(fallback.iter_events(path))
    assert len(out) == 2
    ids = {e.payload.id for e in out}  # type: ignore[union-attr]
    assert ids == {"a", "b"}


def test_drain_clears_file(tmp_path: Path) -> None:
    path = tmp_path / "fb.jsonl"
    fallback.append_event(path, _make_event("a"))
    drained = fallback.drain(path)
    assert len(drained) == 1
    assert not path.exists()
    assert fallback.drain(path) == []


def test_begin_replay_keeps_events_in_inflight_file(tmp_path: Path) -> None:
    path = tmp_path / "fb.jsonl"
    fallback.append_event(path, _make_event("a"))

    replay = fallback.begin_replay(path)

    assert replay == fallback.replay_path(path)
    assert replay is not None
    assert not path.exists()
    assert replay.exists()
    assert [event.payload.id for event in fallback.iter_events(replay)] == ["a"]


def test_existing_replay_file_takes_precedence(tmp_path: Path) -> None:
    path = tmp_path / "fb.jsonl"
    replay = fallback.replay_path(path)
    fallback.append_event(replay, _make_event("old"))
    fallback.append_event(path, _make_event("new"))

    assert fallback.begin_replay(path) == replay
    assert path.exists()
    assert [event.payload.id for event in fallback.iter_events(replay)] == ["old"]


def test_iter_missing_path_yields_nothing(tmp_path: Path) -> None:
    path = tmp_path / "nope.jsonl"
    assert list(fallback.iter_events(path)) == []


def test_queue_size(tmp_path: Path) -> None:
    path = tmp_path / "fb.jsonl"
    assert fallback.queue_size(path) == 0
    fallback.append_event(path, _make_event("a"))
    fallback.append_event(path, _make_event("b"))
    assert fallback.queue_size(path) == 2


def test_blank_lines_ignored(tmp_path: Path) -> None:
    path = tmp_path / "fb.jsonl"
    fallback.append_event(path, _make_event("a"))
    # Inject blank lines.
    with path.open("a", encoding="utf-8") as fh:
        fh.write("\n\n")
    fallback.append_event(path, _make_event("b"))
    out = list(fallback.iter_events(path))
    assert len(out) == 2


def test_daemon_transport_requeues_failed_and_later_events(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "fb.jsonl"
    for seed_id in ("a", "b", "c"):
        fallback.append_event(path, _make_event(seed_id))

    posted: list[str] = []

    def fake_post(self: DaemonTransport, event: IndividualEvent) -> None:
        del self
        posted.append(event.payload.id)
        if event.payload.id == "b":
            raise httpx.ConnectError("daemon down")

    monkeypatch.setattr(DaemonTransport, "_post", fake_post)
    transport = DaemonTransport(SDKConfig(daemon_url="http://127.0.0.1:7777", fallback_path=path))
    transport.close()

    assert posted == ["a", "b"]
    assert [event.payload.id for event in fallback.iter_events(path)] == ["b", "c"]
    assert not fallback.replay_path(path).exists()
