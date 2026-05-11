"""``hutch`` command-line entry point.

This module wires the Typer app and exposes ``main()`` for the
``hutch`` console script declared in ``pyproject.toml``.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import typer

from hutch import __version__
from hutch.adapters import Adapter, detect_format
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


def _build_sdk_config(db: str | None, daemon_url: str | None) -> SDKConfig:
    if db and daemon_url:
        raise typer.BadParameter("Pass either --db or --daemon, not both.")

    if db is not None:
        return SDKConfig(mode="embedded", db_path=Path(db))
    if daemon_url is not None:
        return SDKConfig(mode="daemon", daemon_url=daemon_url, strict=True)

    cfg = SDKConfig.from_env()
    cfg.strict = True
    return cfg


def _resolve_adapter(path: Path, format: str | None) -> Adapter:
    from hutch.adapters import REGISTRY

    if format is not None:
        match_named = next((a for a in REGISTRY if a.name == format), None)
        if match_named is None:
            available = ", ".join(a.name for a in REGISTRY)
            raise typer.BadParameter(f"Unknown adapter {format!r}. Available: {available}")
        return match_named

    match_detected = detect_format(path)
    if match_detected is None:
        available = ", ".join(a.name for a in REGISTRY)
        raise typer.BadParameter(
            f"Could not auto-detect a format at {path}. "
            f"Try --format=<name> with one of: {available}, "
            "or --llm to generate an adapter on-the-fly."
        )
    return match_detected


def _watch_with_adapter(
    *,
    path: Path,
    cfg: SDKConfig,
    adapter: Any,
    run_id: str | None,
    project: str | None,
    poll_interval: float,
    idle_complete_seconds: float,
    include_audit: bool,
    audit_max_text_chars: int,
    watch_state: Path | None,
) -> None:
    from hutch.adapters.watch import watch_adapter

    adapter_options = _adapter_options(
        adapter=adapter,
        include_audit=include_audit,
        audit_max_text_chars=audit_max_text_chars,
    )
    state_path = watch_state or _default_watch_state_path(
        adapter=adapter,
        path=path,
        run_id=run_id,
        adapter_options=adapter_options,
    )
    transport = build_transport(cfg)
    typer.echo(
        f"watching {path} via adapter {adapter.name!r} → {cfg.mode} (poll={poll_interval}s)…"
    )
    typer.echo(f"  watch state: {state_path}")
    try:
        result = watch_adapter(
            adapter,
            path,
            transport,
            run_id=run_id,
            project=project,
            poll_interval=poll_interval,
            idle_complete_seconds=idle_complete_seconds,
            adapter_options=adapter_options,
            state_path=state_path,
            progress=lambda message: typer.echo(f"  {message}"),
        )
    finally:
        transport.close()

    if result.interrupted:
        typer.echo(f"watch interrupted after {result.events_sent} event(s).")
    else:
        typer.echo(f"watch completed after {result.events_sent} event(s).")


def _default_watch_state_path(
    *,
    adapter: Any,
    path: Path,
    run_id: str | None,
    adapter_options: dict[str, Any],
) -> Path:
    key = json.dumps(
        {
            "adapter": getattr(adapter, "name", "unknown"),
            "source_path": str(path.resolve()),
            "run_id": run_id,
            "adapter_options": adapter_options,
        },
        sort_keys=True,
        default=str,
    )
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]
    filename = f"{getattr(adapter, 'name', 'adapter')}-{digest}.json"
    return Path.home() / ".hutch" / "watch-state" / filename


def _adapter_options(
    *,
    adapter: Any,
    include_audit: bool,
    audit_max_text_chars: int,
) -> dict[str, Any]:
    if audit_max_text_chars < 0:
        raise typer.BadParameter("--audit-max-text-chars must be zero or greater.")
    if not include_audit:
        return {}
    if getattr(adapter, "name", None) != "cvevolve":
        raise typer.BadParameter(
            "--include-audit is currently supported only for --format cvevolve."
        )
    return {
        "include_audit": True,
        "audit_max_text_chars": audit_max_text_chars,
    }


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
    watch: bool = typer.Option(
        False,
        "--watch",
        help="Poll the adapter source until completion instead of doing a one-shot import.",
    ),
    poll_interval: float = typer.Option(
        2.0,
        "--poll-interval",
        min=0.01,
        help="Seconds between watch polls.",
    ),
    idle_complete_seconds: float = typer.Option(
        60.0,
        "--idle-complete-seconds",
        min=0.01,
        help="For idle-completion adapters, finish after this many quiet seconds.",
    ),
    watch_state: Path | None = typer.Option(
        None,
        "--watch-state",
        help="Path to a watch checkpoint JSON file. Defaults under ~/.hutch/watch-state/.",
    ),
    include_audit: bool = typer.Option(
        False,
        "--include-audit",
        help=(
            "For CVEvolve, import high-volume messages.sqlite/tool_calls.sqlite "
            "audit rows as stream events."
        ),
    ),
    audit_max_text_chars: int = typer.Option(
        8000,
        "--audit-max-text-chars",
        min=0,
        help="Maximum text characters per imported audit event; 0 disables truncation.",
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
    cfg = _build_sdk_config(db, daemon_url)
    if include_audit and (llm or (path.is_file() and path.suffix == ".ara")):
        raise typer.BadParameter(
            "--include-audit is only supported for hand-written CVEvolve adapter imports."
        )

    # ARA tarballs are recognised by extension and round-trip imported via
    # the dedicated unpacker rather than the adapter registry.
    if path.is_file() and path.suffix == ".ara":
        if watch:
            raise typer.BadParameter("--watch is only supported for adapter imports.")
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
        if watch:
            raise typer.BadParameter("--watch is only supported for hand-written adapters.")
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

    adapter = _resolve_adapter(path, format)
    if watch:
        _watch_with_adapter(
            path=path,
            cfg=cfg,
            adapter=adapter,
            run_id=run_id,
            project=project,
            poll_interval=poll_interval,
            idle_complete_seconds=idle_complete_seconds,
            include_audit=include_audit,
            audit_max_text_chars=audit_max_text_chars,
            watch_state=watch_state,
        )
        return

    adapter_options = _adapter_options(
        adapter=adapter,
        include_audit=include_audit,
        audit_max_text_chars=audit_max_text_chars,
    )
    transport = build_transport(cfg)
    typer.echo(f"importing {path} via adapter {adapter.name!r} → {cfg.mode}…")
    count = 0
    try:
        for event in adapter.iter_events(path, run_id=run_id, project=project, **adapter_options):
            transport.send(event)
            count += 1
    finally:
        transport.close()
    typer.echo(f"imported {count} events.")


@app.command("watch")
def watch_(
    path: Path = typer.Argument(
        ...,
        exists=True,
        file_okay=True,
        dir_okay=True,
        help="Path to an adapter source to watch.",
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
    poll_interval: float = typer.Option(
        2.0,
        "--poll-interval",
        min=0.01,
        help="Seconds between watch polls.",
    ),
    idle_complete_seconds: float = typer.Option(
        60.0,
        "--idle-complete-seconds",
        min=0.01,
        help="For idle-completion adapters, finish after this many quiet seconds.",
    ),
    watch_state: Path | None = typer.Option(
        None,
        "--watch-state",
        help="Path to a watch checkpoint JSON file. Defaults under ~/.hutch/watch-state/.",
    ),
    include_audit: bool = typer.Option(
        False,
        "--include-audit",
        help=(
            "For CVEvolve, import high-volume messages.sqlite/tool_calls.sqlite "
            "audit rows as stream events."
        ),
    ),
    audit_max_text_chars: int = typer.Option(
        8000,
        "--audit-max-text-chars",
        min=0,
        help="Maximum text characters per imported audit event; 0 disables truncation.",
    ),
) -> None:
    """Continuously import adapter events until the source completes."""
    cfg = _build_sdk_config(db, daemon_url)
    adapter = _resolve_adapter(path, format)
    _watch_with_adapter(
        path=path,
        cfg=cfg,
        adapter=adapter,
        run_id=run_id,
        project=project,
        poll_interval=poll_interval,
        idle_complete_seconds=idle_complete_seconds,
        include_audit=include_audit,
        audit_max_text_chars=audit_max_text_chars,
        watch_state=watch_state,
    )


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
