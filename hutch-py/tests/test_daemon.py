"""Smoke tests for the M0 daemon stub.

These tests pin the M0 done-condition: ``hutch serve`` returns a page on the root
URL, and the health and version endpoints answer correctly.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from fastapi.testclient import TestClient
from fastapi.websockets import WebSocketDisconnect

import hutch.daemon.app as daemon_app
from hutch import __version__
from hutch.daemon.app import create_app


def test_index_returns_html_index() -> None:
    """Root serves an HTML page — either the M0 placeholder or the built UI."""
    client = TestClient(create_app())
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Hutch" in response.text


def test_healthz_ok() -> None:
    client = TestClient(create_app())
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_version_endpoint_matches_package() -> None:
    client = TestClient(create_app())
    response = client.get("/version")
    assert response.status_code == 200
    assert response.json() == {"version": __version__}


def test_openapi_schema_served() -> None:
    client = TestClient(create_app())
    response = client.get("/openapi.json")
    assert response.status_code == 200
    schema = response.json()
    assert schema["info"]["title"] == "The Hutch"
    assert schema["info"]["version"] == __version__


def test_token_auth_protects_api_routes() -> None:
    with TestClient(create_app(auth_token="secret")) as client:
        assert client.get("/healthz").status_code == 200
        assert client.get("/openapi.json").status_code == 401
        assert client.get("/docs").status_code == 401
        assert client.get("/runs").status_code == 401
        assert client.get("/runs", headers={"authorization": "Bearer wrong"}).status_code == 401
        assert (
            client.get("/openapi.json", headers={"authorization": "Bearer secret"}).status_code
            == 200
        )
        assert client.get("/runs", headers={"authorization": "Bearer secret"}).status_code == 200


def test_token_auth_protects_event_ingest() -> None:
    with TestClient(create_app(auth_token="secret")) as client:
        body = {"run_id": "r-auth", "event_kind": "run_start", "payload": {}}
        assert client.post("/events", json=body).status_code == 401
        response = client.post("/events", json=body, headers={"authorization": "Bearer secret"})
        assert response.status_code == 200
        assert response.json()["accepted"] == 1


def test_concurrent_event_posts_are_serialized() -> None:
    with TestClient(create_app()) as client:

        def post_one(i: int) -> dict[str, int]:
            response = client.post(
                "/events",
                json={
                    "event_id": str(uuid4()),
                    "run_id": "r-concurrent",
                    "event_kind": "run_start",
                    "timestamp_ns": i,
                    "payload": {"name": f"run-{i}"},
                },
            )
            assert response.status_code == 200
            return response.json()

        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(post_one, range(24)))

        assert sum(result["accepted"] for result in results) == 24
        assert sum(result["rejected"] for result in results) == 0
        assert sum(result["duplicates"] for result in results) == 0

        events = client.get("/runs/r-concurrent/events?limit=50")
        assert events.status_code == 200
        assert len(events.json()) == 24


def test_token_auth_protects_websocket_stream() -> None:
    with TestClient(create_app(auth_token="secret")) as client:
        try:
            with client.websocket_connect("/runs/r-auth/stream"):
                raise AssertionError("websocket connected without token")
        except WebSocketDisconnect as exc:
            assert exc.code == 1008

        with client.websocket_connect("/runs/r-auth/stream?token=secret"):
            pass


def _post_event(client: TestClient, record: dict[str, object]) -> None:
    response = client.post("/events", json=record)
    assert response.status_code == 200, response.text
    assert response.json()["accepted"] == 1


def test_run_capabilities_merge_and_infer_from_events() -> None:
    with TestClient(create_app()) as client:
        _post_event(
            client,
            {
                "run_id": "r-caps",
                "event_kind": "run_start",
                "timestamp_ns": 1,
                "payload": {"capabilities": {"steering": False, "audit": False}},
            },
        )
        _post_event(
            client,
            {
                "run_id": "r-caps",
                "event_kind": "run_update",
                "timestamp_ns": 2,
                "payload": {"capabilities": {"audit": True, "live_updates": True}},
            },
        )
        _post_event(
            client,
            {
                "run_id": "r-caps",
                "event_kind": "operator",
                "timestamp_ns": 3,
                "payload": {
                    "id": "op-1",
                    "kind": "propose",
                    "parent_ids": [],
                    "child_id": "ind-1",
                    "cost_usd": 0.0,
                },
            },
        )
        _post_event(
            client,
            {
                "run_id": "r-caps",
                "event_kind": "stream_event",
                "timestamp_ns": 4,
                "payload": {"label": "cvevolve_message", "text": "audit"},
            },
        )

        detail = client.get("/runs/r-caps")
        assert detail.status_code == 200
        assert detail.json()["capabilities"] == {
            "steering": False,
            "audit": True,
            "live_updates": True,
            "llm_usage": True,
        }

        run_list = client.get("/runs")
        assert run_list.status_code == 200
        listed = next(item for item in run_list.json() if item["run_id"] == "r-caps")
        assert listed["capabilities"]["llm_usage"] is True
        assert listed["capabilities"]["steering"] is False


def test_run_capabilities_do_not_infer_llm_usage_from_json_nulls() -> None:
    with TestClient(create_app()) as client:
        _post_event(
            client,
            {
                "run_id": "r-null-usage",
                "event_kind": "run_start",
                "timestamp_ns": 1,
                "payload": {},
            },
        )
        _post_event(
            client,
            {
                "run_id": "r-null-usage",
                "event_kind": "operator",
                "timestamp_ns": 2,
                "payload": {
                    "id": "op-1",
                    "kind": "propose",
                    "parent_ids": [],
                    "child_id": "ind-1",
                    "cost_usd": None,
                    "tokens_in": None,
                    "tokens_out": None,
                },
            },
        )

        detail = client.get("/runs/r-null-usage")
        assert detail.status_code == 200
        assert "llm_usage" not in detail.json()["capabilities"]


def test_run_system_kind_is_inferred_from_adapter_and_operator_shape() -> None:
    with TestClient(create_app()) as client:
        _post_event(
            client,
            {
                "run_id": "r-cvevolve-kind",
                "event_kind": "run_start",
                "timestamp_ns": 1,
                "payload": {"metadata": {"adapter": "cvevolve"}},
            },
        )
        _post_event(
            client,
            {
                "run_id": "r-cvevolve-kind",
                "event_kind": "operator",
                "timestamp_ns": 2,
                "payload": {
                    "id": "op-1",
                    "kind": "propose",
                    "parent_ids": [],
                    "child_id": "ind-1",
                },
            },
        )
        _post_event(
            client,
            {
                "run_id": "r-mutate-kind",
                "event_kind": "operator",
                "timestamp_ns": 1,
                "payload": {
                    "id": "op-2",
                    "kind": "mutate",
                    "parent_ids": ["seed"],
                    "child_id": "ind-2",
                },
            },
        )
        _post_event(
            client,
            {
                "run_id": "r-unknown-kind",
                "event_kind": "run_start",
                "timestamp_ns": 1,
                "payload": {},
            },
        )

        assert client.get("/runs/r-cvevolve-kind").json()["system_kind"] == "evolutionary"
        assert client.get("/runs/r-mutate-kind").json()["system_kind"] == "evolutionary"
        assert client.get("/runs/r-unknown-kind").json()["system_kind"] == "unknown"

        listed = {item["run_id"]: item for item in client.get("/runs").json()}
        assert listed["r-cvevolve-kind"]["system_kind"] == "evolutionary"
        assert listed["r-mutate-kind"]["system_kind"] == "evolutionary"
        assert listed["r-unknown-kind"]["system_kind"] == "unknown"


def test_steering_post_requires_capability_and_running_run() -> None:
    with TestClient(create_app()) as client:
        _post_event(
            client,
            {
                "run_id": "r-no-steering",
                "event_kind": "run_start",
                "timestamp_ns": 1,
                "payload": {},
            },
        )
        response = client.post("/steering/r-no-steering", json={"command": "pause_run"})
        assert response.status_code == 409

        _post_event(
            client,
            {
                "run_id": "r-steering",
                "event_kind": "run_start",
                "timestamp_ns": 1,
                "payload": {"capabilities": {"steering": True}},
            },
        )
        response = client.post("/steering/r-steering", json={"command": "pause_run"})
        assert response.status_code == 200, response.text
        assert response.json()["command"] == "pause_run"

        _post_event(
            client,
            {
                "run_id": "r-done",
                "event_kind": "run_start",
                "timestamp_ns": 1,
                "payload": {"capabilities": {"steering": True}},
            },
        )
        _post_event(
            client,
            {
                "run_id": "r-done",
                "event_kind": "run_end",
                "timestamp_ns": 2,
                "payload": {"status": "finished"},
            },
        )
        response = client.post("/steering/r-done", json={"command": "pause_run"})
        assert response.status_code == 409


def test_persisted_steering_history_is_read_back_after_restart_event_log() -> None:
    with TestClient(create_app()) as client:
        _post_event(
            client,
            {
                "run_id": "r-history",
                "event_kind": "run_start",
                "timestamp_ns": 1,
                "payload": {},
            },
        )
        _post_event(
            client,
            {
                "run_id": "r-history",
                "event_kind": "steering_command",
                "timestamp_ns": 2,
                "payload": {
                    "command": "pause_run",
                    "actor": "human",
                    "metadata": {"command_id": "cmd-existing", "status": "acked"},
                },
            },
        )

        detail = client.get("/runs/r-history")
        assert detail.status_code == 200
        assert "steering" not in detail.json()["capabilities"]

        history = client.get("/steering/r-history")
        assert history.status_code == 200
        assert history.json()[0]["command_id"] == "cmd-existing"
        assert history.json()[0]["status"] == "acked"

        response = client.post("/steering/r-history", json={"command": "pause_run"})
        assert response.status_code == 409


def test_stream_events_endpoint_pages_and_filters_server_side() -> None:
    with TestClient(create_app()) as client:
        _post_event(
            client,
            {
                "run_id": "r-streams",
                "event_kind": "run_start",
                "timestamp_ns": 1,
                "payload": {},
            },
        )
        for index, (label, text) in enumerate(
            [
                ("cvevolve_message", "alpha prompt"),
                ("candidate_failure", "syntax error"),
                ("cvevolve_tool_call", "alpha tool"),
            ],
            start=2,
        ):
            _post_event(
                client,
                {
                    "run_id": "r-streams",
                    "event_kind": "stream_event",
                    "timestamp_ns": index,
                    "payload": {"label": label, "text": text},
                },
            )

        page = client.get("/runs/r-streams/stream_events?query=alpha&limit=1")
        assert page.status_code == 200
        assert page.json()["total"] == 2
        assert len(page.json()["events"]) == 1

        tools = client.get("/runs/r-streams/stream_events?label=cvevolve_tool_call")
        assert tools.status_code == 200
        assert tools.json()["total"] == 1
        assert tools.json()["events"][0]["payload"]["label"] == "cvevolve_tool_call"


def test_run_list_uses_batched_summary_helpers(monkeypatch) -> None:
    with TestClient(create_app()) as client:
        _post_event(
            client,
            {
                "run_id": "r-batched",
                "event_kind": "run_start",
                "timestamp_ns": 1,
                "payload": {"metadata": {"adapter": "cvevolve"}},
            },
        )

        def fail(*args: object, **kwargs: object) -> None:
            raise AssertionError("per-run helper should not be called by /runs")

        monkeypatch.setattr(daemon_app, "_run_capabilities", fail)
        monkeypatch.setattr(daemon_app, "_run_system_kind", fail)
        response = client.get("/runs")
        assert response.status_code == 200
        listed = next(item for item in response.json() if item["run_id"] == "r-batched")
        assert listed["system_kind"] == "evolutionary"
