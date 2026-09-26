#!/usr/bin/env python3
"""Domain-general mechanical fragment supplier (2026-09-25, task (b)).

Replaces the banking/hotel-lexical fragment extraction of tq_questions.py v1
(whose FUTURE_OFFER lexicon missed «запишу», whose ID regex missed «SD-5101»,
whose ACTION_TOOL_HINTS knew no service-desk tools, and whose claim list was
therefore empty on the third domain — the measured fragment-supply failure).

Principles:
- EVERY fragment is verbatim text with a stable id and code-computed flags.
- NO domain lexicon decides what becomes a fragment: claims are ALL declarative
  sentences of the response (capped); asks are ALL interrogative or imperative
  request sentences; observations are ALL tool responses, JSON-parsed.
- The entity vocabulary is DATA-DRIVEN: ids are read out of observation JSON
  values (any *_id key, any value matching the generic id shape), user turns
  and the response — never from a hand-written per-domain list.
- Tense/status markers are recorded as FLAGS for the trace only; they never
  decide a refutation (the model judges, code re-verifies cited ids and
  call-count facts, exactly as in the frozen v1 discipline).
- The transcript is parsed into an ORDERED event timeline (user turns, assistant
  text, tool calls, tool responses) so "before/after" and "latest" are code
  facts: the temporal/ordering material the new typed questions need.
"""
from __future__ import annotations

import csv
import json
import re

csv.field_size_limit(2 ** 30)

# ---------------- transcript markers (competition transport; domain-independent) -------------
CALL_LINE = re.compile(r"→ TOOL_CALL ([\w.-]+)(?:\s*:\s*(\{.*?\}))?\s*$", re.MULTILINE)
RESP_LINE = re.compile(r"← TOOL_RESPONSE ([\w.-]+): (.*)")
USER_TURN = re.compile(r"⟦USER⟧\n(.*?)(?=⟦|\Z)", re.DOTALL)
ASST_TURN = re.compile(r"⟦ASSISTANT(?: · ход (\d+))?⟧\n(.*?)(?=⟦|\Z)", re.DOTALL)
SENT_SPLIT = re.compile(r"(?<=[.!?…])\s+|\n+")

# ---------------- generic value markers --------------------------------------------------------
ID_SHAPE = re.compile(r"\b[A-Z]{2,}(?:-\d{2,})?\d{2,}\b|\b\d{6,}\b")  # SD-5101, HAT317, W1234567...
AMOUNT = re.compile(r"\$\s?\d{1,6}(?:[.,]\d+)?|\b\d{1,6}(?:[.,]\d+)?\s?(?:руб\.?|₽|USD|RUB|долл)", re.IGNORECASE)
ANY_ID_KEY = re.compile(r"(?:^|_)(?:id|Id|ID)$|^(?:case|device|account|card|booking|order|reservation|"
                        r"incident|profile|user|ticket|police|claim|contract|ref)$", re.IGNORECASE)

# ---------------- soft flags (trace metadata only; never refutation evidence) -----------------
FUTURE_LEX = re.compile(r"(оформлю|забронирую|отменю|произведу|обработаю|верну|сделаю|переведу|запишу|"
                        r"выполню|закажу|отправлю|сообщу|предложу|проверю|создам|удалю|изменю|обновлю|"
                        r"активирую|заблокирую|верну|выплачу|начислю|передам|проведу|оформим|выполним|"
                        r"(?:will|shall|i'll|we'll)\b|going to|happy to|как только вы|после вашего|"
                        r"once you|after you)", re.IGNORECASE)
PAST_LEX = re.compile(r"(?:успешно|уже|сделано|выполнено|готово|оформлен|завершен|разморожен|активн|"
                      r"закрыт|отменен|processed|completed|confirmed|refunded|cancelled|activated|"
                      r"unfrozen|booked|has been|was)\b", re.IGNORECASE)
RU_1SG_FUTURE = re.compile(r"\b(?:я\s+|,\s*)?[а-яё]+(?:шу|щу|жу|чу|ду|ту|ну|му|лу|бу|ву|гу|ку|пу|ру|"
                           r"су|цу|зу|фу|ху|влю|плю|блю|флю|млю|нлю|рлю|лю|рую|ую|аю|ию)\b")
