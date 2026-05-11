"""``hutch`` command-line entry point.

This module wires the Typer app and exposes ``main()`` for the
``hutch`` console script declared in ``pyproject.toml``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import typer

from hutch import __version__
from hutch.adapters import detect_format
from hutch.daemon.server import run_daemon
from hutch.sdk import SDKConfig
from hutch.sdk.transport import build_transport

app = typer.Typer(
    name="hutch",
    help="Observability, steering, and provenance for autonomous-research agents.",
    no_args_is_help=True,
    add_completion=False,
)


def _print_version(value: bool) -> None:
    if value:
        typer.echo(f"hutch {__version__}")
        raise typer.Exit


@app.callback()
def _root(
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        help="Print the installed Hutch version and exit.",
        callback=_print_version,
        is_eager=True,
    ),
) -> None:
    """Top-level options."""


@app.command("import")
def import_(
    path: Path = typer.Argument(
        ...,
        exists=True,
        file_okay=True,
        dir_okay=True,
        help="Path to a checkpoint or run dump.",
    ),
    db: str | None = typer.Option(
        None,
        "--db",
        help=("Write directly to a DuckDB file (embedded mode). Mutually exclusive with --daemon."),
    ),
    daemon_url: str | None = typer.Option(
        None,
        "--daemon",
        help="POST events to a running daemon at this URL (e.g. http://localhost:7777).",
    ),
    run_id: str | None = typer.Option(
        None,
        "--run-id",
        help="Override the canonical run id (default: derived from the path).",
    ),
    project: str | None = typer.Option(
        None,
        "--project",
        help="Tag the run with a project name.",
    ),
    format: str | None = typer.Option(
        None,
        "--format",
        help="Force a specific adapter instead of auto-detection.",
    ),
    llm: bool = typer.Option(
        False,
        "--llm",
        help=(
            "Use the LLM-assisted importer to "
            "generate a one-off adapter for an unknown format. Requires "
            "OPENAI_API_KEY (default) or ANTHROPIC_API_KEY in the env."
        ),
    ),
    no_cache: bool = typer.Option(
        False,
        "--no-cache",
        help="Force the LLM-importer to regenerate the adapter even if a "
        "cached one exists for this prompt fingerprint.",
    ),
) -> None:
    """Import a foreign checkpoint into Hutch by auto-detecting its format."""
    if db and daemon_url:
        raise typer.BadParameter("Pass either --db or --daemon, not both.")

    from hutch.adapters import REGISTRY

    if db is not None:
        cfg = SDKConfig(mode="embedded", db_path=Path(db))
    elif daemon_url is not None:
        cfg = SDKConfig(mode="daemon", daemon_url=daemon_url, strict=True)
    else:
        cfg = SDKConfig.from_env()
        cfg.strict = True

    # ARA tarballs are recognised by extension and round-trip imported via
    # the dedicated unpacker rather than the adapter registry.
    if path.is_file() and path.suffix == ".ara":
        from hutch.export import import_ara

        typer.echo(f"importing ARA tarball {path}…")
        ara_result, events_iter = import_ara(path)
        typer.echo(
            f"  manifest: run_id={ara_result.manifest.run_id} "
            f"hutch={ara_result.manifest.hutch_version} "
            f"events={ara_result.manifest.event_count} "
            f"blobs={ara_result.manifest.blob_count}"
        )
        transport = build_transport(cfg)
        try:
            count = 0
            for ev in events_iter:
                transport.send(ev)
                count += 1
        finally:
            transport.close()
        typer.echo(f"imported {count} events from {path}.")
        return

    if llm:
        from hutch.importer import import_with_llm

        typer.echo(f"running LLM-assisted importer on {path}…")
        typer.echo(
            "  ⚠ generated adapters run under constrained Python execution, "
            "not a full OS sandbox. Use --llm only for trusted or staged inputs."
        )
        result, events = import_with_llm(path, use_cache=not no_cache)
        typer.echo(
            f"  adapter:   {result.adapter.fingerprint} "
            f"({'cache hit' if result.cache_hit else 'fresh'}) "
            f"via {result.adapter.provider}/{result.adapter.model}"
        )
        if result.notes:
            typer.echo(f"  notes:     {result.notes[:200]}")
        typer.echo(
            f"  sample:    {result.sample_valid}/{result.sample_total} "
            f"events valid ({result.sample_coverage:.0%})"
        )
        typer.echo(
            f"  full corpus: {result.full_valid}/{result.full_total} "
            f"events valid ({result.full_coverage:.0%})"
        )
        if result.full_records_truncated:
            typer.echo(
                "  ⚠ import capped at "
                f"{result.full_records_seen} JSON-shaped records. "
                "Use a hand-written adapter for larger corpora until "
                "the LLM importer streams full datasets."
            )
        if result.full_coverage < 0.5:
            typer.echo(
                "  ⚠ low coverage — the LLM struggled with this format. "
                "Consider hand-tuning the cached adapter at "
                f"~/.hutch/adapters/{result.adapter.fingerprint}.json"
            )
        transport = build_transport(cfg)
        count = 0
        try:
            for event in events:
                transport.send(event)
                count += 1
        finally:
            transport.close()
        typer.echo(f"imported {count} events.")
        return

    if format is not None:
        match_named = next((a for a in REGISTRY if a.name == format), None)
        if match_named is None:
            available = ", ".join(a.name for a in REGISTRY)
            raise typer.BadParameter(f"Unknown adapter {format!r}. Available: {available}")
        adapter = match_named
    else:
        match_detected = detect_format(path)
        if match_detected is None:
            available = ", ".join(a.name for a in REGISTRY)
            raise typer.BadParameter(
                f"Could not auto-detect a format at {path}. "
                f"Try --format=<name> with one of: {available}, "
                "or --llm to generate an adapter on-the-fly."
            )
        adapter = match_detected

    transport = build_transport(cfg)
    typer.echo(f"importing {path} via adapter {adapter.name!r} → {cfg.mode}…")
    count = 0
    try:
        for event in adapter.importer(path, run_id=run_id, project=project):
            transport.send(event)
            count += 1
    finally:
        transport.close()
    typer.echo(f"imported {count} events.")


export_app = typer.Typer(
    name="export",
    help="Export a finished run as PROV-O / RO-Crate / ARA package.",
    no_args_is_help=True,
    add_completion=False,
)
app.add_typer(export_app, name="export")


def _read_events_for_export(run_id: str, db: str | None) -> tuple[list[Any], Path | None]:
    """Open the configured DuckDB and read every event for *run_id*."""
    from hutch.store import open_and_migrate, read_events

    if db is not None:
        db_path: Path | None = Path(db)
    else:
        # SDKConfig holds the DuckDB path under both modes; we don't bother
        # branching on cfg.mode since the embedded DB is the source of truth
        # whether or not the daemon is also reading from it.
        db_path = SDKConfig.from_env().db_path
    conn = open_and_migrate(db_path)
    try:
        events = read_events(conn, run_id)
    finally:
        conn.close()
    if not events:
        raise typer.BadParameter(
            f"No events found for run_id={run_id!r} in {db_path}. "
            "Pass --db to point at the right DuckDB file, or use --daemon-url."
        )
    return events, db_path


@export_app.command("ara")
def export_ara_cmd(
    run_id: str = typer.Argument(..., help="Run id to export."),
    output: Path = typer.Option(
        ...,
        "--output",
        "-o",
        help="Output path for the .ara tarball.",
    ),
    db: str | None = typer.Option(
        None,
        "--db",
        help="DuckDB file to read from (defaults to HUTCH_DB_PATH or ~/.hutch/hutch.duckdb).",
    ),
    notes: str | None = typer.Option(
        None,
        "--notes",
        help="Free-form notes string to embed in the manifest.",
    ),
    include_local_files: bool = typer.Option(
        False,
        "--include-local-files",
        help=(
            "Bundle readable local file paths referenced by event payloads. "
            "Off by default to avoid accidental local-file disclosure."
        ),
    ),
    blob_root: Path | None = typer.Option(
        None,
        "--blob-root",
        help="Optional root directory local file bundling must stay under.",
    ),
) -> None:
    """Export a run as a self-contained .ara tarball (M15)."""
    from hutch.export import export_ara

    events, _ = _read_events_for_export(run_id, db)
    written = export_ara(
        run_id=run_id,
        events=events,
        output_path=output,
        notes=notes,
        include_local_files=include_local_files,
        blob_root=blob_root,
    )
    typer.echo(f"wrote {written} ({len(events)} events).")


@export_app.command("prov")
def export_prov_cmd(
    run_id: str = typer.Argument(..., help="Run id to export."),
    output: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Output file path. If omitted, the serialised PROV is written to stdout.",
    ),
    fmt: str = typer.Option(
        "turtle",
        "--format",
        "-f",
        help="Serialisation format: turtle (default), json-ld, n-triples, xml.",
    ),
    db: str | None = typer.Option(
        None,
        "--db",
        help="DuckDB file to read from.",
    ),
) -> None:
    """Export a run as W3C PROV-O (M13)."""
    from hutch.export import PROV_FORMATS, export_prov

    if fmt not in PROV_FORMATS:
        raise typer.BadParameter(f"--format must be one of {PROV_FORMATS}, got {fmt!r}")

    events, _ = _read_events_for_export(run_id, db)
    serialised = export_prov(
        run_id=run_id,
        events=events,
        output_path=output,
        format=fmt,
    )
    if output is None:
        typer.echo(serialised)
    else:
        typer.echo(f"wrote {output} ({len(events)} events, {fmt}).")


@export_app.command("ro-crate")
def export_ro_crate_cmd(
    run_id: str = typer.Argument(..., help="Run id to export."),
    output_dir: Path = typer.Option(
        ...,
        "--output",
        "-o",
        help="Output directory for the RO-Crate.",
    ),
    db: str | None = typer.Option(
        None,
        "--db",
        help="DuckDB file to read from.",
    ),
) -> None:
    """Export a run as a Workflow Run RO-Crate (M14)."""
    from hutch.export import export_ro_crate

    events, _ = _read_events_for_export(run_id, db)
    written = export_ro_crate(
        run_id=run_id,
        events=events,
        output_dir=output_dir,
    )
    typer.echo(f"wrote {written}/ro-crate-metadata.json ({len(events)} events).")


@app.command()
def serve(
    host: str = typer.Option(
        "127.0.0.1",
        "--host",
        help="Interface to bind. Use 0.0.0.0 to expose on the network.",
    ),
    port: int = typer.Option(7777, "--port", help="TCP port to listen on."),
    db: str | None = typer.Option(
        None,
        "--db",
        help=(
            "Path to the DuckDB file. Defaults to $HUTCH_DB_PATH or "
            "~/.hutch/hutch.duckdb. Pass ':memory:' for an ephemeral run."
        ),
    ),
    reload: bool = typer.Option(
        False,
        "--reload",
        help="Auto-reload on code changes (development only).",
    ),
    unsafe_no_auth: bool = typer.Option(
        False,
        "--unsafe-no-auth",
        help=("Allow non-loopback binds without HUTCH_TOKEN. Only use on trusted local networks."),
    ),
) -> None:
    """Start the Hutch daemon (FastAPI on :7777 by default)."""
    try:
        run_daemon(
            host=host,
            port=port,
            db_path=db,
            reload=reload,
            unsafe_no_auth=unsafe_no_auth,
        )
    except RuntimeError as exc:
        raise typer.BadParameter(str(exc)) from exc


def main() -> None:
    """Console-script entry point."""
    app()


if __name__ == "__main__":
    main()
