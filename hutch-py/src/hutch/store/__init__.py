"""DuckDB-backed event store and blob storage abstraction."""

from __future__ import annotations

from hutch.store.blob import (
    DEFAULT_LOCAL_ROOT,
    LOCAL_URI_PREFIX,
    BlobStore,
    LocalBlobStore,
    hash_bytes,
)
from hutch.store.database import (
    DuckConn,
    applied_versions,
    migrate,
    open_and_migrate,
    open_db,
)
from hutch.store.events_io import insert_event, insert_events, read_events

__all__ = [
    "DEFAULT_LOCAL_ROOT",
    "LOCAL_URI_PREFIX",
    "BlobStore",
    "DuckConn",
    "LocalBlobStore",
    "applied_versions",
    "hash_bytes",
    "insert_event",
    "insert_events",
    "migrate",
    "open_and_migrate",
    "open_db",
    "read_events",
]
