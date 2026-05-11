"""Hand-tuned per-system adapters.

Each adapter exposes ``import_<system>(path) -> Iterator[Event]`` and a
``detect(path) -> bool`` helper. The :data:`REGISTRY` below is consulted by
``hutch import <path>`` to auto-pick the right adapter.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from hutch.adapters import (
    aide,
    asi_arch,
    coral,
    cvevolve,
    dgm,
    funsearch,
    openevolve,
    poet,
    ptychi_evolve,
    qdax,
    shinka_evolve,
)
from hutch.adapters.support import decorate_adapter_events
from hutch.schema import AnyEvent

logger = logging.getLogger("hutch.adapters")

CompletionPolicy = Literal["explicit", "idle"]


def _unknown_complete(path: Path) -> bool | None:
    del path
    return None


@dataclass(frozen=True, slots=True)
class Adapter:
    """A registered adapter — name, format detector, importer."""

    name: str
    detect: Callable[[Path], bool]
    importer: Callable[..., Iterator[AnyEvent]]
    is_complete: Callable[[Path], bool | None] = _unknown_complete
    completion_policy: CompletionPolicy = "idle"

    def iter_events(
        self,
        path: str | Path,
        *,
        run_id: str | None = None,
        project: str | None = None,
        finalize: bool = True,
        **importer_options: Any,
    ) -> Iterator[AnyEvent]:
        """Yield adapter events with stable ids and source metadata."""
        events = self.importer(
            path,
            run_id=run_id,
            project=project,
            finalize=finalize,
            **importer_options,
        )
        return decorate_adapter_events(events, adapter_name=self.name, source_path=path)


REGISTRY: tuple[Adapter, ...] = (
    Adapter(name="openevolve", detect=openevolve.detect, importer=openevolve.import_openevolve),
    Adapter(name="aide", detect=aide.detect, importer=aide.import_aide),
    Adapter(name="dgm", detect=dgm.detect, importer=dgm.import_dgm),
    Adapter(name="qdax", detect=qdax.detect, importer=qdax.import_qdax),
    Adapter(name="asi_arch", detect=asi_arch.detect, importer=asi_arch.import_asi_arch),
    Adapter(name="funsearch", detect=funsearch.detect, importer=funsearch.import_funsearch),
    Adapter(name="coral", detect=coral.detect, importer=coral.import_coral),
    Adapter(name="poet", detect=poet.detect, importer=poet.import_poet),
    Adapter(
        name="cvevolve",
        detect=cvevolve.detect,
        importer=cvevolve.import_cvevolve,
        is_complete=cvevolve.is_complete,
        completion_policy="explicit",
    ),
    Adapter(
        name="ptychi_evolve",
        detect=ptychi_evolve.detect,
        importer=ptychi_evolve.import_ptychi_evolve,
    ),
    Adapter(
        name="shinka_evolve",
        detect=shinka_evolve.detect,
        importer=shinka_evolve.import_shinka_evolve,
    ),
)


def detect_format(path: Path) -> Adapter | None:
    """Return the first adapter whose ``detect`` matches *path*."""
    for adapter in REGISTRY:
        try:
            if adapter.detect(path):
                return adapter
        except Exception as exc:  # detectors must be cheap and total
            logger.debug("detector %s raised on %s: %s", adapter.name, path, exc)
            continue
    return None


__all__ = [
    "REGISTRY",
    "Adapter",
    "CompletionPolicy",
    "aide",
    "asi_arch",
    "coral",
    "cvevolve",
    "detect_format",
    "dgm",
    "funsearch",
    "openevolve",
    "poet",
    "ptychi_evolve",
    "qdax",
    "shinka_evolve",
]
