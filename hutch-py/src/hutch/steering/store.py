"""In-memory steering queues, keyed by ``run_id``.

The daemon maintains a per-run command queue that the agent polls between
iterations. We keep the queue in memory for simplicity (single-process
daemon for v0) and additionally persist every command — both at issue
time and on outcome — as a ``steering_command`` event so the steering
trail survives a daemon restart and shows up in the run-history audit
table.

The queue distinguishes three states per command:

``pending``   — issued by the UI, not yet returned to a poll
``delivered`` — returned to a poll, awaiting an ack from the agent
``acked``     — agent has reported an outcome (``accepted`` / ``rejected``
                / ``done``); the command is removed from the live queue
                but kept in the history list for the panel UI.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

from hutch.schema.types import SteeringActor, SteeringCommandKind

CommandStatus = Literal["pending", "delivered", "acked"]


@dataclass(slots=True)
class SteeringRecord:
    """A single steering command tracked by the queue."""

    command_id: str
    run_id: str
    command: SteeringCommandKind
    target_id: str | None
    params: dict[str, Any]
    actor: SteeringActor
    created_at_ns: int
    status: CommandStatus = "pending"
    delivered_at_ns: int | None = None
    acked_at_ns: int | None = None
    outcome: str | None = None
    outcome_note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "command_id": self.command_id,
            "run_id": self.run_id,
            "command": self.command,
            "target_id": self.target_id,
            "params": dict(self.params),
            "actor": self.actor,
            "created_at_ns": self.created_at_ns,
            "status": self.status,
            "delivered_at_ns": self.delivered_at_ns,
            "acked_at_ns": self.acked_at_ns,
            "outcome": self.outcome,
            "outcome_note": self.outcome_note,
        }


@dataclass(slots=True)
class _RunQueue:
    pending: list[SteeringRecord] = field(default_factory=list)
    history: list[SteeringRecord] = field(default_factory=list)


class SteeringStore:
    """Per-run steering queues.

    Designed for single-process use; a multi-replica deployment would need
    to swap the in-memory dict for Redis (post-v0.1.0).
    """

    def __init__(self) -> None:
        self._queues: dict[str, _RunQueue] = {}
        self._lock = asyncio.Lock()

    @staticmethod
    def _now_ns() -> int:
        return time.time_ns()

    @staticmethod
    def _new_id() -> str:
        return f"cmd-{uuid.uuid4().hex[:12]}"

    async def issue(
        self,
        *,
        run_id: str,
        command: SteeringCommandKind,
        target_id: str | None,
        params: dict[str, Any],
        actor: SteeringActor,
    ) -> SteeringRecord:
        record = SteeringRecord(
            command_id=self._new_id(),
            run_id=run_id,
            command=command,
            target_id=target_id,
            params=dict(params),
            actor=actor,
            created_at_ns=self._now_ns(),
        )
        async with self._lock:
            queue = self._queues.setdefault(run_id, _RunQueue())
            queue.pending.append(record)
            queue.history.append(record)
        return record

    async def poll(self, run_id: str) -> list[SteeringRecord]:
        """Return + mark every pending command as ``delivered``.

        The agent is expected to ack each one after handling. Until then the
        records remain visible in :meth:`list_history` with status
        ``delivered``; on next poll they aren't returned again.
        """
        now = self._now_ns()
        async with self._lock:
            queue = self._queues.get(run_id)
            if queue is None or not queue.pending:
                return []
            delivered = list(queue.pending)
            for rec in delivered:
                rec.status = "delivered"
                rec.delivered_at_ns = now
            queue.pending.clear()
        return delivered

    async def ack(
        self,
        *,
        run_id: str,
        command_id: str,
        outcome: str,
        note: str | None = None,
    ) -> SteeringRecord | None:
        async with self._lock:
            queue = self._queues.get(run_id)
            if queue is None:
                return None
            for rec in queue.history:
                if rec.command_id == command_id:
                    rec.status = "acked"
                    rec.outcome = outcome
                    rec.outcome_note = note
                    rec.acked_at_ns = self._now_ns()
                    return rec
        return None

    async def list_history(self, run_id: str) -> list[SteeringRecord]:
        async with self._lock:
            queue = self._queues.get(run_id)
            if queue is None:
                return []
            return list(queue.history)

    async def list_pending(self, run_id: str) -> list[SteeringRecord]:
        async with self._lock:
            queue = self._queues.get(run_id)
            if queue is None:
                return []
            return list(queue.pending)
