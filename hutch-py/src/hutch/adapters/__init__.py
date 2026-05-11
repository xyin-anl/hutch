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

from hutch.adapters import (
    aide,
    asi_arch,
    coral,
    dgm,
    funsearch,
    openevolve,
    poet,
    ptychi_evolve,
    qdax,
    shinka_evolve,
)
from hutch.schema import AnyEvent

logger = logging.getLogger("hutch.adapters")


@dataclass(frozen=True, slots=True)
class Adapter:
    """A registered adapter — name, format detector, importer."""

    name: str
    detect: Callable[[Path], bool]
    importer: Callable[..., Iterator[AnyEvent]]


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
    "aide",
    "asi_arch",
    "coral",
    "detect_format",
    "dgm",
    "funsearch",
    "openevolve",
    "poet",
    "ptychi_evolve",
    "qdax",
    "shinka_evolve",
]
