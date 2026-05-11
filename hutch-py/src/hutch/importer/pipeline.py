"""Orchestrate the LLM-assisted import pipeline.

Stages:

1. **Detect** — sample records, files, and metadata.
2. **Plan + Generate** — call the LLM to produce ``to_canonical(record)``.
3. **Validate** — run the adapter in a constrained subprocess on the
   held-out sample, parse every emitted event through
   :data:`hutch.schema.EVENT_ADAPTER`, compute coverage stats.
4. **Cache** — store the adapter + stats keyed by prompt fingerprint.
5. **Run** — stream the full corpus through the cached adapter and yield
   :class:`AnyEvent` instances for the caller (typically the SDK's
   transport).
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Best-effort load of a sibling `.env` so `hutch import --llm` picks up the
# user's API key from a local file. python-dotenv lives in the optional
# [skill-eval] extra; if missing we fall back to the process environment.
try:
    from dotenv import load_dotenv

    for _candidate in (
        Path.cwd() / ".env",
        Path(__file__).resolve().parents[4] / ".env",
    ):
        if _candidate.is_file():
            load_dotenv(_candidate, override=False)
            break
except ImportError:
    pass

from hutch.importer.cache import (
    DEFAULT_CACHE_DIR,
    CachedAdapter,
    fingerprint_for,
    now_ns,
)
from hutch.importer.cache import (
    load as load_cached,
)
from hutch.importer.cache import (
    store as store_cached,
)
from hutch.importer.detect import MAX_RECORD_FILE_BYTES, FormatSample, detect_structure
from hutch.importer.generate import SYSTEM_PROMPT, build_user_prompt, generate_adapter
from hutch.importer.llm import LLMClient, build_client
from hutch.importer.sandbox import execute_adapter
from hutch.schema import EVENT_ADAPTER, AnyEvent

logger = logging.getLogger("hutch.importer.pipeline")


@dataclass(slots=True)
class ImportResult:
    """Summary returned by :func:`import_with_llm` to the CLI."""

    sample: FormatSample
    adapter: CachedAdapter
    cache_hit: bool
    notes: str
    sample_valid: int
    sample_total: int
    full_valid: int
    full_total: int
    full_records_seen: int
    full_records_truncated: bool = False
    runtime_errors: list[str] = field(default_factory=list)

    @property
    def sample_coverage(self) -> float:
        return self.sample_valid / self.sample_total if self.sample_total else 0.0

    @property
    def full_coverage(self) -> float:
        return self.full_valid / self.full_total if self.full_total else 0.0


def import_with_llm(
    path: str | Path,
    *,
    client: LLMClient | None = None,
    cache_dir: Path = DEFAULT_CACHE_DIR,
    use_cache: bool = True,
    progress: bool = False,
) -> tuple[ImportResult, Iterator[AnyEvent]]:
    """Run the LLM-assisted importer end-to-end.

    Returns ``(result, events)``. ``events`` is a lazy iterator over every
    canonical event the adapter produced for the full corpus; consume it
    to send events to the daemon / write embedded.
    """
    root = Path(path)
    sample = detect_structure(root)
    if not sample.sample_records:
        raise ValueError(
            f"{root} contains no JSON-shaped records the importer could sample. "
            "Either add a hand-written adapter or convert the data to JSON/JSONL first."
        )

    user_prompt = build_user_prompt(sample)
    fingerprint = fingerprint_for(SYSTEM_PROMPT, user_prompt)
    cached = load_cached(fingerprint, cache_dir) if use_cache else None
    cache_hit = cached is not None
    if cache_hit and cached is not None:
        logger.info("using cached adapter %s", fingerprint)
        adapter_code = cached.adapter_code
        notes = cached.notes
    else:
        active_client = client or build_client()
        logger.info("calling %s/%s for adapter generation", active_client.name, active_client.model)
        adapter_code, notes = generate_adapter(active_client, sample)

    # Validate on the sample.
    sample_valid, sample_total, sample_errors = _validate_records(
        adapter_code, sample.sample_records
    )

    if not cache_hit:
        active_client = client or build_client()
        adapter_record = CachedAdapter(
            fingerprint=fingerprint,
            adapter_code=adapter_code,
            notes=notes,
            coverage=(sample_valid / sample_total) if sample_total else 0.0,
            sample_size=sample_total,
            valid_events=sample_valid,
            total_events=sample_total,
            created_at_ns=now_ns(),
            path=str(root.resolve()),
            provider=active_client.name,
            model=active_client.model,
        )
        store_cached(adapter_record, cache_dir)
        result_adapter = adapter_record
    else:
        assert cached is not None
        result_adapter = cached

    # Build the full record stream (sample + the rest, capped only by what
    # detect can reach).
    full_records, full_records_seen, full_records_truncated = _collect_all_records(root)
    full_valid, full_total, full_errors = _validate_records(adapter_code, full_records)

    result = ImportResult(
        sample=sample,
        adapter=result_adapter,
        cache_hit=cache_hit,
        notes=notes,
        sample_valid=sample_valid,
        sample_total=sample_total,
        full_valid=full_valid,
        full_total=full_total,
        full_records_seen=full_records_seen,
        full_records_truncated=full_records_truncated,
        runtime_errors=(sample_errors + full_errors)[:20],
    )
    del progress

    def emit() -> Iterator[AnyEvent]:
        # Re-execute the adapter on the full corpus and yield validated events.
        if not full_records:
            return
        # Run in chunks to keep the subprocess timeout reasonable.
        chunk = 256
        for start in range(0, len(full_records), chunk):
            payload = execute_adapter(adapter_code, full_records[start : start + chunk])
            for record_events in payload.get("results", []):
                if isinstance(record_events, dict):
                    # That's the runtime-error sentinel; skip.
                    continue
                for raw in record_events:
                    try:
                        yield EVENT_ADAPTER.validate_python(raw)
                    except Exception as exc:
                        logger.debug("dropping invalid event: %s", exc)

    return result, emit()


# ---------- helpers --------------------------------------------------------


def _validate_records(
    adapter_code: str, records: list[dict[str, Any]]
) -> tuple[int, int, list[str]]:
    """Return (valid_event_count, total_event_count, error_strings)."""
    if not records:
        return 0, 0, []
    payload = execute_adapter(adapter_code, records)
    if payload.get("error"):
        return 0, 0, [str(payload["error"])]
    valid = 0
    total = 0
    errors: list[str] = []
    for record_events in payload.get("results", []):
        if isinstance(record_events, dict):
            err = record_events.get("_error")
            if err:
                errors.append(str(err))
            continue
        for raw in record_events:
            total += 1
            try:
                EVENT_ADAPTER.validate_python(raw)
                valid += 1
            except Exception as exc:
                errors.append(f"validation: {exc}")
    return valid, total, errors


def _collect_all_records(root: Path) -> tuple[list[dict[str, Any]], int, bool]:
    """Stream-read every JSON/JSONL record in *root* (cap-bounded)."""
    out: list[dict[str, Any]] = []
    cap = 5_000
    files = [root] if root.is_file() else sorted(root.rglob("*"))
    for f in files:
        # Skip symlinks for the same reason `detect._list_files` does — a
        # malicious checkpoint could symlink to a host-side JSON-shaped secret.
        if f.is_symlink():
            continue
        if not f.is_file():
            continue
        suffix = f.suffix.lower()
        if suffix == ".json" and f.name in {"metadata.json", "config.json"}:
            continue
        if suffix not in (".json", ".jsonl", ".ndjson"):
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
                        if not line:
                            continue
                        try:
                            rec = __import__("json").loads(line)
                        except Exception as exc:
                            logger.debug("skipping malformed line in %s: %s", f, exc)
                            continue
                        if isinstance(rec, dict):
                            out.append(rec)
                            if len(out) >= cap:
                                return out, len(out), True
            except OSError:
                continue
        else:
            if size > MAX_RECORD_FILE_BYTES:
                continue
            try:
                text = f.read_text(encoding="utf-8")
                rec = __import__("json").loads(text)
            except Exception as exc:
                logger.debug("skipping malformed file %s: %s", f, exc)
                continue
            if isinstance(rec, dict):
                out.append(rec)
            elif isinstance(rec, list):
                for item in rec:
                    if isinstance(item, dict):
                        out.append(item)
                        if len(out) >= cap:
                            return out, len(out), True
            if len(out) >= cap:
                return out, len(out), True
    return out, len(out), False
