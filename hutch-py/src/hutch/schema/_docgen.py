"""Generate ``docs/schema.md`` from the Pydantic event/payload models.

Run as ``python -m hutch.schema._docgen`` to regenerate. The output is
deterministic given a fixed schema, so CI can diff against the committed
copy to catch missed regenerations.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from pydantic.fields import FieldInfo

from hutch.schema.events import EVENT_CLASSES
from hutch.schema.payloads import _PayloadBase
from hutch.schema.types import (
    ArtifactKind,
    DescriptorArchiveKind,
    EvaluatorKind,
    EvidenceStance,
    IndividualKind,
    OperatorKind,
    PopulationKind,
    RunStatus,
    SelfModVerdict,
    SteeringActor,
    SteeringCommandKind,
)

_LITERAL_TABLES: tuple[tuple[str, Any], ...] = (
    ("IndividualKind", IndividualKind),
    ("OperatorKind", OperatorKind),
    ("PopulationKind", PopulationKind),
    ("EvaluatorKind", EvaluatorKind),
    ("ArtifactKind", ArtifactKind),
    ("DescriptorArchiveKind", DescriptorArchiveKind),
    ("EvidenceStance", EvidenceStance),
    ("SelfModVerdict", SelfModVerdict),
    ("SteeringActor", SteeringActor),
    ("SteeringCommandKind", SteeringCommandKind),
    ("RunStatus", RunStatus),
)


def _literal_values(literal_type: Any) -> tuple[str, ...]:
    """Extract the string values from a ``Literal[...]`` type."""
    args = getattr(literal_type, "__args__", ())
    return tuple(str(a) for a in args)


def _format_type(annotation: Any) -> str:
    """Pretty-print a field's annotation for the docs."""
    if isinstance(annotation, type):
        return annotation.__name__
    text = str(annotation)
    text = text.replace("typing.", "").replace("hutch.schema.types.", "")
    text = text.replace("hutch.schema.payloads.", "")
    text = text.replace("NoneType", "None")
    return text


def _format_field(name: str, info: FieldInfo) -> tuple[str, str, str, str]:
    is_required = info.is_required()
    type_str = _format_type(info.annotation)
    default = "—" if is_required else repr(info.get_default(call_default_factory=True))
    description = (info.description or "").replace("\n", " ").strip()
    required = "yes" if is_required else "no"
    return name, type_str, required, description or default


def render_markdown() -> str:
    """Render the canonical schema as Markdown."""
    lines: list[str] = [
        "# Canonical event schema",
        "",
        "> **Auto-generated from `hutch-py/src/hutch/schema/`.**",
        "> To regenerate, run `python -m hutch.schema._docgen` from `hutch-py/`.",
        "",
        "This page is the field-level reference for every event a Hutch run",
        "can produce. For the higher-level meaning of each field, see",
        "[Concepts](concepts.md).",
        "",
        "From v0.1.0 onward, the schema is **additive-only** between minor",
        "releases. New optional fields and new `kind` enum values are fine.",
        "Renaming or removing an existing field is a breaking change and",
        "requires a migration in `hutch-py/src/hutch/store/migrations/`.",
        "",
        "## Schema invariants",
        "",
        "- Every Individual has at least one `parent_id`, or `is_seed=True`.",
        "- A Fitness event with a non-null `invalid_reason` may have empty",
        "  `scores`. Otherwise `scores` must be non-empty.",
        "- A Pareto-front snapshot must list at least one id.",
        "- If both are supplied, a Descriptor's `coordinates` length must",
        "  match the length of its `dimensions`.",
        "- Archive coverage is in `[0, 1]`.",
        "- `parent_ids` may have any length: 0 for a seed, 1 for a refine or",
        "  mutation, 2 for a crossover, more for an ensemble or distillation.",
        "",
        "## Literal kind enums",
        "",
    ]
    for name, lit in _LITERAL_TABLES:
        values = _literal_values(lit)
        lines.append(f"### `{name}`")
        lines.append("")
        lines.append(", ".join(f"`{v}`" for v in values))
        lines.append("")

    lines += [
        "## Event variants",
        "",
        "Every event has a fixed envelope plus a typed payload. The envelope:",
        "",
        "| field | type | required | description |",
        "|---|---|---|---|",
        "| `event_id` | `UUID` | auto | Unique event identifier (default: random UUIDv4). |",
        "| `event_kind` | `EventKind` | yes | Discriminator: selects the payload type. |",
        "| `run_id` | `str` | yes | Owning run. |",
        "| `timestamp_ns` | `int` | auto | UNIX time in nanoseconds (default: now). |",
        "| `stream_id` | `str?` | no | Swimlane / worker label. |",
        "| `worker_id` | `str?` | no | Concrete worker / process / agent. |",
        "| `span_id` | `str?` | no | OTel span id, if also emitted to OTel. |",
        "| `trace_id` | `str?` | no | OTel trace id, if also emitted to OTel. |",
        "",
    ]

    for event_cls in EVENT_CLASSES:
        kind = event_cls.model_fields["event_kind"].default
        payload_field = event_cls.model_fields["payload"]
        payload_type = payload_field.annotation
        if payload_type is None or not isinstance(payload_type, type):
            continue
        if not issubclass(payload_type, _PayloadBase):
            continue
        lines.append(f'### `event_kind = "{kind}"` (`{event_cls.__name__}`)')
        lines.append("")
        if event_cls.__doc__:
            lines.append(event_cls.__doc__.strip().splitlines()[0])
            lines.append("")
        lines.append(f"**Payload:** `{payload_type.__name__}`")
        lines.append("")
        lines.append("| field | type | required | description |")
        lines.append("|---|---|---|---|")
        for f_name, f_info in payload_type.model_fields.items():
            name, type_str, required, description = _format_field(f_name, f_info)
            lines.append(f"| `{name}` | `{type_str}` | {required} | {description} |")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    target = Path(__file__).resolve().parents[3].parent / "docs" / "schema.md"
    target.write_text(render_markdown(), encoding="utf-8")
    sys.stdout.write(f"wrote {target}\n")


if __name__ == "__main__":
    main()
