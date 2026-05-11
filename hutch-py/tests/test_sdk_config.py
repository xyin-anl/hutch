"""Tests for SDKConfig env resolution."""

from __future__ import annotations

import pytest

from hutch.sdk.config import (
    DEFAULT_DAEMON_URL,
    DEFAULT_DB_PATH,
    SDKConfig,
)


def test_default_mode_is_daemon() -> None:
    cfg = SDKConfig.from_env({})
    assert cfg.mode == "daemon"
    assert cfg.daemon_url == DEFAULT_DAEMON_URL
    assert cfg.db_path == DEFAULT_DB_PATH
    assert cfg.strict is False


def test_daemon_url_env_var() -> None:
    cfg = SDKConfig.from_env({"HUTCH_DAEMON_URL": "http://daemon:9000"})
    assert cfg.mode == "daemon"
    assert cfg.daemon_url == "http://daemon:9000"


def test_db_path_env_switches_to_embedded(tmp_path: pytest.TempPathFactory) -> None:
    db = "/tmp/hutch.duckdb"
    cfg = SDKConfig.from_env({"HUTCH_DB_PATH": db})
    assert cfg.mode == "embedded"
    assert str(cfg.db_path) == db


def test_daemon_url_takes_precedence_over_db_path() -> None:
    """If both env vars are set, daemon mode wins (the daemon writes to its own DB)."""
    cfg = SDKConfig.from_env({"HUTCH_DAEMON_URL": "http://x", "HUTCH_DB_PATH": "/tmp/y.duckdb"})
    assert cfg.mode == "daemon"
    assert cfg.daemon_url == "http://x"


def test_strict_mode_env_truthy() -> None:
    for truthy in ("1", "true", "yes"):
        cfg = SDKConfig.from_env({"HUTCH_STRICT": truthy})
        assert cfg.strict is True, truthy


def test_strict_mode_env_falsy() -> None:
    for falsy in ("0", "false", "no", ""):
        cfg = SDKConfig.from_env({"HUTCH_STRICT": falsy})
        assert cfg.strict is False, falsy


def test_timeout_env_var() -> None:
    cfg = SDKConfig.from_env({"HUTCH_TIMEOUT_S": "12.5"})
    assert cfg.request_timeout_s == 12.5


def test_timeout_env_var_must_be_positive() -> None:
    with pytest.raises(ValueError, match="HUTCH_TIMEOUT_S"):
        SDKConfig.from_env({"HUTCH_TIMEOUT_S": "0"})


def test_fallback_path_env_var() -> None:
    cfg = SDKConfig.from_env({"HUTCH_FALLBACK_PATH": "/tmp/fb.jsonl"})
    assert str(cfg.fallback_path) == "/tmp/fb.jsonl"


def test_auth_token_env_var() -> None:
    cfg = SDKConfig.from_env({"HUTCH_TOKEN": "secret"})
    assert cfg.auth_token == "secret"
