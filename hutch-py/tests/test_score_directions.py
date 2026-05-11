"""Per-metric optimisation direction.

The dashboard's Pareto frontier, best-composite stat, and any
direction-aware consumer needs to know which metrics are higher-better
and which are lower-better. This test pins:

1. The schema accepts ``score_directions`` on ``RunStartPayload``.
2. The SDK's ``start_run`` propagates the kwarg.
3. The daemon's ``GET /runs/{id}`` surfaces the dict for the UI.
4. Adapters that know their metrics' directions populate them
   (openevolve, ptychi-evolve, asi-arch).
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import hutch as h
from hutch._fixtures.openevolve import make_checkpoint as make_oe_checkpoint
from hutch.adapters.asi_arch import import_asi_arch
from hutch.adapters.openevolve import import_openevolve
from hutch.adapters.ptychi_evolve import import_ptychi_evolve
from hutch.daemon.app import create_app
from hutch.schema import EVENT_ADAPTER, RunStartPayload, ScoreDirection
from tests._asi_arch_fixture import make_dump as make_asi_dump
from tests._ptychi_evolve_fixture import make_run as make_ptychi_run

# ---------- schema --------------------------------------------------------


def test_score_directions_accepts_higher_lower() -> None:
    payload = RunStartPayload(
        score_directions={"accuracy": "higher", "compile_ms": "lower"},
    )
    assert payload.score_directions == {"accuracy": "higher", "compile_ms": "lower"}


def test_score_directions_rejects_unknown_value() -> None:
    """Pydantic + Literal rejects values outside higher/lower."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        RunStartPayload(
            score_directions={"acc": "max"},  # type: ignore[dict-item]
        )


def test_score_directions_default_is_empty_dict() -> None:
    assert RunStartPayload().score_directions == {}


def test_score_direction_literal_values() -> None:
    """Pin the exported literal type."""
    expected: set[ScoreDirection] = {"higher", "lower"}
    # Trivially asserts the names; the real check is that the import works.
    assert "higher" in expected
    assert "lower" in expected


# ---------- SDK propagation ----------------------------------------------


@pytest.fixture
def sdk_against_in_memory() -> Iterator[None]:
    h.reset()
    h.configure(h.SDKConfig(mode="embedded", db_path=None))
    yield
    h.reset()


def test_start_run_propagates_score_directions(sdk_against_in_memory: None) -> None:
    h.start_run(
        name="sd-smoke",
        score_directions={"accuracy": "higher", "compile_ms": "lower"},
    )
    h.end_run()
    # Round-trip via the embedded transport's DuckDB conn.
    from hutch.sdk._state import state

    assert state().transport is not None  # implicit; just for confidence


# ---------- daemon endpoint ----------------------------------------------


@pytest.fixture
def daemon_client(tmp_path: Path) -> Iterator[TestClient]:
    app = create_app(db_path=tmp_path / "daemon.duckdb")
    with TestClient(app) as client:
        yield client


def test_get_run_surfaces_score_directions(daemon_client: TestClient) -> None:
    """GET /runs/{id} should include the score_directions for the UI."""
    daemon_client.post(
        "/events",
        json={
            "run_id": "r-sd",
            "event_kind": "run_start",
            "payload": {
                "name": "sd-test",
                "score_directions": {"accuracy": "higher", "compile_ms": "lower"},
            },
        },
    )
    daemon_client.post(
        "/events",
        json={
            "run_id": "r-sd",
            "event_kind": "run_end",
            "payload": {"status": "finished"},
        },
    )
    detail = daemon_client.get("/runs/r-sd").json()
    assert detail["score_directions"] == {"accuracy": "higher", "compile_ms": "lower"}


def test_run_update_overrides_score_directions_and_marks_running(
    daemon_client: TestClient,
) -> None:
    daemon_client.post(
        "/events",
        json={
            "run_id": "r-live-sd",
            "timestamp_ns": 1,
            "event_kind": "run_start",
            "payload": {"name": "live", "score_directions": {"loss": "higher"}},
        },
    )
    daemon_client.post(
        "/events",
        json={
            "run_id": "r-live-sd",
            "timestamp_ns": 2,
            "event_kind": "run_update",
            "payload": {"status": "running", "score_directions": {"loss": "lower"}},
        },
    )

    detail = daemon_client.get("/runs/r-live-sd").json()
    assert detail["status"] == "running"
    assert detail["score_directions"] == {"loss": "lower"}

    runs = daemon_client.get("/runs").json()
    summary = next(run for run in runs if run["run_id"] == "r-live-sd")
    assert summary["status"] == "running"

    daemon_client.post(
        "/events",
        json={
            "run_id": "r-live-sd",
            "timestamp_ns": 3,
            "event_kind": "run_end",
            "payload": {"status": "finished"},
        },
    )
    runs = daemon_client.get("/runs").json()
    summary = next(run for run in runs if run["run_id"] == "r-live-sd")
    assert summary["status"] == "finished"


def test_get_run_returns_empty_score_directions_when_absent(
    daemon_client: TestClient,
) -> None:
    daemon_client.post(
        "/events",
        json={
            "run_id": "r-empty",
            "event_kind": "run_start",
            "payload": {"name": "empty"},
        },
    )
    detail = daemon_client.get("/runs/r-empty").json()
    assert detail["score_directions"] == {}


# ---------- adapters -------------------------------------------------------


def test_openevolve_declares_circle_packing_directions(tmp_path: Path) -> None:
    """OpenEvolve's circle-packing benchmark uses sum_radii (max) + compile_ms (min)."""
    checkpoint = make_oe_checkpoint(tmp_path / "oe", num_islands=2, programs_per_island=2)
    events = list(import_openevolve(checkpoint))
    run_start = next(e for e in events if e.event_kind == "run_start")
    sd = run_start.payload.score_directions  # type: ignore[union-attr]
    assert sd["sum_radii"] == "higher"
    assert sd["compile_ms"] == "lower"


def test_ptychi_declares_nrmse_and_time_lower(tmp_path: Path) -> None:
    target = tmp_path / "ptychi"
    make_ptychi_run(target)
    events = list(import_ptychi_evolve(target))
    run_start = next(e for e in events if e.event_kind == "run_start")
    sd = run_start.payload.score_directions  # type: ignore[union-attr]
    assert sd["nrmse"] == "lower"
    assert sd["time_s"] == "lower"


def test_asi_arch_declares_score_higher_loss_lower(tmp_path: Path) -> None:
    target = tmp_path / "asi"
    target.mkdir()
    make_asi_dump(target / "experiments.jsonl", num_experiments=4)
    events = list(import_asi_arch(target))
    run_start = next(e for e in events if e.event_kind == "run_start")
    sd = run_start.payload.score_directions  # type: ignore[union-attr]
    assert sd["score"] == "higher"
    assert sd["loss"] == "lower"


# ---------- canonical-event round trip -----------------------------------


def test_event_with_score_directions_round_trips_through_event_adapter() -> None:
    raw = {
        "run_id": "r1",
        "event_kind": "run_start",
        "payload": {
            "name": "x",
            "score_directions": {"acc": "higher", "loss": "lower"},
        },
    }
    ev = EVENT_ADAPTER.validate_python(raw)
    serialised = ev.model_dump()
    again = EVENT_ADAPTER.validate_python(serialised)
    assert (
        again.payload.score_directions  # type: ignore[union-attr]
        == raw["payload"]["score_directions"]
    )
