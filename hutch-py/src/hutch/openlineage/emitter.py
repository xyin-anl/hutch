"""POST OpenLineage RunEvents to a configured backend.

The emitter is opt-in: :func:`build_openlineage_emitter` returns
``None`` when no endpoint is configured. When active, it posts one OL
``RunEvent`` per lineage-relevant Hutch event to
``<endpoint>/api/v1/lineage`` and swallows failures so the SDK's
primary path never breaks.

OpenLineage spec: <https://openlineage.io/spec/2-0-2/OpenLineage.json>.
We hand-build the JSON; no ``openlineage-python`` dep required.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

import httpx

from hutch import __version__
from hutch.schema import AnyEvent

logger = logging.getLogger("hutch.openlineage")


OPENLINEAGE_PRODUCER = f"https://github.com/xyin/hutch/v{__version__}"
"""``producer`` URI for every emitted RunEvent. Per OL spec, identifies
the integration that emitted the event."""

OPENLINEAGE_SCHEMA_URL = "https://openlineage.io/spec/2-0-2/OpenLineage.json#/$defs/RunEvent"
"""``schemaURL`` we advertise in every event."""

_DEFAULT_NAMESPACE = "hutch"
_LINEAGE_PATH = "/api/v1/lineage"

# ---------- public surface --------------------------------------------------


def build_openlineage_emitter(
    *,
    endpoint: str | None,
    namespace: str = _DEFAULT_NAMESPACE,
    job_name_default: str = "research-loop",
    timeout_s: float = 5.0,
) -> OpenLineageEmitter | None:
    """Return an :class:`OpenLineageEmitter` for *endpoint*, or ``None``
    when *endpoint* is empty / ``None``.

    *endpoint* may be the bare backend root (``http://localhost:5000``)
    or the full lineage path; the well-known suffix
    ``/api/v1/lineage`` is appended automatically when it isn't
    already there. Pass the literal ``"in-memory"`` to wire up the
    in-memory transport for tests.
    """
    if not endpoint:
        return None
    return OpenLineageEmitter(
        endpoint=endpoint,
        namespace=namespace,
        job_name_default=job_name_default,
        timeout_s=timeout_s,
    )


# ---------- emitter ---------------------------------------------------------


class OpenLineageEmitter:
    """Stream Hutch lineage to an OpenLineage backend.

    The emitter remembers the resolved job name per run (taken from
    ``run_start.payload.name`` if present, else the run id) so
    subsequent operator events can reference the same OL Job.
    """

    def __init__(
        self,
        *,
        endpoint: str,
        namespace: str = _DEFAULT_NAMESPACE,
        job_name_default: str = "research-loop",
        timeout_s: float = 5.0,
    ) -> None:
        if endpoint == "in-memory":
            self._client: httpx.Client | None = None
        else:
            url = endpoint
            if not url.endswith(_LINEAGE_PATH):
                url = url.rstrip("/") + _LINEAGE_PATH
            urlparse(url)  # validates at construction
            self._client = httpx.Client(timeout=timeout_s)
            self._endpoint_url = url
        self._endpoint = endpoint
        self._namespace = namespace
        self._job_name_default = job_name_default
        self._job_name_for_run: dict[str, str] = {}
        # Tests inspect this to assert what we'd POST.
        self._captured: list[dict[str, Any]] = []

    @property
    def captured_events(self) -> list[dict[str, Any]]:
        """For ``endpoint="in-memory"`` (tests): every RunEvent the
        emitter would have POSTed, in order."""
        return list(self._captured)

    def emit(self, event: AnyEvent) -> None:
        """Map *event* to one or zero OL RunEvents and dispatch them."""
        try:
            payload = self._payload_for(event)
        except Exception as exc:
            logger.warning("OL payload build failed for %s: %s", event.event_kind, exc)
            return
        if payload is None:
            return
        self._dispatch(payload)

    def shutdown(self) -> None:
        if self._client is not None:
            try:
                self._client.close()
            except Exception as exc:
                logger.debug("OL client close raised: %s", exc)
            self._client = None
        self._job_name_for_run.clear()

    # ---------- mapping ----------------------------------------------------

    def _payload_for(self, event: AnyEvent) -> dict[str, Any] | None:
        kind = event.event_kind

        if kind == "run_start":
            job_name = self._job_name_for(event, set_if_unset=True)
            return self._build_event(
                event_type="START",
                event=event,
                job_name=job_name,
                inputs=[],
                outputs=[],
                run_facets={
                    "hutchRun": {
                        "_producer": OPENLINEAGE_PRODUCER,
                        "_schemaURL": _facet_schema_url("hutchRun"),
                        "name": getattr(event.payload, "name", None),
                        "project": getattr(event.payload, "project", None),
                        "started_by": getattr(event.payload, "started_by", None),
                    }
                },
            )

        if kind == "run_end":
            job_name = self._job_name_for(event)
            status = getattr(event.payload, "status", "finished")
            event_type = "COMPLETE" if status in {"finished", "running"} else "FAIL"
            payload = self._build_event(
                event_type=event_type,
                event=event,
                job_name=job_name,
                inputs=[],
                outputs=[],
                run_facets={
                    "hutchRunOutcome": {
                        "_producer": OPENLINEAGE_PRODUCER,
                        "_schemaURL": _facet_schema_url("hutchRunOutcome"),
                        "status": status,
                        "summary": getattr(event.payload, "summary", None),
                    }
                },
            )
            self._job_name_for_run.pop(event.run_id, None)
            return payload

        if kind == "operator":
            job_name = self._job_name_for(event)
            parents = list(getattr(event.payload, "parent_ids", []) or [])
            child_id = getattr(event.payload, "child_id", None)
            if child_id is None:
                return None
            return self._build_event(
                event_type="RUNNING",
                event=event,
                job_name=job_name,
                inputs=[self._dataset_for_individual(pid) for pid in parents],
                outputs=[self._dataset_for_individual(child_id)],
                run_facets={
                    "hutchOperator": {
                        "_producer": OPENLINEAGE_PRODUCER,
                        "_schemaURL": _facet_schema_url("hutchOperator"),
                        "operator_id": event.payload.id,  # type: ignore[union-attr]
                        "operator_kind": event.payload.kind,  # type: ignore[union-attr]
                        "cost_usd": getattr(event.payload, "cost_usd", None),
                        "tokens_in": getattr(event.payload, "tokens_in", None),
                        "tokens_out": getattr(event.payload, "tokens_out", None),
                        "llm_id": getattr(event.payload, "llm_id", None),
                    }
                },
            )

        if kind == "self_mod":
            job_name = self._job_name_for(event)
            parent_agent = getattr(event.payload, "parent_agent_id", None)
            child_agent = getattr(event.payload, "child_agent_id", None)
            if parent_agent is None or child_agent is None:
                return None
            return self._build_event(
                event_type="RUNNING",
                event=event,
                job_name=job_name,
                inputs=[self._dataset_for_agent(parent_agent)],
                outputs=[self._dataset_for_agent(child_agent)],
                run_facets={
                    "hutchSelfMod": {
                        "_producer": OPENLINEAGE_PRODUCER,
                        "_schemaURL": _facet_schema_url("hutchSelfMod"),
                        "overseer_verdict": getattr(event.payload, "overseer_verdict", None),
                        "score_before": getattr(event.payload, "score_before", None),
                        "score_after": getattr(event.payload, "score_after", None),
                        "target_path": getattr(event.payload, "target_path", None),
                    }
                },
            )

        # Other event kinds are deliberately not emitted as OL events.
        return None

    # ---------- helpers ----------------------------------------------------

    def _job_name_for(self, event: AnyEvent, *, set_if_unset: bool = False) -> str:
        cached = self._job_name_for_run.get(event.run_id)
        if cached:
            return cached
        name = getattr(event.payload, "name", None) if event.event_kind == "run_start" else None
        resolved = str(name) if name else event.run_id or self._job_name_default
        if set_if_unset:
            self._job_name_for_run[event.run_id] = resolved
        return resolved

    def _dataset_for_individual(self, ind_id: str) -> dict[str, Any]:
        return {
            "namespace": self._namespace,
            "name": f"individual:{ind_id}",
        }

    def _dataset_for_agent(self, agent_id: str) -> dict[str, Any]:
        return {
            "namespace": self._namespace,
            "name": f"agent:{agent_id}",
        }

    def _build_event(
        self,
        *,
        event_type: str,
        event: AnyEvent,
        job_name: str,
        inputs: list[dict[str, Any]],
        outputs: list[dict[str, Any]],
        run_facets: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "eventType": event_type,
            "eventTime": _iso_z(event.timestamp_ns),
            "run": {
                "runId": event.run_id,
                "facets": run_facets,
            },
            "job": {
                "namespace": self._namespace,
                "name": job_name,
            },
            "inputs": inputs,
            "outputs": outputs,
            "producer": OPENLINEAGE_PRODUCER,
            "schemaURL": OPENLINEAGE_SCHEMA_URL,
        }

    def _dispatch(self, payload: dict[str, Any]) -> None:
        # Always capture for in-memory mode + tests; only POST when a
        # real client is configured.
        self._captured.append(payload)
        if self._client is None:
            return
        try:
            resp = self._client.post(self._endpoint_url, json=payload)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("OL POST failed: %s", exc)


# ---------- helpers ---------------------------------------------------------


def _iso_z(ns: int) -> str:
    """Format nanoseconds-since-epoch as an ISO-8601 ``Z`` string per OL spec."""
    seconds, frac_ns = divmod(int(ns), 1_000_000_000)
    dt = datetime.fromtimestamp(seconds, tz=UTC)
    micros = frac_ns // 1000
    return dt.replace(microsecond=micros).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _facet_schema_url(facet_name: str) -> str:
    return f"{OPENLINEAGE_PRODUCER}#/$defs/{facet_name}"
