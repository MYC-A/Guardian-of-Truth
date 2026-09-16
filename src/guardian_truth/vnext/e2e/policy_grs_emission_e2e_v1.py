"""E2E V1 GRS emission boundary: frozen canonicalizer + envelope repair.

NEW versioned component (spec sections 47-48, 176-178).  The FROZEN
policy-line canonicalizer (policy_grs_emission.canonicalize_dsl) is applied
FIRST, unchanged.  This wrapper adds exactly ONE additional
structure-preserving repair that the frozen boundary never needed but the
E2E V1 live corpus surfaced: a well-formed top-level `RULE(...)` or
`ONE_OF(...)` sequence WITHOUT the `RULESET(...)` envelope gets the envelope
inserted.  The audit proves only RULESET/( ) tokens are added; any other
malformation stays invalid.  The FROZEN validator always runs AFTER the
repair; semantics are untouched.
"""
from __future__ import annotations

from ..policy_grs import GRSInvalid
from ..policy_grs_emission import EmissionInvalid, canonicalize_dsl


def canonicalize_dsl_e2e(text: str) -> tuple[str, dict]:
    """Frozen canonicalizer first; then the missing-envelope repair.

    Returns (canonical_dsl_text, audit).  Raises EmissionInvalid when the
    input is outside both repair scopes (stays invalid — never semantic)."""
    try:
        canonical, audit = canonicalize_dsl(text)
        return canonical, audit
    except EmissionInvalid:
        repaired, envelope_audit = _insert_missing_ruleset_envelope(text)
        if repaired is None:
            raise
        # the envelope-repaired text goes through the FROZEN canonicalizer
        # again (it may then also need the inner RULE-wrapper repair)
        canonical, audit = canonicalize_dsl(repaired)
        audit = dict(audit)
        audit["envelope_repair"] = envelope_audit
        return canonical, audit


def _insert_missing_ruleset_envelope(text: str) -> tuple[str | None, dict]:
    """Wrap a bare top-level RULE(...)/ONE_OF(...)/modality sequence in
    RULESET(...).  Token-multiset audit: only RULESET, '(' and ')' are added."""
    from ..policy_grs import _tokenize as _grs_tokenize
    try:
        tokens = _grs_tokenize(text)
    except GRSInvalid:
        return None, {}
    tokens = [token for token in tokens if token.strip()]
    if not tokens:
        return None, {}
    head = tokens[0]
    if head in ("RULESET",):
        return None, {}       # envelope exists; the failure is something else
    if head in ("RULE", "ONE_OF") or head in ("PERMIT", "PROHIBIT", "REQUIRE"):
        before = _multiset(tokens)
        rebuilt = " ".join(["RULESET", "("] + tokens + [")"])
        after = _multiset(_grs_tokenize(rebuilt))
        added = {key: after[key] - before.get(key, 0) for key in after
                 if after[key] - before.get(key, 0) > 0}
        removed = {key: before[key] - after.get(key, 0) for key in before
                   if before[key] - after.get(key, 0) > 0}
        if removed or set(added) - {"RULESET", "(", ")"} or added.get("RULESET", 0) != 1:
            return None, {}
        return rebuilt, {"changed": True, "inserted_ruleset_envelope": 1,
                         "added": added, "removed": removed}
    return None, {}


def _multiset(tokens) -> dict:
    counts: dict[str, int] = {}
    for token in tokens:
        counts[token] = counts.get(token, 0) + 1
    return counts
