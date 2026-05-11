"""OTel span emitter for canonical Hutch events.

The emitter is constructed by :func:`build_otel_exporter` when the user
opts in via ``HUTCH_OTEL_ENDPOINT`` or ``otel_endpoint=…``. The function
returns ``None`` (and logs a one-time warning) when the
``opentelemetry`` packages aren't installed; the rest of the SDK works
exactly as if OTel had never been configured.

Span model — one canonical event = one short-lived child span. Run-level
``run_start`` / ``run_end`` envelopes additionally maintain a *run
span* in :attr:`OTelEmitter._run_spans` so per-run children can hang
off it; if the user reports events out-of-order or omits the
envelopes, the emitter degrades to one span per event without a
parent. The point is breadcrumbs in the user's existing OTel backend,
not full hierarchical traces.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any
from urllib.parse import urlparse

from hutch.schema import AnyEvent

logger = logging.getLogger("hutch.otel")


# ---------- public surface --------------------------------------------------


RESEARCH_ATTRS: tuple[str, ...] = (
    # envelope
    "research.event.kind",
    "research.run.id",
    "research.stream.id",
    "research.worker.id",
    # individual
    "research.individual.id",
    "research.individual.kind",
    "research.individual.is_seed",
    "research.individual.parent_ids",
    "research.individual.island_id",
    "research.individual.generation_index",
    # operator
    "research.operator.id",
    "research.operator.kind",
    "research.operator.parent_ids",
    "research.operator.child_id",
    "research.operator.cost_usd",
    "research.operator.tokens_in",
    "research.operator.tokens_out",
    "research.operator.llm_id",
    # fitness
    "research.fitness.individual_id",
    "research.fitness.evaluator_kind",
    "research.fitness.composite",
    "research.fitness.invalid_reason",
    "research.fitness.scores",  # JSON-encoded dict
    # descriptor
    "research.descriptor.individual_id",
    "research.descriptor.archive_id",
    "research.descriptor.kind",
    "research.descriptor.cell_id",
    # self-mod
    "research.self_mod.parent_agent_id",
    "research.self_mod.child_agent_id",
    "research.self_mod.overseer_verdict",
    "research.self_mod.score_before",
    "research.self_mod.score_after",
    # claim/evidence
    "research.claim.id",
    "research.claim.requires_reproduction",
    "research.evidence.claim_id",
    "research.evidence.stance",
    "research.evidence.confidence",
    # steering
    "research.steering.command",
    "research.steering.target_id",
    "research.steering.actor",
    # run
    "research.run.name",
    "research.run.project",
    "research.run.status",
)
"""The canonical attribute keys an Hutch OTel span may carry. Not every
attribute appears on every span — only the ones relevant to that
event_kind. Listed here so docs / future schema-validation tooling can
cross-reference."""


def is_otel_available() -> bool:
    """Return ``True`` iff the optional ``opentelemetry`` packages import."""
    import importlib.util

    try:
        return all(
            importlib.util.find_spec(mod) is not None
            for mod in ("opentelemetry.trace", "opentelemetry.sdk.trace")
        )
    except ModuleNotFoundError:
        return False


def build_otel_exporter(
    *,
    endpoint: str | None,
    service_name: str = "hutch",
) -> OTelEmitter | None:
    """Build an :class:`OTelEmitter` for the given OTLP endpoint, or
    return ``None`` when OTel isn't configured / available.

    *endpoint* — OTLP/HTTP endpoint (e.g. ``http://localhost:4318``). The
    well-known suffix ``/v1/traces`` is appended automatically when the
    URL doesn't already end with ``/v1/traces``. Pass the literal
    ``"in-memory"`` to wire up an in-memory exporter for tests.

    Returns ``None`` if *endpoint* is empty / ``None``, or if OTel isn't
    importable.
    """
    if not endpoint:
        return None
    if not is_otel_available():
        logger.warning(
            "HUTCH_OTEL_ENDPOINT was set to %r but the optional [otel] "
            "extra isn't installed. Run `pip install thehutch[otel]`. "
            "Continuing without OTel emission.",
            endpoint,
        )
        return None
    return OTelEmitter(endpoint=endpoint, service_name=service_name)


# ---------- emitter ---------------------------------------------------------


class OTelEmitter:
    """Emit one OpenTelemetry span per canonical event.

    Construction is gated behind :func:`build_otel_exporter`, which is
    why we import the OTel packages lazily inside ``__init__`` — the
    rest of the SDK never pays the import cost when OTel isn't enabled.
    """

    def __init__(self, *, endpoint: str, service_name: str) -> None:
        # Lazy imports: opentelemetry isn't a hard dep of the SDK.
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import (
            BatchSpanProcessor,
            SimpleSpanProcessor,
            SpanExporter,
        )

        resource = Resource.create({"service.name": service_name})
        provider = TracerProvider(resource=resource)
        exporter: SpanExporter
        if endpoint == "in-memory":
            from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
                InMemorySpanExporter,
            )

            exporter = InMemorySpanExporter()
            provider.add_span_processor(SimpleSpanProcessor(exporter))
        else:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                OTLPSpanExporter,
            )

            url = endpoint
            if not url.endswith("/v1/traces"):
                url = url.rstrip("/") + "/v1/traces"
            # Validate at construction so a typo raises here, not on every send.
            urlparse(url)
            exporter = OTLPSpanExporter(endpoint=url)
            provider.add_span_processor(BatchSpanProcessor(exporter))

        self._tracer = trace.get_tracer("hutch", "0.1.0", tracer_provider=provider)
        self._provider = provider
        self._exporter = exporter
        self._endpoint = endpoint
        # When run_start has been seen for a run we keep a long-lived span open
        # so per-run children can be linked. run_end closes it.
        self._run_spans: dict[str, Any] = {}

    @property
    def in_memory_spans(self) -> list[Any]:
        """Return spans collected by the in-memory exporter, for tests.

        Raises if the emitter was constructed for an OTLP endpoint.
        """
        from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
            InMemorySpanExporter,
        )

        if not isinstance(self._exporter, InMemorySpanExporter):
            raise RuntimeError("emitter not configured with the in-memory exporter")
        return list(self._exporter.get_finished_spans())

    def emit(self, event: AnyEvent) -> None:
        """Emit *event* as a span. Non-fatal: any exception is logged
        and swallowed so a misconfigured OTel pipeline never breaks
        the SDK's primary path."""
        try:
            self._emit_inner(event)
        except Exception as exc:
            logger.warning("OTel emission failed for %s: %s", event.event_kind, exc)

    def _emit_inner(self, event: AnyEvent) -> None:
        from opentelemetry import trace
        from opentelemetry.trace import SpanKind

        if event.event_kind == "run_start":
            ctx = trace.set_span_in_context(trace.INVALID_SPAN)
            span = self._tracer.start_span(
                name=f"hutch.run:{event.run_id}",
                context=ctx,
                kind=SpanKind.SERVER,
                start_time=event.timestamp_ns,
                attributes=_attrs_for(event),
            )
            self._run_spans[event.run_id] = span
            return

        if event.event_kind == "run_end":
            span = self._run_spans.pop(event.run_id, None)
            if span is not None:
                _set_attrs(span, _attrs_for(event))
                span.end(end_time=event.timestamp_ns)
            return

        # Per-event child span. If we've seen a run_start for this run,
        # parent the child under that run span.
        parent_span = self._run_spans.get(event.run_id)
        kwargs: dict[str, Any] = {
            "name": f"hutch.{event.event_kind}",
            "kind": SpanKind.INTERNAL,
            "start_time": event.timestamp_ns,
            "attributes": _attrs_for(event),
            "end_on_exit": False,
        }
        if parent_span is not None:
            kwargs["context"] = trace.set_span_in_context(parent_span)
        with self._tracer.start_as_current_span(**kwargs) as span:
            # Events are points in time, not durations: end the span immediately.
            span.end(end_time=event.timestamp_ns + 1)

    def shutdown(self) -> None:
        """Close any open run spans and flush the exporter."""
        for span in list(self._run_spans.values()):
            span.end()
        self._run_spans.clear()
        try:
            self._provider.shutdown()
        except Exception as exc:
            logger.debug("OTel provider shutdown raised: %s", exc)


# ---------- attribute mapping ----------------------------------------------


def _attrs_for(event: AnyEvent) -> dict[str, Any]:
    """Build the ``research.*`` attribute dict for *event*.

    Spec: every span carries ``research.event.kind`` and
    ``research.run.id``; per-payload-kind attributes round out the
    picture. We deliberately keep the surface compact — full payload
    fidelity already lives in the canonical event log.
    """
    attrs: dict[str, Any] = {
        "research.event.kind": event.event_kind,
        "research.run.id": event.run_id,
    }
    if event.stream_id is not None:
        attrs["research.stream.id"] = event.stream_id
    if event.worker_id is not None:
        attrs["research.worker.id"] = event.worker_id

    payload = event.payload
    kind = event.event_kind

    if kind == "run_start":
        _maybe(attrs, "research.run.name", getattr(payload, "name", None))
        _maybe(attrs, "research.run.project", getattr(payload, "project", None))
    elif kind == "run_end":
        _maybe(attrs, "research.run.status", getattr(payload, "status", None))

    elif kind == "individual":
        attrs["research.individual.id"] = payload.id  # type: ignore[union-attr]
        attrs["research.individual.kind"] = payload.kind  # type: ignore[union-attr]
        attrs["research.individual.is_seed"] = bool(payload.is_seed)  # type: ignore[union-attr]
        parent_ids = list(getattr(payload, "parent_ids", []) or [])
        if parent_ids:
            attrs["research.individual.parent_ids"] = parent_ids
        _maybe(attrs, "research.individual.island_id", getattr(payload, "island_id", None))
        _maybe(attrs, "research.individual.generation_index", payload.generation_index)  # type: ignore[union-attr]

    elif kind == "operator":
        attrs["research.operator.id"] = payload.id  # type: ignore[union-attr]
        attrs["research.operator.kind"] = payload.kind  # type: ignore[union-attr]
        attrs["research.operator.child_id"] = payload.child_id  # type: ignore[union-attr]
        parent_ids = list(getattr(payload, "parent_ids", []) or [])
        if parent_ids:
            attrs["research.operator.parent_ids"] = parent_ids
        _maybe(attrs, "research.operator.cost_usd", getattr(payload, "cost_usd", None))
        _maybe(attrs, "research.operator.tokens_in", getattr(payload, "tokens_in", None))
        _maybe(attrs, "research.operator.tokens_out", getattr(payload, "tokens_out", None))
        _maybe(attrs, "research.operator.llm_id", getattr(payload, "llm_id", None))

    elif kind == "fitness":
        attrs["research.fitness.individual_id"] = payload.individual_id  # type: ignore[union-attr]
        attrs["research.fitness.evaluator_kind"] = payload.evaluator_kind  # type: ignore[union-attr]
        scores = getattr(payload, "scores", {}) or {}
        if scores:
            # OTel attributes are scalars or lists of scalars — flatten to one
            # attr per score so backends like Grafana can group on them.
            for k, v in scores.items():
                if _is_number(v):
                    attrs[f"research.fitness.score.{k}"] = float(v)
            attrs["research.fitness.scores"] = sorted(scores.keys())
        _maybe(attrs, "research.fitness.composite", getattr(payload, "composite", None))
        _maybe(attrs, "research.fitness.invalid_reason", getattr(payload, "invalid_reason", None))

    elif kind == "descriptor":
        attrs["research.descriptor.individual_id"] = payload.individual_id  # type: ignore[union-attr]
        attrs["research.descriptor.archive_id"] = payload.archive_id  # type: ignore[union-attr]
        attrs["research.descriptor.kind"] = payload.kind  # type: ignore[union-attr]
        _maybe(attrs, "research.descriptor.cell_id", getattr(payload, "cell_id", None))

    elif kind == "self_mod":
        attrs["research.self_mod.parent_agent_id"] = payload.parent_agent_id  # type: ignore[union-attr]
        attrs["research.self_mod.child_agent_id"] = payload.child_agent_id  # type: ignore[union-attr]
        _maybe(attrs, "research.self_mod.overseer_verdict", payload.overseer_verdict)  # type: ignore[union-attr]
        _maybe(attrs, "research.self_mod.score_before", payload.score_before)  # type: ignore[union-attr]
        _maybe(attrs, "research.self_mod.score_after", payload.score_after)  # type: ignore[union-attr]

    elif kind == "claim":
        attrs["research.claim.id"] = payload.id  # type: ignore[union-attr]
        attrs["research.claim.requires_reproduction"] = bool(payload.requires_reproduction)  # type: ignore[union-attr]

    elif kind == "evidence":
        attrs["research.evidence.claim_id"] = payload.claim_id  # type: ignore[union-attr]
        attrs["research.evidence.stance"] = payload.stance  # type: ignore[union-attr]
        _maybe(attrs, "research.evidence.confidence", getattr(payload, "confidence", None))

    elif kind == "steering_command":
        attrs["research.steering.command"] = payload.command  # type: ignore[union-attr]
        attrs["research.steering.actor"] = payload.actor  # type: ignore[union-attr]
        _maybe(attrs, "research.steering.target_id", getattr(payload, "target_id", None))

    return attrs


def _maybe(attrs: dict[str, Any], key: str, value: Any) -> None:
    if value is None:
        return
    attrs[key] = value


def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _set_attrs(span: Any, attrs: Iterable[tuple[str, Any]] | dict[str, Any]) -> None:
    items = attrs.items() if isinstance(attrs, dict) else attrs
    for k, v in items:
        try:
            span.set_attribute(k, v)
        except Exception as exc:  # OTel raises on weird attr types
            logger.debug("OTel set_attribute(%s=%r) raised: %s", k, v, exc)
