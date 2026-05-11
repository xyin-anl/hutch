"""Content-addressable blob storage.

Hutch separates **events** (small, structured, indexed in DuckDB) from
**blobs** (genomes, diffs, papers, datasets — large, opaque,
content-addressed). Events store URIs; this module owns the URI scheme
and the on-disk layout.

For v0.1.0 the only backend is :class:`LocalBlobStore` (writes to
``~/.hutch/blobs/`` by default, content-addressable). Remote-storage
backends (S3 / GCS) are deferred; until then the recommended path for
per-machine portability is ``hutch export ara`` (see ``hutch.export.ara``),
which bundles every referenced blob into a self-contained tarball.
"""

from __future__ import annotations

import hashlib
import os
import re
from abc import ABC, abstractmethod
from pathlib import Path
from uuid import uuid4

DEFAULT_LOCAL_ROOT = Path.home() / ".hutch" / "blobs"
"""Default root for the local blob store."""

LOCAL_URI_PREFIX = "hutch+local://"
"""URI scheme for the local blob store. ``hutch+local://<hash>`` resolves to
``<root>/<hash[:2]>/<hash[2:]>`` on disk."""

_HASH_RE = re.compile(r"^[0-9a-fA-F]{64}$")


def hash_bytes(data: bytes) -> str:
    """Return the content-address hash for a blob (hex SHA-256)."""
    return hashlib.sha256(data).hexdigest()


def normalize_hash(hash_: str) -> str:
    """Validate and normalize a SHA-256 hex content hash."""
    if not _HASH_RE.fullmatch(hash_):
        raise ValueError(f"invalid blob hash: {hash_!r}")
    return hash_.lower()


class BlobStore(ABC):
    """Abstract content-addressable blob store."""

    @abstractmethod
    def put(self, data: bytes) -> tuple[str, str]:
        """Store *data*. Return ``(hash, uri)``. Idempotent on hash."""

    @abstractmethod
    def get(self, hash_: str) -> bytes:
        """Fetch by hash. Raise :class:`FileNotFoundError` if missing."""

    @abstractmethod
    def exists(self, hash_: str) -> bool:
        """Cheap existence check."""

    @abstractmethod
    def uri_for(self, hash_: str) -> str:
        """Return the URI a freshly-stored blob with this hash would have."""


class LocalBlobStore(BlobStore):
    """Filesystem-backed blob store, default at ``~/.hutch/blobs``.

    Layout: ``<root>/<hash[:2]>/<hash[2:]>``. The two-level fan-out keeps any
    one directory under ~16 K entries even for millions of blobs.
    """

    def __init__(self, root: Path | str | None = None) -> None:
        self._root = Path(root) if root is not None else DEFAULT_LOCAL_ROOT
        self._root.mkdir(parents=True, exist_ok=True)

    @property
    def root(self) -> Path:
        return self._root

    def _path(self, hash_: str) -> Path:
        normalized = normalize_hash(hash_)
        root = self._root.resolve()
        path = (root / normalized[:2] / normalized[2:]).resolve(strict=False)
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise ValueError(f"blob path escapes root: {hash_!r}") from exc
        return path

    def uri_for(self, hash_: str) -> str:
        return f"{LOCAL_URI_PREFIX}{normalize_hash(hash_)}"

    def put(self, data: bytes) -> tuple[str, str]:
        h = hash_bytes(data)
        path = self._path(h)
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
            tmp.write_bytes(data)
            os.replace(tmp, path)
        return h, self.uri_for(h)

    def get(self, hash_: str) -> bytes:
        path = self._path(hash_)
        if not path.exists():
            raise FileNotFoundError(f"blob {hash_} not in {self._root}")
        return path.read_bytes()

    def exists(self, hash_: str) -> bool:
        return self._path(hash_).exists()
