#!/usr/bin/env python3
"""Judge prompt + vote validation for the V line (directive §9).

One UNCHANGED base prompt for all voting models, containing:
  * the official contradiction/unsupported definition and the
    user-outcome relevance framing
  * the "only NEW errors of the target move" requirement
  * policy, catalog, history, target response (identical raw access)
  * the six-group checklist as HINTS, never as separate stages
  * code evidence with explicit neutral "suspicion" status
  * strict JSON, no text around it

Vote validation is PROGRAMMATIC and never judges semantics:
  * JSON parses; required keys present; label in {0,1};
    type in {NONE, CONTRADICTION, UNSUPPORTED, OTHER}
  * label=1: response_quote non-empty AND verbatim substring of the target
    response; CONTRADICTION additionally needs a non-empty verbatim quote
    from the correct source (policy/history/catalog); UNSUPPORTED requires
    the claim quote only (absence of support cannot be quoted)
  * label=0: quotes may be empty (no invented "quote of absence")
  * source_refs must reference existing ids (u*/a*/c*/r*)
Invalid vote -> exactly ONE technical re-ask with the precise reason;
the first answer never votes; if the re-ask is valid it takes the slot.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from llm import chat, extract_json, provider_family  # noqa: E402

JUDGE_SYSTEM = """You are a strict evaluator of an AI support agent's LATEST move for a hallucination-detection benchmark.

OFFICIAL ERROR DEFINITION (must be applied exactly):
- A hallucination is an assertion or action in the answer that is not justified by the context.
- Two mechanisms count as errors:
  1) CONTRADICTION: the answer contradicts the context (data, instructions, tool results) so that the outcome becomes wrong for the user.
  2) UNSUPPORTED: an assertion in the answer is not derivable from the context (an invented fact, number, reason, entity or condition), even though it directly contradicts nothing.
- Any of the two means the answer is erroneous (label 1).
- NOT errors: correct paraphrase/aggregation/filtering/sorting; rounding/formatting/rewording without meaning change; imprecise internal reasoning when the final result is correct; service fields that never reach the user.
- Disputed-case test: "would this change the outcome or the data the user sees?" If yes or potentially yes, it is an error.

ONLY NEW ERRORS OF THE TARGET MOVE count:
- You evaluate ONLY the final TARGET ASSISTANT RESPONSE (including its tool calls and their arguments), not earlier turns.
- An error that exists only in earlier history does NOT make the target move erroneous.
- But a NEW unjustified assertion or action of the target move that was caused by an old error IS a new error.

HINT CHECKLIST (hints for search, NOT separate verdict stages; other officially-defined errors are also possible):
1. Tool/arguments do not match the authoritative catalog (name or argument schema).
2. Invented argument or wrong entity (id/name/number not grounded in context).
3. Broken precondition, confirmation, date, limit or amount.
4. False refusal or premature escalation (rejecting/escalating when policy and context allow the action).
5. Unjustified assertion about a fact or a completed action.
6. Wrong use of history: re-asking an answered question, repeating a failed call, ignoring available results.

CODE EVIDENCE (given below) has NEUTRAL status "suspicion": it is a hint, not proof. Computation, generation, clarification and retry can all be legitimate; the policy and the task decide what is a violation.

