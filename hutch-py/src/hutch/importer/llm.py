"""Pluggable LLM client for the importer.

Two providers today:

* ``openai`` — uses ``OPENAI_API_KEY`` (default).
* ``anthropic`` — uses ``ANTHROPIC_API_KEY``.

Both are loaded lazily so the rest of the importer stays import-safe when
neither SDK is installed. Pick a provider via ``HUTCH_LLM_PROVIDER`` and a
model via ``HUTCH_LLM_MODEL``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Protocol


class LLMClient(Protocol):
    name: str
    model: str

    def generate_json(self, system: str, user: str) -> dict[str, Any]:
        """Return a parsed JSON object from the model."""


@dataclass(slots=True)
class OpenAIJSONClient:
    name: str = "openai"
    model: str = "gpt-4o"

    def generate_json(self, system: str, user: str) -> dict[str, Any]:
        # Imported lazily so the rest of the importer is usable without
        # the optional ``[skill-eval]`` extra installed.
        import json

        from openai import OpenAI

        client = OpenAI()
        response = client.chat.completions.create(
            model=self.model,
            response_format={"type": "json_object"},
            temperature=0.1,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        content = response.choices[0].message.content or "{}"
        parsed = json.loads(content)
        if not isinstance(parsed, dict):
            raise ValueError(f"OpenAI returned non-object JSON: {content[:120]!r}")
        return parsed


@dataclass(slots=True)
class AnthropicJSONClient:
    name: str = "anthropic"
    model: str = "claude-sonnet-4-6"

    def generate_json(self, system: str, user: str) -> dict[str, Any]:
        import json
        import re

        from anthropic import Anthropic  # type: ignore[import-not-found,unused-ignore]

        client = Anthropic()
        response = client.messages.create(
            model=self.model,
            max_tokens=4096,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        text_parts: list[str] = []
        for block in response.content:
            if getattr(block, "type", None) == "text":
                text_parts.append(getattr(block, "text", ""))
        full_text = "\n".join(text_parts)
        match = re.search(r"\{.*\}", full_text, re.DOTALL)
        parsed = json.loads(match.group(0) if match else full_text)
        if not isinstance(parsed, dict):
            raise ValueError(f"Anthropic returned non-object JSON: {full_text[:120]!r}")
        return parsed


def build_client(provider: str | None = None, model: str | None = None) -> LLMClient:
    p = (provider or os.environ.get("HUTCH_LLM_PROVIDER") or "openai").lower()
    m = model or os.environ.get("HUTCH_LLM_MODEL")
    if p == "openai":
        return OpenAIJSONClient(model=m or "gpt-4o")
    if p == "anthropic":
        return AnthropicJSONClient(model=m or "claude-sonnet-4-6")
    raise ValueError(f"unknown HUTCH_LLM_PROVIDER {p!r} (expected openai or anthropic)")
