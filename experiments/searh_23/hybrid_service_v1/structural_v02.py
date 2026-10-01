#!/usr/bin/env python3
"""Structural channel v0.2 — policy-clause parsing per directive §5.1 (2026-10-01).

Fixes the four counterexamples of the hybrid-service directive against the
V0.1 rules that lived in three_architectures/common.py (ONE_CALL_CLAUSE):

  CE1  policy "You should only make one tool call at a time."
       target = 1 tool call + "I will check the record."
       -> a clause that limits the NUMBER of calls does not by itself
          forbid accompanying text; NO text_and_call hit from the
          one-call clause (old R2 did fire here — false positive class).

  CE2  policy "You are not restricted to one tool call at a time."
       target = 2 tool calls
       -> the restriction is NEGATED; regex hit on the fragment does not
          confirm a prohibition; NO one_call hit.

  CE3  policy "Only make one tool call at a time. You may make two
       read-only calls together."  target = 2 read-only calls
       -> the exception must not be lost; NO confirmed hit, a NEUTRAL
          suspicion is emitted for the judge instead.

  CE4  an explicit separate prohibition of combining text with a call is
       its own requirement class with its OWN verbatim quote
       ("Do not combine text and tool calls."), never conflated with the
       one-call clause.

Principles (directive §5.1):
  * a CONFIRMED structural hit needs an unambiguous verbatim restriction
    clause, no negation of that restriction, and no potentially
    applicable exception for the actual call pattern;
  * whenever a natural formulation cannot be reliably parsed by code
    (exception present but applicability unclear, read-only-ness
    uncertain, mixed patterns), the candidate is DOWNGRADED to a neutral
    suspicion for the judge — never a mechanical label=1;
  * returning former TPs never justifies new FPs.

The frozen V0.1 in three_architectures/common.py is PRESERVED untouched
(historical baseline); this module is the corrected channel used by the
new hybrid-service harness (and the common harness for the main arms).
Catalog/schema/subfield checks (catalog_absent, args_unparseable,
schema_*) are reused from the frozen parser implementation unchanged.
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "three_architectures"))
from common import (  # noqa: E402
    CaseContext,
    StructuralHit,
    Suspicion,
    _check_schema,
    _near_miss,
)

# ------------------------------------------------------------------ sentences

_SENT_SPLIT = re.compile(r'(?<=[.!?])\s+')


def _sentences(text: str) -> list[str]:
    """Sentence units: paragraphs (newlines) first, then sentences —
    bullet lists and markdown headers must not merge with unrelated
    sections into giant pseudo-sentences."""
    if not text:
        return []
    units: list[str] = []
    for para in text.split("\n"):
        para = para.strip()
        if not para:
            continue
        for s in _SENT_SPLIT.split(para):
            s = s.strip()
            if s:
                units.append(s)
    return units


# ------------------------------------------------------ clause classification

# A sentence RESTRICTS the number of calls per turn when it contains one of
# these patterns (fragment must occur inside ONE sentence).
_COUNT_RESTRICTION = re.compile(
    r"\b(?:"
    r"only\s+make\s+(?:one|a\s+single)\s+(?:tool\s+)?(?:call|action|request)"
    r"|make\s+(?:exactly\s+)?(?:one|a\s+single)\s+(?:tool\s+)?(?:call|action|request)\s+at\s+a\s+time"
    r"|(?:one|a\s+single)\s+(?:tool\s+)?(?:call|action|request)s?\s+at\s+a\s+time"
    r"|at\s+most\s+(?:make\s+)?(?:one|a\s+single)\s+(?:tool\s+)?(?:call|action|request)"
    r"|one\s+action\s+at\s+a\s+time"
    r")\b",
    re.IGNORECASE,
)

# Same-sentence markers that NEGATE / cancel the restriction (permission).
_NEGATION = re.compile(
    r"\b(?:"
    r"not\s+(?:restricted|limited|bound|constrained|required|obliged)\s+to"
    r"|no\s+(?:restriction|limit)\s+on"
    r"|aren'?t\s+(?:restricted|limited)\s+to"
    r"|is\s+not\s+(?:restricted|limited)\s+to"
    r"|(?:may|can|are\s+allowed|are\s+permitted|is\s+allowed|is\s+permitted)\s+(?:to\s+)?(?:make|issue|send|perform)\s+(?:multiple|several|two|three|more\s+than\s+one|any\s+number\s+of)\s+(?:tool\s+)?(?:calls?|actions?|requests?)"
    r"|unrestricted\s+(?:number|tool\s+calls)"
    r"|without\s+(?:any\s+)?(?:restriction|limit)"
    r"|(?:freely|free)\s+to\s+(?:make|issue)\s+(?:multiple|several|any\s+number\s+of)"
    r")\b",
    re.IGNORECASE,
)

# Sentence-level markers of an EXCEPTION / additional permission that may
# cover the actual call pattern. SCOPED: the sentence must BOTH mention
# call/action vocabulary AND carry a permission/combination marker — a
# bare "unless" in an unrelated section (refunds, compensation, ...) is
# NOT an exception to the one-call rule.
_CALL_VOCAB = re.compile(
    r"\b(?:tool\s+calls?|\bcalls?\b|\bactions?\b|\brequests?\b|"
    r"read-only|read\s+only)\b",
    re.IGNORECASE,
)
_EXCEPTION_MARKERS = re.compile(
    r"\b(?:"
    r"you\s+may\s+(?:also\s+)?(?:make|issue|send|combine|use)"
    r"|(?:may|might)\s+(?:be\s+)?(?:made|issued|combined|sent|used)\s+together"
    r"|are\s+(?:allowed|permitted)\s+to\s+(?:make|combine|use)"
    r"|\bexception\b|\bexcept\b|\bunless\b"
    r"|\btogether\b|\bat\s+once\b|\bsimultaneously\b|\bin\s+combination\b|\balongside\b"
    r"|(?:two|three|multiple|several)\s+(?:read-only\s+|read\s+only\s+)?(?:tool\s+)?(?:calls?|actions?|requests?)\s+(?:are|may|can|is)\b"
    r")\b",
    re.IGNORECASE,
)

# An explicit SEPARATE prohibition of mixing text with a tool call (CE4):
# its own requirement class, its own quote.
_TEXT_CALL_PROHIBITION = [
    re.compile(p, re.IGNORECASE) for p in (
        # "Do not combine text and tool calls" / "...text with tool calls"
        r"\b(?:do\s+not|don'?t|never|must\s+not|should\s+not)\s+"
        r"(?:combine|mix|pair|merge|join)\b[^.!?]*\b"
        r"(?:text|prose|explanations?|comments?|narration|messages?)\b",
        # "Tool calls must be sent without any accompanying text"
        r"\b(?:tool\s+)?(?:calls?|invocations?)\b[^.!?]*\bwithout\s+"
        r"(?:any\s+|additional\s+|accompanying\s+|extra\s+)*"
        r"(?:text|prose|explanations?|comments?)\b",
        # "... without accompanying text ... tool call" (reversed order)
        r"\bwithout\s+(?:any\s+|additional\s+|accompanying\s+|extra\s+)*"
        r"(?:text|prose|explanations?|comments?)\b[^.!?]*\b"
        r"(?:tool\s+)?(?:call|invocation)s?\b",
        # "respond with either text or a tool call, never both"
        r"\beither\b[^.!?]*\bor\b[^.!?]*\bnever\s+both\b",
        # "text and tool calls must not be mixed / are not allowed ..."
        r"\b(?:text|prose|explanations?|comments?)\b[^.!?]*\b"
        r"(?:and|with|alongside|together\s+with)\b[^.!?]*\b"
        r"(?:tool\s+)?(?:calls?|invocations?)\b[^.!?]*\b"
        r"(?:must\s+not|is\s+not\s+allowed|are\s+not\s+allowed|"
        r"is\s+forbidden|are\s+forbidden|is\s+prohibited|are\s+prohibited)\b",
        # "if you make a tool call, you should not respond to the user
        #  simultaneously" (airline-family rich restriction sentence)
        r"\bif\s+you\s+(?:make|send|perform)\s+(?:a\s+)?(?:tool\s+)?call\b"
        r"[^.!?]*?\b(?:should\s+not|must\s+not|cannot|can'?t|do\s+not|don'?t)\s+"
        r"(?:also\s+|simultaneously\s+)*respond\b",
        # "you should not respond to the user simultaneously / at the same
        #  time / while making a call"
        r"\b(?:should\s+not|must\s+not|cannot|can'?t|not\s+allowed\s+to)\s+"
        r"respond\s+to\s+the\s+user\s+"
        r"(?:simultaneously|at\s+the\s+same\s+time|in\s+parallel|while\b)",
        # "You cannot do both at the same time" — ONLY in proximity of an
        # either-message-or-tool-call enumeration (official instruction
        # block); the proximity is checked by the classifier, see below.
        r"\b(?:cannot|can'?t|must\s+not|may\s+not)\s+do\s+both\b",
    )
]
# index of the proximity-guarded pattern ("cannot do both")
_BOTH_PAT_IDX = len(_TEXT_CALL_PROHIBITION) - 1
_EITHER_CONTEXT = re.compile(
    r"\beither\b[^.!?]{0,200}?(?:message|tool\s+call)",
    re.IGNORECASE | re.DOTALL,
)

# Exception is explicitly scoped to READ-ONLY calls.
_READ_ONLY_SCOPED = re.compile(
    r"\b(?:read-only|read\s+only)\b",
    re.IGNORECASE,
)

# Read/write classification of a tool by its DESCRIPTION head verbs.
_READ_HEADS = re.compile(
    r"^(?:checks?|check|reads?|read|gets?|get|lists?|list|views?|view|"
    r"inspects?|inspect|fetch(?:es)?|queries?|query|shows?|show|"
    r"verifies?|verify|looks?\s+up|retrieves?|retrieve|search(?:es)?|"
    r"finds?|displays?|obtains?|examines?)\b",
    re.IGNORECASE,
)
_WRITE_HEADS = re.compile(
    r"^(?:creates?|create|updates?|update|deletes?|delete|removes?|remove|"
    r"sends?|send|publish(?:es)?|replaces?|replace|records?|record|"
    r"writes?|write|makes?|make|process(?:es)?|submits?|submit|"
    r"cancels?|cancel|issues?|issue|dispatch(?:es)?|transfers?|transfer|"
    r"closes?|opens?|adds?|add|modifies?|modify|edits?|edit|"
    r"schedules?|schedule|approves?|approve|pays?|pay|refunds?|refund|"
    r"charges?|charge|posts?|assigns?)\b",
    re.IGNORECASE,
)


@dataclass
class Clause:
    quote: str                 # verbatim sentence
    index: int                 # sentence index in policy


@dataclass
class PolicyClauses:
    count_restriction: Clause | None = None
    restriction_negated: bool = False
    exceptions: list = field(default_factory=list)
    exception_read_only_scoped: bool = False
    text_call_prohibitions: list = field(default_factory=list)


def analyze_policy(policy_text: str) -> PolicyClauses:
    """Classify policy sentences into restriction/exception/prohibition
    clauses. Purely textual, deterministic, gold-free. A single sentence
    may carry SEVERAL classes (e.g. the airline rich sentence is both a
    count restriction and a text+call prohibition)."""
    out = PolicyClauses()
    sents = _sentences(policy_text)
    joined = "\n".join(sents)
    for i, s in enumerate(sents):
        # --- count restriction (with same-sentence negation guard) -----
        if _COUNT_RESTRICTION.search(s):
            if _NEGATION.search(s):
                # CE2: the restriction is negated in the same sentence —
                # this sentence is a permission, not a restriction.
                out.restriction_negated = True
            elif out.count_restriction is None:
                out.count_restriction = Clause(quote=s, index=i)
        # --- exception: SCOPED (call vocab + permission marker) ------
        if _CALL_VOCAB.search(s) and _EXCEPTION_MARKERS.search(s):
            if out.count_restriction is None or i > out.count_restriction.index:
                out.exceptions.append(Clause(quote=s, index=i))
                if _READ_ONLY_SCOPED.search(s):
                    out.exception_read_only_scoped = True
        # --- explicit text+call prohibition (own requirement) --------
        for pat_idx, pat in enumerate(_TEXT_CALL_PROHIBITION):
            if not pat.search(s):
                continue
            if pat_idx == _BOTH_PAT_IDX:
                # "cannot do both" — require an either-message-or-call
                # enumeration earlier in the policy (proximity guard)
                window = joined[max(0, sum(len(x) + 1 for x in sents[:i]) - 400):sum(len(x) + 1 for x in sents[:i])]
                if not _EITHER_CONTEXT.search(window):
                    continue
            clause = Clause(quote=s, index=i)
            if clause not in out.text_call_prohibitions:
                out.text_call_prohibitions.append(clause)
            break
    return out


def _tool_kind(ctx: CaseContext, tool_name: str) -> str:
    """read / write / unknown — by the tool DESCRIPTION head verb from the
    authoritative catalog (never by the tool name)."""
    spec = ctx.catalog.tools.get(tool_name)
    desc = (spec.description or "").strip() if spec is not None else ""
    if not desc:
        return "unknown"
    head = desc.split("\n")[0].strip()
    if _READ_HEADS.search(head):
        return "read"
    if _WRITE_HEADS.search(head):
        return "write"
    return "unknown"


def _prose_text(ctx: CaseContext) -> str:
    tgt = ctx.target()
    return re.sub(r"⟦[^⟧]*⟧", "", tgt.text).strip()


# ------------------------------------------------------ the v0.2 channel

def structural_channel_v02(ctx: CaseContext) -> None:
    """CONFIRMED mechanical violations only, on the TARGET response.

    v0.2 policy-gated rules (replacing the V0.1 ONE_CALL_CLAUSE block):
      * R1 policy_one_call_violation — fires ONLY when an unambiguous
        count-restriction clause exists, is not negated, there is NO
        exception clause, and the target turn makes >= 2 tool calls;
      * R1 read-only-scoped exception variant — all-read calls -> suspicion
        (exception applies, CE3); any unclassifiable tool -> suspicion;
        otherwise (write tools clearly outside the exception scope) ->
        confirmed with the exception quoted alongside the restriction;
      * R2 policy_text_and_call_violation — fires ONLY from an explicit
        separate text+call prohibition clause with its OWN quote (CE4);
        the one-call clause alone NEVER triggers it (CE1);
      * mixed text+call under a bare one-call clause -> neutral suspicion.
    Catalog/schema checks are identical to the frozen implementation.
    """
    catalog_names = set(ctx.catalog.tools)

    # ---- catalog / schema / args (identical to frozen V0.1) ------------
    for call in ctx.target().tool_calls:
        tool = ctx.catalog.tools.get(call.name)
        if catalog_names and tool is None:
            near = _near_miss(call.name, catalog_names)
            ctx.structural_hits.append(StructuralHit(
                reason="catalog_absent", tool=call.name, call_id=call.call_id,
                basis=(f"tool '{call.name}' absent from authoritative "
                       f"[AVAILABLE TOOLS] catalog ({len(catalog_names)} tools)"
                       + (f"; nearest catalog name: '{near}'" if near else ""))))
        if call.args_error is not None:
            ctx.structural_hits.append(StructuralHit(
                reason="args_unparseable", tool=call.name,
                call_id=call.call_id,
                basis=(f"arguments not parseable JSON ({call.args_error}): "
                       f"{call.args_raw[:120]}")))
        if tool is not None and call.args is not None:
            ctx.structural_hits.extend(_check_schema(call, tool))

    # ---- policy-gated rules (v0.2) --------------------------------------
    clauses = analyze_policy(ctx.policy_text or "")
    tgt = ctx.target()
    call_ids = [c.call_id for c in tgt.tool_calls]
    prose = _prose_text(ctx) if call_ids else ""

    # R1: one-call restriction (CE1/CE2/CE3 guards)
    if clauses.count_restriction is not None \
            and not clauses.restriction_negated and len(call_ids) >= 2:
        quote = clauses.count_restriction.quote
        if not clauses.exceptions:
            ctx.structural_hits.append(StructuralHit(
                reason="policy_one_call_violation",
                tool=",".join(c.name for c in tgt.tool_calls),
                call_id=",".join(call_ids),
                basis=(f"target turn makes {len(call_ids)} tool calls "
                       f"({', '.join(call_ids)}) while the policy states: "
                       f"\"{quote}\"")))
        elif clauses.exception_read_only_scoped:
            kinds = [_tool_kind(ctx, c.name) for c in tgt.tool_calls]
            if any(k == "unknown" for k in kinds):
                ctx.suspicions.append(Suspicion(
                    kind="policy_one_call_exception_unresolved",
                    detail=("read-only-scoped exception exists but a called "
                            "tool's read/write kind is not classifiable "
                            "from its description; passed to the judge"),
                    evidence_refs=list(call_ids)))
            elif all(k == "read" for k in kinds):
                # CE3: the exception covers exactly this pattern
                ctx.suspicions.append(Suspicion(
                    kind="policy_one_call_exception_applies",
                    detail=("all target calls are read-only by catalog "
                            "description; policy permits them together: "
                            f"\"{clauses.exceptions[0].quote}\""),
                    evidence_refs=list(call_ids)))
            else:
                exc_quote = clauses.exceptions[0].quote
                ctx.structural_hits.append(StructuralHit(
                    reason="policy_one_call_violation",
                    tool=",".join(c.name for c in tgt.tool_calls),
                    call_id=",".join(call_ids),
                    basis=(f"target turn makes {len(call_ids)} tool calls "
                           f"({', '.join(call_ids)}), including non-read-only "
                           f"tools, while the policy states: \"{quote}\" "
                           f"with the exception scoped to read-only calls "
                           f"only: \"{exc_quote}\"")))
        else:
            # exception present but not mechanically resolvable -> judge
            ctx.suspicions.append(Suspicion(
                kind="policy_one_call_exception_unresolved",
                detail=("an exception/permission clause follows the "
                        "one-call restriction and its applicability to the "
                        f"actual calls cannot be parsed by code: "
                        f"\"{clauses.exceptions[0].quote}\""),
                evidence_refs=list(call_ids)))

    # R2: explicit text+call prohibition (CE4) — its own requirement
    if call_ids and prose and clauses.text_call_prohibitions:
        for cl in clauses.text_call_prohibitions:
            ctx.structural_hits.append(StructuralHit(
                reason="policy_text_and_call_violation",
                tool=tgt.tool_calls[0].name, call_id=call_ids[0],
                basis=(f"target turn mixes a text response and tool call "
                       f"{call_ids[0]} while the policy separately forbids "
                       f"combining text with a tool call: \"{cl.quote}\"")))
    elif call_ids and prose and clauses.count_restriction is not None:
        # CE1: a bare count restriction does NOT forbid accompanying text;
        # keep it as a neutral suspicion for the judge, never label=1.
        ctx.suspicions.append(Suspicion(
            kind="policy_mixed_text_and_call_possible",
            detail=("target turn mixes text and a tool call; the one-call "
                    "clause limits the NUMBER of calls, not accompanying "
                    "text; no explicit text+call prohibition clause found"),
            evidence_refs=[call_ids[0]]))

    # history-side anomalies stay neutral (current-move semantics)
    for t in ctx.history_turns():
        for call in t.tool_calls:
            if catalog_names and call.name not in catalog_names:
                ctx.parse_warnings.append(
                    f"history call {call.call_id} uses non-catalog tool "
                    f"{call.name} (not a current-move error)")


def structural_label_v02(ctx: CaseContext) -> int:
    return 1 if ctx.structural_hits else 0


_V02_SUSPICION_KINDS = (
    "policy_one_call_exception_unresolved",
    "policy_one_call_exception_applies",
    "policy_mixed_text_and_call_possible",
)


def parse_case_v02(case_id: str, prompt: str, response: str) -> CaseContext:
    """Same lossless parse as the frozen common.parse_case, with the v0.2
    structural channel substituted (frozen V0.1 stays importable intact).

    Suspicion extractors of the frozen parser (value_not_in_history,
    failed_call_retry, repeated_question) are re-run and kept — they are
    neutral judge evidence, exactly as in V0.1.
    """
    import common as _common
    ctx = _common.parse_case(case_id, prompt, response)
    # keep the neutral suspicion extractors; drop ALL frozen V0.1
    # structural hits — the v0.2 channel re-derives the catalog/schema
    # checks itself (composition must not double-count hits)
    ctx.structural_hits = []
    ctx.suspicions = [s for s in ctx.suspicions
                      if s.kind not in _V02_SUSPICION_KINDS]
    structural_channel_v02(ctx)
    return ctx
