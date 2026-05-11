"""Property-based tests for the §5.4 schema invariants.

These exercise the *invariant statements* directly with Hypothesis so we
get coverage across pathological shapes the example-based tests in
:mod:`tests.test_schema_payloads` don't reach.
"""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from hutch.schema import (
    ArchiveSnapshotPayload,
    DescriptorPayload,
    FitnessPayload,
    IndividualPayload,
    OperatorPayload,
    ParetoSnapshotPayload,
)
from hutch.schema.types import EvaluatorKind, IndividualKind, OperatorKind

# ----- strategies -------------------------------------------------------

ids = st.text(
    alphabet=st.characters(min_codepoint=33, max_codepoint=126, blacklist_characters="\\"),
    min_size=1,
    max_size=8,
).filter(lambda s: s.strip() != "")

individual_kinds = st.sampled_from(list(IndividualKind.__args__))  # type: ignore[attr-defined]
operator_kinds = st.sampled_from(list(OperatorKind.__args__))  # type: ignore[attr-defined]
evaluator_kinds = st.sampled_from(list(EvaluatorKind.__args__))  # type: ignore[attr-defined]

scores = st.dictionaries(
    keys=st.text(min_size=1, max_size=8),
    values=st.floats(allow_nan=False, allow_infinity=False, width=32),
    min_size=1,
    max_size=4,
)

# ----- §5.4 invariant: Individuals have parents OR are seeds ------------


@given(parent_ids=st.lists(ids, min_size=1, max_size=6), kind=individual_kinds, ind_id=ids)
def test_individual_with_parents_validates(parent_ids: list[str], kind: str, ind_id: str) -> None:
    p = IndividualPayload(id=ind_id, kind=kind, parent_ids=parent_ids)
    assert p.parent_ids == parent_ids
    assert not p.is_seed


@given(kind=individual_kinds, ind_id=ids)
def test_individual_seed_with_no_parents_validates(kind: str, ind_id: str) -> None:
    p = IndividualPayload(id=ind_id, kind=kind, is_seed=True)
    assert p.parent_ids == []


@given(kind=individual_kinds, ind_id=ids)
def test_individual_orphan_always_rejected(kind: str, ind_id: str) -> None:
    try:
        IndividualPayload(id=ind_id, kind=kind)
    except ValidationError:
        return
    raise AssertionError("orphan individual was accepted")


@given(parent_ids=st.lists(ids, min_size=1, max_size=4), kind=individual_kinds, ind_id=ids)
def test_individual_seed_with_parents_always_rejected(
    parent_ids: list[str], kind: str, ind_id: str
) -> None:
    try:
        IndividualPayload(id=ind_id, kind=kind, is_seed=True, parent_ids=parent_ids)
    except ValidationError:
        return
    raise AssertionError("seed with parents was accepted")


# ----- §5.4 invariant: parent_ids has arbitrary length ------------------


@given(n=st.integers(min_value=0, max_value=20))
def test_operator_parent_ids_arbitrary_length(n: int) -> None:
    parents = [f"p{i}" for i in range(n)]
    p = OperatorPayload(id="op", kind="distill", parent_ids=parents, child_id="c")
    assert len(p.parent_ids) == n


# ----- §5.4 invariant: Fitness needs scores OR invalid_reason -----------


@given(individual_id=ids, kind=evaluator_kinds, sc=scores)
def test_fitness_with_scores_validates(individual_id: str, kind: str, sc: dict[str, float]) -> None:
    p = FitnessPayload(individual_id=individual_id, evaluator_kind=kind, scores=sc)
    assert p.scores == sc


@given(individual_id=ids, kind=evaluator_kinds, reason=st.text(min_size=1, max_size=20))
def test_fitness_with_invalid_reason_validates(individual_id: str, kind: str, reason: str) -> None:
    p = FitnessPayload(individual_id=individual_id, evaluator_kind=kind, invalid_reason=reason)
    assert p.invalid_reason == reason
    assert p.scores == {}


@given(individual_id=ids, kind=evaluator_kinds)
def test_fitness_empty_no_reason_rejected(individual_id: str, kind: str) -> None:
    try:
        FitnessPayload(individual_id=individual_id, evaluator_kind=kind)
    except ValidationError:
        return
    raise AssertionError("empty FitnessPayload was accepted")


# ----- §5.4 invariant: Archive coverage in [0, 1] -----------------------


@given(coverage=st.floats(min_value=0.0, max_value=1.0, allow_nan=False))
def test_archive_coverage_in_range(coverage: float) -> None:
    p = ArchiveSnapshotPayload(archive_id="a1", coverage=coverage, size=10)
    assert 0.0 <= p.coverage <= 1.0


@given(coverage=st.floats(min_value=1.0001, max_value=1e6, allow_nan=False, allow_infinity=False))
def test_archive_coverage_above_one_rejected(coverage: float) -> None:
    try:
        ArchiveSnapshotPayload(archive_id="a1", coverage=coverage, size=10)
    except ValidationError:
        return
    raise AssertionError(f"coverage {coverage} > 1 was accepted")


@given(coverage=st.floats(max_value=-0.0001, min_value=-1e6, allow_nan=False, allow_infinity=False))
def test_archive_coverage_below_zero_rejected(coverage: float) -> None:
    try:
        ArchiveSnapshotPayload(archive_id="a1", coverage=coverage, size=10)
    except ValidationError:
        return
    raise AssertionError(f"coverage {coverage} < 0 was accepted")


# ----- §5.4 invariant: Descriptor coords match dimensions ---------------


@given(
    dim_count=st.integers(min_value=1, max_value=6),
    coord_count=st.integers(min_value=1, max_value=6),
)
def test_descriptor_dim_coord_match(dim_count: int, coord_count: int) -> None:
    dims = [f"d{i}" for i in range(dim_count)]
    coords = [0.1 * i for i in range(coord_count)]
    if dim_count == coord_count:
        DescriptorPayload(
            individual_id="i1",
            archive_id="a1",
            kind="grid",
            dimensions=dims,
            coordinates=coords,
        )
    else:
        try:
            DescriptorPayload(
                individual_id="i1",
                archive_id="a1",
                kind="grid",
                dimensions=dims,
                coordinates=coords,
            )
        except ValidationError:
            return
        raise AssertionError("dim/coord mismatch was accepted")


# ----- §5.4 invariant: Pareto front non-empty ---------------------------


@given(front=st.lists(ids, min_size=1, max_size=10))
def test_pareto_front_non_empty_validates(front: list[str]) -> None:
    p = ParetoSnapshotPayload(population_id="pop", front=front, objectives=["x"])
    assert len(p.front) >= 1


def test_pareto_empty_front_rejected_property() -> None:
    try:
        ParetoSnapshotPayload(population_id="pop", front=[], objectives=["x"])
    except ValidationError:
        return
    raise AssertionError("empty front was accepted")
