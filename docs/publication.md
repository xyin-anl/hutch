# Publication-quality exports

These exports are **optional**, off the hot path. Use them when you want
a portable, archival, or citeable version of a finished run.

Three formats are supported, all reading from the same canonical event
log:

| Format | CLI | Purpose | Optional dep |
|---|---|---|---|
| **ARA** | `hutch export ara` | Self-contained, lossless tarball; round-trips through `hutch import` | none |
| **PROV-O** | `hutch export prov` | W3C provenance graph for academic and data-lineage tooling | `[publish]` for non-Turtle formats |
| **RO-Crate** | `hutch export ro-crate` | Workflow Run RO-Crate, FAIR-friendly bundle for publication | none |

Any of them runs against any run already captured in DuckDB. The CLI
takes a `--db` flag if your daemon is using a non-default database
path.

## ARA: Autonomous Research Artifact

```bash
hutch export ara <run_id> --output run.ara --notes "circle-packing v3"
hutch import run.ara --db /tmp/rehydrated.duckdb
```

An `.ara` is a gzipped tarball:

```
run.ara
├── manifest.json        # ARAManifest: format version, run_id, hutch version, counts
├── events.jsonl         # one canonical event per line
└── blobs/               # content-addressable blob store, deduped by sha256
    └── <hash[:2]>/<hash[2:]>
```

The exporter walks every event and rewrites resolvable URIs in
`genome_uri`, `diff_uri`, `snapshot_uri`, and `Artifact.uri` to
`ara://blobs/<sha256>`, slurping the bytes into the tarball. Local file
paths are not read by default; pass `--include-local-files` (and
ideally `--blob-root <dir>`) to bundle them, with file collection
confined to the explicit artifact directory. Library callers can also
pass a custom `blob_resolver` callable for S3, GCS, or HTTP.

`import_ara(path, blob_target_dir=…)` is the inverse: it extracts the
tarball, restores blobs to a target directory, and rewrites
`ara://blobs/<hash>` URIs to `file://<absolute>`, so the rehydrated run
is self-contained on the target machine.

Round-trip is **lossless**: every event re-validates against
`EVENT_ADAPTER` after import. Use ARA when you want to:

- Hand a finished run to a collaborator without giving them filesystem
  access.
- Snapshot a run for posterity before deleting the daemon's DuckDB.
- Package an experiment for a paper supplement.

## PROV-O: W3C Provenance Ontology

```bash
hutch export prov <run_id> --output run.ttl                   # default: turtle
hutch export prov <run_id> --format json-ld --output run.jsonld
hutch export prov <run_id> --format n-triples --output run.nt
hutch export prov <run_id> --format xml --output run.rdf
```

The exporter maps Hutch's five concepts onto
[W3C PROV-O](https://www.w3.org/TR/prov-o/):

- `prov:Entity` ← every Individual and Artifact
- `prov:Activity` ← every Operator, plus the run as a whole
- `prov:Agent` ← `run.started_by` and per-operator `llm_id`
- `prov:wasGeneratedBy` ← Individual → Operator that produced it
- `prov:used` ← Operator → each parent Individual
- `prov:wasDerivedFrom` ← child Individual → each parent Individual
- `prov:wasAssociatedWith` ← Operator → Agent (LLM)
- `prov:wasAttributedTo` ← Individual → run starter
- `prov:startedAtTime` and `prov:endedAtTime` ← run plus each Activity

Turtle is hand-built and dep-free. The other formats round-trip Turtle
through `rdflib` and require the `[publish]` extra:

```bash
pip install thehutch[publish]
```

Without the extra, `hutch export prov --format json-ld` raises a clear
error pointing at the install command.

A 100-event run typically produces a few hundred lines of Turtle. Load
it into Apache Jena Fuseki, GraphDB, or Stardog to query the provenance
with SPARQL.

## RO-Crate: Workflow Run RO-Crate

```bash
hutch export ro-crate <run_id> --output ./run-crate/
zip -r run-crate.zip run-crate/                  # for distribution
```

This produces a directory:

```
run-crate/
├── ro-crate-metadata.json    # Schema.org / RO-Crate JSON-LD
└── data/
    └── events.jsonl
```

The output conforms to:

- [RO-Crate 1.1](https://w3id.org/ro/crate/1.1)
- [Workflow RO-Crate 1.0](https://w3id.org/workflowhub/workflow-ro-crate/1.0)
- [Process Run Crate 0.5](https://w3id.org/ro/wfrun/process/0.5)

Each Operator becomes a Schema.org `CreateAction`. Each Individual
becomes a `Dataset`. Each `llm_id` becomes a `SoftwareApplication`.
Custom `hutch*` properties carry the schema-specific fields
(`hutchOperatorKind`, `hutchRunId`, `hutchCostUsd`, etc.); RO-Crate
explicitly accepts custom predicates as long as the JSON-LD is
well-formed.

Use RO-Crate when publishing an experiment alongside a paper. Many
journals and repositories (Zenodo, FAIRsharing, WorkflowHub) accept
RO-Crate ZIPs natively.

## Composability

All three exporters read from the same event log, so they are
consistent with each other by construction. A common pattern is to
bundle a finished run for a collaborator and a journal at once:

```bash
RUN=run-abc123
hutch export ara $RUN --output ${RUN}.ara
hutch export ro-crate $RUN --output ${RUN}-crate/
hutch export prov $RUN --output ${RUN}.ttl
```

The ARA contains the full event log (lossless round-trip), the RO-Crate
is the FAIR-friendly distribution, and the PROV-O is the
SPARQL-queryable provenance graph.

## Stability

The export formats are stable from v0.1.0. The manifest schema, the
PROV-O attribute names (`hutch:*`), and the RO-Crate custom properties
(`hutch*`) are all additive-only between minor versions. The
`ARA_FORMAT_VERSION` constant exposes the on-disk version; it bumps
only on incompatible changes, with a corresponding migration path
documented in
[CHANGELOG.md](https://github.com/xyin/hutch/blob/main/CHANGELOG.md).
