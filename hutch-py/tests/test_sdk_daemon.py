"""SDK + daemon round-trip tests using FastAPI's TestClient.

The TestClient drives the FastAPI app in-process (no real socket), which is
fast and deterministic. The integration test in :mod:`tests.test_integration`
exercises the same path against a real ``hutch serve`` subprocess.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

import hutch as h
from hutch.daemon.app import create_app
from hutch.schema import IndividualEvent, IndividualPayload
from hutch.sdk import SDKConfig
from hutch.sdk._state import active_run
from hutch.sdk.transport import DaemonTransport


@pytest.fixture
def daemon_app(tmp_path: Path) -> Iterator[TestClient]:
    """A FastAPI TestClient backed by a tmp-path DuckDB.

    Yielded inside ``with TestClient(...) as client`` so the lifespan opens
    (and later closes) the DuckDB connection on ``app.state.db_conn``.
    """
    app = create_app(db_path=tmp_path / "daemon.duckdb")
    with TestClient(app) as client:
        yield client


@pytest.fixture
def sdk_against_test_app(
    daemon_app: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> SDKConfig:
    """Configure the SDK in daemon mode against the in-process TestClient.

    We monkeypatch httpx.Client inside DaemonTransport so the SDK's POSTs
    land on the TestClient's app rather than going over the network.
    """
    cfg = SDKConfig(
        mode="daemon",
        daemon_url="http://test-daemon",
        fallback_path=tmp_path / "fb.jsonl",
        strict=True,
    )

    def _patched_init(self: DaemonTransport, config: SDKConfig) -> None:  # type: ignore[no-redef]
        self._config = config
        # Use the TestClient's underlying httpx client. TestClient *is* an httpx.Client.
        self._client = daemon_app
        if config.auto_fallback:
            self._drain_fallback()

    monkeypatch.setattr(DaemonTransport, "__init__", _patched_init)
    h.configure(cfg)
    return cfg


def test_post_single_event(daemon_app: TestClient) -> None:
    payload = {
        "run_id": "r1",
        "event_kind": "individual",
        "payload": {"id": "i1", "kind": "program", "is_seed": True},
    }
    response = daemon_app.post("/events", json=payload)
    assert response.status_code == 200
    assert response.json() == {"accepted": 1, "rejected": 0, "duplicates": 0}


def test_post_ndjson_batch(daemon_app: TestClient) -> None:
    e1 = {
        "run_id": "r1",
        "event_kind": "individual",
        "payload": {"id": "i1", "kind": "program", "is_seed": True},
    }
    e2 = {
        "run_id": "r1",
        "event_kind": "fitness",
        "payload": {
            "individual_id": "i1",
            "evaluator_kind": "deterministic_metric",
            "scores": {"acc": 0.5},
        },
    }
    body = "\n".join([str(e1).replace("'", '"').replace("True", "true"), str(e2).replace("'", '"')])
    response = daemon_app.post(
        "/events", content=body, headers={"content-type": "application/x-ndjson"}
    )
    assert response.status_code == 200
    assert response.json()["accepted"] == 2


def test_post_rejects_empty_body(daemon_app: TestClient) -> None:
    response = daemon_app.post("/events", content=b"")
    assert response.status_code == 400


def test_post_partially_invalid_batch_counts_rejections(daemon_app: TestClient) -> None:
    body = (
        '{"run_id":"r1","event_kind":"individual","payload":'
        '{"id":"i1","kind":"program","is_seed":true}}\n'
        '{"this":"is_garbage"}\n'
    )
    response = daemon_app.post(
        "/events", content=body, headers={"content-type": "application/x-ndjson"}
    )
    assert response.status_code == 200
    body_json = response.json()
    assert body_json["accepted"] == 1
    assert body_json["rejected"] == 1


def test_get_runs_lists_seen_runs(daemon_app: TestClient) -> None:
    daemon_app.post(
        "/events",
        json={
            "run_id": "alpha",
            "event_kind": "run_start",
            "payload": {"name": "alpha-run"},
        },
    )
    daemon_app.post(
        "/events",
        json={
            "run_id": "beta",
            "event_kind": "individual",
            "payload": {"id": "i1", "kind": "program", "is_seed": True},
        },
    )
    runs = daemon_app.get("/runs").json()
    run_ids = {r["run_id"] for r in runs}
    assert run_ids == {"alpha", "beta"}


def test_get_run_404_for_unknown(daemon_app: TestClient) -> None:
    assert daemon_app.get("/runs/does-not-exist").status_code == 404


def test_get_run_individuals_filtered(daemon_app: TestClient) -> None:
    daemon_app.post(
        "/events",
        json={
            "run_id": "r1",
            "event_kind": "individual",
            "payload": {"id": "i1", "kind": "program", "is_seed": True},
        },
    )
    daemon_app.post(
        "/events",
        json={
            "run_id": "r1",
            "event_kind": "fitness",
            "payload": {
                "individual_id": "i1",
                "evaluator_kind": "deterministic_metric",
                "scores": {"x": 1.0},
            },
        },
    )
    inds = daemon_app.get("/runs/r1/individuals").json()
    assert len(inds) == 1
    assert inds[0]["payload"]["id"] == "i1"


def test_sdk_daemon_round_trip(daemon_app: TestClient, sdk_against_test_app: SDKConfig) -> None:
    """The SDK's high-level API ends up readable via the daemon's GET endpoints."""
    del sdk_against_test_app
    run = h.start_run(name="sdk-round-trip")
    seed = h.log_individual(kind="program")
    h.log_fitness(individual=seed, scores={"acc": 0.42})
    h.end_run()

    response = daemon_app.get(f"/runs/{run.id}")
    assert response.status_code == 200
    body = response.json()
    assert body["event_count"] == 4
    assert "individual" in body["kinds_seen"]
    assert "fitness" in body["kinds_seen"]


def test_sdk_daemon_sends_auth_token(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    app = create_app(db_path=tmp_path / "daemon.duckdb", auth_token="secret")
    with TestClient(app) as client:
        cfg = SDKConfig(
            mode="daemon",
            daemon_url="http://test-daemon",
            fallback_path=tmp_path / "fb.jsonl",
            strict=True,
            auth_token="secret",
        )

        def _patched_init(self: DaemonTransport, config: SDKConfig) -> None:
            self._config = config
            self._client = client
            if config.auto_fallback:
                self._drain_fallback()

        monkeypatch.setattr(DaemonTransport, "__init__", _patched_init)
        transport = DaemonTransport(cfg)
        transport.send(
            IndividualEvent(
                run_id="secure",
                payload=IndividualPayload(id="i1", kind="program", is_seed=True),
            )
        )

        response = client.get("/runs/secure", headers={"authorization": "Bearer secret"})
        assert response.status_code == 200
        assert response.json()["event_count"] == 1


def test_sdk_strict_mode_raises_on_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """In strict mode, daemon failures propagate as exceptions."""
    del monkeypatch
    cfg = SDKConfig(
        mode="daemon",
        daemon_url="http://127.0.0.1:1",  # nothing listens here
        fallback_path=tmp_path / "fb.jsonl",
        strict=True,
        request_timeout_s=0.5,
    )
    h.configure(cfg)
    # ``start_run`` itself emits a run_start event, which raises in strict mode.
    with pytest.raises(httpx.HTTPError):
        h.start_run(name="r")
    with pytest.raises(RuntimeError, match="No active Hutch run"):
        active_run()


def test_sdk_loose_mode_falls_back_to_jsonl(tmp_path: Path) -> None:
    """In loose mode, daemon failures land in the fallback file."""
    cfg = SDKConfig(
        mode="daemon",
        daemon_url="http://127.0.0.1:1",
        fallback_path=tmp_path / "fb.jsonl",
        strict=False,
        request_timeout_s=0.5,
    )
    h.configure(cfg)
    h.start_run(name="r")
    h.log_individual(kind="program")
    h.log_fitness(individual="i-foo", scores={"x": 1.0})
    from hutch.sdk import fallback

    queued = list(fallback.iter_events(cfg.fallback_path))
    # run_start + individual + fitness = 3
    assert len(queued) == 3
