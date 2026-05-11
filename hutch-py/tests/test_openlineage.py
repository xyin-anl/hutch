"""Tests for the optional OpenLineage emitter.

Dep-free: the emitter speaks the OL JSON spec directly over httpx, no
``openlineage-python`` package required. Tests use the in-memory mode
(``endpoint="in-memory"``) for round-trip checks plus a starlette
capture server for the network-IO path.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

from hutch.openlineage import (
    OPENLINEAGE_PRODUCER,
    OPENLINEAGE_SCHEMA_URL,
    OpenLineageEmitter,
    build_openlineage_emitter,
)
from hutch.schema import (
    IndividualEvent,
    IndividualPayload,
    OperatorEvent,
    OperatorPayload,
    RunEndEvent,
    RunEndPayload,
    RunStartEvent,
    RunStartPayload,
)

# ---------- builder + sanity --------------------------------------------------


def test_build_returns_none_for_empty_endpoint() -> None:
    assert build_openlineage_emitter(endpoint=None) is None
    assert build_openlineage_emitter(endpoint="") is None


def test_in_memory_emitter_has_no_http_client() -> None:
    emitter = OpenLineageEmitter(endpoint="in-memory")
    assert emitter._client is None


def test_endpoint_lineage_path_appended() -> None:
    """The well-known suffix ``/api/v1/lineage`` is appended automatically
    when callers pass the bare backend root."""
    emitter = OpenLineageEmitter(endpoint="http://localhost:5000")
    assert emitter._endpoint_url == "http://localhost:5000/api/v1/lineage"
    explicit = OpenLineageEmitter(endpoint="http://localhost:5000/api/v1/lineage")
    assert explicit._endpoint_url == "http://localhost:5000/api/v1/lineage"


# ---------- mapping --------------------------------------------------------


@pytest.fixture
def emitter() -> OpenLineageEmitter:
    return OpenLineageEmitter(endpoint="in-memory", namespace="hutch")


def _make_run_start(run_id: str = "r1", name: str = "search-loop") -> RunStartEvent:
    return RunStartEvent(
        run_id=run_id,
        timestamp_ns=1_700_000_000_000_000_000,
        payload=RunStartPayload(name=name, project="research"),
    )


def _make_run_end(run_id: str = "r1", status: str = "finished") -> RunEndEvent:
    return RunEndEvent(
        run_id=run_id,
        timestamp_ns=1_700_000_002_000_000_000,
        payload=RunEndPayload(status=status, summary="done"),  # type: ignore[arg-type]
    )


def _make_individual(ind_id: str, parents: list[str]) -> IndividualEvent:
    return IndividualEvent(
        run_id="r1",
        timestamp_ns=1_700_000_001_000_000_000,
        payload=IndividualPayload(
            id=ind_id,
            kind="program",
            parent_ids=parents,
            is_seed=not parents,
        ),
    )


def _make_operator(op_id: str, parent_ids: list[str], child_id: str) -> OperatorEvent:
    return OperatorEvent(
        run_id="r1",
        timestamp_ns=1_700_000_001_500_000_000,
        payload=OperatorPayload(
            id=op_id,
            kind="refine",
            parent_ids=parent_ids,
            child_id=child_id,
            cost_usd=0.012,
            tokens_in=120,
            tokens_out=45,
            llm_id="claude-sonnet-4-6",
        ),
    )


def test_run_start_emits_ol_start(emitter: OpenLineageEmitter) -> None:
    emitter.emit(_make_run_start())
    captured = emitter.captured_events
    assert len(captured) == 1
    ev = captured[0]
    assert ev["eventType"] == "START"
    assert ev["job"] == {"namespace": "hutch", "name": "search-loop"}
    assert ev["run"]["runId"] == "r1"
    assert ev["producer"] == OPENLINEAGE_PRODUCER
    assert ev["schemaURL"] == OPENLINEAGE_SCHEMA_URL
    assert ev["run"]["facets"]["hutchRun"]["project"] == "research"


def test_run_end_emits_complete_or_fail(emitter: OpenLineageEmitter) -> None:
    emitter.emit(_make_run_start())
    emitter.emit(_make_run_end(status="finished"))
    assert emitter.captured_events[-1]["eventType"] == "COMPLETE"

    emitter.emit(_make_run_start(run_id="r2"))
    emitter.emit(_make_run_end(run_id="r2", status="failed"))
    assert emitter.captured_events[-1]["eventType"] == "FAIL"


def test_operator_emits_running_with_parent_outputs(emitter: OpenLineageEmitter) -> None:
    """Parents become input Datasets, child becomes the single output."""
    emitter.emit(_make_run_start())
    emitter.emit(_make_individual("ind-A", parents=[]))
    emitter.emit(_make_individual("ind-B", parents=["ind-A"]))
    emitter.emit(_make_operator(op_id="op-1", parent_ids=["ind-A"], child_id="ind-B"))

    op_event = emitter.captured_events[-1]
    assert op_event["eventType"] == "RUNNING"
    assert op_event["inputs"] == [{"namespace": "hutch", "name": "individual:ind-A"}]
    assert op_event["outputs"] == [{"namespace": "hutch", "name": "individual:ind-B"}]

    facet = op_event["run"]["facets"]["hutchOperator"]
    assert facet["operator_kind"] == "refine"
    assert facet["cost_usd"] == 0.012
    assert facet["tokens_in"] == 120
    assert facet["tokens_out"] == 45
    assert facet["llm_id"] == "claude-sonnet-4-6"


def test_individual_event_does_not_emit_ol(emitter: OpenLineageEmitter) -> None:
    """Individual / fitness / descriptor are not lineage-relevant on their
    own — the operator event is what carries the lineage edge."""
    emitter.emit(_make_run_start())
    captured_after_start = len(emitter.captured_events)
    emitter.emit(_make_individual("ind-X", parents=["ind-Y"]))
    assert len(emitter.captured_events) == captured_after_start


def test_event_time_is_iso_z_format(emitter: OpenLineageEmitter) -> None:
    """OL spec: eventTime is ISO-8601 with 'Z' suffix and microsecond precision."""
    emitter.emit(_make_run_start())
    et = emitter.captured_events[0]["eventTime"]
    assert et.endswith("Z")
    assert "T" in et
    # Round-trip parse
    from datetime import datetime

    datetime.fromisoformat(et.replace("Z", "+00:00"))


# ---------- network round-trip via a capture server -----------------------


@pytest.fixture
def capture_server() -> Iterator[httpx.MockTransport]:
    """A mock transport that captures every POSTed payload."""
    captured: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/lineage" and request.method == "POST":
            captured.append(json.loads(request.content))
            return httpx.Response(200, json={"ok": True})
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    transport.captured = captured  # type: ignore[attr-defined]
    yield transport


def test_dispatch_posts_to_lineage_endpoint(capture_server: httpx.MockTransport) -> None:
    """Round-trip through a real httpx.Client + MockTransport so the path,
    method, and body match what an OL backend would receive."""
    emitter = OpenLineageEmitter(endpoint="http://lineage.example.com")
    # Replace the real client with one wired to the mock transport.
    emitter._client.close()
    emitter._client = httpx.Client(transport=capture_server, timeout=5.0)

    emitter.emit(_make_run_start())
    emitter.emit(_make_run_end(status="finished"))

    posted = capture_server.captured  # type: ignore[attr-defined]
    assert len(posted) == 2
    assert posted[0]["eventType"] == "START"
    assert posted[1]["eventType"] == "COMPLETE"


def test_post_failure_does_not_raise(capture_server: httpx.MockTransport) -> None:
    """A broken backend must not break the primary SDK path."""

    def handler_500(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "down"})

    transport = httpx.MockTransport(handler_500)
    emitter = OpenLineageEmitter(endpoint="http://lineage.example.com")
    emitter._client.close()
    emitter._client = httpx.Client(transport=transport, timeout=5.0)

    # No raise.
    emitter.emit(_make_run_start())
    # And the captured list still records what we tried to send.
    assert emitter.captured_events[0]["eventType"] == "START"


# ---------- integration: SDK in-memory mode --------------------------------


def test_sdk_round_trip_via_tee(tmp_path: Path) -> None:
    """End-to-end through SDK ``h.configure(openlineage_endpoint=…)``."""
    import hutch as h
    from hutch.openlineage import OpenLineageEmitter
    from hutch.sdk import SDKConfig
    from hutch.sdk._state import state
    from hutch.sdk.transport import _TeeTransport

    h.reset()
    h.configure(
        SDKConfig(
            mode="embedded",
            db_path=tmp_path / "hutch.duckdb",
            openlineage_endpoint="in-memory",
        )
    )
    transport = state().transport
    assert isinstance(transport, _TeeTransport)
    emitter = next(e for e in transport.emitters if isinstance(e, OpenLineageEmitter))

    run = h.start_run(name="ol-demo", project="research")
    seed = h.log_individual(kind="program")
    child = h.log_individual(kind="program", parent_ids=[seed.id])
    h.log_operator(kind="refine", parent_ids=[seed.id], child_id=child.id, cost_usd=0.001)
    h.end_run(status="finished")

    captured = emitter.captured_events
    types = [e["eventType"] for e in captured]
    assert types == ["START", "RUNNING", "COMPLETE"]
    op_event = captured[1]
    assert op_event["job"]["name"] == "ol-demo"
    assert op_event["inputs"][0]["name"] == f"individual:{seed.id}"
    assert op_event["outputs"][0]["name"] == f"individual:{child.id}"
    assert op_event["run"]["runId"] == run.id

    h.reset()


def test_off_by_default(tmp_path: Path) -> None:
    """Without ``openlineage_endpoint`` the SDK builds the plain transport."""
    import hutch as h
    from hutch.sdk import SDKConfig
    from hutch.sdk._state import state
    from hutch.sdk.transport import _TeeTransport

    h.reset()
    h.configure(SDKConfig(mode="embedded", db_path=tmp_path / "hutch.duckdb"))
    transport = state().transport
    assert not isinstance(transport, _TeeTransport)
    h.reset()
