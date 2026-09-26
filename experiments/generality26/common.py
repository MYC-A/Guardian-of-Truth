#!/usr/bin/env python3
"""Shared utilities for the 2026-09-26 generality probe suite (Stage B).

Design principles (from the cycle directive):
- joins are (key, value)-anchored on parsed JSON, never on tool-name lexicons;
- tool semantics come from the CATALOG (name morphology + description + arg
  schema shape), not from hand-written per-domain lists;
- absence of a join degrades to UNKNOWN, never to a permissive default;
- every verdict carries its evidence.
"""
from __future__ import annotations

import csv
import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

csv.field_size_limit(2 ** 30)

REPO = Path(os.environ.get("GOT_ROOT", "/mnt/data/guardian/agent-workspace/Guardian-of-Truth"))
SEARH = REPO / "experiments" / "searh_23"
GENERality = Path(__file__).resolve().parent
sys.path.insert(0, str(SEARH))

MISTRAL_ENV_CANDIDATES = [
    Path("/mnt/data/guardian/agent-workspace/.mistral.env"),
    REPO.parent / ".mistral.env",
]


def mistral_settings() -> dict:
    saved = {}
    for p in MISTRAL_ENV_CANDIDATES:
        if p.is_file():
            for raw in p.read_text(encoding="utf-8").splitlines():
                line = raw.strip()
                if line.startswith("export "):
                    line = line[7:].strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                if k.strip() in {"MISTRAL_API_KEY", "MISTRAL_MODEL"}:
                    saved[k.strip()] = v.strip().strip("\"'")
            break
    return {"MISTRAL_API_KEY": os.environ.get("MISTRAL_API_KEY") or saved.get("MISTRAL_API_KEY", ""),
            "MISTRAL_MODEL": os.environ.get("MISTRAL_MODEL") or saved.get("MISTRAL_MODEL", "ministral-14b-latest")}


