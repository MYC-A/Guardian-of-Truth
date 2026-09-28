"""Step 2 — Evidence / Tool Effects / World State.

Isolated research module. It answers ONE question: which world facts are
provable from observed tool calls, tool results and tool contracts?

It never answers "what probably happened". Absence of evidence is UNKNOWN,
never FALSE. Tool names are never trusted proof of business effects.
"""

from .types import (Authority, EffectClass, EffectStrength, FactEvent,
                    FactView, Provenance, ResultType, SupportStatus, Truth,
                    WorldFact)
from .result_types import classify_payload, classify_result_text
from .ledger import FactLedger, LedgerQueryError

__all__ = [
    "Authority", "EffectClass", "EffectStrength", "FactEvent", "FactView",
    "Provenance", "ResultType", "SupportStatus", "Truth", "WorldFact",
    "classify_result", "FactLedger", "LedgerQueryError",
]
