"""CLI smoke tests for M0."""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from typer.testing import CliRunner

from hutch import __version__
from hutch.cli import app
from hutch.store import open_and_migrate, read_events
from tests._cvevolve_fixture import make_session

runner = CliRunner()

# Newer versions of Rich (via Typer) wrap option-flag names with ANSI bold
# codes like ``\x1b[1m--host\x1b[0m``, which splits the literal ``--host``
# substring. Strip ANSI before asserting so the tests behave identically
# on a developer's TTY and on CI's terminal.
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _plain(text: str) -> str:
    return _ANSI_RE.sub("", text)


def test_help_runs() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    out = _plain(result.stdout)
    assert "hutch" in out.lower()
    assert "serve" in out


def test_version_flag() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in _plain(result.stdout)


def test_serve_command_listed() -> None:
    result = runner.invoke(app, ["serve", "--help"])
    assert result.exit_code == 0
    out = _plain(result.stdout)
    assert "--host" in out
    assert "--port" in out
    assert "--unsafe-no-auth" in out


def test_watch_command_imports_cvevolve_session(tmp_path: Path) -> None:
    session_dir = make_session(tmp_path / "session")
    db_path = tmp_path / "hutch.duckdb"
    state_path = tmp_path / "watch-state.json"

    result = runner.invoke(
        app,
        [
            "watch",
            str(session_dir),
            "--db",
            str(db_path),
            "--format",
            "cvevolve",
            "--poll-interval",
            "0.01",
            "--idle-complete-seconds",
            "0.01",
            "--watch-state",
            str(state_path),
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert "watch completed" in _plain(result.stdout)
    assert state_path.is_file()


def test_import_watch_alias_imports_cvevolve_session(tmp_path: Path) -> None:
    session_dir = make_session(tmp_path / "session")
    db_path = tmp_path / "hutch.duckdb"
    state_path = tmp_path / "import-watch-state.json"

    result = runner.invoke(
        app,
        [
            "import",
            str(session_dir),
            "--watch",
            "--db",
            str(db_path),
            "--format",
            "cvevolve",
            "--poll-interval",
            "0.01",
            "--idle-complete-seconds",
            "0.01",
            "--watch-state",
            str(state_path),
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert "watch completed" in _plain(result.stdout)


def test_watch_include_audit_imports_cvevolve_audit_streams(tmp_path: Path) -> None:
    session_dir = make_session(tmp_path / "session")
    db_path = tmp_path / "hutch.duckdb"
    state_path = tmp_path / "audit-watch-state.json"
    run_id = "cli-cvevolve-audit"

    result = runner.invoke(
        app,
        [
            "watch",
            str(session_dir),
            "--db",
            str(db_path),
            "--run-id",
            run_id,
            "--format",
            "cvevolve",
            "--include-audit",
            "--poll-interval",
            "0.01",
            "--idle-complete-seconds",
            "0.01",
            "--watch-state",
            str(state_path),
        ],
    )

    assert result.exit_code == 0, result.stdout
    conn = open_and_migrate(db_path)
    try:
        events = read_events(conn, run_id)
    finally:
        conn.close()
    labels = Counter(
        event.payload.label
        for event in events
        if event.event_kind == "stream_event"
        and event.payload.label in {"cvevolve_message", "cvevolve_tool_call"}
    )
    assert labels["cvevolve_message"] == 2
    assert labels["cvevolve_tool_call"] == 1


def test_server_rejects_non_loopback_without_token(monkeypatch) -> None:
    from hutch.daemon.server import run_daemon

    monkeypatch.delenv("HUTCH_TOKEN", raising=False)
    try:
        run_daemon(host="0.0.0.0")
    except RuntimeError as exc:
        assert "HUTCH_TOKEN" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("run_daemon should refuse unauthenticated non-loopback bind")
