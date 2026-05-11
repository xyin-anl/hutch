"""Tests for the publication-quality exporters.

Three exporters share a common ``hutch.export`` module and CLI surface:

* ARA    — round-trip a tarball (lossless)
* PROV-O — Turtle dep-free; JSON-LD via rdflib (skip when not installed)
* RO-Crate — hand-built JSON-LD, dep-free, validate the manifest shape
"""

from __future__ import annotations

import importlib.util
import io
import json
import tarfile
from pathlib import Path

import pytest

from hutch.export import (
    ARA_FORMAT_VERSION,
    PROV_FORMATS,
    RO_CRATE_PROFILE,
    export_ara,
    export_prov,
    export_ro_crate,
    import_ara,
)
from hutch.schema import (
    EVENT_ADAPTER,
    AnyEvent,
    FitnessEvent,
    FitnessPayload,
    IndividualEvent,
    IndividualPayload,
    OperatorEvent,
    OperatorPayload,
    RunEndEvent,
    RunEndPayload,
    RunStartEvent,
    RunStartPayload,
)

# ---------- shared fixture ------------------------------------------------


@pytest.fixture
def sample_events() -> list[AnyEvent]:
    """Two-individual run with one operator. Covers run_start, individual,
    fitness, operator, run_end."""
    base_ts = 1_700_000_000_000_000_000
    return [
        RunStartEvent(
            run_id="r-export",
            timestamp_ns=base_ts,
            payload=RunStartPayload(name="export-test", project="research", started_by="ci-bot"),
        ),
        IndividualEvent(
            run_id="r-export",
            timestamp_ns=base_ts + 1,
            payload=IndividualPayload(id="ind-1", kind="hypothesis", is_seed=True),
        ),
        FitnessEvent(
            run_id="r-export",
            timestamp_ns=base_ts + 2,
            payload=FitnessPayload(
                individual_id="ind-1",
                evaluator_kind="deterministic_metric",
                scores={"plausibility": 0.5},
            ),
        ),
        IndividualEvent(
            run_id="r-export",
            timestamp_ns=base_ts + 3,
            payload=IndividualPayload(id="ind-2", kind="hypothesis", parent_ids=["ind-1"]),
        ),
        OperatorEvent(
            run_id="r-export",
            timestamp_ns=base_ts + 4,
            payload=OperatorPayload(
                id="op-1",
                kind="refine",
                parent_ids=["ind-1"],
                child_id="ind-2",
                llm_id="claude-sonnet-4-6",
                cost_usd=0.012,
            ),
        ),
        FitnessEvent(
            run_id="r-export",
            timestamp_ns=base_ts + 5,
            payload=FitnessPayload(
                individual_id="ind-2",
                evaluator_kind="deterministic_metric",
                scores={"plausibility": 0.85},
            ),
        ),
        RunEndEvent(
            run_id="r-export",
            timestamp_ns=base_ts + 6,
            payload=RunEndPayload(status="finished", summary="2 inds, 1 op"),
        ),
    ]


# ---------- ARA ----------------------------------------------------------


def test_ara_round_trip(tmp_path: Path, sample_events: list[AnyEvent]) -> None:
    """Write an ARA, read it back, assert every event survives intact."""
    target = tmp_path / "run.ara"
    written = export_ara(
        run_id="r-export",
        events=sample_events,
        output_path=target,
        notes="round-trip test",
    )
    assert written == target
    assert target.is_file()

    # The manifest is valid JSON.
    with tarfile.open(target, "r:gz") as tar:
        manifest_member = tar.getmember("manifest.json")
        handle = tar.extractfile(manifest_member)
        assert handle is not None
        manifest = json.loads(handle.read())
    assert manifest["ara_format_version"] == ARA_FORMAT_VERSION
    assert manifest["run_id"] == "r-export"
    assert manifest["event_count"] == len(sample_events)
    assert manifest["notes"] == "round-trip test"

    # Round-trip yields the same events (validated by the canonical schema).
    result, ev_iter = import_ara(target)
    rehydrated = list(ev_iter)
    assert result.events_replayed == len(sample_events)
    assert len(rehydrated) == len(sample_events)
    assert [e.event_kind for e in rehydrated] == [e.event_kind for e in sample_events]
    assert rehydrated[1].payload.id == "ind-1"  # type: ignore[union-attr]


