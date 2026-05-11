"""Tests for the optional OTel emitter.

Skipped when the optional ``[otel]`` extra isn't installed — same
opt-in posture as ``[skill-eval]``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hutch.otel import is_otel_available

needs_otel = pytest.mark.skipif(
    not is_otel_available(),
    reason="install with `pip install -e .[otel]` to enable",
)


@needs_otel
def test_off_by_default_no_emitter() -> None:
    """Without ``otel_endpoint`` the SDK builds the plain transport."""
    from hutch.otel import build_otel_exporter
    from hutch.sdk import SDKConfig
    from hutch.sdk.transport import _OTelTeeTransport, build_transport

    cfg = SDKConfig(mode="embedded", db_path=Path(":memory:"))
    transport = build_transport(cfg)
    assert not isinstance(transport, _OTelTeeTransport)
    assert build_otel_exporter(endpoint=None) is None
    assert build_otel_exporter(endpoint="") is None


@needs_otel
def test_in_memory_round_trip(tmp_path: Path) -> None:
    """Configure the SDK with the in-memory OTel exporter and assert that
    a small loop produces one span per canonical event with the
    ``research.*`` attributes wired up correctly."""
    import hutch as h
    from hutch.sdk import SDKConfig

    h.reset()
    h.configure(
        SDKConfig(
            mode="embedded",
            db_path=tmp_path / "hutch.duckdb",
            otel_endpoint="in-memory",
            otel_service_name="test-otel",
        )
    )

    from hutch.otel import OTelEmitter
    from hutch.sdk._state import state
    from hutch.sdk.transport import _TeeTransport

    transport = state().transport
    assert isinstance(transport, _TeeTransport)
    emitter = next(e for e in transport.emitters if isinstance(e, OTelEmitter))

    run = h.start_run(name="otel-demo", project="otel-test")
    seed = h.log_individual(kind="hypothesis", metadata={"text": "seed"})
    h.log_fitness(individual=seed, scores={"plausibility": 0.7})
    refined = h.log_individual(kind="hypothesis", parent_ids=[seed.id])
    h.log_operator(
        kind="refine",
        parent_ids=[seed.id],
        child_id=refined.id,
        cost_usd=0.01,
        tokens_in=42,
        tokens_out=18,
    )
    h.log_fitness(individual=refined, scores={"plausibility": 0.85})
    h.log_claim(text="the hypothesis is plausible", supported_by=[refined.id])
    h.end_run(status="finished")

    spans = emitter.in_memory_spans
    # 7 events emit spans (the run's start/end forms a single span).
    by_name: dict[str, list] = {}
    for span in spans:
        by_name.setdefault(span.name, []).append(span)

    assert any(name.startswith("hutch.run:") for name in by_name)
    assert "hutch.individual" in by_name
    assert len(by_name["hutch.individual"]) == 2
    assert "hutch.operator" in by_name
    assert "hutch.fitness" in by_name
    assert "hutch.claim" in by_name

    # Pick the operator span and verify the research.* attributes.
    op_span = by_name["hutch.operator"][0]
    attrs = dict(op_span.attributes)
    assert attrs["research.event.kind"] == "operator"
    assert attrs["research.run.id"] == run.id
    assert attrs["research.operator.kind"] == "refine"
    assert attrs["research.operator.cost_usd"] == 0.01
    assert attrs["research.operator.tokens_in"] == 42
    assert attrs["research.operator.tokens_out"] == 18

    # Fitness span flattens scores into research.fitness.score.<name>.
    fit = by_name["hutch.fitness"][1]  # the second fitness, plausibility=0.85
    fit_attrs = dict(fit.attributes)
    assert fit_attrs["research.fitness.individual_id"] == refined.id
    assert fit_attrs["research.fitness.score.plausibility"] == pytest.approx(0.85)

    # Run span carries the run name + project.
    run_span = by_name[f"hutch.run:{run.id}"][0]
    run_attrs = dict(run_span.attributes)
    assert run_attrs["research.run.name"] == "otel-demo"
    assert run_attrs["research.run.project"] == "otel-test"
    assert run_attrs["research.run.status"] == "finished"

    h.reset()


@needs_otel
def test_emit_failure_does_not_crash_send(tmp_path: Path) -> None:
    """A broken emitter must not break the primary transport."""
    import hutch as h
    from hutch.sdk import SDKConfig
    from hutch.sdk._state import state

    h.reset()
    h.configure(
        SDKConfig(
            mode="embedded",
            db_path=tmp_path / "hutch.duckdb",
            otel_endpoint="in-memory",
        )
    )
    # Replace the emitter list with one that raises on .emit.
    transport = state().transport

    class _Boom:
        def emit(self, _ev):
            raise RuntimeError("boom")

        def shutdown(self) -> None:
            pass

    transport._emitters = [_Boom()]

    run = h.start_run(name="otel-failure")
    h.log_individual(kind="hypothesis", metadata={"text": "still works"})
    h.end_run()
    assert run.id  # if we got here, the failed emitter didn't take the SDK down

    h.reset()


def test_build_otel_exporter_warns_without_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    """When the [otel] extra isn't importable, build_otel_exporter
    returns None even if an endpoint is provided."""
    import hutch.otel as otel_mod
    from hutch.otel import build_otel_exporter

    monkeypatch.setattr(otel_mod.emitter, "is_otel_available", lambda: False)
    assert build_otel_exporter(endpoint="http://localhost:4318") is None
