"""End-to-end integration test.

Spawns the real ``hutch serve`` subprocess on a free port with a tmp DuckDB,
runs the SDK against it, queries events back through the daemon's HTTP API,
and verifies correctness. This is the test that proves a fresh
``pip install thehutch && hutch serve`` actually works end-to-end.

Skipped on systems where the ``hutch`` console script isn't on PATH (e.g.
CI matrices that test source-only without installing the package).
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

import hutch as h
from hutch.sdk import SDKConfig

pytestmark = pytest.mark.skipif(
    shutil.which("hutch") is None and shutil.which(sys.executable) is None,
    reason="hutch console script not installed",
)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _wait_until_ready(url: str, *, timeout: float = 15.0) -> None:
    deadline = time.monotonic() + timeout
    last_exc: Exception | None = None
    while time.monotonic() < deadline:
        try:
            response = httpx.get(f"{url}/healthz", timeout=0.5)
            if response.status_code == 200:
                return
        except httpx.HTTPError as exc:
            last_exc = exc
        time.sleep(0.1)
    raise RuntimeError(f"daemon at {url} did not become ready in {timeout}s: {last_exc}")


@pytest.fixture
def daemon_subprocess(tmp_path: Path) -> Iterator[str]:
    """Spawn ``hutch serve`` as a real subprocess and yield its base URL."""
    port = _free_port()
    db_path = tmp_path / "integration.duckdb"
    env = {**os.environ, "HUTCH_DB_PATH": str(db_path)}
    proc = subprocess.Popen(
        [sys.executable, "-m", "hutch", "serve", "--port", str(port), "--db", str(db_path)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    base_url = f"http://127.0.0.1:{port}"
    try:
        _wait_until_ready(base_url)
        yield base_url
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:  # pragma: no cover
            proc.kill()
            proc.wait(timeout=5)


def test_subprocess_serves_index_and_endpoints(daemon_subprocess: str) -> None:
    """Sanity: the spawned daemon answers / and the metadata endpoints."""
    response = httpx.get(daemon_subprocess + "/", timeout=2.0)
    assert response.status_code == 200
    assert "Hutch" in response.text
    assert httpx.get(daemon_subprocess + "/version", timeout=2.0).json() == {
        "version": h.__version__
    }


def test_full_sdk_round_trip_through_real_daemon(daemon_subprocess: str) -> None:
    """The M2 done-criterion check.

    Run a small linear loop through the SDK, then query every read endpoint
    on the live daemon and assert the events were stored correctly.
    """
    cfg = SDKConfig(
        mode="daemon",
        daemon_url=daemon_subprocess,
        strict=True,  # surface failures loudly in this test
        request_timeout_s=2.0,
    )
    h.configure(cfg)

    run = h.start_run(name="integration-linear", project="hutch-tests")
    seed = h.log_individual(kind="hypothesis")
    refined = h.log_individual(kind="hypothesis", parent_ids=[seed.id])
    h.log_operator(kind="refine", parent_ids=[seed.id], child_id=refined.id)
    h.log_fitness(individual=refined, scores={"plausibility": 0.7})
    claim = h.log_claim(text="hypothesis is plausible", supported_by=[refined.id])
    h.log_evidence(claim_id=claim.id, source_uri="arxiv:1234", stance="supports")
    h.end_run(status="finished")

    client = httpx.Client(base_url=daemon_subprocess, timeout=2.0)

    # Run summary
    summary = client.get(f"/runs/{run.id}").json()
    assert summary["event_count"] == 8  # run_start + 2 ind + op + fit + claim + ev + run_end
    assert set(summary["kinds_seen"]) >= {
        "run_start",
        "individual",
        "operator",
        "fitness",
        "claim",
        "evidence",
        "run_end",
    }

    # Run list
    runs = client.get("/runs").json()
    assert any(r["run_id"] == run.id for r in runs)

    # Individuals
    inds = client.get(f"/runs/{run.id}/individuals").json()
    assert len(inds) == 2
    ind_ids = {i["payload"]["id"] for i in inds}
    assert ind_ids == {seed.id, refined.id}

    # Operators
    ops = client.get(f"/runs/{run.id}/operators").json()
    assert len(ops) == 1
    assert ops[0]["payload"]["child_id"] == refined.id

    # Fitness
    fits = client.get(f"/runs/{run.id}/fitness").json()
    assert len(fits) == 1
    assert fits[0]["payload"]["scores"] == {"plausibility": 0.7}

    client.close()


def test_404_on_unknown_run_via_real_daemon(daemon_subprocess: str) -> None:
    response = httpx.get(daemon_subprocess + "/runs/does-not-exist", timeout=2.0)
    assert response.status_code == 404
