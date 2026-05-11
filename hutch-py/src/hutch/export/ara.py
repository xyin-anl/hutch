"""Autonomous-Research-Artifact (ARA) packages.

An ``.ara`` is a self-contained gzipped tarball with the entire state of
one Hutch run::

    run.ara
    ├── manifest.json        # ARAManifest dict — version, run_id, counts
    ├── events.jsonl          # one canonical AnyEvent per line
    └── blobs/                # content-addressable blob store
        └── <hash[:2]>/<hash[2:]>

The blob bundling deduplicates by SHA-256 over content. Blob bytes are only
included when a caller supplies a resolver or explicitly opts into local file
inclusion; by default, payload URIs are left untouched.

``import_ara(path, daemon_url=…)`` is the inverse — extracts the
tarball, verifies the manifest, restores blobs to a target ``BlobStore``,
and replays events into a destination daemon (or DuckDB file).

Dep-free: stdlib ``tarfile`` + ``json`` + ``hashlib``.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import tarfile
import tempfile
from collections.abc import Callable, Iterable, Iterator
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from hutch import __version__
from hutch.schema import EVENT_ADAPTER, AnyEvent

logger = logging.getLogger("hutch.export.ara")

BlobResolver = Callable[[str], bytes | None]
"""Callable signature: given a URI, return the bytes (or ``None`` to skip)."""

ARA_FORMAT_VERSION = "1"
"""Bumped when the on-disk ARA layout changes incompatibly."""

_MANIFEST_NAME = "manifest.json"
_EVENTS_NAME = "events.jsonl"
_BLOBS_PREFIX = "blobs/"
_BLOB_URI_RE = re.compile(r"^ara://blobs/([0-9a-f]{64})$")
_BLOB_MEMBER_RE = re.compile(r"^blobs/([0-9a-f]{2})/([0-9a-f]{62})$")
DEFAULT_MAX_BLOB_BYTES = 512 * 1024 * 1024
DEFAULT_MAX_MANIFEST_BYTES = 1 * 1024 * 1024
DEFAULT_MAX_EVENTS_BYTES = 512 * 1024 * 1024
DEFAULT_MAX_MEMBERS = 100_000
DEFAULT_MAX_TOTAL_UNCOMPRESSED_BYTES = 2 * 1024 * 1024 * 1024


@dataclass(slots=True)
class ARAManifest:
    """Top-level ``manifest.json`` inside an ARA tarball."""

    ara_format_version: str
    hutch_version: str
    run_id: str
    event_count: int
    blob_count: int
    schema_version: str = "0.1.0"
    notes: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, sort_keys=True)

    @classmethod
    def from_json(cls, s: str) -> ARAManifest:
        data = json.loads(s)
        return cls(
            ara_format_version=str(data["ara_format_version"]),
            hutch_version=str(data.get("hutch_version", "")),
            run_id=str(data["run_id"]),
            event_count=int(data["event_count"]),
            blob_count=int(data["blob_count"]),
            schema_version=str(data.get("schema_version", "0.1.0")),
            notes=data.get("notes"),
            extra=dict(data.get("extra") or {}),
        )


# ---------- export ----------------------------------------------------------


def export_ara(
    *,
    run_id: str,
    events: Iterable[AnyEvent],
    output_path: Path | str,
    blob_resolver: BlobResolver | None = None,
    include_local_files: bool = False,
    blob_root: Path | str | None = None,
    notes: str | None = None,
    extra_metadata: dict[str, Any] | None = None,
) -> Path:
    """Write an ``.ara`` tarball at *output_path* and return the resolved path.

    *events*           — iterable of canonical events for this run (any order;
                         no sort enforced).
    *blob_resolver*    — optional callable that, given a blob URI, returns the
                         bytes for that blob.
    *include_local_files* — opt in to resolving local ``file://`` / path URIs.
                         Off by default so exported ARA packages cannot
                         accidentally package arbitrary files named in events.
    *blob_root*        — optional root that local file inclusion is confined to.

    Behaviour: every event is rewritten so URIs that the resolver could
    fetch are replaced with ``ara://blobs/<sha256>`` and the bytes are
    bundled into the tarball at ``blobs/<hash[:2]>/<hash[2:]>``.
    Unresolvable URIs are kept as-is — the resulting ARA still imports
    cleanly, just with dangling references.
    """
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if blob_resolver is not None:
        resolver = blob_resolver
    elif include_local_files or blob_root is not None:
        resolver = _local_file_resolver(blob_root)
    else:
        resolver = _no_blob_resolver

    # Step 1: rewrite events + collect blob bytes (deduped by hash).
    blobs: dict[str, bytes] = {}
    rewritten: list[AnyEvent] = []
    for ev in events:
        rewritten.append(_rewrite_event(ev, resolver, blobs))

    # Step 2: build manifest + write the tarball.
    manifest = ARAManifest(
        ara_format_version=ARA_FORMAT_VERSION,
        hutch_version=__version__,
        run_id=run_id,
        event_count=len(rewritten),
        blob_count=len(blobs),
        notes=notes,
        extra=dict(extra_metadata or {}),
    )

    with tarfile.open(target, mode="w:gz", format=tarfile.PAX_FORMAT) as tar:
        _add_text(tar, _MANIFEST_NAME, manifest.to_json())
        events_jsonl = "\n".join(_event_to_json(e) for e in rewritten) + "\n"
        _add_text(tar, _EVENTS_NAME, events_jsonl)
        for blob_hash, blob_bytes in sorted(blobs.items()):
            arcname = f"{_BLOBS_PREFIX}{blob_hash[:2]}/{blob_hash[2:]}"
            _add_bytes(tar, arcname, blob_bytes)
    return target


# ---------- import ----------------------------------------------------------


@dataclass(slots=True)
class ARAImportResult:
    """Returned by :func:`import_ara` — counts + the resolved manifest."""

    manifest: ARAManifest
    events_replayed: int
    blobs_restored: int
    blob_target_dir: Path | None


def import_ara(
    archive_path: Path | str,
    *,
    blob_target_dir: Path | str | None = None,
    max_blob_bytes: int = DEFAULT_MAX_BLOB_BYTES,
    max_manifest_bytes: int = DEFAULT_MAX_MANIFEST_BYTES,
    max_events_bytes: int = DEFAULT_MAX_EVENTS_BYTES,
    max_members: int = DEFAULT_MAX_MEMBERS,
    max_total_uncompressed_bytes: int = DEFAULT_MAX_TOTAL_UNCOMPRESSED_BYTES,
) -> tuple[ARAImportResult, Iterator[AnyEvent]]:
    """Extract an ``.ara`` and yield canonical events back.

    *blob_target_dir* — when provided, every bundled blob is written to
    ``<dir>/<hash[:2]>/<hash[2:]>`` and event URIs of the form
    ``ara://blobs/<hash>`` are rewritten to ``file://<absolute-path>``.
    When omitted, blobs are dropped on the floor and the URI keeps its
    ``ara://`` form (the canonical event log + UI tolerate this).

    Returns ``(result, events_iter)``. The iterator must be consumed for
    ``events_replayed`` to be accurate; the count on *result* is updated
    in-place as the iterator advances.
    """
    src = Path(archive_path)
    if not src.is_file():
        raise FileNotFoundError(f"ARA archive {src} does not exist")

    with tarfile.open(src, mode="r:gz") as tar:
        _validate_archive_limits(
            tar,
            max_members=max_members,
            max_total_uncompressed_bytes=max_total_uncompressed_bytes,
        )
        # Manifest first.
        try:
            manifest_member = tar.getmember(_MANIFEST_NAME)
        except KeyError as exc:
            raise ValueError(f"{src} is missing {_MANIFEST_NAME}; not a valid ARA package") from exc
        manifest_bytes = _extract_bytes(tar, manifest_member, max_manifest_bytes)
        manifest = ARAManifest.from_json(manifest_bytes.decode("utf-8"))
        if manifest.ara_format_version != ARA_FORMAT_VERSION:
            logger.warning(
                "ARA format version mismatch (archive=%s, importer=%s); best-effort import.",
                manifest.ara_format_version,
                ARA_FORMAT_VERSION,
            )

        # Restore blobs.
        target_dir = Path(blob_target_dir) if blob_target_dir is not None else None
        blob_path_for_hash: dict[str, Path] = {}
        if target_dir is not None:
            target_dir.mkdir(parents=True, exist_ok=True)
            target_root = target_dir.resolve()
            restored_hashes: set[str] = set()
            for member in tar.getmembers():
                if not member.name.startswith(_BLOBS_PREFIX):
                    continue
                match = _BLOB_MEMBER_RE.fullmatch(member.name)
                if match is None:
                    raise ValueError(f"invalid ARA blob member path: {member.name!r}")
                if not member.isfile() or member.issym() or member.islnk():
                    raise ValueError(f"invalid ARA blob member type: {member.name!r}")
                if member.size < 0 or member.size > max_blob_bytes:
                    raise ValueError(f"ARA blob member too large: {member.name!r}")
                blob_hash = "".join(match.groups())
                rel = Path(match.group(1)) / match.group(2)
                dest = (target_root / rel).resolve(strict=False)
                try:
                    dest.relative_to(target_root)
                except ValueError as exc:
                    message = f"ARA blob member escapes target dir: {member.name!r}"
                    raise ValueError(message) from exc
                blob_bytes = _extract_bytes(tar, member, max_blob_bytes)
                actual_hash = hashlib.sha256(blob_bytes).hexdigest()
                if actual_hash != blob_hash:
                    raise ValueError(
                        f"ARA blob hash mismatch for {member.name!r}: expected {blob_hash}, "
                        f"got {actual_hash}"
                    )
                if blob_hash in restored_hashes:
                    continue
                restored_hashes.add(blob_hash)
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(blob_bytes)
                blob_path_for_hash[blob_hash] = dest

        # Events.
        try:
            events_member = tar.getmember(_EVENTS_NAME)
        except KeyError as exc:
            raise ValueError(f"{src} is missing {_EVENTS_NAME}; not a valid ARA package") from exc
        _validate_regular_member(events_member, _EVENTS_NAME, max_events_bytes)

    result = ARAImportResult(
        manifest=manifest,
        events_replayed=0,
        blobs_restored=len(blob_path_for_hash),
        blob_target_dir=target_dir,
    )

    def _yield_events() -> Iterator[AnyEvent]:
        with tarfile.open(src, mode="r:gz") as tar:
            _validate_archive_limits(
                tar,
                max_members=max_members,
                max_total_uncompressed_bytes=max_total_uncompressed_bytes,
            )
            events_member = tar.getmember(_EVENTS_NAME)
            _validate_regular_member(events_member, _EVENTS_NAME, max_events_bytes)
            handle = tar.extractfile(events_member)
            if handle is None:
                raise RuntimeError(f"could not read {_EVENTS_NAME} from ARA archive")
            for line_no, raw_line in enumerate(handle, start=1):
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    raw = json.loads(line)
                except json.JSONDecodeError as exc:
                    logger.warning("dropping malformed event on line %d: %s", line_no, exc)
                    continue
                if blob_path_for_hash:
                    _rewrite_uris_inplace(raw, blob_path_for_hash)
                try:
                    ev = EVENT_ADAPTER.validate_python(raw)
                except Exception as exc:
                    logger.warning(
                        "dropping invalid event on line %d (%s): %s",
                        line_no,
                        raw.get("event_kind"),
                        exc,
                    )
                    continue
                result.events_replayed += 1
                yield ev

    return result, _yield_events()


# ---------- helpers --------------------------------------------------------


def _no_blob_resolver(uri: str) -> bytes | None:
    """Safe default resolver: do not read local files from event payload URIs."""
    del uri
    return None


def _local_file_resolver(blob_root: Path | str | None = None) -> BlobResolver:
    """Return a resolver for explicit local-file inclusion.

    When *blob_root* is set, only files under that resolved root are read.
    """
    root = Path(blob_root).resolve() if blob_root is not None else None

    def resolve(uri: str) -> bytes | None:
        if uri.startswith("ara://"):
            return None
        candidate: Path | None = None
        if uri.startswith("file://"):
            parsed = urlparse(uri)
            candidate = Path(unquote(parsed.path))
        elif uri.startswith(("/", "./", "../")):
            candidate = Path(uri)
        if candidate is None:
            return None
        try:
            resolved = candidate.resolve(strict=True)
            if root is not None:
                try:
                    resolved.relative_to(root)
                except ValueError:
                    logger.debug("skipping local blob outside root: %s", resolved)
                    return None
            if resolved.is_file():
                return resolved.read_bytes()
        except OSError as exc:
            logger.debug("could not read %s: %s", candidate, exc)
        return None

    return resolve


_BLOB_URI_FIELDS = ("genome_uri", "diff_uri", "snapshot_uri", "uri")


def _rewrite_event(
    event: AnyEvent,
    resolver: Any,
    blobs: dict[str, bytes],
) -> AnyEvent:
    """Return *event* with any resolvable blob URIs rewritten to
    ``ara://blobs/<sha256>`` and the bytes added to *blobs*."""
    raw = json.loads(event.model_dump_json())
    payload = raw.get("payload") or {}
    if not isinstance(payload, dict):
        return event
    for field_name in _BLOB_URI_FIELDS:
        uri = payload.get(field_name)
        if not isinstance(uri, str):
            continue
        if uri.startswith("ara://"):
            continue
        try:
            blob_bytes = resolver(uri)
        except Exception as exc:
            logger.debug("resolver raised on %s: %s", uri, exc)
            blob_bytes = None
        if blob_bytes is None:
            continue
        h = hashlib.sha256(blob_bytes).hexdigest()
        blobs[h] = blob_bytes
        payload[field_name] = f"ara://blobs/{h}"
    raw["payload"] = payload
    return EVENT_ADAPTER.validate_python(raw)


