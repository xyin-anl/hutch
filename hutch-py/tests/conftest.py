"""Shared pytest fixtures for the Hutch test suite."""

from __future__ import annotations

import os
import socket
from collections.abc import Iterator
from pathlib import Path

import pytest

from hutch.sdk import _state


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-llm",
        action="store_true",
        default=False,
        help="run live LLM importer tests that may call provider APIs",
    )


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "live_llm: tests that require explicit opt-in and live provider credentials",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if config.getoption("--run-llm"):
        return
    skip_live_llm = pytest.mark.skip(reason="need --run-llm to run live LLM importer tests")
    for item in items:
        if "live_llm" in item.keywords:
            item.add_marker(skip_live_llm)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture
def free_port() -> int:
    """Allocate an OS-assigned free TCP port for the daemon."""
    return _free_port()


@pytest.fixture(autouse=True)
def _isolate_sdk_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Reset SDK state between tests and pin fallback / db paths into tmp_path.

    Without this, a daemon-mode test that touched ``~/.hutch/...`` could leak
    state into a later embedded-mode test and vice versa. This fixture
    auto-applies; opt out by calling ``hutch.configure(...)`` explicitly.
    """
    fallback_path = tmp_path / "fallback.jsonl"
    db_path = tmp_path / "hutch.duckdb"
    monkeypatch.setenv("HUTCH_FALLBACK_PATH", str(fallback_path))
    # Default each test to embedded mode in tmp_path; tests that want daemon
    # mode override via os.environ inside the test body.
    monkeypatch.delenv("HUTCH_DAEMON_URL", raising=False)
    monkeypatch.setenv("HUTCH_DB_PATH", str(db_path))
    monkeypatch.delenv("HUTCH_STRICT", raising=False)
    _state.reset()
    yield
    _state.reset()
    # Belt-and-suspenders: scrub any spillover env that might affect later
    # files outside this fixture's scope.
    for key in ("HUTCH_DAEMON_URL", "HUTCH_DB_PATH", "HUTCH_FALLBACK_PATH", "HUTCH_STRICT"):
        os.environ.pop(key, None)
