"""Fallback JSONL queue.

If a daemon POST fails and the SDK is *not* in strict mode, events are
appended to a local JSONL file and replayed when the daemon comes back.
Each line is one canonical event in JSON form, deserializable through
:data:`hutch.schema.EVENT_ADAPTER`.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from pathlib import Path

from hutch.schema import EVENT_ADAPTER, AnyEvent

logger = logging.getLogger("hutch.sdk.fallback")
REPLAY_SUFFIX = ".replay"


def append_event(path: Path, event: AnyEvent) -> None:
    """Append a single event to the fallback JSONL."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(event.model_dump_json())
        fh.write("\n")


def iter_events(path: Path) -> Iterator[AnyEvent]:
    """Yield every event currently in the fallback file."""
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                yield EVENT_ADAPTER.validate_json(line)
            except Exception as exc:
                logger.warning("dropping malformed fallback event at %s:%d: %s", path, line_no, exc)


def drain(path: Path) -> list[AnyEvent]:
    """Return every event in the fallback file and remove the file.

    The atomicity here is "good enough for telemetry": we read everything,
    delete the file, then return the events for the caller to re-send. If the
    process dies between read and delete the events get replayed twice;
    daemon de-duplicates on event_id (which is part of the canonical model).
    """
    if not path.exists():
        return []
    events = list(iter_events(path))
    path.unlink(missing_ok=True)
    return events


def replay_path(path: Path) -> Path:
    """Return the durable in-flight replay file for *path*."""
    return path.with_name(path.name + REPLAY_SUFFIX)


def begin_replay(path: Path) -> Path | None:
    """Atomically move the live queue into an in-flight replay file.

    If a previous process crashed during replay, the existing replay file is
    returned first and the live queue is left untouched for a later pass.
    """
    replay = replay_path(path)
    if replay.exists():
        return replay
    if not path.exists():
        return None
    path.replace(replay)
    return replay


def finish_replay(path: Path) -> None:
    """Remove a replay file after all confirmed events have been handled."""
    path.unlink(missing_ok=True)


def queue_size(path: Path) -> int:
    """Cheap line count for tests."""
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8") as fh:
        return sum(1 for line in fh if line.strip())
