"""Per-run WebSocket pub/sub for live dashboard updates.

When an event is accepted via ``POST /events``, the broadcaster fans it out
to every WebSocket currently subscribed to that run. Subscribers maintained
per ``run_id`` so a noisy run doesn't push events into the wrong dashboard.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import WebSocket

logger = logging.getLogger("hutch.daemon.broadcaster")


class RunBroadcaster:
    """In-process pub/sub keyed by ``run_id``.

    For v0 this is a single-process broadcaster; multi-replica deployments
    will need a Redis or NATS-backed implementation. Tracked for post-v0.1.0.
    """

    def __init__(self) -> None:
        self._subscribers: dict[str, set[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def subscribe(self, run_id: str, ws: WebSocket) -> None:
        async with self._lock:
            self._subscribers.setdefault(run_id, set()).add(ws)

    async def unsubscribe(self, run_id: str, ws: WebSocket) -> None:
        async with self._lock:
            subs = self._subscribers.get(run_id)
            if subs is not None:
                subs.discard(ws)
                if not subs:
                    del self._subscribers[run_id]

    async def publish(self, run_id: str, payload: str) -> None:
        """Send *payload* (a JSON-encoded event) to every subscriber of *run_id*.

        Failures on individual sockets are swallowed — those connections are
        removed on their next disconnect notification.
        """
        async with self._lock:
            targets = list(self._subscribers.get(run_id, set()))
        for ws in targets:
            try:
                await ws.send_text(payload)
            except Exception as exc:
                logger.debug("dropping broken subscriber on run %s: %s", run_id, exc)

    def subscriber_count(self, run_id: str) -> int:
        """Number of live subscribers for *run_id* (test helper)."""
        return len(self._subscribers.get(run_id, set()))
