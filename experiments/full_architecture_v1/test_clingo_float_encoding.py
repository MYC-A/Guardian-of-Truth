"""Regression for non-integral JSON numbers in FullArch ASP input."""

from __future__ import annotations

import sys
from pathlib import Path

import clingo


ORIGINAL_SYS_PATH = list(sys.path)
FULLARCH = Path(__file__).resolve().parent
BAKEOFF = FULLARCH.parent / "core_engine_bakeoff_v1"
for path in (BAKEOFF, BAKEOFF / "backends"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from clingo_backend import _term, probe  # noqa: E402
from neutral_types import (  # noqa: E402
    NeutralAtom,
    NeutralCoreInput,
    NeutralFact,
    NeutralInterpretation,
)
sys.path[:] = ORIGINAL_SYS_PATH


def _parse_fact(term: str) -> None:
    control = clingo.Control()
    control.add("base", [], f"value({term}).")
    control.ground([("base", [])])


def test_nonintegral_float_is_parseable_and_typed_apart_from_string():
    encoded = _term(7.8)
    assert encoded != _term("7.8")
    _parse_fact(encoded)


def test_integral_float_remains_an_asp_integer():
    assert _term(7.0) == "num(7)"
    _parse_fact(_term(7.0))


def test_hyphenated_fact_id_remains_evidence_and_preserves_witness_id():
    fact = NeutralFact(
        "case-with-hyphen-f1", "ACTION_ATTEMPTED", "assistant", "*",
        "lookup", event_index=1,
    )
    core_input = NeutralCoreInput(
        case_id="case-with-hyphen",
        facts=(fact,),
        interpretations=(NeutralInterpretation("i0"),),
    )
    atom = NeutralAtom(
        "q", "attempted", action="lookup", entity="*", actor="assistant",
        time_index=1,
    )
    result = probe(core_input, [atom])[0]
    assert result.value == "TRUE"
    assert result.supports == ("case-with-hyphen-f1",)
