#!/usr/bin/env python3
"""Typed-question layer v2 (2026-09-25): domain-general fragments + generalized mechanisms.

Built on the frozen v1 discipline (Jev-form short typed questions; verbatim
fragments with stable ids; every model verdict re-verified by code; INCONSISTENT
never refutes; all-cards-refuted -> 0, any UNKNOWN -> keep). What changes and why
(measured on 2026-09-25):

1. FRAGMENTS come from fragment_supplier.py (task (b)): all declarative sentences
   as claims, generalized asks, data-driven entity vocabulary, ordered event
   timeline. The v1 banking/hotel lexicon left claims empty on 8/11 service-desk
   NL cases, which silently disabled the action-state question.
2. GENERALIZED not-due: the v1 rule anchored on log_verification (banking) and
   never fired on "After a replacement completes successfully, record an audit".
   v2 asks Q_CONDITION_APPLICABLE with direction POSTCONDITION: no prior success
   of the antecedent + dependent action not called + action only proposed ->
   obligation NOT_DUE -> refuted with cited observations.
3. Action-state question is askable whenever claims exist (v1 gated it on
   banking action-tool hints), and the action-precondition family accepts
   obligation_kind intent (v1 accepted only performed_action /
   required_action_missing, which kept the twin card of every future-offer
   false alarm alive on the third domain).
4. Q_CLAIM_SOURCE (generalized latest-observation): value/status claims are
   grounded against code-selected observations for the claimed entity/value.
5. Q_DEMAND_PRESENT: the judge demand says the response fails to do something
   that the response literally does (telecom t15 class).
6. Q_OBLIGATION_HISTORY: the quote requires asking the user; the ask was already
   made or the choice already given in prior turns (airline__24 class).
7. Q_CONDITION_APPLICABLE for live calls — the source-bound call verifier:
   the model maps the policy quote to a governed action + typed condition list
   (identity / user confirmation / authorization-exact / latest stock / prior
   success / entity-same / amount-exact); CODE verifies every mapped condition
   from the parsed timeline (entity, amount, latest observation, confirmation,
   moment of action). All satisfied -> refuted; any unmet -> keep (violation);
   model mapping incomplete vs code patterns -> UNKNOWN (conservative).

Safety gates kept: NOT_ENTAILED never clears a live-call card; action-precondition
refutations require no executing calls; structural violations (undeclared tool /
missing required args) block refutation; per-card UNKNOWN keeps the case.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "experiments/searh_23"))

import fragment_supplier as fs  # noqa: E402
import tq_questions as tq1  # noqa: E402  (frozen v1: transport, fuzzy_in, SYSTEM, verify core)
import fp_refute_layer_v4 as v4mod  # noqa: E402  (structural guard)

sys.stderr = sys.stdout  # gateway captures stdout only
csv.field_size_limit(2 ** 30)

MISTRAL_ENV = tq1.MISTRAL_ENV
Mistral = tq1.Mistral
SYSTEM = tq1.SYSTEM
fuzzy_in = tq1.fuzzy_in
clip = tq1.clip

# ---------------- v2 patterns -------------------------------------------------------------------
AFTER_PATTERN = re.compile(r"\b(after|после)\b", re.IGNORECASE)
BEFORE_PATTERN = re.compile(r"\b(before|до\s|раньше)\b", re.IGNORECASE)
WHEN_PATTERN = re.compile(r"^(when|if|only|в случае|если|только)\b|only when", re.IGNORECASE)
MAY_PATTERN = re.compile(r"\b(may|может|разреш\w+|allowed)\b", re.IGNORECASE)
ASK_DIRECTIVE = re.compile(r"(?:should|must|need to)?\s*ask\s+(?:if|whether|about|the user)|"
                          r"ask the user|спросить|запросить у пользователя", re.IGNORECASE)
QUOTE_OBLIGATION_PHRASES = re.compile(r"(?:\b(?:must|should|shall|need to)\s+[^,.;]{3,70})|"
                                       r"(?:\b(?:obtain|verify|list|record|confirm|check)\s+[^,.;]{3,60})",
                                       re.IGNORECASE)
QUOTE_ACTION_GOVERNED = re.compile(r"(?:before executing|before taking|after|when|may be executed|"
                                   r"must handle|should not|do not|перед выполнением|после)", re.IGNORECASE)
GENERIC_GOVERNED = re.compile(r"\b(?:tool call|tool calls|one call|respond to the user|"
                              r"message to the user|воздейст|один вызов)\b", re.IGNORECASE)
OTHER_OBLIGATION = re.compile(r"\b(?:must|should|shall|required|obtain|verify|confirm|record|"
                               r"do not|don't|необходимо|должен|обязан)\b", re.IGNORECASE)
COND_PATTERNS = {  # code-proposed condition types (completeness check of the model's mapping)
    "IDENTITY_VERIFIED": re.compile(r"verif\w+.{0,40}(identity|requester)|провер\w+\w*\s+личност|"
                                    r"identity.{0,20}verif", re.IGNORECASE),
    "USER_CONFIRMATION": re.compile(r"explicit confirmation|obtain.{0,30}confirmation|user'?s? "
                                    r"confirmation|подтверждени\w* (от|пользовател|user)", re.IGNORECASE),
    "AUTHORIZATION_EXACT": re.compile(r"authoriz\w+.{0,60}(SAME|EXACT|recorded)|requires authorization|"
                                      r"согласован\w+|авторизац", re.IGNORECASE),
    "STOCK_AVAILABLE": re.compile(r"latest inventory|stock is available|склад|наличи|in stock", re.IGNORECASE),
    "PRIOR_SUCCESS": re.compile(r"completes successfully|после\s+.*успешн|successful.{0,30}"
                                r"(replacement|completion)", re.IGNORECASE),
}
COND_TYPES = ("IDENTITY_VERIFIED", "USER_CONFIRMATION", "AUTHORIZATION_EXACT", "STOCK_AVAILABLE",
              "PRIOR_SUCCESS", "ENTITY_SAME", "AMOUNT_EXACT", "OTHER")
WAIT_MARKER = re.compile(r"(жду|ждать|ожид|wait|как только|как только вы|после вашего|once you|"
                          r"после того как|after you)", re.IGNORECASE)
# bilingual topic bridge: English policy nouns <-> Russian user-turn stems
TOPIC_BRIDGE = {"insurance": ("страхов",), "booking": ("брон",), "baggage": ("багаж", "чемодан"),
                "flight": ("рейс", "перелет", "полет"), "refund": ("возврат",), "cancel": ("отмен",),
                "exchange": ("обмен",), "card": ("карт",), "account": ("счет", "аккаунт"),
                "device": ("устройств", "аппарат"), "replacement": ("замен",), "delivery": ("доставк",),
                "breakfast": ("завтрак",), "membership": ("статус", "уровнев", "участи"),
                "confirmation": ("подтвержд",), "voucher": ("ваучер",), "payment": ("оплат", "платеж")}
ASK_VERB_ANY = re.compile(r"\b(?:укажите|предоставьте|подтвердите|введите|напишите|скажите|выберите|"
                          r"сообщите|отправьте|проверьте|назовите|передайте|уточните|ответьте|"
                          r"please\s+(?:confirm|provide|select|specify|enter|state)|confirm|provide)\b",
                          re.IGNORECASE)
VALUE_TOKENS = re.compile(r"[A-ZА-ЯЁ][a-zA-Zа-яёA-ZА-ЯЁ]{2,}|\b\d+(?:[.,]\d+)?\b")


# ---------------- legacy adapter for reused v1 builders -----------------------------------------
def legacy_fr(fr: dict) -> dict:
    return {"resp_calls": [{"name": c["name"], "args": c["args"]} for c in fr["resp_calls"]],
            "resp_text": fr["resp_text"], "sents": [c["text"] for c in fr["claims"]],
            "user_turns": [u["text"] for u in fr["users"]],
            "obs": [{"tool": o["tool"], "text": o["text"]} for o in fr["obs"]],
            "call_names_prompt": [], "kb_calls": 0, "human_req": 0}


# ---------------- new question builders ---------------------------------------------------------
def q_action_state(card: dict, fr: dict, claims: list[dict], demand: str) -> dict | None:
    """v1 question, v2 gating: askable whenever claims exist (no action-hint lexicon)."""
    if not claims and not fr["resp_calls"]:
        return None
    # flagged claims first (future/past/status/id/amount carriers), then the rest
    ordered = sorted(claims, key=lambda c: (not (c["flags"]["future"] or c["flags"]["past"]
                                                 or c["flags"]["ids"] or c["flags"]["amounts"]
                                                 or c["flags"]["status"]), 0))
    shown = ordered[:10]
    lines = ["RESPONSE_TOOL_CALLS (the assistant's calls in the final response, complete list):"]
    lines += [f"  {c['name']} {clip(c['args'], 120)}" for c in fr["resp_calls"][:6]] or ["  NONE"]
    lines.append("CLAIM_SENTENCES (verbatim from the same response):")
    lines += [f"  {c['id']}: {c['text']}" for c in shown] or ["  NONE"]
    if card.get("policy_quote"):
        lines.append(f"POLICY_CLAUSE (verbatim): p1: {clip(card['policy_quote'], 700)}")
    lines.append(f"JUDGE_DEMAND (verbatim): d1: {clip(demand, 320)}")
    lines.append("QUESTION: Considering ONLY the fragments above, the behavior demanded in d1: was it "
                 "EXECUTED (a matching tool call in RESPONSE_TOOL_CALLS), CLAIMED_COMPLETED (a claim "
                 "sentence asserts it already happened, past tense), PROPOSED_ONLY (offered, conditional "
                 "or future), or UNCLEAR? Answer for the whole response.")
    lines.append('ANSWER JSON: {"verdict":"EXECUTED|CLAIMED_COMPLETED|PROPOSED_ONLY|UNCLEAR",'
                 '"deciding_id":"call-name|c#|null","reason":"..."}')
    return {"type": "Q_ACTION_STATE", "action": "", "user": "\n".join(lines)}


def _obs_window(text: str, tokens, width: int = 110) -> str:
    """Show the part of a long observation that matters: a window around the
    first value token it contains, else head+tail. Long JSON observations hide
    the deciding field in the middle/end (airline__3: membership at char ~640)."""
    text = " ".join((text or "").split())
    if len(text) <= 260:
        return text
    low = text.lower()
    for w in tokens:
        if not w:
            continue
        i = low.find(w.lower())
        if i >= 0:
            start = max(0, i - width)
            end = min(len(text), i + len(w) + width)
            out = ("… " if start > 0 else "") + text[start:end] + (" …" if end < len(text) else "")
            return out
    return text[:170] + " … " + text[-170:]


def q_claim_source(card: dict, fr: dict, claims: list[dict], demand: str = "") -> dict | None:
    """Value/status claim grounding against code-selected observations (generalized)."""
    if not claims:
        return None
    anchor_ids = sorted({i for c in claims for i in c["flags"]["ids"]}
                        | {i for c in fr["resp_calls"] for i in (c.get("ids") or [])})
    sel = []
    if anchor_ids:
        sel = [o for o in fr["obs"] if set(o["ids"]) & set(anchor_ids)]
    val_tokens = set()
    for c in claims:
        for w in re.findall(r"\b[A-ZА-ЯЁ][a-zA-Zа-яё]{2,}\b|\b\d+(?:[.,]\d+)?\b", c["text"]):
            if w.lower() not in ("the", "для", "ваш", "это"):
                val_tokens.add(w)
        for s in c["flags"]["status"]:
            val_tokens |= set(fs.STATUS_LEX.get(s, set()))
    if not sel and val_tokens:
        low_join = [(o, (o["text"] + " " + json.dumps(o.get("kv") or {}, ensure_ascii=False)).lower())
                    for o in fr["obs"]]
        sel = [o for o, blob in low_join
               if any(w.lower() in blob for w in val_tokens)]
    if not sel:
        sel = fr["obs"]
    if not sel:
        return None
    latest = sel[-1]["id"]
    lines = ["OBSERVATIONS (chronological, verbatim tool results; " + latest + " is the LATEST shown):"]
    lines += [f"  {o['id']} [{o['tool']}]: {_obs_window(o['text'], val_tokens)}" for o in sel[-10:]]
    lines.append("CLAIM_SENTENCES (verbatim from the response):")
    lines += [f"  {c['id']}: {c['text']}" for c in claims[:6]]
    lines.append(f"JUDGE_DEMAND (verbatim): d1: {clip(demand, 320)}" if demand else "")
    lines.append("QUESTION: Pick the ONE claim sentence that asserts the concrete status, value or "
                 "amount that JUDGE_DEMAND disputes or calls unconfirmed. "
                 "Is that assertion SUPPORTED by the LATEST observation that mentions the same entity or "
                 "value, CONTRADICTED by it, or UNCLEAR (no matching observation)? Judge only factual "
                 "status/values, not style.")
    lines.append('ANSWER JSON: {"verdict":"SUPPORTED|CONTRADICTED|UNCLEAR","claim_id":"c#",'
                 '"obs_id":"o#|null","value":"<exact value words copied from the claim>","reason":"..."}')
    return {"type": "Q_CLAIM_SOURCE", "latest_id": latest, "user": "\n".join(lines)}


def q_demand_present(card: dict, claims: list[dict], asks: list[dict], demand: str) -> dict | None:
    """Does the response literally perform the behavior the judge demand says is missing?"""
    if not demand:
        return None
    frags = claims + asks
    if not frags:
        return None
    lines = [f"JUDGE_DEMAND (verbatim): d1: {clip(demand, 320)}"]
    lines.append("RESPONSE_SENTENCES (verbatim):")
    lines += [f"  {f['id']}: {f['text']}" for f in frags[:10]]
    lines.append("QUESTION: d1 claims the response fails to do something. Copy the demanded behavior "
                 "words from d1, then decide: does any RESPONSE_SENTENCE explicitly perform that exact "
                 "behavior (the instruction, ask, confirmation-wait, or acknowledgment d1 says is "
                 "missing)? PRESENT only for a literal match, not a paraphrase.")
    lines.append('ANSWER JSON: {"verdict":"PRESENT|ABSENT|UNCLEAR","fragment_id":"c#|a#|null",'
                 '"demand_part":"<copied from d1>","reason":"..."}')
    return {"type": "Q_DEMAND_PRESENT", "user": "\n".join(lines)}


def q_obligation_history(card: dict, fr: dict, demand: str) -> dict | None:
    """Only for ask-DIRECTIVE quotes: the policy orders the agent to ASK the user
    something (insurance/choice). Precondition phrasing ("obtain confirmation
    before executing X") is NOT an ask-directive: its satisfaction belongs to
    the action-precondition family, and a user confirmation in history must
    never discharge it (that false discharge killed true positives)."""
    quote = card.get("policy_quote") or ""
    if not (ASK_DIRECTIVE.search(quote) or ASK_DIRECTIVE.search(demand or "")):
        return None
    lines = ["POLICY_QUOTE (verbatim):", f"  p1: {clip(quote, 500)}"]
    lines.append(f"JUDGE_DEMAND (verbatim): d1: {clip(demand, 320)}")
    lines.append("PRIOR_USER_TURNS (verbatim, chronological):")
    lines += [f"  {u['id']}: {u['text']}" for u in fr["users"][:8]] or ["  NONE"]
    lines.append("QUESTION: Copy the item the policy requires asking the user about (insurance, "
                 "confirmation, choice...) from p1 or d1. Then decide: do PRIOR_USER_TURNS already show "
                 "that item being asked about or answered by the user (so a new ask in this response "
                 "was not required)? ALREADY_PRESENT only with a cited turn that mentions the item.")
    lines.append('ANSWER JSON: {"verdict":"ALREADY_PRESENT|ABSENT|UNCLEAR","evidence_id":"u#|null",'
                 '"required_item":"<copied from p1/d1>","reason":"..."}')
    return {"type": "Q_OBLIGATION_HISTORY", "user": "\n".join(lines)}


def _cond_facts_lines(fr: dict) -> list[str]:
    f = fr["facts"]
    lines = ["CODE FACTS (each computed from the ordered transcript; ids cite the sources):"]
    lines.append(f"  user_confirmation_before_response: {'YES' if f['confirmation_before_response'] else 'NO'}"
                 + (f" — {clip('; '.join(f['confirmation_texts']), 160)}" if f["confirmation_texts"] else ""))
    lines.append(f"  identity_verifications: {json.dumps(f['verification_matches'], ensure_ascii=False)[:300]}")
    lines.append(f"  authorizations: {json.dumps(f['authorizations'], ensure_ascii=False)[:300]}")
    lines.append(f"  latest_stock: {json.dumps(f['stock_latest'], ensure_ascii=False)[:300]}")
    lines.append(f"  prior_successes: {json.dumps(f['prior_successes'], ensure_ascii=False)[:300]}")
    lines.append(f"  response_calls: {json.dumps([{c['name']: c['kv']} for c in fr['resp_calls']], ensure_ascii=False)[:400]}")
    lines.append(f"  entity_ids_seen: {f['entities'][:10]}")
    return lines


def q_condition_applicable(card: dict, fr: dict, demand: str) -> dict | None:
    """The source-bound call/obligation verifier (entity, amount, latest observation,
    confirmation, moment of action). Model maps the quote; code verifies."""
    quote = card.get("policy_quote") or ""
    if not quote:
        return None
    directional = (AFTER_PATTERN.search(quote) or BEFORE_PATTERN.search(quote)
                   or WHEN_PATTERN.search(quote) or MAY_PATTERN.search(quote)
                   or QUOTE_ACTION_GOVERNED.search(quote))
    if not directional:
        return None
    lines = ["POLICY_QUOTE (verbatim):", f"  p1: {clip(quote, 700)}"]
    lines.append(f"JUDGE_DEMAND (verbatim): d1: {clip(demand, 320)}")
    lines += _cond_facts_lines(fr)
    lines.append("QUESTION: Map p1 to the action it governs and EVERY binding condition it imposes "
                 "on that action. Copy the governed action words from p1. For each condition, choose its TYPE "
                 "from: IDENTITY_VERIFIED, USER_CONFIRMATION, AUTHORIZATION_EXACT, STOCK_AVAILABLE, "
                 "PRIOR_SUCCESS, ENTITY_SAME, AMOUNT_EXACT, OTHER. Do NOT list explanatory clauses, "
                 "definitions, or permissions (may/can) as conditions — only binding requirements "
                 "imposed on the agent. Also give the DIRECTION of p1: "
                 "PRECONDITION (before doing A, satisfy C...), POSTCONDITION (after X, do Y), "
                 "PERMISSION (A is allowed only under C / if C, may do A), or REQUIREMENT (when C hold, "
                 "must do A). List EVERY condition; do not omit any.")
    lines.append('ANSWER JSON: {"governed_action":"<copied from p1>","direction":"PRECONDITION|'
                 'POSTCONDITION|PERMISSION|REQUIREMENT","conditions":[{"text":"<copied from p1>",'
                 '"type":"..."}],"reason":"..."}')
    return {"type": "Q_CONDITION_APPLICABLE", "user": "\n".join(lines)}


# ---------------- code verification of the new answers -------------------------------------------
def verify_claim_source(q: dict, ans: dict, ctx: dict) -> tuple[str, str]:
    v = str(ans.get("verdict", "UNCLEAR")).upper()
    claims, obs = ctx["claims"], ctx["obs"]
    if v in ("SUPPORTED", "CONTRADICTED"):
        cid = str(ans.get("claim_id") or "")
        claim = next((c for c in claims if c["id"] == cid), None)
        if claim is None:
            return "INCONSISTENT", f"cited claim {cid} not in fragment list"
        oid = str(ans.get("obs_id") or "")
        o = next((x for x in obs if x["id"] == oid), None)
        if v == "SUPPORTED":
            if o is None:
                return "INCONSISTENT", "SUPPORTED without citing an observation"
            value = str(ans.get("value") or "")
            if not value or not fuzzy_in(value, claim["text"], 0.60):
                return "INCONSISTENT", "cited value not found in the claim sentence"
            # amounts / ids are order-invariant (any observation counts); statuses
            # are order-sensitive (only the code-selected latest counts)
            amount_like = bool(re.search(r"\d", value))
            if amount_like:
                blob = " ".join(x["text"] for x in obs) + " " + json.dumps(
                    {k: vv for x in obs for k, vv in (x.get("kv") or {}).items()}, ensure_ascii=False)
                if not fuzzy_in(value, blob, 0.60) and value not in blob:
                    return "INCONSISTENT", "cited value not found in any observation"
                return "SUPPORTED", f"code verified value in obs {oid} (amount/id: order-invariant)"
            if oid != q.get("latest_id"):
                return "INCONSISTENT", f"cited {oid} but code selected {q.get('latest_id')} as latest"
            if not fuzzy_in(value, o["text"], 0.60) and value not in json.dumps(o.get("kv") or {}, ensure_ascii=False):
                return "INCONSISTENT", "cited value not found in the cited observation"
            return "SUPPORTED", f"code verified value in latest obs {oid}"
        if o is not None:
            value = str(ans.get("value") or "")
            conflict = value and not fuzzy_in(value, o["text"], 0.60) \
                and value not in json.dumps(o.get("kv") or {}, ensure_ascii=False)
            if conflict:
                return "CONTRADICTED", f"code verified: value absent from latest obs {oid}"
        return "UNCLEAR", "CONTRADICTED without code-verifiable mismatch; downgraded"
    return v, ""


def verify_demand_present(q: dict, ans: dict, ctx: dict) -> tuple[str, str]:
    v = str(ans.get("verdict", "UNCLEAR")).upper()
    if v == "PRESENT":
        fid = str(ans.get("fragment_id") or "")
        frag = next((f for f in ctx["claims"] + ctx["asks"] if f["id"] == fid), None)
        if frag is None:
            return "INCONSISTENT", f"cited fragment {fid} unknown"
        # a claim citation must itself perform the demanded behavior: carry a
        # wait/confirm marker or an explicit request verb; ask citations are fine
        if fid.startswith("c"):
            if not (WAIT_MARKER.search(frag["text"]) or ASK_VERB_ANY.search(frag["text"])):
                return "INCONSISTENT", "claim cited without wait/request marker"
        part = str(ans.get("demand_part") or "")
        if not part or not fuzzy_in(part, ctx["demand"], 0.60):
            return "INCONSISTENT", "demand_part not copied from d1"
        return "PRESENT", f"cited {fid}; demand part verbatim in d1"
    return v, ""


def q_handoff_trigger(card: dict, fr: dict, demand: str) -> dict | None:
    """For before-transfer quotes: is a transfer actually performed or claimed in the response?"""
    quote = card.get("policy_quote") or ""
    if not tq1.HANDOFF_FAMILY.search(quote):
        return None
    lines = ["POLICY_QUOTE (verbatim):", f"  p1: {clip(quote, 500)}"]
    lines.append("RESPONSE_TOOL_CALLS (complete list):")
    lines += [f"  {c['name']} {clip(c['args'], 100)}" for c in fr["resp_calls"][:5]] or ["  NONE"]
    lines.append("RESPONSE_SENTENCES (verbatim):")
    sents = fr["claims"] + fr["asks"]
    lines += [f"  {f['id']}: {f['text']}" for f in sents[:8]] or ["  NONE"]
    lines.append("QUESTION: Does the response itself perform or claim a handoff/transfer to a human "
                 "agent (a transfer tool call, or a sentence saying it transfers / passes to an "
                 "operator/specialist)? PRESENT only for an actual transfer in this response.")
    lines.append('ANSWER JSON: {"verdict":"PRESENT|ABSENT|UNCLEAR","evidence_id":"call-name|c#|a#|null",'
                 '"reason":"..."}')
    return {"type": "Q_HANDOFF_TRIGGER", "user": "\n".join(lines)}


def verify_handoff_trigger(q: dict, ans: dict, ctx: dict) -> tuple[str, str]:
    v = str(ans.get("verdict", "UNCLEAR")).upper()
    fr = ctx["fr"]
    transfer_call = [c["name"] for c in fr["resp_calls"] if "transfer" in c["name"].lower()]
    handoff_text = [f["text"] for f in fr["claims"] + fr["asks"]
                    if tq1.HUMAN_REQ.search(f["text"])
                    or re.search(r"передаю|передаю\s+.*специалист|перевожу\s+вас|переведу\s+к|"
                                 r"transferring you|passing you|connect you", f["text"], re.IGNORECASE)]
    if v == "PRESENT":
        eid = str(ans.get("evidence_id") or "")
        if eid in transfer_call or any(eid and eid in f.get("id", "") for f in fr["claims"] + fr["asks"]
                                       if tq1.HUMAN_REQ.search(f["text"])):
            return "PRESENT", f"cited {eid}"
        if transfer_call:
            return "PRESENT", f"code confirms transfer call {transfer_call}"
        return "INCONSISTENT", "PRESENT verdict but no transfer call or handoff text found"
    if v == "ABSENT":
        if transfer_call or handoff_text:
            return "INCONSISTENT", "ABSENT verdict but code finds transfer markers in the response"
        return "ABSENT", "code confirms: no transfer call and no handoff text in the response"
    return v, ""


def verify_obligation_history(q: dict, ans: dict, ctx: dict) -> tuple[str, str]:
    v = str(ans.get("verdict", "UNCLEAR")).upper()
    if v == "ALREADY_PRESENT":
        eid = str(ans.get("evidence_id") or "")
        turn = next((u for u in ctx["users"] if u["id"] == eid), None)
        if turn is None:
            return "INCONSISTENT", f"cited turn {eid} unknown"
        item = str(ans.get("required_item") or "")
        words = [w for w in re.split(r"\W+", (item or "").lower()) if len(w) > 3]
        turn_low = turn["text"].lower()
        hit = any(w in turn_low for w in words)
        if not hit:
            # bilingual topic bridge: English policy nouns vs Russian user turns
            for w in words:
                for ru in TOPIC_BRIDGE.get(w, ()):
                    if ru in turn_low:
                        hit = True
                        break
        if not words or not hit:
            return "INCONSISTENT", "required_item words not in cited turn (incl. topic bridge)"
        return "ALREADY_PRESENT", f"cited {eid}; item words present in the turn"
    return v, ""


def _check_condition(ctype: str, fr: dict, call_ids: set, call_amount) -> tuple[str, str]:
    """One typed condition -> (TRUE/FALSE/UNKNOWN, evidence)."""
    f = fr["facts"]
    if ctype == "IDENTITY_VERIFIED":
        if not f["verification_matches"]:
            return "UNKNOWN", "no identity-verification observation"
        hit = [v for v in f["verification_matches"] if not call_ids or set(v["ids"]) & call_ids]
        if hit:
            return "TRUE", f"match=true obs {hit[0]['obs_id']}"
        return "FALSE", "verification observed for another entity"
    if ctype == "USER_CONFIRMATION":
        if f["confirmation_before_response"]:
            return "TRUE", "user confirmation before response: " + clip(f["confirmation_texts"][0], 90)
        if f["n_user_turns"] == 0:
            return "UNKNOWN", "no user turns"
        return "FALSE", "no explicit user confirmation found in prior turns"
    if ctype == "AUTHORIZATION_EXACT":
        if not f["authorizations"]:
            return "UNKNOWN", "no authorization observation"
        ok = [a for a in f["authorizations"]
              if (not call_ids or str(a.get("case_id")) in call_ids)
              and (call_amount is None or str(a.get("amount")) == str(call_amount))]
        if ok:
            return "TRUE", f"granted auth {ok[0]['obs_id']} same case/amount"
        return "FALSE", "authorization for another case or amount"
    if ctype == "STOCK_AVAILABLE":
        if not f["stock_latest"]:
            return "UNKNOWN", "no inventory observation"
        # any device relevant to the call / request
        dev = sorted(f["stock_latest"])
        if not dev:
            return "UNKNOWN", "no device keyed stock"
        latest = f["stock_latest"][dev[-1]]
        return ("TRUE" if latest["available"] else "FALSE"), f"latest stock obs {latest['obs_id']}"
    if ctype == "PRIOR_SUCCESS":
        hits = [s for s in f["prior_successes"] if not call_ids or set(s["ids"]) & call_ids] \
            or f["prior_successes"]
        if hits:
            return "TRUE", f"prior success obs {hits[0]['obs_id']}"
        return "UNKNOWN", "no prior success observation (absence is not failure)"
    if ctype == "ENTITY_SAME":
        if not fr["resp_calls"]:
            return "UNKNOWN", "no call to bind"
        bound = all(set(c.get("ids") or []) & set(f["entities"]) for c in fr["resp_calls"])
        return ("TRUE" if bound else "UNKNOWN"), "call entities known from observations/request"
    if ctype == "AMOUNT_EXACT":
        if call_amount is None:
            return "UNKNOWN", "no amount in call"
        return "UNKNOWN", "amount cross-check requires request/obs match (not computed)"
    return "UNKNOWN", "untyped condition"


def verify_condition_applicable(q: dict, ans: dict, ctx: dict) -> tuple[str, str]:
    """Model mapping -> code verdict. Refutes only when every mapped condition is
    code-verified TRUE (or the quote does not govern the executed action)."""
    fr = ctx["fr"]
    quote = ctx["card"].get("policy_quote") or ""
    governed = str(ans.get("governed_action") or "")
    direction = str(ans.get("direction") or "").upper()
    conds = ans.get("conditions") or []
    # --- mapping sanity (code re-checks the model's copy work)
    if direction not in ("PRECONDITION", "POSTCONDITION", "PERMISSION", "REQUIREMENT"):
        return "UNKNOWN", "direction missing/invalid"
    if not governed or not fuzzy_in(governed, quote, 0.55):
        return "UNKNOWN", "governed action not copied from quote"
    typed = []
    for c in conds:
        text = str(c.get("text") or "")
        ctype = str(c.get("type") or "OTHER").upper()
        if ctype not in COND_TYPES:
            ctype = "OTHER"
        if text and not fuzzy_in(text, quote, 0.55):
            return "INCONSISTENT", "condition text not copied from quote"
        typed.append((ctype, text))
    # --- completeness: code patterns must be covered by the model's mapping
    code_types = {t for t, pat in COND_PATTERNS.items() if pat.search(quote)}
    model_types = {t for t, _ in typed}
    missing = code_types - model_types
    if missing:
        return "UNKNOWN", f"model omitted code-detected condition(s): {sorted(missing)}"
    # governed action must not overlap its own conditions: a mapping that names
    # the obligations themselves as the action ("verify identity" as governed)
    # inverts the quote's structure and must never certify anything
    gov_word_set = set(w for w in re.split(r"\W+", governed.lower()) if len(w) > 3)
    for _t, text in typed:
        if text:
            t_words = set(w for w in re.split(r"\W+", text.lower()) if len(w) > 3)
            if len(gov_word_set & t_words) >= 2:
                return "UNKNOWN", "governed action overlaps a mapped condition (mapping suspect)"
    # OTHER-typed conditions that actually match a code-checkable pattern are
    # mistyped obligations: certification is blocked
    for t, text in typed:
        if t == "OTHER" and any(pat.search(text or "") for pat in COND_PATTERNS.values()):
            return "UNKNOWN", f"OTHER-typed condition matches a checkable pattern: {text[:60]}"
    # --- coverage: every obligation phrase the quote itself states must be
    # accounted for by a mapped condition or the governed action; a silently
    # dropped binding clause ("list the action details") blocks certification
    covered_blob = " ".join([governed] + [text for _, text in typed])
    for phrase in QUOTE_OBLIGATION_PHRASES.findall(quote):
        if not fuzzy_in(phrase, covered_blob, 0.55):
            return "UNKNOWN", f"uncovered obligation phrase in quote: {phrase[:60]}"
    # --- code verdict from facts
    f = fr["facts"]
    call_names = [c["name"] for c in fr["resp_calls"]]
    call_ids = {i for c in fr["resp_calls"] for i in (c.get("ids") or [])}
    call_amount = None
    for c in fr["resp_calls"]:
        for key in ("amount", "fee", "cost"):
            if key in (c.get("kv") or {}):
                try:
                    call_amount = int(c["kv"][key])
                except (TypeError, ValueError):
                    call_amount = c["kv"][key]
    gov_words = [w for w in re.split(r"\W+", governed.lower()) if len(w) > 3]
    gov_match = any(any(w in n.lower() for w in gov_words) for n in call_names) if gov_words else False
    generic_gov = bool(GENERIC_GOVERNED.search(governed))
    manner_violation = (len(fr["resp_calls"]) > 1
                        or bool(fr["resp_calls"] and re.search(r"[а-яёa-z]{3,}", fr["resp_text"])))

    # a response with several calls, or a call plus text, has unverifiable call
    # manner: no condition certification is sound until manner is checked
    if manner_violation and fr["resp_calls"]:
        return "UNKNOWN", (f"call manner unverified ({len(fr['resp_calls'])} calls"
                           + (" + text" if fr["resp_text"] else "") + " in one response)")

    if direction == "PRECONDITION":
        if not fr["resp_calls"]:
            return "UNKNOWN", "no executing call in the response; precondition clause not exercised"
        if not gov_match and not generic_gov:
            if ctx["kind"] == "performed_action":
                return "REFUTED", (f"response executes {call_names}, not the governed action; "
                                   "this clause does not rule the executed call")
            return "UNKNOWN", "executed call not governed, but card kind is not performed_action"
        results = {t: _check_condition(t, fr, call_ids, call_amount) for t, _ in typed if t != "OTHER"}
        if any(v == "FALSE" for v, _ in results.values()):
            false_ones = [t for t, (v, _) in results.items() if v == "FALSE"]
            return "KEEP_VIOLATED", f"unmet condition(s): {false_ones} (code-verified)"
        if results and all(v == "TRUE" for v, _ in results.values()):
            return "REFUTED", "all mapped conditions code-verified TRUE: " + \
                "; ".join(f"{t}:{n}" for t, (v, n) in results.items())
        return "UNKNOWN", "some condition unverifiable from observations"
    if direction == "POSTCONDITION":
        # the AFTER-structure mechanically implies a prior-success antecedent;
        # code injects it even if the model typed the antecedent as OTHER
        typed_dict = {t: txt for t, txt in typed}
        if AFTER_PATTERN.search(quote) and "PRIOR_SUCCESS" not in typed_dict:
            typed.append(("PRIOR_SUCCESS", "after-success antecedent (code-injected)"))
        dep_match = gov_match
        prior = _check_condition("PRIOR_SUCCESS", fr, call_ids, call_amount)
        if fr["resp_calls"] and dep_match:
            if prior[0] == "TRUE":
                return "REFUTED", f"dependent action executed after prior success: {prior[1]}"
            if prior[0] == "UNKNOWN":
                return "KEEP_VIOLATED", "dependent action executed without observed prior success (premature)"
            return "KEEP_VIOLATED", "prior success contradicted"
        # dependent action NOT exercised in this response
        if prior[0] == "TRUE":
            return "KEEP_VIOLATED", "antecedent completed but dependent action not performed"
        qa = ctx.get("action_state")
        if qa and qa.get("checked_verdict") == "CLAIMED_COMPLETED":
            return "KEEP_VIOLATED", "completion claimed without the dependent call"
        if ctx["kind"] == "required_action_missing":
            return "UNKNOWN", ("antecedent-based alarm; code cannot certify the antecedent action "
                               "itself was not the missing obligation")
        return "REFUTED", ("obligation not yet due: no successful antecedent observation, "
                           "dependent action not called")
    if direction in ("PERMISSION", "REQUIREMENT"):
        if fr["resp_calls"] and not gov_match and not generic_gov \
                and ctx["kind"] == "performed_action":
            return "REFUTED", (f"response executes {call_names}, not the governed action; "
                               "this clause does not rule the executed call")
        results = {t: _check_condition(t, fr, call_ids, call_amount) for t, _ in typed if t != "OTHER"}
        if any(v == "FALSE" for v, _ in results.values()):
            false_ones = [t for t, (v, _) in results.items() if v == "FALSE"]
            if direction == "PERMISSION":
                return "KEEP_VIOLATED", f"permission condition(s) unmet: {false_ones}"
            return "REFUTED", f"requirement conditions not all hold ({false_ones}); clause inapplicable"
        if results and all(v == "TRUE" for v, _ in results.values()):
            if direction == "PERMISSION":
                return "REFUTED", "permission conditions code-verified TRUE: action permitted"
            return "UNKNOWN", "requirement conditions hold; check whether the action was performed"
        return "UNKNOWN", "permission/requirement conditions unverifiable"
    return "UNKNOWN", "unmapped direction"


NEW_VERIFIERS = {"Q_CLAIM_SOURCE": verify_claim_source,
                 "Q_DEMAND_PRESENT": verify_demand_present,
                 "Q_OBLIGATION_HISTORY": verify_obligation_history,
                 "Q_HANDOFF_TRIGGER": verify_handoff_trigger,
                 "Q_CONDITION_APPLICABLE": verify_condition_applicable}


# ---------------- v2 arbitration -----------------------------------------------------------------
def arbitrate_card(card: dict, qres: list[dict], fr: dict, sig_has_calls: bool,
                   structural_violation: bool) -> tuple[str, str]:
    by_type = {q["type"]: q for q in qres}
    quote = card.get("policy_quote") or ""
    kind = card.get("obligation_kind") or ""
    # 0) structural violation blocks every refutation (v4 guard principle)
    if structural_violation:
        return "KEEP", "structural violation present (undeclared tool / missing required args)"
    # 1) invented obligation (v1; live-call safety gate kept)
    qe = by_type.get("Q_QUOTE_ENTAILMENT")
    if qe and qe["checked_verdict"] == "NOT_ENTAILED" and not sig_has_calls:
        return "REFUTED", f"quote-entailment: demand not in policy quote ({qe['note']})"
    # 2) result claims: generalized latest-observation grounding
    if kind == "result_claim":
        qo = by_type.get("Q_CLAIM_SOURCE")
        if qo and qo["checked_verdict"] == "SUPPORTED":
            return "REFUTED", f"claim grounded in latest observation (code-checked): {qo['note']}"
        if qo and qo["checked_verdict"] == "CONTRADICTED":
            return "KEEP", f"claim contradicts latest observation: {qo['note']}"
        return "UNKNOWN", "no code-verified claim-source verdict"
    # 3) handoff family: trigger first (no transfer performed/claimed -> the
    #    before-transfer obligations are not exercised), then v1 code facts
    facts = fr["facts"]
    if tq1.HANDOFF_FAMILY.search(quote):
        qht = by_type.get("Q_HANDOFF_TRIGGER")
        if qht and qht["checked_verdict"] == "ABSENT" and kind in ("intent", "performed_action"):
            return "REFUTED", (f"no transfer performed or claimed in this response: {qht['note']}; "
                               "before-transfer obligations not exercised")
        if facts.get("request_count", 0) >= 4:
            return "REFUTED", f"code count: {facts['request_count']} human-agent requests >= 4"
        if (facts.get("kb_before_transfer", 0) >= 1 and facts.get("resp_has_transfer")
                and facts.get("last_user_req")):
            return "REFUTED", "code: KB searches precede the transfer; last user turn asks for a human"
        return "KEEP", "handoff obligation stands under code facts (v3.1 conjunction not met)"
    # 4) NEW: source-bound call/obligation verifier (live calls and typed directions)
    qc = by_type.get("Q_CONDITION_APPLICABLE")
    if qc:
        cv = qc["checked_verdict"]
        if cv == "REFUTED":
            return "REFUTED", f"condition-applicable: {qc['note']}"
        if cv == "KEEP_VIOLATED":
            return "KEEP", f"condition-applicable violation: {qc['note']}"
    # 5) NEW: demand literally performed (telecom t15 class) and required ask
    #    already in history (airline__24 class) — BEFORE the action-state KEEP,
    #    because a spurious demand or an already-answered ask invalidates the
    #    card regardless of the action-state phrasing
    qdp = by_type.get("Q_DEMAND_PRESENT")
    if qdp and qdp["checked_verdict"] == "PRESENT" and not sig_has_calls:
        return "REFUTED", f"demand literally performed in response: {qdp['note']}"
    qoh = by_type.get("Q_OBLIGATION_HISTORY")
    if qoh and qoh["checked_verdict"] == "ALREADY_PRESENT":
        return "REFUTED", f"required ask/choice already present in prior turns: {qoh['note']}"
    # 6) action-precondition family (v1; kind extended with intent; no live calls)
    live_action = sig_has_calls and (tq1.ACTION_PRECOND.search(quote) or kind in
                                     ("performed_action", "required_action_missing"))
    if not live_action and (tq1.ACTION_PRECOND.search(quote) or kind in
                            ("performed_action", "required_action_missing", "intent")):
        qa = by_type.get("Q_ACTION_STATE")
        qconf = by_type.get("Q_CONFIRMATION_ASKED")
        qrd = by_type.get("Q_REQUIRED_DATA")
        if qa is not None and qa["checked_verdict"] == "PROPOSED_ONLY" and not sig_has_calls:
            if qconf and qconf["checked_verdict"] == "YES":
                return "REFUTED", (f"action only proposed (code-checked) and response asks "
                                   f"confirmation: {qa['note']}; {qconf['note']}")
            if qrd and qrd["checked_verdict"] == "ALL_REQUESTED":
                return "REFUTED", f"action only proposed and required data requested: {qrd['note']}"
            return "UNKNOWN", "action proposed but no code-verified confirmation/data ask"
        if qa is not None and qa["checked_verdict"] in ("EXECUTED", "CLAIMED_COMPLETED"):
            return "KEEP", f"action executed or claimed done: {qa['note']}"
    # 6) required-data obligations fulfilled by asking (v1; generalized asks)
    qrd = by_type.get("Q_REQUIRED_DATA")
    if tq1.REQUIRED_DATA.search(quote) and not sig_has_calls and qrd \
            and qrd["checked_verdict"] == "ALL_REQUESTED":
        return "REFUTED", f"required data all requested: {qrd['note']}"
    # 7) trigger-governed obligations (v1)
    qt = by_type.get("Q_TRIGGER_PRESENT")
    if qt and qt["checked_verdict"] == "ABSENT":
        return "REFUTED", f"trigger absent (code cross-checked): {qt['note']}"
    if qt and qt["checked_verdict"] == "PRESENT":
        return "KEEP", f"trigger present: {qt['note']}"
    # 8) v1 logging rule (kept for public46 parity)
    if tq1.LOGGING_TOOL.search(quote):
        if facts.get("log_called_in_response"):
            return "KEEP", "code fact: log_verification called in the response while unverified"
        if not facts.get("verification_observation_present"):
            return "REFUTED", "code fact: no verification observation yet; logging obligation not due"
    # 9) conditional scope without live action (v1)
    if not live_action and not sig_has_calls and tq1.CONDITIONAL_SCOPE.search(quote):
        qa = by_type.get("Q_ACTION_STATE")
        if qa and qa["checked_verdict"] == "PROPOSED_ONLY":
            return "REFUTED", "conditional-scope quote; action only proposed (code-checked)"
    # 10) NEW: claim grounding for any kind when nothing else fired
    qo = by_type.get("Q_CLAIM_SOURCE")
    if qo and qo["checked_verdict"] == "SUPPORTED" and not sig_has_calls:
        return "REFUTED", f"claim grounded in latest observation (code-checked): {qo['note']}"
    return "KEEP", "no applicable typed refutation; conservative keep"


# ---------------- main ---------------------------------------------------------------------------
def build_questions(card: dict, fr: dict, demand: str) -> tuple[list[dict], dict]:
    claims, asks = fr["claims"], fr["asks"]
    qs = []
    qa = q_action_state(card, fr, claims, demand)
    if qa:
        qs.append(qa)
    if card.get("policy_quote") or demand:
        qs.append(tq1.q_quote_entailment(card, demand))
    if asks:
        qc = tq1.q_confirmation_asked(card, asks)
        if qc:
            qs.append(qc)
    qo = q_claim_source(card, fr, claims, demand)
    if qo:
        qs.append(qo)
    lfr = legacy_fr(fr)
    qrd = tq1.q_required_data(card, asks)
    if qrd:
        qs.append(qrd)
    qt = tq1.q_trigger_present(card, lfr, card.get("policy_quote") or "")
    if qt:
        qs.append(qt)
    qht = q_handoff_trigger(card, fr, demand)
    if qht:
        qs.append(qht)
    if demand:
        qdp = q_demand_present(card, claims, asks, demand)
        if qdp:
            qs.append(qdp)
    qoh = q_obligation_history(card, fr, demand)
    if qoh:
        qs.append(qoh)
    qca = q_condition_applicable(card, fr, demand)
    if qca:
        qs.append(qca)
    ctx = {"claims": claims, "asks": asks, "obs": fr["obs"], "users": fr["users"], "card": card,
           "fr": fr, "kind": card.get("obligation_kind") or "",
           "user_blob": " ".join(u["text"] for u in fr["users"]),
           "obs_blob": " ".join(o["text"] for o in fr["obs"][:8]),
           "resp_calls_blob": " ".join(c["name"] + " " + (c["args"] or "") for c in fr["resp_calls"]),
           "demand": demand}
    return qs, ctx


def verify(q: dict, ans: dict, ctx: dict) -> tuple[str, str]:
    t = q["type"]
    if t in NEW_VERIFIERS:
        return NEW_VERIFIERS[t](q, ans, ctx)
    if t == "Q_ACTION_STATE":
        v = str(ans.get("verdict", "UNCLEAR")).upper()
        calls = ctx["fr"]["facts"]["response_call_names"]
        if v == "EXECUTED":
            if calls:
                return "EXECUTED", f"code confirms {len(calls)} response call(s)"
            return "INCONSISTENT", "model says EXECUTED but code counts 0 response calls"
        if v == "PROPOSED_ONLY":
            if calls:
                return "INCONSISTENT", f"model says PROPOSED_ONLY but code finds calls {calls}"
            return "PROPOSED_ONLY", f"code confirms no executing response call (calls={calls})"
        if v == "CLAIMED_COMPLETED":
            did = str(ans.get("deciding_id") or "")
            claim = next((c for c in ctx["claims"] if c["id"] == did), None)
            if claim is not None and fs.FUTURE_LEX.search(claim["text"]):
                return "INCONSISTENT", ("model says CLAIMED_COMPLETED but the cited claim carries "
                                        "a future-offer marker (curated lexicon)")
        return v, "no code re-check for this verdict"
    if t == "Q_QUOTE_ENTAILMENT":
        return tq1.verify_answer(q, ans, ctx)
    if t == "Q_CONFIRMATION_ASKED":
        return tq1.verify_answer(q, ans, ctx)
    if t == "Q_REQUIRED_DATA":
        return tq1.verify_answer(q, ans, ctx)
    if t == "Q_TRIGGER_PRESENT":
        return tq1.verify_answer(q, ans, ctx)
    return "UNCLEAR", "unknown question type"


def code_facts_v1(fr: dict) -> dict:
    """v1-compatible facts (handoff counts, verification flag, log flag)."""
    users = fr["users"]
    timeline = fr["timeline"]
    call_names_prompt = [e["name"] for e in timeline if e["kind"] == "call" and not e.get("in_response")]
    kb = sum(1 for n in call_names_prompt if n.startswith("KB_search"))
    human_req = sum(1 for u in users if tq1.HUMAN_REQ.search(u["text"]))
    human_req += sum(1 for n in call_names_prompt if "request_human_agent_transfer" in n)
    transfer_idx = next((i for i, n in enumerate(call_names_prompt) if "transfer" in n), None)
    kb_before = kb if transfer_idx is None else sum(
        1 for n in call_names_prompt[:transfer_idx] if n.startswith("KB_search"))
    resp_names = [c["name"] for c in fr["resp_calls"]]
    verification_done = any(re.search(r"verif|identity|подтвержден|идентификац", (o["tool"] or ""), re.I)
                            for o in fr["obs"])
    return {"response_call_count": len(resp_names), "response_call_names": resp_names,
            "request_count": human_req, "kb_calls_total": kb, "kb_before_transfer": kb_before,
            "verification_observation_present": verification_done,
            "last_user_req": bool(users and tq1.HUMAN_REQ.search(users[-1]["text"])),
            "resp_has_transfer": any("transfer" in n for n in resp_names),
            "log_called_in_response": any("log_verification" in n for n in resp_names)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--records", type=Path, required=True)
    ap.add_argument("--cards", type=Path, required=True)
    ap.add_argument("--cases", type=Path, required=True)
    ap.add_argument("--gold", type=Path, default=None)
    ap.add_argument("--gold-json", type=Path, default=None)
    ap.add_argument("--no-gold", action="store_true")
    ap.add_argument("--v31", type=Path, required=True, help="base per-case decisions (v3.1/v4/modal-safe)")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--tag", default="_v2")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()

    recs = {json.loads(l)["id"]: json.loads(l) for l in open(args.records, encoding="utf-8")}
    cards_by_case = {json.loads(l)["id"]: (json.loads(l).get("cards") or [])
                     for l in open(args.cards, encoding="utf-8")}
    cases = {r["id"]: r for r in csv.DictReader(open(args.cases, encoding="utf-8"))}
    if args.no_gold or (args.gold is None and args.gold_json is None):
        gold = {}
    elif args.gold_json:
        gold = {k: int(v) for k, v in json.load(open(args.gold_json, encoding="utf-8")).items()}
    else:
        gold = {r["id"]: int(r["gold"]) for r in csv.DictReader(open(args.gold, encoding="utf-8"))}
    base = json.loads(args.v31.read_text(encoding="utf-8"))
    base_labels = {e["id"]: e["new_label"] for e in base.get("per_case", [])}

    surviving = [cid for cid in sorted(recs)
                 if recs[cid]["label"] == 1 and base_labels.get(cid, 1) == 1]
    if args.limit:
        surviving = surviving[: args.limit]

    client = None if args.dry else Mistral()
    args.out.mkdir(parents=True, exist_ok=True)
    per_case, n_calls = [], 0
    for cid in surviving:
        case = cases[cid]
        rec = recs[cid]
        fr = fs.supply_fragments(case)
        fr["facts"].update(code_facts_v1(fr))
        sig_has_calls = fr["facts"]["response_call_count"] > 0
        sv = v4mod.structural_violation(case["prompt"], case["response"])
        grounded = [c for c in cards_by_case.get(cid, []) if c.get("quote_grounded")]
        idxs = [i for i in (rec.get("violated_cards") or [])
                if isinstance(i, int) and 1 <= i <= len(grounded)]
        card_slots = [(i, grounded[i - 1]) for i in idxs] or [(None, None)]
        card_results = []
        for slot_idx, card in card_slots:
            demand = rec.get("reason") or ""
            qs, ctx = build_questions(card or {}, fr, demand)
            ctx["facts"] = fr["facts"]
            qres = []
            for q in qs:
                if args.dry:
                    qres.append({"type": q["type"], "model_verdict": None,
                                 "checked_verdict": "DRY", "note": "", "answer": None})
                    continue
                try:
                    ans = client.ask(SYSTEM, q["user"])
                    n_calls += 1
                    verdict, note = verify(q, ans["value"], ctx)
                    qres.append({"type": q["type"], "model_verdict": ans["value"].get("verdict"),
                                 "checked_verdict": verdict, "note": note, "answer": ans["value"]})
                    if q["type"] == "Q_ACTION_STATE":
                        ctx["action_state"] = {"checked_verdict": verdict}
                except Exception as exc:
                    qres.append({"type": q["type"], "model_verdict": None,
                                 "checked_verdict": "ERROR", "note": str(exc)[:200], "answer": None})
            if card is None:
                tq_verdict, tq_note = ("KEEP", "no grounded violated card; conservative keep")
                # demand-present can still clear a cardless alarm
                qdp = next((q for q in qres if q["type"] == "Q_DEMAND_PRESENT"), None)
                if qdp and qdp["checked_verdict"] == "PRESENT" and not sig_has_calls:
                    tq_verdict, tq_note = "REFUTED", f"demand literally performed: {qdp['note']}"
            else:
                ctx["action_state"] = next((q for q in qres if q["type"] == "Q_ACTION_STATE"), None)
                tq_verdict, tq_note = arbitrate_card(card, qres, fr, sig_has_calls, bool(sv))
            card_results.append({"card_index": slot_idx,
                                 "policy_quote": (card or {}).get("policy_quote"),
                                 "obligation_kind": (card or {}).get("obligation_kind"),
                                 "questions": qres, "tq_verdict": tq_verdict, "tq_evidence": tq_note,
                                 "fragments": {"claims": [{"id": c["id"], "text": c["text"]}
                                                          for c in fr["claims"][:6]],
                                               "asks": [{"id": a["id"], "text": a["text"]}
                                                        for a in fr["asks"][:4]],
                                               "obs_ids": [o["id"] for o in fr["obs"][:8]],
                                               "response_calls": [c["name"] for c in fr["resp_calls"]]}})
        all_refuted = bool(card_results) and all(cr["tq_verdict"] == "REFUTED" for cr in card_results)
        any_unknown = any(cr["tq_verdict"] == "UNKNOWN" for cr in card_results)
        new_label = 0 if all_refuted else 1
        per_case.append({"id": cid, "gold": gold.get(cid), "v31_label": 1, "new_label": new_label,
                         "facts": {k: fr["facts"].get(k) for k in
                                   ("response_call_count", "response_call_names",
                                    "confirmation_before_response", "structural_violation")},
                         "structural_violation": bool(sv),
                         "cards": card_results, "any_unknown": any_unknown})

    base_rows = base.get("per_case", [])
    removed = [row["id"] for row in per_case if row["new_label"] == 0]
    res = {"layer": "typed-question layer v2 (domain-general fragments + generalized mechanisms)",
           "model": tq1.mistral_settings()["MISTRAL_MODEL"], "n_model_calls": n_calls,
           "dry": args.dry, "n_surviving": len(surviving), "base": str(args.v31),
           "removed": removed, "removed_count": len(removed), "per_case": per_case}
    if gold and all(row.get("gold") in (0, 1) for row in base_rows):
        base_tp = sum(row["new_label"] == 1 and gold.get(row["id"]) == 1 for row in base_rows)
        base_fp = sum(row["new_label"] == 1 and gold.get(row["id"]) == 0 for row in base_rows)
        tp_lost = [row["id"] for row in per_case if row["new_label"] == 0 and gold.get(row["id"]) == 1]
        after_tp = base_tp - len(tp_lost)
        after_fp = base_fp - (len(removed) - len(tp_lost))
        res.update({"base_confusion": {"TP": base_tp, "FP": base_fp},
                    "after": {"TP": after_tp, "FP": after_fp, "FN": len(tp_lost)},
                    "tp_lost": tp_lost})
    out_name = f"tq_questions{args.tag}.json"
    (args.out / out_name).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in res.items() if k != "per_case"}, ensure_ascii=False, indent=1))
    for e in per_case:
        print(f"{e['id'][:56]:56s} gold={e['gold']} new={e['new_label']} "
              f"cards={[c['tq_verdict'] for c in e['cards']]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
