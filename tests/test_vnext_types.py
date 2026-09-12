from dataclasses import FrozenInstanceError
import itertools
import json
from pathlib import Path

import pytest

from guardian_truth.vnext.types import (CoreStatus, CoverageStatus, Disposition, Reason,
                                       SemanticCoverage, Span, Truth, consensus)


def test_stable_reason_vocabulary_covers_full_objective():
    root = Path(__file__).resolve().parents[1]
    contract = json.loads((root / "contracts/vnext_requirements_v1.json").read_text(encoding="utf-8"))
    assert set(contract["mandatory_reason_codes"]) <= {reason.value for reason in Reason}


def test_unknown_never_becomes_false_or_safety():
    assert Truth.UNKNOWN != Truth.FALSE
    assert consensus((Truth.UNKNOWN,), material_space_complete=True) is CoreStatus.UNRESOLVED
    assert consensus((Truth.FALSE,), material_space_complete=False) is CoreStatus.UNRESOLVED


def test_consensus_is_not_any_error_or_majority_vote():
    assert consensus((Truth.TRUE,) * 9 + (Truth.FALSE,), material_space_complete=True) is CoreStatus.UNRESOLVED
    assert consensus((Truth.FALSE,) * 9 + (Truth.TRUE,), material_space_complete=True) is CoreStatus.UNRESOLVED
    assert consensus((), material_space_complete=True) is CoreStatus.UNRESOLVED


@pytest.mark.parametrize("values", list(itertools.product(list(Truth), repeat=3)))
def test_all_combinations_preserve_unknown_disagreement_and_contradiction(values):
    result = consensus(values, material_space_complete=True)
    if Truth.BOTH in values:
        assert result is CoreStatus.INCONSISTENT
    elif Truth.UNKNOWN in values or len(set(values)) > 1:
        assert result is CoreStatus.UNRESOLVED
    else:
        assert result is (CoreStatus.PROVED_ERROR if values[0] is Truth.TRUE else CoreStatus.PROVED_NO_ERROR)


@pytest.mark.parametrize("source,complete,terms", [(None, True, ()), ("ontology", False, ()), ("ontology", True, ("old",))])
def test_closed_coverage_rejects_missing_enumeration_premises(source, complete, terms):
    with pytest.raises(ValueError):
        SemanticCoverage(CoverageStatus.PROVABLY_CLOSED, source, complete, terms)


def test_empirical_challenger_is_not_closed():
    coverage = SemanticCoverage(CoverageStatus.EMPIRICALLY_COVERED, None, False)
    assert coverage.status is not CoverageStatus.PROVABLY_CLOSED


def test_source_span_is_immutable_and_nonempty():
    span = Span("response", 0, 3)
    with pytest.raises(FrozenInstanceError):
        span.start = 1
    for args in [("response", 0, 0), ("response", -1, 3), ("response", True, 3)]:
        with pytest.raises(ValueError):
            Span(*args)