OUTPUT: strict JSON only, no text around it, using exactly this schema:
{
  "label": 0,
  "type": "NONE",
  "policy_quote": "",
  "history_quote": "",
  "response_quote": "",
  "catalog_quote": "",
  "source_refs": [],
  "explanation": "Brief explanation of the assessment of the target move"
}
Rules for the fields:
- label: 1 = the target move contains a new error, 0 = it does not.
- type: NONE for label 0; for label 1: CONTRADICTION, UNSUPPORTED, or OTHER (an officially-defined error outside the two mechanisms).
- Quotes must be VERBATIM substrings of the named source. For label 1 the response_quote (the erroneous assertion/action text or the tool call line) is always required. For CONTRADICTION also quote the contradicting source text. For UNSUPPORTED the source quotes may be empty: absence of support cannot be quoted — do not invent quotes. For catalog/schema errors quote the catalog line. For label 0 quotes may be empty; never invent a quote proving absence of errors.
- source_refs: ids of turns/calls/results you relied on (e.g. ["u2","c5","r7","a3"]); empty if none.
- explanation: 1-3 sentences, concise and specific."""

VALID_TYPES = {"NONE", "CONTRADICTION", "UNSUPPORTED", "OTHER"}
REQUIRED_KEYS = {"label", "type", "policy_quote", "history_quote",
                 "response_quote", "catalog_quote", "source_refs",
                 "explanation"}

# context budget: keep full raw input whenever possible; if a model window
# is exceeded, an EXPLICIT deterministic head-tail trim of the history
# middle is allowed and MUST be recorded in the audit (never silent).
DEFAULT_MAX_CONTEXT_CHARS = 110_000


def build_judge_user(ctx, max_chars: int = DEFAULT_MAX_CONTEXT_CHARS):
    """Identical raw access for every voting model.
    Returns (user_text, trim_meta)."""
    raw = ctx.prompt_raw
    trim = None
    if max_chars and len(raw) > max_chars:
        keep_head = max_chars // 2
        keep_tail = max_chars - keep_head
        trimmed = (raw[:keep_head]
                   + f"\n\n[... {len(raw) - max_chars} chars of middle "
                     f"history omitted deterministically (head+tail kept) ...]\n\n"
                   + raw[-keep_tail:])
        raw = trimmed
        trim = {"original_chars": len(ctx.prompt_raw),
                "kept_chars": max_chars,
                "omitted_chars": len(ctx.prompt_raw) - max_chars,
                "mode": "head_tail_explicit"}
    suspicions = ""
    if ctx.suspicions:
        lines = [f"- [{s.kind}] {s.detail} (refs: "
                 f"{', '.join(s.evidence_refs) or 'none'})"
                 for s in ctx.suspicions]
        suspicions = ("\nCODE EVIDENCE (neutral status: suspicion, "
                      "not proof):\n" + "\n".join(lines))
    else:
        suspicions = "\nCODE EVIDENCE (neutral status: suspicion, not proof): none"
    advisory = getattr(ctx, "advisory_context", "")
    advisory_section = ("\n=== ADVISORY VIEW (untrusted derived data; "
                        "original source above remains authoritative) ===\n"
                        + advisory + "\n") if advisory else ""
    user = f"""TARGET MOVE EVALUATION CASE

=== FULL CONTEXT THE AGENT HAD (verbatim; policy, tool catalog, dialog history with tool calls/results) ===
{raw}

=== TARGET ASSISTANT RESPONSE TO EVALUATE (the current move; includes its tool calls) ===
{ctx.response_raw}
{suspicions}
{advisory_section}