IMPERATIVE_ASK_RU = re.compile(r"(?:^|[.\n!?]\s*)(?:укажите|предоставьте|подтвердите|введите|напишите|"
                               r"скажите|выберите|сообщите|отправьте|проверьте|назовите|передайте|"
                               r"уточните|ответьте)\b", re.IGNORECASE)
ASK_LEX = re.compile(r"(подтверд|да или нет|«да»|ответьте|выберите|что вы выберете|напишите какой|"
                     r"уточните|хотите|пожалуйста|please (?:confirm|provide|select|specify|enter|state)|"
                     r"could you (?:confirm|provide)|would you like|kindly)", re.IGNORECASE)
CONFIRM_YES = re.compile(r"(да[, .]{0,3}(?:я\s+)?подтвержд\w*|подтвержда\w+|подтвердил[аи]?|"
                         r"соглас[аие]н|yes[, .]{0,3}i\s+confirm|^confirm|confirmed|approv\w+|"
                         r"соглас\w+ на)", re.IGNORECASE)
DECLINE_NO = re.compile(r"(не хочу|не нужна|не нужно|отказ\w+|без страховк|no[, .](?:i do not|thanks)|"
                        r"don't want|do not want|decline)", re.IGNORECASE)
STATUS_LEX = {
    "active": {"активн", "active", "разморожен", "unfrozen", "confirmed", "подтвержд", "granted", "open"},
    "frozen": {"заморожен", "frozen"},
    "closed": {"закрыт", "closed", "deactiv", "деактив"},
    "failed": {"не прош", "failed", "declined", "отклон", "error", "ошибк"},
    "success": {"успешн", "successful", "успешно", "completed", "выполнено"},
    "pending": {"pending", "в обработке", "ожидает", "in progress"},
    "cancelled": {"отмен", "cancelled", "canceled"},
    "available": {"available", "доступн", "в наличии"},
    "unavailable": {"unavailable", "отсутств", "нет в наличии", "out of stock"},
}
OK_KV_VALUES = {"true", "granted", "completed", "success", "successful", "active", "yes", "confirmed",
                "approved", "available", "open", "match"}
BAD_KV_VALUES = {"false", "denied", "declined", "failed", "error", "no", "rejected", "unavailable",
                 "closed", "missing"}


# ---------------- helpers ---------------------------------------------------------------------
def sentences(text: str, lo: int = 12, hi: int = 500, cap: int = 10) -> list[str]:
    out = []
    for chunk in SENT_SPLIT.split(text or ""):
        chunk = chunk.strip()
        if lo <= len(chunk) <= hi:
            out.append(chunk)
    return out[:cap]


def clip(text: str, limit: int) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 3] + "..."


def try_json(raw: str) -> dict:
    try:
        v = json.loads(raw)
        return v if isinstance(v, dict) else {}
    except Exception:
        return {}


def kv_ids(kv: dict) -> list[str]:
    out = []
    for k, v in kv.items():
        if isinstance(v, str):
            if ANY_ID_KEY.search(k) or ID_SHAPE.fullmatch(v or ""):
                out.append(v)
        elif isinstance(v, (int,)) and ANY_ID_KEY.search(k):
            out.append(str(v))
    return out


def status_flags(text: str) -> list[str]:
    low = (text or "").lower()
    return [k for k, ws in STATUS_LEX.items() if any(w in low for w in ws)]


# ---------------- transcript timeline ----------------------------------------------------------
def parse_timeline(prompt: str, response: str) -> list[dict]:
    """Ordered events: user turns, assistant text, tool calls, tool responses.

    The prompt carries the whole prior history; the response contributes the
    final assistant turn (its calls and text) as the LAST events.
    """
    events: list[dict] = []
    spans: list[tuple[int, int, str]] = []
    for m in USER_TURN.finditer(prompt or ""):
        spans.append((m.start(), m.end(), "user"))
    for m in ASST_TURN.finditer(prompt or ""):
        spans.append((m.start(), m.end(), "asst"))
    spans.sort()
    for start, end, kind in spans:
        block = prompt[start:end]
        turn_no = None
        am = ASST_TURN.match(block) if kind == "asst" else None
        if am:
            turn_no = int(am.group(1)) if am.group(1) else None
        body = block.split("⟧\n", 1)[1] if "⟧\n" in block else ""
        text_lines = [ln for ln in body.splitlines()
                      if ln.strip() and not ln.strip().startswith(("→", "←"))]
        if kind == "user":
            events.append({"kind": "user", "text": body.strip()})
        else:
            if text_lines:
                events.append({"kind": "asst_text", "text": "\n".join(text_lines).strip()})
        for cm in CALL_LINE.finditer(body):
            events.append({"kind": "call", "name": cm.group(1), "args": (cm.group(2) or "").strip()})
        for rm in RESP_LINE.finditer(body):
            events.append({"kind": "obs", "tool": rm.group(1), "text": rm.group(2).strip()})
    # final response events
    for cm in CALL_LINE.finditer(response or ""):
        events.append({"kind": "call", "name": cm.group(1), "args": (cm.group(2) or "").strip(),
                       "in_response": True})
    resp_text_lines = [ln for ln in (response or "").splitlines()
                       if ln.strip() and not ln.strip().startswith(("→", "←", "⟦"))]
    if resp_text_lines:
        events.append({"kind": "asst_text", "text": "\n".join(resp_text_lines).strip(),
                       "in_response": True})
    for rm in RESP_LINE.finditer(response or ""):
        events.append({"kind": "obs", "tool": rm.group(1), "text": rm.group(2).strip(),
                       "in_response": True})
    for i, e in enumerate(events):
        e["index"] = i
    return events


