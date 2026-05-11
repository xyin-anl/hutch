"""CLI smoke tests for M0."""

from __future__ import annotations

from typer.testing import CliRunner

from hutch import __version__
from hutch.cli import app

runner = CliRunner()


def test_help_runs() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "hutch" in result.stdout.lower()
    assert "serve" in result.stdout


def test_version_flag() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.stdout


def test_serve_command_listed() -> None:
    result = runner.invoke(app, ["serve", "--help"])
    assert result.exit_code == 0
    assert "--host" in result.stdout
    assert "--port" in result.stdout
    assert "--unsafe-no-auth" in result.stdout


def test_server_rejects_non_loopback_without_token(monkeypatch) -> None:
    from hutch.daemon.server import run_daemon

    monkeypatch.delenv("HUTCH_TOKEN", raising=False)
    try:
        run_daemon(host="0.0.0.0")
    except RuntimeError as exc:
        assert "HUTCH_TOKEN" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("run_daemon should refuse unauthenticated non-loopback bind")