def test_ara_blob_bundling(tmp_path: Path, sample_events: list[AnyEvent]) -> None:
    """Events with file:// URIs in ``genome_uri`` get the bytes bundled."""
    blob = tmp_path / "genome.txt"
    blob.write_text("def f(): return 42\n", encoding="utf-8")
    events_with_blob = [
        *sample_events,
        IndividualEvent(
            run_id="r-export",
            timestamp_ns=1_700_000_000_000_000_010,
            payload=IndividualPayload(
                id="ind-with-blob",
                kind="program",
                parent_ids=["ind-2"],
                genome_uri=blob.as_uri(),
            ),
        ),
    ]
    target = tmp_path / "with-blob.ara"
    export_ara(
        run_id="r-export",
        events=events_with_blob,
        output_path=target,
        include_local_files=True,
    )

    with tarfile.open(target, "r:gz") as tar:
        names = tar.getnames()
        manifest = json.loads(tar.extractfile(tar.getmember("manifest.json")).read())  # type: ignore[union-attr]
    assert manifest["blob_count"] == 1
    blob_files = [n for n in names if n.startswith("blobs/")]
    assert len(blob_files) == 1

    # Round-trip with a target dir restores the blob and rewrites the URI.
    blob_dir = tmp_path / "restored-blobs"
    result, ev_iter = import_ara(target, blob_target_dir=blob_dir)
    rehydrated = list(ev_iter)
    assert result.blobs_restored == 1
    blob_event = rehydrated[-1]
    new_uri = blob_event.payload.genome_uri  # type: ignore[union-attr]
    assert new_uri.startswith("file://")
    assert Path(new_uri[len("file://") :]).is_file()

    # Without a target dir the URI keeps its ara:// form.
    _, ev_iter_b = import_ara(target)
    rehydrated_b = list(ev_iter_b)
    assert rehydrated_b[-1].payload.genome_uri.startswith("ara://blobs/")  # type: ignore[union-attr]


def test_ara_does_not_bundle_local_files_by_default(
    tmp_path: Path, sample_events: list[AnyEvent]
) -> None:
    blob = tmp_path / "genome.txt"
    blob.write_text("secret local data\n", encoding="utf-8")
    event = IndividualEvent(
        run_id="r-export",
        timestamp_ns=1_700_000_000_000_000_010,
        payload=IndividualPayload(
            id="ind-with-blob",
            kind="program",
            parent_ids=["ind-2"],
            genome_uri=blob.as_uri(),
        ),
    )
    target = tmp_path / "safe-default.ara"
    export_ara(run_id="r-export", events=[*sample_events, event], output_path=target)

    with tarfile.open(target, "r:gz") as tar:
        manifest = json.loads(tar.extractfile(tar.getmember("manifest.json")).read())  # type: ignore[union-attr]
        names = tar.getnames()
    assert manifest["blob_count"] == 0
    assert not any(n.startswith("blobs/") for n in names)

    _, ev_iter = import_ara(target)
    rehydrated = list(ev_iter)
    assert rehydrated[-1].payload.genome_uri == blob.as_uri()  # type: ignore[union-attr]


