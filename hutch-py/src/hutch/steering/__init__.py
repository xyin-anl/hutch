"""Steering / write-back command channel.

Two surfaces:

* :mod:`hutch.steering.store` — the daemon-side queue.
* The user-facing API exposed at the package root: :func:`poll`,
  :func:`handler`, :func:`send`, :func:`ack`. Agents in their main loop
  do::

      from hutch import steering as s

      @s.handler("pause_run")
      def on_pause(cmd): ...

      while running:
          s.poll()         # dispatches to handlers above
          do_one_iteration()
"""

from __future__ import annotations

from hutch.steering.api import (
    SteeringCommand,
    ack,
    handler,
    poll,
    send,
)
from hutch.steering.store import SteeringRecord, SteeringStore

__all__ = [
    "SteeringCommand",
    "SteeringRecord",
    "SteeringStore",
    "ack",
    "handler",
    "poll",
    "send",
]
