"""User-facing steering API for agents.

The user instruments their loop with two pieces:

* ``@hutch.steering.handler("cancel_individual")`` registers a per-command
  callback.
* ``hutch.steering.poll()`` pulls every pending command for the active
  run, dispatches to handlers, and acks each one with the result. If no
  handler is registered for a given command, it's still acked but with
  outcome ``rejected`` and a note explaining "no handler".

For programmatic command issuance (used by examples/tests/CI) call
:func:`send`. The UI uses ``POST /steering/{run_id}`` directly.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx

from hutch.schema.types import SteeringActor, SteeringCommandKind
from hutch.sdk._state import active_run, state

logger = logging.getLogger("hutch.steering")

HandlerFn = Callable[["SteeringCommand"], Any]


@dataclass(slots=True)
class SteeringCommand:
    """The lightweight client-side view of a queued command."""

    command_id: str
    run_id: str
    command: SteeringCommandKind
    target_id: str | None
    params: dict[str, Any]
    actor: SteeringActor
    created_at_ns: int

    @classmethod
    def from_payload(cls, raw: dict[str, Any]) -> SteeringCommand:
        return cls(
            command_id=raw["command_id"],
            run_id=raw["run_id"],
            command=raw["command"],
            target_id=raw.get("target_id"),
            params=dict(raw.get("params") or {}),
            actor=raw["actor"],
            created_at_ns=int(raw["created_at_ns"]),
        )


# ---------- handler registry ----------------------------------------------

_handlers_lock = threading.Lock()
_handlers: dict[SteeringCommandKind, HandlerFn] = {}


def handler(command: SteeringCommandKind) -> Callable[[HandlerFn], HandlerFn]:
    """Register a handler for *command*. The decorated function receives a
    :class:`SteeringCommand` and may return any JSON-serialisable value
    (used as the ack note)."""

    def deco(fn: HandlerFn) -> HandlerFn:
        with _handlers_lock:
            _handlers[command] = fn
        return fn

    return deco


def _client() -> httpx.Client:
    """Build an httpx client targeting the configured daemon.

    Tests monkey-patch this to hand back an in-process FastAPI ``TestClient``;
    callers must therefore use the returned client *without* a ``with`` block
    so the test client's lifespan stays open across multiple steering calls.
    """
    cfg = state().config
    headers = {"authorization": f"Bearer {cfg.auth_token}"} if cfg.auth_token else None
    return httpx.Client(base_url=cfg.daemon_url, timeout=cfg.request_timeout_s, headers=headers)


def _close_if_own_client(client: httpx.Client) -> None:
    """Close real httpx clients while preserving monkeypatched TestClients."""
    if hasattr(client, "app"):
        return
    client.close()


# ---------- public API ----------------------------------------------------


def send(
    *,
    command: SteeringCommandKind,
    target_id: str | None = None,
    params: dict[str, Any] | None = None,
    actor: SteeringActor = "human",
    run_id: str | None = None,
) -> dict[str, Any]:
    """Issue a steering command. Used by the UI (via HTTP) but also
    available to agents/tests that want to enqueue programmatically."""
    target_run = run_id or active_run().id
    body = {
        "command": command,
        "target_id": target_id,
        "params": params or {},
        "actor": actor,
    }
    client = _client()
    try:
        resp = client.post(f"/steering/{target_run}", json=body)
        resp.raise_for_status()
        result: Any = resp.json()
    finally:
        _close_if_own_client(client)
    if isinstance(result, dict):
        return dict(result)
    raise RuntimeError(f"unexpected POST /steering/{target_run} response: {result!r}")


def poll(*, run_id: str | None = None, raise_on_failure: bool = False) -> list[SteeringCommand]:
    """Drain the steering queue for the run, dispatching to registered
    handlers. Returns the list of commands that were processed."""
    target_run = run_id or active_run().id
    try:
        client = _client()
        try:
            resp = client.get(f"/steering/{target_run}/poll")
            resp.raise_for_status()
            raw_payload: Any = resp.json()
        finally:
            _close_if_own_client(client)
    except httpx.HTTPError as exc:
        if raise_on_failure:
            raise
        logger.debug("steering poll failed: %s", exc)
        return []
    raw = list(raw_payload) if isinstance(raw_payload, list) else []
    commands = [SteeringCommand.from_payload(rec) for rec in raw]
    for cmd in commands:
        with _handlers_lock:
            fn = _handlers.get(cmd.command)
        if fn is None:
            ack(
                run_id=cmd.run_id,
                command_id=cmd.command_id,
                outcome="rejected",
                note=f"no handler registered for {cmd.command!r}",
            )
            continue
        try:
            note = fn(cmd)
        except Exception as exc:
            logger.warning("steering handler %s raised: %s", cmd.command, exc)
            ack(
                run_id=cmd.run_id,
                command_id=cmd.command_id,
                outcome="rejected",
                note=f"handler raised {type(exc).__name__}: {exc}",
            )
            continue
        ack(
            run_id=cmd.run_id,
            command_id=cmd.command_id,
            outcome="done",
            note=str(note) if note is not None else None,
        )
    return commands


def ack(
    *,
    run_id: str,
    command_id: str,
    outcome: str,
    note: str | None = None,
) -> dict[str, Any]:
    """Acknowledge a steering command. Most users never call this directly —
    :func:`poll` handles acking automatically once a handler returns."""
    body = {"outcome": outcome, "note": note}
    client = _client()
    try:
        resp = client.post(f"/steering/{run_id}/{command_id}/ack", json=body)
        resp.raise_for_status()
        result: Any = resp.json()
    finally:
        _close_if_own_client(client)
    if isinstance(result, dict):
        return dict(result)
    raise RuntimeError(f"unexpected ack response: {result!r}")
