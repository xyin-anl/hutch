"""Detect the structure of an unknown foreign-format directory.

The detector samples a handful of records from each suspected format, plus
any README/config/metadata files, so the LLM has enough context to write a
``to_canonical`` adapter without us having to understand the format
ourselves.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

MAX_FILES = 200
MAX_SAMPLE_RECORDS = 12
MAX_README_BYTES = 8_000
MAX_RECORD_FILE_BYTES = 2 * 1024 * 1024
SUPPORTED_RECORD_SUFFIXES = (".json", ".jsonl", ".ndjson")


@dataclass(slots=True)
class FormatSample:
    """What the importer hands the LLM."""

    root: Path
    summary: str
    file_listing: list[str] = field(default_factory=list)
    readme: str | None = None
    metadata: dict[str, Any] | None = None
    sample_records: list[dict[str, Any]] = field(default_factory=list)
    sample_record_paths: list[str] = field(default_factory=list)


def detect_structure(path: Path) -> FormatSample:
    """Inspect *path* and return what we'd show the LLM."""
    if path.is_file():
        root = path.parent
        files = [path]
        readme = None
        metadata = None
        top_level_entries = 1
    elif path.is_dir():
        root = path
        files = _list_files(path)
        readme = _read_readme(path)
        metadata = _read_known_metadata(path)
        top_level_entries = len(list(path.iterdir()))
    else:
        raise ValueError(f"{path} is not a file or directory")
    samples, sample_paths = _sample_records(files)

    summary_lines = [
        f"Path: {path}",
        f"Top-level entries: {top_level_entries}",
        f"Total files (recursive, capped at {MAX_FILES}): {len(files)}",
    ]
    suffix_counts: dict[str, int] = {}
    for f in files:
        suffix_counts[f.suffix] = suffix_counts.get(f.suffix, 0) + 1
    summary_lines.append(
        "File-suffix histogram: "
        + ", ".join(f"{s or '(none)'}={n}" for s, n in sorted(suffix_counts.items()))
    )
    if readme is not None:
        summary_lines.append(f"README found ({len(readme)} chars).")
    if metadata is not None:
        summary_lines.append(f"metadata.json found ({len(metadata)} top-level keys).")

    return FormatSample(
        root=path,
        summary="\n".join(summary_lines),
        file_listing=[str(f.relative_to(root)) for f in files[:MAX_FILES]],
        readme=readme,
        metadata=metadata,
        sample_records=samples,
        sample_record_paths=sample_paths,
    )


def _list_files(root: Path) -> list[Path]:
    out: list[Path] = []
    for f in root.rglob("*"):
        # Skip symlinks: a malicious checkpoint could symlink to a JSON-shaped
        # secret file (e.g. an SSH config or a sibling `.env.json`) and we'd
        # otherwise read it and ship its contents to the LLM.
        if f.is_symlink():
            continue
        if f.is_file():
            out.append(f)
            if len(out) >= MAX_FILES:
                break
    return out


def _read_readme(root: Path) -> str | None:
    for name in ("README.md", "README.rst", "README.txt", "README"):
        p = root / name
        if p.is_file():
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            return text[:MAX_README_BYTES]
    return None


def _read_known_metadata(root: Path) -> dict[str, Any] | None:
    for name in ("metadata.json", "config.json"):
        p = root / name
        if p.is_file():
            try:
                parsed = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(parsed, dict):
                return parsed
    return None


def _sample_records(files: list[Path]) -> tuple[list[dict[str, Any]], list[str]]:
    """Pull up to MAX_SAMPLE_RECORDS from the JSON-shaped files we find."""
    samples: list[dict[str, Any]] = []
    sample_paths: list[str] = []
    for f in files:
        if len(samples) >= MAX_SAMPLE_RECORDS:
            break
        suffix = f.suffix.lower()
        if suffix not in SUPPORTED_RECORD_SUFFIXES:
            continue
        # Skip obvious "metadata" files; we surface those separately.
        if f.name in {"metadata.json", "config.json"}:
            continue
        try:
            size = f.stat().st_size
        except OSError:
            continue
        if suffix in (".jsonl", ".ndjson"):
            try:
                with f.open("r", encoding="utf-8", errors="replace") as fh:
                    bytes_seen = 0
                    for line in fh:
                        bytes_seen += len(line.encode("utf-8", errors="ignore"))
                        if bytes_seen > MAX_RECORD_FILE_BYTES:
                            break
                        line = line.strip()
                        if not line or len(samples) >= MAX_SAMPLE_RECORDS:
                            continue
                        try:
                            rec = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if isinstance(rec, dict):
                            samples.append(rec)
                            sample_paths.append(str(f.name))
            except OSError:
                continue
        else:
            if size > MAX_RECORD_FILE_BYTES:
                continue
            try:
                text = f.read_text(encoding="utf-8")
                rec = json.loads(text)
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(rec, dict):
                samples.append(rec)
                sample_paths.append(str(f.name))
            elif isinstance(rec, list):
                for item in rec[: MAX_SAMPLE_RECORDS - len(samples)]:
                    if isinstance(item, dict):
                        samples.append(item)
                        sample_paths.append(str(f.name))
    return samples, sample_paths
