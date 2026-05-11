"""The Hutch — Observability, steering, and provenance for autonomous-research agents.

The canonical event schema is **additive-only** between minor releases
from v0.1.0 onward (see ``docs/schema.md``). The public Python API +
CLI follow `SemVer <https://semver.org/>`_.

Typical use::

    import hutch as h
    h.start_run(name="my-research")
    seed = h.log_individual(kind="hypothesis")
    h.log_fitness(individual=seed, scores={"plausibility": 0.7})
    h.end_run()
"""

from __future__ import annotations

from hutch import steering
from hutch.sdk import (
    DEFAULT_DAEMON_URL,
    DEFAULT_DB_PATH,
    DEFAULT_FALLBACK_PATH,
    Population,
    RunHandle,
    SDKConfig,
    TransportMode,
    configure,
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
    log_run_update,
    log_self_modification,
    log_stream_event,
    log_tree_expansion,
    reset,
    start_population,
    start_run,
)

__all__ = [
    "DEFAULT_DAEMON_URL",
    "DEFAULT_DB_PATH",
    "DEFAULT_FALLBACK_PATH",
    "Population",
    "RunHandle",
    "SDKConfig",
    "TransportMode",
    "__version__",
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
    "log_run_update",
    "log_self_modification",
    "log_stream_event",
    "log_tree_expansion",
    "reset",
    "start_population",
    "start_run",
    "steering",
]

__version__ = "0.1.0"
