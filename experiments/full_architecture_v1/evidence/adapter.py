"""full_architecture_v1 — NeutralCoreInput -> Clingo data facts (directive §13).

The adapter is a TRANSLATION LAYER ONLY: facts, query descriptors, condition
trees and obligation records become ground data atoms; every rule lives in
the static evidence.lp / policy.lp files.  Reuses the bake-off emitters
byte-for-byte (same data predicates) so the 43-scenario regression is exact.
"""

from __future__ import annotations

import sys
from pathlib import Path

_FULLARCH = Path(__file__).resolve().parents[1]
_BAKEOFF = _FULLARCH.parent / "core_engine_bakeoff_v1"
for p in (str(_BAKEOFF), str(_BAKEOFF / "backends"), str(_FULLARCH)):
    if p not in sys.path:
        sys.path.insert(0, p)

from clingo_backend import (  # noqa: E402
    _Program, _TreeEmitter, _emit_facts, _emit_obligations,
)

EVIDENCE_LP = (_FULLARCH / "evidence" / "evidence.lp").read_text(encoding="utf-8")
POLICY_LP = (_FULLARCH / "policy" / "policy.lp").read_text(encoding="utf-8")

_CONTROL = str.maketrans({"\n": " ", "\r": " ", "\t": " "})


def _sanitize(ci):
    """ASP string literals must not carry raw control characters (newlines
    in benchmark transcripts crash the grounder); replace with spaces and
    cap length.  Semantics-preserving: values are compared as strings after
    the same normalization on both the fact and query side is NOT applied —
    queries come from compiled rules whose text already has no newlines."""
    from neutral_types import NeutralFact
    facts = []
    for fact in ci.facts:
        predicate = str(fact.predicate).translate(_CONTROL)[:120]
        entity = str(fact.entity).translate(_CONTROL)[:120]
        value = fact.value
        if isinstance(value, str):
            value = value.translate(_CONTROL)[:512]
        elif isinstance(value, list):
            value = value[:20]
        elif isinstance(value, dict):
            value = {str(k)[:60]: v for k, v in list(value.items())[:20]}
        facts.append(NeutralFact(
            fact.fact_id, fact.kind, fact.actor, entity, predicate,
            value=value, event_index=fact.event_index,
            call_id=(str(fact.call_id).translate(_CONTROL)[:120]
                     if fact.call_id else None),
            region=fact.region, evidence_status=fact.evidence_status,
            source_ref=fact.source_ref))
    from neutral_types import NeutralCoreInput
    return NeutralCoreInput(
        case_id=ci.case_id, facts=tuple(facts),
        interpretations=ci.interpretations,
        history_complete=ci.history_complete,
        completeness_basis=ci.completeness_basis,
        closed_action_universe=ci.closed_action_universe,
        source_refs=ci.source_refs, notes=ci.notes)


def build_program(ci):
    """Return (program_text, program, obligations) — data + static rules.

    Layout (directive §15: logically separate):
      <data facts>            (this module; per-case ground atoms)
      <evidence.lp>           (facts -> sup/ref/tval; four-valued evidence)
      <policy.lp>             (condition folds + obligations + worlds +
                               consensus; reads ONLY tval + its own data)
    """
    ci = _sanitize(ci)
    prog = _Program()
    _emit_facts(ci, prog)
    emitter = _TreeEmitter(prog)
    obligations = _emit_obligations(ci, prog, emitter)
    data = "\n".join(prog.data) + "\n"
    program_text = data + "\n" + EVIDENCE_LP + "\n" + POLICY_LP + "\n"
    return program_text, prog, obligations