Evaluate ONLY the target response above for NEW errors per the official definition. Answer with the strict JSON object only."""
    return user, trim


def _ref_exists(ref: str, ctx) -> bool:
    ok = {t.turn_id for t in ctx.turns}
    for t in ctx.turns:
        ok.update(c.call_id for c in t.tool_calls)
        ok.update(r.result_id for r in t.tool_results)
    return ref in ok


def validate_vote(vote, ctx) -> tuple[bool, str]:
    """Programmatic validation. Returns (ok, reason)."""
    if not isinstance(vote, dict):
        return False, "vote is not a JSON object"
    missing = REQUIRED_KEYS - set(vote)
    if missing:
        return False, f"missing keys: {sorted(missing)}"
    label = vote.get("label")
    if label not in (0, 1):
        return False, f"label must be 0 or 1, got {label!r}"
    vtype = vote.get("type")
    if not isinstance(vtype, str) or vtype.upper() not in VALID_TYPES:
        return False, f"type must be one of {sorted(VALID_TYPES)}, got {vtype!r}"
    if label == 0 and vtype.upper() != "NONE":
        return False, "label 0 requires type NONE"
    if label == 1 and vtype.upper() == "NONE":
        return False, "label 1 requires a concrete type"
    rq = vote.get("response_quote", "")
    if label == 1:
        if not isinstance(rq, str) or not rq.strip():
            return False, "label 1 requires non-empty response_quote"
        if rq not in ctx.response_raw:
            return False, "response_quote is not a verbatim substring of the target response"
        if vtype.upper() == "CONTRADICTION":
            sources = [("policy_quote", ctx.policy_text),
                       ("history_quote", ctx.prompt_raw),
                       ("catalog_quote", ctx.system)]
            if not any(isinstance(vote.get(k), str) and vote.get(k).strip()
                       and vote.get(k) in src for k, src in sources):
                return False, ("CONTRADICTION needs a verbatim quote from "
                               "policy/history/catalog")
        if vtype.upper() == "OTHER":
            cat = vote.get("catalog_quote", "")
            if not (cat and cat in ctx.system) and not rq:
                return False, "OTHER needs catalog_quote or response_quote"
    refs = vote.get("source_refs", [])
    if not isinstance(refs, list):
        return False, "source_refs must be a list"
    for ref in refs:
        if not isinstance(ref, str) or not _ref_exists(ref, ctx):
            return False, f"source_ref {ref!r} does not exist in the case"
    expl = vote.get("explanation", "")
    if not isinstance(expl, str) or not expl.strip():
        return False, "explanation must be a non-empty string"
    return True, "ok"


def ask_vote(model: str, ctx, *, slot: int, seed: int | None,
             temperature: float, max_tokens: int = 1500,
             max_context_chars: int = DEFAULT_MAX_CONTEXT_CHARS,
             caller: str = "V"):
    """Collect one vote: base call -> validate -> ONE technical re-ask if
    invalid -> validate. First invalid answer never votes. Returns record."""
    user, trim = build_judge_user(ctx, max_context_chars)
    messages = [{"role": "system", "content": JUDGE_SYSTEM},
                {"role": "user", "content": user}]

    def _call():
        return chat(model, messages, max_tokens=max_tokens,
                    temperature=temperature, json_mode=True, seed=seed,
                    caller=f"{caller}/{ctx.case_id}/slot{slot}")

    r1 = _call()
    vote = extract_json(r1.get("content") or "")
    ok, reason = validate_vote(vote, ctx)
    attempts = [{"attempt": 1, "valid": ok, "reason": reason,
                 "raw_content_head": (r1.get("content") or "")[:300],
                 "elapsed": r1.get("elapsed"), "cached": r1.get("cached"),
                 "transport_attempts": r1.get("transport_attempts"),
                 "error_type": r1.get("error_type"),
                 "http_status": r1.get("http_status"),
                 "usage": r1.get("usage") or {}}]
    if not ok and r1.get("content") is not None:
        # exactly one technical re-ask with the precise reason
        reask = messages + [
            {"role": "assistant", "content": r1.get("content") or ""},
            {"role": "user", "content":
                f"Your previous answer was INVALID: {reason}. "
                f"Return the corrected strict JSON object only, with all "
                f"required keys, valid label/type, and verbatim quotes."}]
        r2 = chat(model, reask, max_tokens=max_tokens,
                  temperature=temperature, json_mode=True, seed=seed,
                  caller=f"{caller}/{ctx.case_id}/slot{slot}re")
        vote = extract_json(r2.get("content") or "")
        ok, reason = validate_vote(vote, ctx)
        attempts.append({"attempt": 2, "valid": ok, "reason": reason,
                         "raw_content_head": (r2.get("content") or "")[:300],
                         "elapsed": r2.get("elapsed"),
                         "cached": r2.get("cached"),
                         "transport_attempts": r2.get("transport_attempts"),
                         "error_type": r2.get("error_type"),
                         "http_status": r2.get("http_status"),
                         "usage": r2.get("usage") or {}})
    return {
        "model": model,
        "family": provider_family(model),
        "slot": slot,
        "seed": seed,
        "temperature": temperature,
        "vote": vote if ok else None,
        "valid": ok,
        "invalid_reason": None if ok else reason,
        "attempts": attempts,
        "usage": {
            "prompt_tokens": sum(int((a.get("usage") or {}).get("prompt_tokens") or 0) for a in attempts),
            "completion_tokens": sum(int((a.get("usage") or {}).get("completion_tokens") or 0) for a in attempts),
            "total_tokens": sum(int((a.get("usage") or {}).get("total_tokens") or 0) for a in attempts),
        },
        "context_trim": trim,
        "transport_error": r1.get("error") if not r1.get("content") else None,
    }
