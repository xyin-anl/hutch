"""Tests for the steering write-back channel."""

from __future__ import annotations

from fastapi.testclient import TestClient

from hutch.daemon.app import create_app


def test_issue_poll_ack_roundtrip() -> None:
    """End-to-end: POST /steering, GET poll, POST ack — and the in-memory
    queue lines up with the persisted ``steering_command`` events."""
    with TestClient(create_app()) as client:
        run = "r-steering-1"

        issue = client.post(
            f"/steering/{run}",
            json={
                "command": "pause_run",
                "actor": "human",
                "params": {"reason": "spot check"},
            },
        )
        assert issue.status_code == 200
        body = issue.json()
        cmd_id = body["command_id"]
        assert body["status"] == "pending"
        assert body["command"] == "pause_run"
        assert body["params"]["reason"] == "spot check"

        # Poll: gets the command and flips its status.
        poll1 = client.get(f"/steering/{run}/poll")
        assert poll1.status_code == 200
        assert len(poll1.json()) == 1
        assert poll1.json()[0]["command_id"] == cmd_id
        assert poll1.json()[0]["status"] == "delivered"

        # Polling again is empty — once delivered, never re-issued.
        poll2 = client.get(f"/steering/{run}/poll")
        assert poll2.status_code == 200
        assert poll2.json() == []

        # Ack with an outcome.
        ack = client.post(
            f"/steering/{run}/{cmd_id}/ack",
            json={"outcome": "done", "note": "loop paused"},
        )
        assert ack.status_code == 200
        assert ack.json()["status"] == "acked"
        assert ack.json()["outcome"] == "done"
        assert ack.json()["outcome_note"] == "loop paused"

        # History: still one entry.
        hist = client.get(f"/steering/{run}")
        assert hist.status_code == 200
        items = hist.json()
        assert len(items) == 1
        assert items[0]["status"] == "acked"

        # Persisted as steering_command events: one for issue, one for ack.
        events = client.get(f"/runs/{run}/events").json()
        sc_events = [e for e in events if e["event_kind"] == "steering_command"]
        assert len(sc_events) == 2
        statuses = {e["payload"]["metadata"]["status"] for e in sc_events}
        assert statuses == {"pending", "acked"}


def test_ack_unknown_command_returns_404() -> None:
    with TestClient(create_app()) as client:
        run = "r-steering-2"
        # Issue + poll something so the queue is initialized.
        client.post(f"/steering/{run}", json={"command": "pause_run", "actor": "human"})
        client.get(f"/steering/{run}/poll")

        bad = client.post(
            f"/steering/{run}/cmd-does-not-exist/ack",
            json={"outcome": "rejected"},
        )
        assert bad.status_code == 404


def test_unknown_run_polls_empty() -> None:
    with TestClient(create_app()) as client:
        empty = client.get("/steering/never-issued/poll")
        assert empty.status_code == 200
        assert empty.json() == []


def test_multiple_commands_preserve_order() -> None:
    """Order of polled commands matches order of issuance (FIFO)."""
    with TestClient(create_app()) as client:
        run = "r-steering-3"
        for cmd in ("pause_run", "resume_run", "inject_hint"):
            r = client.post(f"/steering/{run}", json={"command": cmd, "actor": "human"})
            assert r.status_code == 200
        polled = client.get(f"/steering/{run}/poll").json()
        assert [c["command"] for c in polled] == ["pause_run", "resume_run", "inject_hint"]
