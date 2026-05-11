"""LLM-assisted importer for foreign autoresearch run artifacts.

Pointer-driven entry point: pass a file or directory of unknown JSONL/JSON records
to :func:`import_with_llm`. The pipeline samples a few records, asks an
LLM to write a ``to_canonical(record)`` adapter, runs it in a constrained
validation subprocess, and yields canonical Hutch events along with coverage
stats. This is defense-in-depth, not an OS/container sandbox.
"""

from __future__ import annotations

from hutch.importer.cache import CachedAdapter, fingerprint_for
from hutch.importer.detect import FormatSample, detect_structure
from hutch.importer.generate import build_user_prompt, generate_adapter
from hutch.importer.llm import (
    AnthropicJSONClient,
    LLMClient,
    OpenAIJSONClient,
    build_client,
)
from hutch.importer.pipeline import ImportResult, import_with_llm
from hutch.importer.sandbox import execute_adapter

__all__ = [
    "AnthropicJSONClient",
    "CachedAdapter",
    "FormatSample",
    "ImportResult",
    "LLMClient",
    "OpenAIJSONClient",
    "build_client",
    "build_user_prompt",
    "detect_structure",
    "execute_adapter",
    "fingerprint_for",
    "generate_adapter",
    "import_with_llm",
]
