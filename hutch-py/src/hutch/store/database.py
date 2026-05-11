"""DuckDB connection management and migration runner.

Migrations live in :mod:`hutch.store.migrations`. Each module exposes an
integer ``VERSION`` and an ``up(conn)`` function. The runner records applied
versions in the ``hutch_migrations`` table and is idempotent.
"""

from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path
from types import ModuleType
from typing import Any, Protocol, cast

import duckdb

import hutch.store.migrations as _migration_pkg


class DuckConn(Protocol):
    """Structural protocol for DuckDB connection objects.

    DuckDB's Python binding doesn't expose a public ``DuckDBPyConnection``
    class for type hints in older versions; this protocol pins the surface
    we actually use so :mod:`hutch.store.migrations` doesn't import duckdb.
    """

    def execute(self, query: str, parameters: object | None = ...) -> Any: ...
    def fetchall(self) -> list[tuple[Any, ...]]: ...
    def fetchone(self) -> tuple[Any, ...] | None: ...
    def close(self) -> None: ...


CREATE_MIGRATIONS_TABLE = """
CREATE TABLE IF NOT EXISTS hutch_migrations (
    version    INTEGER PRIMARY KEY,
    applied_ns BIGINT  NOT NULL
);
"""


def open_db(path: str | Path | None = None) -> DuckConn:
    """Open (or create) a DuckDB database file. ``None`` opens an in-memory db."""
    target = ":memory:" if path is None else str(path)
    conn = duckdb.connect(target)
    return cast(DuckConn, conn)


def _discover_migrations() -> list[tuple[int, ModuleType]]:
    """Find every migration module under :mod:`hutch.store.migrations`."""
    out: list[tuple[int, ModuleType]] = []
    pkg_path = Path(_migration_pkg.__file__).parent if _migration_pkg.__file__ else None
    if pkg_path is None:
        return out
    for info in pkgutil.iter_modules([str(pkg_path)]):
        if info.name.startswith("_"):
            continue
        module = importlib.import_module(f"hutch.store.migrations.{info.name}")
        version_attr = getattr(module, "VERSION", None)
        if not isinstance(version_attr, int):
            continue
        out.append((version_attr, module))
    out.sort(key=lambda pair: pair[0])
    return out


def applied_versions(conn: DuckConn) -> set[int]:
    """Return the set of migration versions already applied to ``conn``."""
    conn.execute(CREATE_MIGRATIONS_TABLE)
    conn.execute("SELECT version FROM hutch_migrations;")
    rows = conn.fetchall()
    return {int(r[0]) for r in rows}


def migrate(conn: DuckConn, *, target: int | None = None) -> list[int]:
    """Apply pending migrations on ``conn``. Returns the versions applied."""
    import time

    conn.execute(CREATE_MIGRATIONS_TABLE)
    seen = applied_versions(conn)
    applied: list[int] = []
    for version, module in _discover_migrations():
        if target is not None and version > target:
            break
        if version in seen:
            continue
        up_fn = getattr(module, "up", None)
        if not callable(up_fn):
            raise RuntimeError(f"migration {version} has no up() function")
        try:
            conn.execute("BEGIN TRANSACTION;")
            up_fn(conn)
            conn.execute(
                "INSERT INTO hutch_migrations (version, applied_ns) VALUES (?, ?);",
                [version, time.time_ns()],
            )
            conn.execute("COMMIT;")
        except Exception:
            conn.execute("ROLLBACK;")
            raise
        applied.append(version)
    return applied


def open_and_migrate(path: str | Path | None = None) -> DuckConn:
    """Convenience: open a db and bring it up to the latest schema."""
    conn = open_db(path)
    migrate(conn)
    return conn
