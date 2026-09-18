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


def build_program(ci):
    """Return (program_text, program, obligations) — data + static rules.

    Layout (directive §15: logically separate):
      <data facts>            (this module; per-case ground atoms)
      <evidence.lp>           (facts -> sup/ref/tval; four-valued evidence)
      <policy.lp>             (condition folds + obligations + worlds +
                               consensus; reads ONLY tval + its own data)
    """
    prog = _Program()
    _emit_facts(ci, prog)
    emitter = _TreeEmitter(prog)
    obligations = _emit_obligations(ci, prog, emitter)
    data = "\n".join(prog.data) + "\n"
    program_text = data + "\n" + EVIDENCE_LP + "\n" + POLICY_LP + "\n"
    return program_text, prog, obligations
