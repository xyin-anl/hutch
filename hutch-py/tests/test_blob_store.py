"""Tests for the content-addressable BlobStore."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from hutch.store.blob import LOCAL_URI_PREFIX, LocalBlobStore, hash_bytes, normalize_hash


def test_hash_bytes_is_sha256() -> None:
    data = b"hello hutch"
    assert hash_bytes(data) == hashlib.sha256(data).hexdigest()


def test_put_and_get_round_trip(tmp_path: Path) -> None:
    store = LocalBlobStore(tmp_path)
    h, uri = store.put(b"some genome")
    assert uri.startswith(LOCAL_URI_PREFIX)
    assert store.exists(h)
    assert store.get(h) == b"some genome"


def test_put_idempotent(tmp_path: Path) -> None:
    """Putting the same data twice is a no-op on disk and returns the same hash."""
    store = LocalBlobStore(tmp_path)
    h1, uri1 = store.put(b"data")
    h2, uri2 = store.put(b"data")
    assert h1 == h2
    assert uri1 == uri2


def test_storage_path_uses_two_level_fanout(tmp_path: Path) -> None:
    """Layout is <root>/<hash[:2]>/<hash[2:]> per §7."""
    store = LocalBlobStore(tmp_path)
    h, _ = store.put(b"a few bytes")
    expected = tmp_path / h[:2] / h[2:]
    assert expected.exists()


def test_distinct_data_distinct_hash(tmp_path: Path) -> None:
    store = LocalBlobStore(tmp_path)
    h1, _ = store.put(b"alpha")
    h2, _ = store.put(b"beta")
    assert h1 != h2


def test_get_missing_raises(tmp_path: Path) -> None:
    store = LocalBlobStore(tmp_path)
    with pytest.raises(FileNotFoundError):
        store.get("0" * 64)


def test_uri_for_uses_local_prefix(tmp_path: Path) -> None:
    store = LocalBlobStore(tmp_path)
    h, uri = store.put(b"x")
    assert uri == store.uri_for(h)
    assert uri == f"{LOCAL_URI_PREFIX}{h}"


def test_default_root_is_under_dot_hutch(tmp_path: Path) -> None:
    """When no root is supplied, default lives under ``~/.hutch/blobs``.

    We don't actually want to write there in tests, so just check the *attribute*
    when constructing a LocalBlobStore with a tmp root, then read the
    module constant.
    """
    from hutch.store.blob import DEFAULT_LOCAL_ROOT

    assert DEFAULT_LOCAL_ROOT.name == "blobs"
    assert DEFAULT_LOCAL_ROOT.parent.name == ".hutch"


def test_short_hash_rejected(tmp_path: Path) -> None:
    store = LocalBlobStore(tmp_path)
    with pytest.raises(ValueError):
        store.exists("ab")


def test_non_hex_hash_rejected(tmp_path: Path) -> None:
    store = LocalBlobStore(tmp_path)
    with pytest.raises(ValueError):
        store.get("../" + "0" * 61)
    with pytest.raises(ValueError):
        store.uri_for("z" * 64)


def test_hash_normalized_to_lowercase() -> None:
    assert normalize_hash("A" * 64) == "a" * 64