class Mistral:
    """Minimal Mistral JSON-mode client (rate-limited, 3 retries)."""

    def __init__(self):
        s = mistral_settings()
        self.model = s["MISTRAL_MODEL"]
        self.key = s["MISTRAL_API_KEY"]
        if not self.key:
            raise RuntimeError("MISTRAL_API_KEY missing")
        self._next = 0.0

    def ask(self, system: str, user: str, *, max_tokens: int = 300) -> dict:
        payload = {"model": self.model, "temperature": 0, "max_tokens": max_tokens,
                   "messages": [{"role": "system", "content": system},
                                {"role": "user", "content": user}],
                   "response_format": {"type": "json_object"}}
        last = None
        for _ in range(3):
            pause = self._next - time.monotonic()
            if pause > 0:
                time.sleep(pause)
            self._next = time.monotonic() + 2.0
            req = urllib.request.Request(
                "https://api.mistral.ai/v1/chat/completions",
                data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                headers={"Authorization": f"Bearer {self.key}",
                         "Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=90) as r:
                    body = json.loads(r.read().decode("utf-8"))
                text = body["choices"][0]["message"]["content"]
                clean = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
                return {"value": json.loads(clean), "usage": body.get("usage", {})}
            except Exception as e:  # noqa: BLE001
                last = e
                time.sleep(3.0)
        raise RuntimeError(f"mistral failed: {last}")


# ---------------- tool catalog -----------------------------------------------------------------
CATALOG_RE = re.compile(r"\[AVAILABLE TOOLS\](.*?)⟦ASSISTANT⟧", re.DOTALL)
TOOL_LINE = re.compile(r"-\s+([\w.-]+)\s+—\s+(.+)")
ARG_LINE = re.compile(r"^\s+(\w+):\s+(\w+)!\s+—\s+(.*)$")


def parse_catalog(prompt: str) -> dict[str, dict]:
    """name -> {description, args: {arg: {type, desc}}} — from the prompt's catalog."""
    m = CATALOG_RE.search(prompt or "")
    if not m:
        return {}
    out: dict[str, dict] = {}
    cur = None
    for line in m.group(1).splitlines():
        tm = TOOL_LINE.match(line)
        if tm:
            cur = tm.group(1)
            out[cur] = {"description": tm.group(2).strip(), "args": {}}
            continue
        am = ARG_LINE.match(line)
        if am and cur:
            out[cur]["args"][am.group(1)] = {"type": am.group(2), "desc": am.group(3).strip()}
    return out


# ---------------- generic effect typing (morphology + schema shape) -----------------------------
READ_VERBS = ("get", "read", "check", "lookup", "find", "search", "list", "view", "show",
              "query", "fetch", "inspect", "load", "match", "verify", "obtain", "see",
              "retrieve", "lookup", "locate")
JOURNAL_VERBS = ("write", "log", "record", "audit", "note", "annotate", "save", "report",
                 "document")
DEFER_VERBS = ("schedule", "queue", "defer", "postpone", "enqueue", "reserve", "hold")
COMMUNICATE_VERBS = ("send", "notify", "message", "email", "sms", "call", "reply", "ask",
                     "tell", "inform")
MUTATION_VERBS = ("execute", "perform", "replace", "cancel", "refund", "create", "update",
                  "modify", "delete", "remove", "add", "issue", "submit", "pay", "activate",
                  "block", "freeze", "unfreeze", "exchange", "approve", "authorize", "swap",
                  "book", "transfer", "close", "open", "set", "apply", "run", "do", "make",
                  "handle", "process", "complete", "finish", "submit")
NOOP_NAMES = {"think", "calculate", "noop", "plan"}
# verbs that override the mutation default when the object is a human/channel
HUMAN_OBJECT = re.compile(r"human|agent|specialist|expert|operator|support|user\b", re.I)
JOURNAL_ARG_HINT = re.compile(r"^(action|note|text|message|comment|summary|reason|description|content|title|label)$", re.I)


def _name_verbs(name: str) -> list[str]:
    parts = re.split(r"[_.\-\s]+", name.lower())
    return [p for p in parts if p]


def effect_type(tool: str, catalog: dict[str, dict] | None = None) -> str:
    """Classify a tool's effect class from generic naming morphology + schema shape.

    Returns one of READ / JOURNAL / DEFER / COMMUNICATE / MUTATION / NOOP.
    This is deliberately generic (English tool-naming conventions), not a
    per-domain lexicon; it is a PROPOSER-class signal, and its measured
    accuracy on three domains is reported by probe_b2.
    """
    entry = (catalog or {}).get(tool) or {}
    desc = entry.get("description", "")
    args = entry.get("args") or {}
    verbs = _name_verbs(tool)
    if tool.lower() in NOOP_NAMES or verbs[:1] == ["think"]:
        return "NOOP"
    # COMMUNICATE: transfer_to_X / route_to_X / send_X where object is a human
    if HUMAN_OBJECT.search(desc) and any(v in verbs for v in ("transfer", "route", "escalate", "handoff", "hand")):
        return "COMMUNICATE"
    if any(v in verbs for v in COMMUNICATE_VERBS[:8]) and HUMAN_OBJECT.search(desc):
        return "COMMUNICATE"
    # permission-creating verbs dominate (authorize/approve/grant create an
    # authorization — a permission fact — even if the description says "record")
    if any(v in verbs for v in ("authorize", "approve", "grant")):
        return "MUTATION"
    # JOURNAL: writes a record; schema has a free-text/annotation argument
    if any(v in verbs for v in JOURNAL_VERBS):
        return "JOURNAL"
    if JOURNAL_ARG_HINT.search(" ".join(args)) and not any(v in verbs for v in MUTATION_VERBS):
        return "JOURNAL"
    # DEFER
    if any(v in verbs for v in DEFER_VERBS):
        return "DEFER"
    # READ
    if any(v in verbs for v in READ_VERBS):
        return "READ"
    # description head verb ("Read one support case", "Replace the requested device")
    head = (desc or "").strip().split()[0].lower().strip("s") if desc else ""
    if head in READ_VERBS:
        return "READ"
    if head in JOURNAL_VERBS:
        return "JOURNAL"
    if head in DEFER_VERBS:
        return "DEFER"
    if head in COMMUNICATE_VERBS and HUMAN_OBJECT.search(desc):
        return "COMMUNICATE"
    # MUTATION (default for causative verbs, entity-id + amount schema)
    if any(v in verbs for v in MUTATION_VERBS) or head in MUTATION_VERBS:
        return "MUTATION"
    if args and all(a.lower().endswith("id") for a in args):
        return "READ"  # pure identifier-keyed lookup shape
    return "MUTATION" if args else "READ"


# ---------------- typed fact extraction over the timeline ---------------------------------------
POSITIVE_VALUES = {"true", "granted", "authorized", "approved", "confirmed", "yes", "success",
                   "successful", "completed", "available", "open", "active", "match", "valid"}
NEGATIVE_VALUES = {"false", "denied", "declined", "rejected", "failed", "error", "no",
                   "unavailable", "closed", "missing", "invalid", "not_found", "mismatch"}
STATUS_KEYS = ("status", "authorization_status", "approval_status", "result", "state",
               "outcome", "match", "available", "success")
ID_ARG_KEYS = re.compile(r"(?:^|_)(?:id|Id|ID)$")


def try_json(raw: str):
    try:
        v = json.loads(raw)
        return v if isinstance(v, dict) else {}
    except Exception:
        return {}


def arg_id_keys(kv: dict) -> set[str]:
    return {k for k in kv if ID_ARG_KEYS.search(k)}


def join_values(a: dict, b: dict, shared_keys: set[str]) -> bool:
    """Value-anchored join: every shared key must have equal values (both parsed)."""
    return all(str(a.get(k)) == str(b.get(k)) for k in shared_keys)


def extract_facts(case: dict, catalog: dict[str, dict]) -> dict:
    """Typed facts from the transcript, joined by (key,value), never by tool name.

    Uses fragment_supplier's timeline (ordered user/asst/call/obs events) and
    pairs each observation with its preceding call by timeline adjacency.
    """
    import fragment_supplier as fs
    timeline = fs.parse_timeline(case.get("prompt", ""), case.get("response", ""))
    obs_events = [e for e in timeline if e["kind"] == "obs"]
    call_events = [e for e in timeline if e["kind"] == "call"]
    resp_calls = [e for e in call_events if e.get("in_response")]

    # pair obs -> nearest preceding call (by index)
    paired = []
    for o in obs_events:
        prior = [c for c in call_events if c["index"] < o["index"] and c["name"] == o["tool"]]
        call_kv = try_json(prior[-1]["args"]) if prior else {}
        paired.append({"tool": o["tool"], "kv": try_json(o["text"]), "call_kv": call_kv,
                       "index": o["index"], "text": o["text"],
                       "etype": effect_type(o["tool"], catalog)})

    facts = {"verifications": [], "authorizations": [], "stock": {}, "effects": [],
             "reads": [], "resp_calls": [], "timeline_len": len(timeline)}
    for p in paired:
        kv, ckv = p["kv"], p["call_kv"]
        shared = set(kv) & set(ckv)
        joined = join_values(kv, ckv, shared) if shared else False
        # 1) verification-shape read: args carry an id key + a non-id string arg,
        #    result carries a positive/negative boolean-ish value
        argk = arg_id_keys(ckv)
        nonid_str = [k for k, v in ckv.items() if isinstance(v, str) and not ID_ARG_KEYS.search(k)]
        bool_fields = {k: v for k, v in kv.items() if str(v).lower() in POSITIVE_VALUES | NEGATIVE_VALUES}
        if argk and nonid_str and bool_fields:
            facts["verifications"].append({**p, "positive": any(str(v).lower() in POSITIVE_VALUES
                                                                for v in bool_fields.values())})
        # 2) authorization-shape read: a grant-semantics key (authorization_status/
        #    approval/authorized/granted) with positive/negative value
        for k in kv:
            if any(w in k.lower() for w in ("authorization", "approval", "authorized", "grant")) \
                    and str(kv[k]).lower() in POSITIVE_VALUES | NEGATIVE_VALUES:
                facts["authorizations"].append({**p, "positive": str(kv[k]).lower() in POSITIVE_VALUES,
                                                "amount": kv.get("amount") or ckv.get("amount")})
                break
        # 3) stock-shape: availability field
        if "available" in kv or any(str(v).lower() in ("available", "unavailable", "in stock", "out of stock")
                                    for v in kv.values()):
            dev = ckv.get("device_id") or kv.get("device_id")
            if dev is not None:
                av = str(kv.get("available", "")).lower() in POSITIVE_VALUES or \
                     any(str(v).lower() == "available" for v in kv.values())
                facts["stock"][str(dev)] = {"available": av, "index": p["index"],
                                            "obs_kv": kv, "call_kv": ckv}
        # 4) mutation effect: successful result of a MUTATION-typed tool
        if p["etype"] == "MUTATION":
            ok = any(str(v).lower() in POSITIVE_VALUES for v in kv.values()) or \
                 str(kv.get("status", "")).lower() in POSITIVE_VALUES
            failed = any(str(v).lower() in NEGATIVE_VALUES for v in kv.values())
            facts["effects"].append({**p, "success": ok and not failed, "failed": failed})
        facts["reads"].append(p)
    facts["resp_calls"] = [{"name": c["name"], "kv": try_json(c["args"]), "etype": effect_type(c["name"], catalog)}
                           for c in resp_calls]
    # user confirmations before the response (negation-aware: "не подтверждаю"
    # / "not confirm" must NOT count — a latent v2 fragment_supplier bug class)
    users = [e for e in timeline if e["kind"] == "user"]
    first_resp = min((e["index"] for e in timeline if e.get("in_response")), default=len(timeline))
    facts["user_confirmed"] = any(_user_confirms(u["text"] or "")
                                  for u in users if u["index"] < first_resp)
    facts["user_declined"] = any(_user_declines(u["text"] or "")
                                 for u in users if u["index"] < first_resp)
    facts["n_user_turns"] = len(users)
    return facts


CONFIRM_RE = re.compile(r"(да[, .]{0,3}(?:я\s+)?подтвержд\w*|подтвержда\w+|соглас[аие]н|"
                        r"yes[, .]{0,3}i\s+confirm|^confirm|confirmed|i\s+approve|approv\w+)", re.I)
# negation immediately preceding the confirmation verb ("Пока не подтверждаю",
# "do not confirm", "won't approve")
CONFIRM_NEG_RE = re.compile(r"(?:\bне|\bnot|\bn't|\bno)\s*$", re.I)


DECLINE_RE = re.compile(r"(пока\s+не\s+подтвержд|не\s+подтвержд|не\s+соглас|не\s+хочу|"
                        r"отказ|без\s+(?:страховк|замен)|not\s+confirm|don'?t\s+confirm|"
                        r"do\s+not\s+confirm|decline|no\s+thanks)", re.I)


def _user_declines(text: str) -> bool:
    return bool(DECLINE_RE.search(text or ""))


def _user_confirms(text: str) -> bool:
    """A confirmation marker counts only without a negation window before it."""
    for m in CONFIRM_RE.finditer(text):
        before = text[max(0, m.start() - 30):m.start()]
        if not CONFIRM_NEG_RE.search(before):
            return True
    return False


def load_cases(path: Path) -> dict[str, dict]:
    return {r["id"]: r for r in csv.DictReader(open(path, encoding="utf-8"))}


def dump(path: Path, obj) -> None:
    Path(path).write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[written] {path}")
