"""Hutch SDK — user-facing logging API.

Typical use::

    import hutch as h

    h.start_run(name="circle-packing")
    seed = h.log_individual(kind="program")
    h.log_fitness(individual=seed, scores={"accuracy": 0.5})
    h.end_run()
"""

from __future__ import annotations

from hutch.sdk._state import (
    Population,
    RunHandle,
    configure,
    reset,
)
from hutch.sdk.api import (
    end_run,
    log_archive_snapshot,
    log_artifact,
    log_claim,
    log_descriptor,
    log_evidence,
    log_fitness,
    log_individual,
    log_island_migration,
    log_operator,
    log_pareto_front,
    log_review,
    log_self_modification,
    log_stream_event,
    log_tree_expansion,
    start_population,
    start_run,
)
from hutch.sdk.config import (
    DEFAULT_DAEMON_URL,
    DEFAULT_DB_PATH,
    DEFAULT_FALLBACK_PATH,
    SDKConfig,
    TransportMode,
)

__all__ = [
    "DEFAULT_DAEMON_URL",
    "DEFAULT_DB_PATH",
    "DEFAULT_FALLBACK_PATH",
    "Population",
    "RunHandle",
    "SDKConfig",
    "TransportMode",
    "configure",
    "end_run",
    "log_archive_snapshot",
    "log_artifact",
    "log_claim",
    "log_descriptor",
    "log_evidence",
    "log_fitness",
    "log_individual",
    "log_island_migration",
    "log_operator",
    "log_pareto_front",
    "log_review",
    "log_self_modification",
    "log_stream_event",
    "log_tree_expansion",
    "reset",
    "start_population",
    "start_run",
]
