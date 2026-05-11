# Changelog

All notable changes to Hutch are documented here.

## 0.1.0 - 2026-05-07

Initial alpha release.

- Added the canonical Hutch event schema, Python SDK, FastAPI daemon, and
  static dashboard bundle.
- Added hand-tuned import adapters for OpenEvolve, AIDE, DGM, QDax, ASI-ARCH,
  FunSearch, CORAL, POET, ptychi-evolve, and ShinkaEvolve.
- Added LLM-assisted import for long-tail JSON/JSONL formats, with explicit
  trusted-input guidance and constrained validation execution.
- Added steering command issue/poll/ack endpoints and SDK helpers.
- Added ARA, PROV-O, RO-Crate, OpenTelemetry, and OpenLineage export paths.
- Hardened release-blocking surfaces before publication: daemon token auth for
  non-local use, bounded request/read paths, durable fallback replay, blob hash
  validation, ARA traversal/hash checks, source hygiene gates, dependency
  audits, and UI smoke tests.
