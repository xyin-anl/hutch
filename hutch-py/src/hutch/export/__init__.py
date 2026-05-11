"""Publication-quality export formats.

Three serializers, all reading from the same canonical event log:

* :mod:`hutch.export.ara` (M15)       — Self-contained ``.ara`` tarball:
  ``events.jsonl`` + every referenced blob (deduped by content hash) +
  ``metadata.json``. Round-trips: ``hutch import run.ara`` rehydrates
  it into any daemon. Dep-free.

* :mod:`hutch.export.prov` (M13)       — W3C PROV-O export. Maps Hutch's
  five-abstraction model onto ``prov:Entity`` / ``prov:Activity`` /
  ``prov:Agent`` with ``wasDerivedFrom`` / ``wasGeneratedBy`` /
  ``wasAssociatedWith``. Output formats: Turtle (default), JSON-LD,
  N-Triples, RDF/XML. Optional dep on ``rdflib`` via
  ``pip install thehutch[publish]``.

* :mod:`hutch.export.ro_crate` (M14)   — Workflow Run RO-Crate profile.
  JSON-LD ``ro-crate-metadata.json`` rooted at a directory containing
  the run's blobs under ``data/``. Dep-free — RO-Crate is just
  Schema.org JSON-LD.

All three are accessed via the CLI: ``hutch export {ara,prov,ro-crate} <run_id>``.
"""

from __future__ import annotations

from hutch.export.ara import (
    ARA_FORMAT_VERSION,
    ARAManifest,
    export_ara,
    import_ara,
)
from hutch.export.prov import (
    PROV_FORMATS,
    export_prov,
)
from hutch.export.ro_crate import (
    RO_CRATE_PROFILE,
    export_ro_crate,
)

__all__ = [
    "ARA_FORMAT_VERSION",
    "PROV_FORMATS",
    "RO_CRATE_PROFILE",
    "ARAManifest",
    "export_ara",
    "export_prov",
    "export_ro_crate",
    "import_ara",
]