def test_ara_import_rejects_malformed_blob_member(tmp_path: Path) -> None:
    target = tmp_path / "evil.ara"
    with tarfile.open(target, "w:gz") as tar:
        manifest = {
            "ara_format_version": ARA_FORMAT_VERSION,
            "hutch_version": "0.1.0",
            "run_id": "evil",
            "event_count": 0,
            "blob_count": 1,
        }
        manifest_bytes = json.dumps(manifest).encode("utf-8")
        info = tarfile.TarInfo("manifest.json")
        info.size = len(manifest_bytes)
        tar.addfile(info, io.BytesIO(manifest_bytes))

        events = b""
        events_info = tarfile.TarInfo("events.jsonl")
        events_info.size = 0
        tar.addfile(events_info, io.BytesIO(events))

        payload = b"x"
        bad = tarfile.TarInfo("blobs/../" + "0" * 64)
        bad.size = len(payload)
        tar.addfile(bad, io.BytesIO(payload))

    with pytest.raises(ValueError, match="invalid ARA blob member path"):
        list(import_ara(target, blob_target_dir=tmp_path / "restore")[1])


def test_ara_import_verifies_blob_hash(tmp_path: Path) -> None:
    target = tmp_path / "corrupt-blob.ara"
    bogus_hash = "0" * 64
    with tarfile.open(target, "w:gz") as tar:
        manifest = {
            "ara_format_version": ARA_FORMAT_VERSION,
            "hutch_version": "0.1.0",
            "run_id": "evil",
            "event_count": 0,
            "blob_count": 1,
        }
        manifest_bytes = json.dumps(manifest).encode("utf-8")
        info = tarfile.TarInfo("manifest.json")
        info.size = len(manifest_bytes)
        tar.addfile(info, io.BytesIO(manifest_bytes))

        events_info = tarfile.TarInfo("events.jsonl")
        events_info.size = 0
        tar.addfile(events_info, io.BytesIO(b""))

        payload = b"not the all-zero hash"
        blob_info = tarfile.TarInfo(f"blobs/{bogus_hash[:2]}/{bogus_hash[2:]}")
        blob_info.size = len(payload)
        tar.addfile(blob_info, io.BytesIO(payload))

    with pytest.raises(ValueError, match="blob hash mismatch"):
        import_ara(target, blob_target_dir=tmp_path / "restore")


def test_ara_import_caps_manifest_size(tmp_path: Path) -> None:
    target = tmp_path / "large-manifest.ara"
    with tarfile.open(target, "w:gz") as tar:
        manifest_bytes = b"{}"
        info = tarfile.TarInfo("manifest.json")
        info.size = len(manifest_bytes)
        tar.addfile(info, io.BytesIO(manifest_bytes))

        events_info = tarfile.TarInfo("events.jsonl")
        events_info.size = 0
        tar.addfile(events_info, io.BytesIO(b""))

    with pytest.raises(ValueError, match="manifest"):
        import_ara(target, max_manifest_bytes=1)


