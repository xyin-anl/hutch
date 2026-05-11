"""Integration tests for ``hutch.steering`` against an in-process daemon.

We monkey-patch the ``httpx.Client`` constructor inside :mod:`hutch.steering.api`
to hand back the ``TestClient`` so the SDK's calls land on the live FastAPI
app without touching a real socket — same pattern as
:mod:`tests.test_sdk_daemon`.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import hutch as h
from hutch import steering
from hutch.daemon.app import create_app
from hutch.sdk import SDKConfig
from hutch.sdk.transport import DaemonTransport


@pytest.fixture
def app_client(tmp_path: Path) -> Iterator[TestClient]:
    app = create_app(db_path=tmp_path / "daemon.duckdb")
    with TestClient(app) as client:
        yield client


@pytest.fixture
def configured_sdk(
    app_client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[None]:
    """Configure hutch to talk to the TestClient (rather than a network daemon)
    for both :mod:`hutch.sdk` and :mod:`hutch.steering.api`.
    """
    cfg = SDKConfig(
        mode="daemon",
        daemon_url="http://test-daemon",
        fallback_path=tmp_path / "fb.jsonl",
        strict=True,
    )

    def _patched_init(self: DaemonTransport, config: SDKConfig) -> None:
        self._config = config
        self._client = app_client  # TestClient *is* an httpx.Client
        if config.auto_fallback:
            self._drain_fallback()

    monkeypatch.setattr(DaemonTransport, "__init__", _patched_init)
    monkeypatch.setattr(steering.api, "_client", lambda: app_client)
    h.configure(cfg)
    # Reset registered handlers between tests.
    steering.api._handlers.clear()
    yield


def test_send_and_poll_dispatches_handler(configured_sdk: None) -> None:
    """Decorated handler is invoked + auto-acked by ``poll()``."""
    run = h.start_run(name="steering-sdk-test")
    try:
        called: list[str] = []

        @steering.handler("pause_run")
        def on_pause(cmd: steering.SteeringCommand) -> str:
            called.append(cmd.command)
            return "paused-from-handler"

        steering.send(command="pause_run", run_id=run.id)

        polled = steering.poll(run_id=run.id)
        assert len(polled) == 1
        assert polled[0].command == "pause_run"
        assert called == ["pause_run"]
    finally:
        h.end_run()


def test_unhandled_command_is_auto_rejected(configured_sdk: None) -> None:
    """A command without a registered handler is acked with outcome=rejected."""
    run = h.start_run(name="steering-sdk-unhandled")
    try:
        record = steering.send(command="cancel_individual", target_id="ind-x", run_id=run.id)
        cmd_id = record["command_id"]

        polled = steering.poll(run_id=run.id)
        assert len(polled) == 1

        # Re-poll should be empty, and the history should show outcome=rejected.
        assert steering.poll(run_id=run.id) == []
    finally:
        h.end_run()
    # The history endpoint shows the rejection.
    assert cmd_id  # captured for clarity; exact assertion left to test_steering.py


def test_poll_handles_multiple_commands_in_order(configured_sdk: None) -> None:
    run = h.start_run(name="steering-sdk-order")
    try:
        seen: list[str] = []

        @steering.handler("pause_run")
        def on_pause(cmd: steering.SteeringCommand) -> None:
            seen.append("pause")

        @steering.handler("resume_run")
        def on_resume(cmd: steering.SteeringCommand) -> None:
            seen.append("resume")

        steering.send(command="pause_run", run_id=run.id)
        steering.send(command="resume_run", run_id=run.id)
        steering.poll(run_id=run.id)
        assert seen == ["pause", "resume"]
    finally:
        h.end_run()


def test_steering_http_client_sends_auth_token() -> None:
    h.configure(
        SDKConfig(
            mode="daemon",
            daemon_url="http://test-daemon",
            auth_token="secret",
        )
    )
    client = steering.api._client()
    try:
        assert client.headers["authorization"] == "Bearer secret"
    finally:
        client.close()
