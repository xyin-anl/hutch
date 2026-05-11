"""Module-level SDK state — the active run, population, and transport.

The SDK is process-global by design: ``h.log_individual(...)`` from anywhere
in the user's code lands on the same run. Tests should call
:func:`reset` to wipe state between cases.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field

from hutch.schema.types import PopulationKind
from hutch.sdk.config import SDKConfig
from hutch.sdk.transport import Transport, build_transport

_lock = threading.Lock()


@dataclass(slots=True)
class RunHandle:
    """User-facing handle returned by :func:`hutch.start_run`."""

    id: str
    name: str | None = None
    project: str | None = None


@dataclass(slots=True)
class Population:
    """User-facing handle returned by :func:`hutch.start_population`."""

    id: str
    name: str
    kind: PopulationKind
    descriptor_dims: list[str] = field(default_factory=list)
    objectives: list[tuple[str, str]] = field(default_factory=list)


@dataclass(slots=True)
class _SDKState:
    config: SDKConfig
    transport: Transport
    run: RunHandle | None = None
    populations: dict[str, Population] = field(default_factory=dict)


_state: _SDKState | None = None


def configure(config: SDKConfig) -> _SDKState:
    """(Re-)initialize the SDK state with *config*. Closes any prior transport."""
    global _state
    with _lock:
        if _state is not None:
            _state.transport.close()
        _state = _SDKState(config=config, transport=build_transport(config))
        return _state


def state() -> _SDKState:
    """Return the active SDK state, initializing from env on first access."""
    global _state
    with _lock:
        if _state is None:
            _state = _SDKState(
                config=(cfg := SDKConfig.from_env()),
                transport=build_transport(cfg),
            )
        return _state


def reset() -> None:
    """Tear down the SDK state. Used by tests."""
    global _state
    with _lock:
        if _state is not None:
            _state.transport.close()
        _state = None


def set_run(handle: RunHandle) -> None:
    state().run = handle


def clear_run() -> None:
    state().run = None


def active_run() -> RunHandle:
    s = state()
    if s.run is None:
        raise RuntimeError(
            "No active Hutch run. Call `hutch.start_run(...)` before logging events."
        )
    return s.run


def register_population(pop: Population) -> None:
    state().populations[pop.id] = pop


def get_population(pop_id: str) -> Population | None:
    return state().populations.get(pop_id)
