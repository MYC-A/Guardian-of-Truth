"""full_architecture_v1 — the incumbent Python evidence layer backend (§20).

Reuses the bake-off's current_guardian adapter VERBATIM: it wraps the
production vnext evidence/ledger/proof_evidence stack behind the
NeutralCoreInput contract.  This is the "current Python Evidence" column of
the directive §20 comparison (primitives, not final verdicts).
"""

from __future__ import annotations

import sys
from pathlib import Path

_FULLARCH = Path(__file__).resolve().parents[1]
_BAKEOFF = _FULLARCH.parent / "core_engine_bakeoff_v1"
for p in (str(_BAKEOFF), str(_BAKEOFF / "backends")):
    if p not in sys.path:
        sys.path.insert(0, p)

from backends import current_guardian  # noqa: E402,F401

evaluate = current_guardian.evaluate
probe = current_guardian.probe
BACKEND_NAME = "current-python-evidence(bakeoff current_guardian adapter)"
