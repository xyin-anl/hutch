"""CLI smoke tests for M0."""

from __future__ import annotations

import re

from typer.testing import CliRunner

from hutch import __version__
from hutch.cli import app

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


def test_server_rejects_non_loopback_without_token(monkeypatch) -> None:
    from hutch.daemon.server import run_daemon

    monkeypatch.delenv("HUTCH_TOKEN", raising=False)
    try:
        run_daemon(host="0.0.0.0")
    except RuntimeError as exc:
        assert "HUTCH_TOKEN" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("run_daemon should refuse unauthenticated non-loopback bind")