def test_ara_rejects_missing_archive(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        list(import_ara(tmp_path / "nonexistent.ara")[1])


def test_ara_rejects_invalid_archive(tmp_path: Path) -> None:
    bad = tmp_path / "broken.ara"
    with tarfile.open(bad, "w:gz") as tar:
        info = tarfile.TarInfo(name="not-the-manifest.txt")
        info.size = 0
        import io

        tar.addfile(info, io.BytesIO(b""))
    with pytest.raises(ValueError, match="manifest"):
        list(import_ara(bad)[1])


# ---------- PROV-O -------------------------------------------------------


def test_prov_turtle_dep_free(sample_events: list[AnyEvent], tmp_path: Path) -> None:
    """Turtle output is hand-built — works without rdflib."""
    out = export_prov(
        run_id="r-export",
        events=sample_events,
        format="turtle",
        output_path=tmp_path / "run.ttl",
    )
    assert "@prefix prov:" in out
    assert "hutch:run-r-export a prov:Activity" in out
    assert 'hutch:name "export-test"' in out
    assert "hutch:ind-ind-1 a prov:Entity" in out
    assert "prov:wasDerivedFrom hutch:ind-ind-1" in out
    assert "hutch:op-op-1 a prov:Activity" in out
    # File written.
    assert (tmp_path / "run.ttl").read_text(encoding="utf-8") == out


def test_prov_format_validation() -> None:
    with pytest.raises(ValueError, match="unknown PROV format"):
        export_prov(run_id="r", events=[], format="totally-fake")  # type: ignore[arg-type]


@pytest.mark.skipif(
    importlib.util.find_spec("rdflib") is None,
    reason="install with `pip install -e .[publish]` to enable",
)
def test_prov_round_trip_via_rdflib(sample_events: list[AnyEvent]) -> None:
    """Turtle parses cleanly + the alternate formats produce non-empty output."""
    import rdflib

    turtle = export_prov(run_id="r-export", events=sample_events, format="turtle")
    g = rdflib.Graph()
    g.parse(data=turtle, format="turtle")
    assert len(g) > 0  # at least one triple

    # Each alternate format returns a non-trivial string.
    for fmt in ("json-ld", "n-triples", "xml"):
        out = export_prov(run_id="r-export", events=sample_events, format=fmt)
        assert isinstance(out, str)
        assert len(out) > 100


def test_prov_format_constant_lists_all() -> None:
    assert set(PROV_FORMATS) == {"turtle", "json-ld", "n-triples", "xml"}


# ---------- RO-Crate -----------------------------------------------------


def test_ro_crate_writes_manifest_and_data(tmp_path: Path, sample_events: list[AnyEvent]) -> None:
    crate_dir = tmp_path / "crate"
    written = export_ro_crate(run_id="r-export", events=sample_events, output_dir=crate_dir)
    assert written == crate_dir
    manifest_path = crate_dir / "ro-crate-metadata.json"
    events_path = crate_dir / "data" / "events.jsonl"
    assert manifest_path.is_file()
    assert events_path.is_file()

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["@context"] == "https://w3id.org/ro/crate/1.1/context"
    graph = manifest["@graph"]
    assert any(n.get("@id") == "ro-crate-metadata.json" for n in graph)
    assert any(n.get("@id") == "./" for n in graph)

    root = next(n for n in graph if n.get("@id") == "./")
    assert root["@type"] == "Dataset"
    assert root["hutchRunId"] == "r-export"
    assert root["name"] == "export-test"
    profile_ids = {
        c["@id"]
        for c in next(n for n in graph if n.get("@id") == "ro-crate-metadata.json")["conformsTo"]
    }
    assert profile_ids == set(RO_CRATE_PROFILE)

    # Events file is one JSON object per line.
    lines = [line for line in events_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == len(sample_events)
    for line in lines:
        EVENT_ADAPTER.validate_python(json.loads(line))


def test_ro_crate_emits_create_action_per_operator(
    tmp_path: Path, sample_events: list[AnyEvent]
) -> None:
    crate_dir = tmp_path / "crate"
    export_ro_crate(run_id="r-export", events=sample_events, output_dir=crate_dir)
    manifest = json.loads((crate_dir / "ro-crate-metadata.json").read_text(encoding="utf-8"))
    create_actions = [n for n in manifest["@graph"] if n.get("@type") == "CreateAction"]
    assert len(create_actions) == 1  # one operator in the fixture
    op = create_actions[0]
    assert op["hutchOperatorKind"] == "refine"
    assert op["object"] == [{"@id": "#ind/ind-1"}]
    assert op["result"] == [{"@id": "#ind/ind-2"}]
    assert op["instrument"] == {"@id": "#agent/claude-sonnet-4-6"}
    assert op["hutchCostUsd"] == pytest.approx(0.012)


def test_ro_crate_includes_software_agent_for_llm(
    tmp_path: Path, sample_events: list[AnyEvent]
) -> None:
    crate_dir = tmp_path / "crate"
    export_ro_crate(run_id="r-export", events=sample_events, output_dir=crate_dir)
    manifest = json.loads((crate_dir / "ro-crate-metadata.json").read_text(encoding="utf-8"))
    agent_node = next(
        (n for n in manifest["@graph"] if n.get("@id") == "#agent/claude-sonnet-4-6"),
        None,
    )
    assert agent_node is not None
    assert agent_node["@type"] == "SoftwareApplication"