def _rewrite_uris_inplace(raw: dict[str, Any], blob_paths: dict[str, Path]) -> None:
    payload = raw.get("payload")
    if not isinstance(payload, dict):
        return
    for field_name in _BLOB_URI_FIELDS:
        uri = payload.get(field_name)
        if not isinstance(uri, str):
            continue
        m = _BLOB_URI_RE.match(uri)
        if m is None:
            continue
        h = m.group(1)
        path = blob_paths.get(h)
        if path is not None:
            payload[field_name] = path.resolve().as_uri()


def _add_text(tar: tarfile.TarFile, name: str, text: str) -> None:
    data = text.encode("utf-8")
    info = tarfile.TarInfo(name=name)
    info.size = len(data)
    info.mode = 0o644
    info.mtime = 0
    import io

    tar.addfile(info, io.BytesIO(data))


def _add_bytes(tar: tarfile.TarFile, name: str, data: bytes) -> None:
    info = tarfile.TarInfo(name=name)
    info.size = len(data)
    info.mode = 0o644
    info.mtime = 0
    import io

    tar.addfile(info, io.BytesIO(data))


def _validate_archive_limits(
    tar: tarfile.TarFile,
    *,
    max_members: int,
    max_total_uncompressed_bytes: int,
) -> None:
    members = tar.getmembers()
    if len(members) > max_members:
        raise ValueError(f"ARA archive has too many members: {len(members)} > {max_members}")
    total = 0
    for member in members:
        if member.size < 0:
            raise ValueError(f"ARA member has negative size: {member.name!r}")
        if member.isfile():
            total += member.size
            if total > max_total_uncompressed_bytes:
                raise ValueError(
                    f"ARA archive uncompressed payload exceeds {max_total_uncompressed_bytes} bytes"
                )


def _validate_regular_member(
    member: tarfile.TarInfo,
    expected_name: str,
    max_bytes: int,
) -> None:
    if member.name != expected_name:
        raise ValueError(f"unexpected ARA member name: {member.name!r}")
    if not member.isfile() or member.issym() or member.islnk():
        raise ValueError(f"invalid ARA member type: {member.name!r}")
    if member.size < 0 or member.size > max_bytes:
        raise ValueError(f"ARA member {member.name!r} exceeds {max_bytes} bytes")


def _extract_bytes(tar: tarfile.TarFile, member: tarfile.TarInfo, max_bytes: int) -> bytes:
    _validate_regular_member(member, member.name, max_bytes)
    handle = tar.extractfile(member)
    if handle is None:
        raise RuntimeError(f"could not read {member.name} from ARA archive")
    data = handle.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError(f"ARA member {member.name!r} exceeds {max_bytes} bytes")
    return data


def _event_to_json(event: AnyEvent) -> str:
    return event.model_dump_json()


# Make the temp-dir helper importable; useful for tests that want a
# scratch blob_target_dir without committing one.
def make_temp_blob_dir() -> Path:
    return Path(tempfile.mkdtemp(prefix="hutch-ara-blobs-"))