# ---------------- the supplier ------------------------------------------------------------------
def supply_fragments(case: dict) -> dict:
    prompt, response = case.get("prompt", ""), case.get("response", "")
    timeline = parse_timeline(prompt, response)

    resp_calls = [e for e in timeline if e["kind"] == "call" and e.get("in_response")]
    resp_text = "\n".join(e["text"] for e in timeline
                          if e["kind"] == "asst_text" and e.get("in_response"))
    obs_all = [e for e in timeline if e["kind"] == "obs"]
    user_turns = [e for e in timeline if e["kind"] == "user"]

    # ---- entity vocabulary: data-driven (observation JSON values + response + user turns)
    entities: list[str] = []
    for e in obs_all:
        e["kv"] = try_json(e["text"])
        for i in kv_ids(e["kv"]) + ID_SHAPE.findall(e["text"]):
            if i not in entities:
                entities.append(i)
    blob = " ".join([resp_text] + [u["text"] for u in user_turns])
    for i in ID_SHAPE.findall(blob):
        if i not in entities:
            entities.append(i)

    # ---- claims: ALL declarative sentences of the final response
    claims = []
    for s in sentences(resp_text):
        claims.append({"id": f"c{len(claims) + 1}", "text": clip(s, 240),
                       "flags": {"ids": ID_SHAPE.findall(s), "amounts": AMOUNT.findall(s),
                                 "future": bool(FUTURE_LEX.search(s)),
                                 "ru_future": bool(RU_1SG_FUTURE.search(s)),
                                 "past": bool(PAST_LEX.search(s)),
                                 "status": status_flags(s)}})

    # ---- asks: interrogative or imperative-request sentences of the final response
    asks = []
    for s in sentences(resp_text):
        if "?" in s or ASK_LEX.search(s) or IMPERATIVE_ASK_RU.search(s):
            asks.append({"id": f"a{len(asks) + 1}", "text": clip(s, 240),
                         "flags": {"confirm": bool(CONFIRM_YES.search(s)),
                                   "ids": ID_SHAPE.findall(s), "amounts": AMOUNT.findall(s)}})

    # ---- observations: all, JSON-parsed, with ids/status/ok flags
    # (full text kept: the deciding field often sits deep in long JSON —
    # consumers clip/window at display time, never here)
    obs = []
    for e in obs_all:
        kv = e.get("kv") or try_json(e["text"])
        ok = any(str(v).lower() in OK_KV_VALUES for v in kv.values())
        bad = any(str(v).lower() in BAD_KV_VALUES for v in kv.values())
        obs.append({"id": f"o{len(obs) + 1}", "tool": e["tool"], "text": e["text"],
                    "index": e["index"], "kv": kv, "ids": kv_ids(kv) + ID_SHAPE.findall(e["text"]),
                    "ok_flag": ok, "bad_flag": bad, "status": status_flags(e["text"])})

    # ---- users with confirmation / decline flags
    users = [{"id": f"u{len(user_turns) - i}", "text": clip(u["text"], 240), "index": u["index"],
              "flags": {"confirm": bool(CONFIRM_YES.search(u["text"])),
                        "decline": bool(DECLINE_NO.search(u["text"])),
                        "ids": ID_SHAPE.findall(u["text"]),
                        "amounts": AMOUNT.findall(u["text"])}} for i, u in enumerate(user_turns)]

    # ---- call args parsed
    calls = []
    for e in resp_calls:
        kv = try_json(e["args"])
        calls.append({"name": e["name"], "args": clip(e["args"], 200), "kv": kv,
                      "ids": kv_ids(kv) + ID_SHAPE.findall(e["args"]),
                      "amounts": AMOUNT.findall(e["args"])})

    fr = {"timeline_len": len(timeline), "claims": claims, "asks": asks, "obs": obs,
          "users": users, "resp_calls": calls, "entities": entities,
          "resp_text": resp_text, "timeline": timeline}
    fr["facts"] = code_facts(fr)
    return fr


