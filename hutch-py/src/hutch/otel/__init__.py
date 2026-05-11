"""Optional OpenTelemetry bridge.

Two halves, both opt-in:

* :class:`OTelEmitter` (this module) — when the user sets
  ``HUTCH_OTEL_ENDPOINT`` (or passes ``otel_endpoint=…`` to
  :func:`hutch.configure`), every canonical event additionally lands as
  an OpenTelemetry span with ``research.*`` attributes. The regular
  daemon / embedded transport runs unchanged.

* ``research.*`` semantic-convention namespace — see
  :data:`RESEARCH_ATTRS` for the attribute list. We track the OTel
  GenAI semconv WG; once stable upstream we'll align names. Until
  then the schema is additive-only between Hutch minor versions, same
  rule as the canonical event schema itself.

opentelemetry-api / -sdk / -exporter-otlp-proto-http are an **optional**
dependency. Install with ``pip install thehutch[otel]``. Without the
extra, :func:`build_otel_exporter` returns ``None`` and the SDK runs as
if OTel were never configured.

A future iteration will add the *inverse* path — listening to the user's
existing ``gen_ai.*`` spans (LangChain / LlamaIndex / OpenAI Agents SDK)
and translating them into canonical events. Tracked in §11.
"""

from __future__ import annotations

from hutch.otel.emitter import (
    RESEARCH_ATTRS,
    OTelEmitter,
    build_otel_exporter,
    is_otel_available,
)

__all__ = [
    "RESEARCH_ATTRS",
    "OTelEmitter",
    "build_otel_exporter",
    "is_otel_available",
]
