"""On-disk cache for LLM-generated adapters.

Cache key = SHA-256 of the system+user prompt that produced the adapter.
Cached payload includes the adapter code, the LLM's notes, the validation
stats, and the prompt for transparency. Default location is
``~/.hutch/adapters/``.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

DEFAULT_CACHE_DIR = Path.home() / ".hutch" / "adapters"


@dataclass(slots=True)
class CachedAdapter:
    fingerprint: str
    adapter_code: str
    notes: str
    coverage: float
    sample_size: int
    valid_events: int
    total_events: int
    created_at_ns: int
    path: str
    provider: str
    model: str


def fingerprint_for(system_prompt: str, user_prompt: str) -> str:
    h = hashlib.sha256()
    h.update(system_prompt.encode("utf-8"))
    h.update(b"\n--\n")
    h.update(user_prompt.encode("utf-8"))
    return h.hexdigest()[:16]


def cache_path(fingerprint: str, root: Path = DEFAULT_CACHE_DIR) -> Path:
    return root / f"{fingerprint}.json"


def store(adapter: CachedAdapter, root: Path = DEFAULT_CACHE_DIR) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    p = cache_path(adapter.fingerprint, root)
    p.write_text(json.dumps(asdict(adapter), indent=2))
    return p


def load(fingerprint: str, root: Path = DEFAULT_CACHE_DIR) -> CachedAdapter | None:
    p = cache_path(fingerprint, root)
    if not p.is_file():
        return None
    try:
        data: dict[str, Any] = json.loads(p.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    return CachedAdapter(**data)


def now_ns() -> int:
    return int(time.time() * 1_000_000_000)