# ---------------- code facts (generic, computed from the timeline) ------------------------------
def code_facts(fr: dict) -> dict:
    """Domain-independent satisfaction facts for the new typed questions.

    All are computed from parsed JSON key/values and event ORDER — no per-domain
    lexicon beyond the shared marker sets above. Each fact names its sources so
    the trace can cite them.
    """
    timeline = fr["timeline"]
    resp_calls = fr["resp_calls"]
    resp_call_names = [c["name"] for c in resp_calls]
    first_resp_idx = min((e["index"] for e in timeline
                          if e.get("in_response")), default=len(timeline))

    # 1) explicit user confirmation BEFORE the response (code)
    confirmations = [u for u in fr["users"] if u["flags"]["confirm"] and u["index"] < first_resp_idx]
    # 2) identity/verification matches (kv match=true or verified status), before response
    verifications = [o for o in fr["obs"]
                     if (str(o["kv"].get("match", "")).lower() == "true"
                         or any(s in ("active", "success", "confirmed") for s in o["status"])
                         and re.search(r"verif|identity|подтвержд|личност|match", o["tool"] + " " + o["text"], re.I))
                     and o["index"] < first_resp_idx]
    verifications = [o for o in verifications if str(o["kv"].get("match", "")).lower() == "true"
                     or re.search(r"verif|identity|личност", (o["tool"] or ""), re.I)]
    # 3) authorizations (granted), with case/amount binding
    authorizations = [o for o in fr["obs"]
                      if str(o["kv"].get("authorization_status", o["kv"].get("status", ""))).lower()
                      in ("granted", "authorized", "approved") and o["index"] < first_resp_idx]
    # 4) latest stock per device (kv has "available")
    stock_latest: dict[str, dict] = {}
    for o in fr["obs"]:
        if "available" in o["kv"] or any(s in ("available", "unavailable") for s in o["status"]):
            for d in (o["ids"] or [None]):
                stock_latest[str(d)] = {"available": str(o["kv"].get("available", "")).lower()
                                        == "true" or "available" in o["status"],
                                        "obs_id": o["id"], "index": o["index"], "text": o["text"]}
    # 5) prior success events (status completed/success) per entity
    successes = [o for o in fr["obs"] if o["index"] < first_resp_idx and (
        str(o["kv"].get("status", "")).lower() in ("completed", "success", "successful")
        or "success" in o["status"])]
    # 6) results of the response's own calls (obs in response after each call)
    call_results = []
    for c in resp_calls:
        call_ev_idx = next((e["index"] for e in timeline if e["kind"] == "call"
                            and e.get("in_response") and e["name"] == c["name"]
                            and e["args"] == c["args"]), None)
        after = [o for o in fr["obs"] if o["tool"] == c["name"]
                 and (call_ev_idx is None or o["index"] > call_ev_idx)]
        call_results.append({"call": c["name"], "result": after[0] if after else None})

    facts = {
        "response_call_count": len(resp_call_names),
        "response_call_names": resp_call_names,
        "confirmation_before_response": bool(confirmations),
        "confirmation_texts": [u["text"] for u in confirmations],
        "verification_matches": [{"obs_id": o["id"], "ids": o["ids"], "kv": o["kv"]} for o in verifications],
        "authorizations": [{"obs_id": o["id"], "case_id": o["kv"].get("case_id"),
                            "amount": o["kv"].get("amount")} for o in authorizations],
        "stock_latest": stock_latest,
        "prior_successes": [{"obs_id": o["id"], "tool": o["tool"], "ids": o["ids"],
                             "kv": o["kv"]} for o in successes],
        "call_results": call_results,
        "n_user_turns": len(fr["users"]),
        "entities": fr["entities"],
    }
    return facts
