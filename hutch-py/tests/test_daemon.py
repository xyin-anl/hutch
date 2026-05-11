"""Smoke tests for the M0 daemon stub.

These tests pin the M0 done-condition: ``hutch serve`` returns a page on the root
URL, and the health and version endpoints answer correctly.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from fastapi.testclient import TestClient
from fastapi.websockets import WebSocketDisconnect

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
