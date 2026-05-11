# OpenLineage emitter

The OpenLineage emitter is **optional** and off by default. It is also
dep-free: the SDK speaks OpenLineage 2.0 JSON over HTTP directly, with
no `openlineage-python` package required.

When you set `HUTCH_OPENLINEAGE_ENDPOINT` (or pass
`openlineage_endpoint=…` to `hutch.configure`), Hutch posts a
`RunEvent` to `<endpoint>/api/v1/lineage` for every lineage-relevant
event. The regular daemon or embedded transport continues unchanged.
Pair the emitter with a backend like Marquez, OpenMetadata, DataHub, or
Astro Cloud Lineage to see the lineage in your existing data-engineering
stack.

## Install and enable

OpenLineage support is built into the base `thehutch` package. Configure
it via environment variable:

```bash
export HUTCH_OPENLINEAGE_ENDPOINT=http://localhost:5000
export HUTCH_OPENLINEAGE_NAMESPACE=hutch       # optional, default "hutch"
```

…or programmatically:

```python
import hutch as h
from hutch.sdk import SDKConfig

h.configure(SDKConfig(
    mode="daemon",                                 # or "embedded"
    openlineage_endpoint="http://localhost:5000",
    openlineage_namespace="my-org",
))
```

The well-known suffix `/api/v1/lineage` is appended automatically when
the URL doesn't already end with it. Pass the literal `"in-memory"` to
wire up an in-memory mode for tests; the emitter then records what it
would have POSTed in `emitter.captured_events` instead of hitting the
network.

## Mapping

One Hutch run is one OpenLineage **Job**. The job's namespace is the
configured namespace (default `hutch`), and its name is the run's
`name`, falling back to `run_id`. Each Hutch `run_id` is one OpenLineage
**Run** (`runId` = `run_id`).

The emitter translates only a subset of Hutch event kinds into OL
`RunEvent`s, picking the ones that carry real lineage edges. That keeps
the OL backend showing clean parent-to-child causation rather than a
flood of point events.

| Hutch event_kind | OL eventType | inputs | outputs | Custom facet |
|---|---|---|---|---|
| `run_start` | `START` | (none) | (none) | `hutchRun` (project, started_by) |
| `run_end` | `COMPLETE` or `FAIL` | (none) | (none) | `hutchRunOutcome` (status, summary) |
| `operator` | `RUNNING` | parent Datasets `individual:<id>` | child Dataset `individual:<id>` | `hutchOperator` (kind, cost_usd, tokens_in/out, llm_id) |
| `self_mod` | `RUNNING` | parent agent Dataset `agent:<id>` | child agent Dataset `agent:<id>` | `hutchSelfMod` (overseer_verdict, score_before/after, target_path) |

Other event kinds (`individual`, `fitness`, `descriptor`, `claim`,
`evidence`, `tree_expansion`, `archive_snapshot`, `pareto_snapshot`,
`steering_command`, etc.) are **not** emitted as standalone OL events.
Their information lives in the canonical event log (DuckDB) and the
Hutch dashboard. The OL emitter projects the lineage edges into OL's
data model; it does not mirror the full event stream.

`run_end.status` mapping:

- `finished` or `running` → `COMPLETE`
- `failed` or `cancelled` → `FAIL`

## Event shape

An OL event posted by Hutch looks like:

```json
{
  "eventType": "RUNNING",
  "eventTime": "2026-05-05T12:34:56.123456Z",
  "run": {
    "runId": "run-abc123",
    "facets": {
      "hutchOperator": {
        "_producer": "https://github.com/xyin-anl/hutch/v0.1.0",
        "_schemaURL": "https://github.com/xyin-anl/hutch/v0.1.0#/$defs/hutchOperator",
        "operator_id": "op-42",
        "operator_kind": "refine",
        "cost_usd": 0.012,
        "tokens_in": 120,
        "tokens_out": 45,
        "llm_id": "claude-sonnet-4-6"
      }
    }
  },
  "job": {
    "namespace": "hutch",
    "name": "circle-packing"
  },
  "inputs":  [{"namespace": "hutch", "name": "individual:ind-A"}],
  "outputs": [{"namespace": "hutch", "name": "individual:ind-B"}],
  "producer":  "https://github.com/xyin-anl/hutch/v0.1.0",
  "schemaURL": "https://openlineage.io/spec/2-0-2/OpenLineage.json#/$defs/RunEvent"
}
```

## Composing with the OTel emitter

Both emitters can run at the same time. Configure both endpoints and
events fan out to all configured targets in addition to the primary
daemon or embedded transport. The transport's `_TeeTransport` wrapper
handles the multiplexing, and each emitter's failures are isolated, so
a broken OL backend does not break OTel emission and vice versa.

```python
h.configure(SDKConfig(
    mode="daemon",
    otel_endpoint="http://localhost:4318",
    openlineage_endpoint="http://localhost:5000",
))
```

## Failure semantics

OL emission is best-effort. A 5xx from the backend, a network timeout,
or a serialization issue is logged at WARNING and swallowed; the
primary daemon or embedded transport continues unchanged. This matches
the project-wide rule that SDK calls do not raise on capture failures by
default. Set `HUTCH_STRICT=1` to opt into raising.

## Stability

The Hutch-to-OL mapping is additive-only between minor versions. New
event kinds may be added to the table above, and new attributes may be
added to the `hutchOperator`, `hutchSelfMod`, `hutchRun`, and
`hutchRunOutcome` facets. Renaming or removing existing fields is a
breaking change.
