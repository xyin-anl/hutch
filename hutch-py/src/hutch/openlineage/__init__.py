"""Optional OpenLineage emitter.

When the user sets ``HUTCH_OPENLINEAGE_ENDPOINT`` (or passes
``openlineage_endpoint=…`` to :func:`hutch.configure`), every Hutch run
additionally streams to an OpenLineage backend (Marquez, DataHub,
custom) as OL ``RunEvent`` JSON. The regular daemon / embedded
transport runs unchanged.

Dep-free by design: we POST OpenLineage 2.0-spec JSON directly via
``httpx`` (already a hard SDK dep) rather than pull in
``openlineage-python``. This keeps the install footprint flat and
avoids a transitive lockstep upgrade with the OL SDK.

Mapping summary — one Hutch run is one OL job:

* Job: ``namespace="hutch"``, ``name=<run.name or run.id>``
* Run: ``runId=<run.id>``
* ``run_start``  → eventType ``START``
* ``run_end``    → eventType ``COMPLETE`` or ``FAIL`` (per ``run_end.status``)
* ``operator``   → eventType ``RUNNING`` with inputs = parent Datasets,
                   output = child Dataset, plus an
                   ``hutchOperator`` custom facet
* ``self_mod``   → eventType ``RUNNING`` with input = parent agent,
                   output = child agent, plus an ``hutchSelfMod`` facet

Other event kinds are not emitted standalone — their data lives in the
canonical event log (DuckDB) and shows up in the dashboard. We emit
the *lineage-relevant* subset.
"""

from __future__ import annotations

from hutch.openlineage.emitter import (
    OPENLINEAGE_PRODUCER,
    OPENLINEAGE_SCHEMA_URL,
    OpenLineageEmitter,
    build_openlineage_emitter,
)

__all__ = [
    "OPENLINEAGE_PRODUCER",
    "OPENLINEAGE_SCHEMA_URL",
    "OpenLineageEmitter",
    "build_openlineage_emitter",
]
