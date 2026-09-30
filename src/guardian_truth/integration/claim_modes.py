"""Source-exact response claim modes; model output is only a proposal.

This stage identifies what the assistant *says*. It never verifies that an
asserted action happened and never maps a phrase to a business predicate.
"""
from __future__ import annotations

from dataclasses import dataclass
import json


MODES = frozenset({"CLAIMED_COMPLETED", "STATE_CLAIM", "PROPOSED",
                   "CONDITIONAL", "REQUEST", "REFUSAL", "UNKNOWN"})
ACTORS = frozenset({"ASSISTANT", "USER", "OTHER", "UNKNOWN"})

SYSTEM_PROMPT = """You extract claims from an assistant reply, not their truth.
Return one JSON object: {"claims":[{"quote":"exact contiguous substring",
"mode":"CLAIMED_COMPLETED|STATE_CLAIM|PROPOSED|CONDITIONAL|REQUEST|REFUSAL|UNKNOWN",
"actor":"ASSISTANT|USER|OTHER|UNKNOWN"}]}.
Extract every material action, state, request, and refusal claim. Split separate
claims even when they share a sentence. Copy each shortest self-contained
quote exactly from the reply, including the named entity when present.
CLAIMED_COMPLETED means the reply asserts an action already happened.
STATE_CLAIM means it asserts a current state without necessarily claiming
who caused it. PROPOSED is a future offer/plan. CONDITIONAL depends on a
future condition. REQUEST asks the user to act or supply information.
REFUSAL says the requested task cannot or will not be done. A request for
the user to use a tool is REQUEST, not assistant tool use.
If the mode is unclear, use UNKNOWN. Do not infer tool calls, policy violations,
or whether a claim is true. Omit greetings and pure politeness."""


@dataclass(frozen=True)
class ResponseClaim:
    quote: str
    start: int
    end: int
    mode: str
    actor: str

    def as_dict(self) -> dict:
        return dict(self.__dict__)


def validate_claim_proposal(response: str, raw: str) -> tuple[tuple[ResponseClaim, ...], tuple[str, ...]]:
    """Check syntax and literal source spans; never repair a paraphrase."""
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return (), ("invalid_json",)
    if not isinstance(value, dict) or not isinstance(value.get("claims"), list):
        return (), ("invalid_envelope",)
    claims: list[ResponseClaim] = []
    issues: list[str] = []
    used: set[tuple[int, int]] = set()
    for index, item in enumerate(value["claims"]):
        if not isinstance(item, dict):
            issues.append(f"{index}:invalid_item")
            continue
        quote, mode, actor = item.get("quote"), item.get("mode"), item.get("actor")
        if not isinstance(quote, str) or not quote or quote not in response:
            issues.append(f"{index}:quote_not_in_source")
            continue
        if mode not in MODES or actor not in ACTORS:
            issues.append(f"{index}:invalid_mode_or_actor")
            continue
        positions = [i for i in range(len(response)) if response.startswith(quote, i)]
        if len(positions) != 1:
            issues.append(f"{index}:ambiguous_quote")
            continue
        start = positions[0]
        key = (start, start + len(quote))
        if key in used:
            issues.append(f"{index}:duplicate_span")
            continue
        used.add(key)
        claims.append(ResponseClaim(quote, *key, mode, actor))
    return tuple(sorted(claims, key=lambda x: x.start)), tuple(issues)
