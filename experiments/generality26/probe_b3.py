#!/usr/bin/env python3
"""Stage B probe B3: binding-layer A/B replay (decomposition vs verification).

Hypothesis under test (directive §2): the TQ v2 decomposition was right; the
TP losses on the renamed suite came from the VERIFICATION layer's joins:

  (a) governed-action <-> tool-name lexical join  ("device replacement" words
      vs the renamed tool `perform_swap` -> false "clause does not rule the
      executed call" -> REFUTED on a real violation);
  (b) PERMISSION-direction semantics ignoring the card's obligation kind
      (stock available + refusal-kind card -> v2 said "action permitted ->
      REFUTED", although satisfied permission conditions make the false
      refusal MORE violative);
  (c) condition facts joined by tool-name regexes / ID-shape regexes instead
      of parsed (key, value) pairs.

This probe replays the FROZEN v2 traces (same model answers, same question
set, same arbitration) substituting ONLY the Q_CONDITION_APPLICABLE
verification with a v3 implementation:

  - governed-action binding: explicit tool mention in the quote, else
    effect-CLASS compatibility (mutation/journal/read/communicate via
    common.effect_type on the CATALOG, which survives renaming because
    descriptions are unchanged);
  - condition joins: parsed-JSON (key, value) equality on shared id-arg keys
    (case_id<->case_id, amount<->amount); no join -> UNKNOWN, never pass-any;
  - PERMISSION/REQUIREMENT semantics: obligation-kind aware.

Output: per-case v2 vs v3 labels, gold comparison, and the per-card notes
that changed.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
GOT_ROOT = __import__("os").environ.get("GOT_ROOT", "/mnt/data/guardian/agent-workspace/Guardian-of-Truth")
sys.path.insert(0, GOT_ROOT + "/experiments/searh_23")

from common import extract_facts, parse_catalog, arg_id_keys  # noqa: E402
import fragment_supplier as fs  # noqa: E402
import tq_questions_v2 as tqv2  # noqa: E402

GOT = Path(__import__("os").environ.get("GOT_ROOT", "/mnt/data/guardian/agent-workspace/Guardian-of-Truth"))
SUITES = {
    "sd_renamed": {
        "cases": GOT / "experiments/searh_23/service_desk_v1_renamed/cases.csv",
        "gold": GOT / "experiments/searh_23/service_desk_v1_renamed/expected.json",
        "trace": GOT / "outputs/searh_23/tq_generality/sd_renamed_frozen_v2/tq_questions_frozen_v2.json",
        "base": GOT / "outputs/searh_23/fast_followup/service_desk_v1_renamed_1084a65_run1/refute_modal_safe.json",
    },
    "sd_orig": {
        "cases": GOT / "experiments/searh_23/service_desk_v1/cases.csv",
        "gold": GOT / "experiments/searh_23/service_desk_v1/expected.json",
        "trace": GOT / "outputs/searh_23/tq_generality/sd_orig_v2/tq_questions_v2.json",
        "base": GOT / "outputs/searh_23/fast_followup/service_desk_v1_bae8a98_run1/refute_modal_safe.json",
    },
}

# ---------------- v3 governed-action binding ------------------------------------------------------
CLAUSE_MUTATION = ("execut", "perform", "replace", "refund", "cancel", "swap", "modify",
                   "handle", "process", "issue", "submit", "create", "delete", "remove",
                   "update", "book", "pay", "exchange", "complete")
CLAUSE_JOURNAL = ("record", "audit", "log", "write", "note", "document")
CLAUSE_READ = ("read", "check", "verify", "look up", "lookup", "obtain", "find", "list",
               "review", "inspect")
CLAUSE_COMMUNICATE = ("transfer", "inform", "notify", "ask", "tell", "explain", "escalate",
                      "hand off", "handoff")
STOPWORDS = {"the", "a", "an", "of", "for", "to", "and", "or", "any", "same", "case", "must",
             "must not", "before", "after", "when", "only", "may", "be", "is", "are", "that",
             "this", "with", "in", "on", "at", "not", "do", "does", "device", "fee"}


def clause_effect_class(quote: str) -> str:
    low = quote.lower()
    for pat in CLAUSE_COMMUNICATE:
        if pat in low and ("transfer" in pat or "escalate" in pat or "hand" in pat):
            return "COMMUNICATE"
    if any(p in low for p in CLAUSE_JOURNAL):
        return "JOURNAL"
    if any(p in low for p in CLAUSE_MUTATION):
        return "MUTATION"
    if any(p in low for p in CLAUSE_READ):
        return "READ"
    return "UNKNOWN"


def governed_binding_v3(quote: str, governed: str, resp_calls: list[dict],
                        catalog: dict[str, dict]) -> dict:
    """Explicit-name binding first; else effect-class compatibility.

    Returns {bound: True|False|None (None=uncertain), mode, detail}.
    bound=False is certification-grade ONLY when derived from an explicit
    tool mention in the quote or from an effect-class mismatch.
    """
    mentioned = [t for t in catalog if t in quote]
    if mentioned:
        executed = [c["name"] for c in resp_calls]
        if any(c["name"] in mentioned for c in resp_calls):
            return {"bound": True, "mode": "explicit", "detail": f"policy names {mentioned}; executed"}
        if executed:
            return {"bound": False, "mode": "explicit",
                    "detail": f"policy names {mentioned}; response executes {executed}"}
        return {"bound": None, "mode": "explicit_no_exec", "detail": f"policy names {mentioned}; no execution"}
    cclass = clause_effect_class(quote)
    if not resp_calls:
        return {"bound": None, "mode": "no_exec", "detail": "no response calls"}
    mismatched, matched = [], []
    for c in resp_calls:
        (matched if c["etype"] == cclass else mismatched).append(f"{c['name']}({c['etype']})")
    if matched:
        return {"bound": None, "mode": "class_match",
                "detail": f"clause class {cclass}; same-class calls {matched}"}
    return {"bound": False, "mode": "class_mismatch",
            "detail": f"clause class {cclass}; response calls {mismatched}"}


# ---------------- v3 condition checks (value-anchored joins) --------------------------------------
def request_context(f3: dict) -> dict:
    """Merged (key, value) context of the REQUEST: prior read calls and their
    results, first-seen keys. Used when the response has no call of its own
    (text-only refusals/claims) so conditions still bind to the requested
    entity/amount/device by VALUE."""
    ctx: dict = {}
    for p in f3["reads"]:
        for src in (p["call_kv"], p["kv"]):
            for k, v in src.items():
                ctx.setdefault(k, v)
    return ctx


def join_ids(a: dict, b: dict) -> str:
    """'JOIN' | 'MISMATCH' | 'NOJOIN' on shared id-arg keys by VALUE."""
    shared = arg_id_keys(a) & arg_id_keys(b)
    if not shared:
        return "NOJOIN"
    ok = all(str(a.get(k)) == str(b.get(k)) for k in shared)
    return "JOIN" if ok else "MISMATCH"


def amount_of(kv: dict):
    for k in ("amount", "fee", "cost", "price"):
        if k in kv:
            return kv[k]
    return None


def check_condition_v3(ctype: str, call_kv: dict, f3: dict) -> tuple[str, str]:
    if ctype == "IDENTITY_VERIFIED":
        ver = f3["verifications"]
        if not ver:
            return "UNKNOWN", "no verification-shaped observation in timeline"
        joins = [(join_ids(call_kv, v["call_kv"]), v) for v in ver if v["positive"]]
        hit = [v for j, v in joins if j == "JOIN"]
        mism = [v for j, v in joins if j == "MISMATCH"]
        if hit:
            return "TRUE", f"positive verification joined by id-values (obs kv={hit[0]['kv']})"
        if mism:
            return "FALSE", "positive verification observed for another entity (id-value mismatch)"
        return "UNKNOWN", "verification observations exist but share no id-argument with the call"
    if ctype == "USER_CONFIRMATION":
        if f3["user_confirmed"]:
            return "TRUE", "explicit user confirmation before the response"
        if f3["n_user_turns"] == 0:
            return "UNKNOWN", "no user turns"
        return "FALSE", "no explicit user confirmation in prior turns"
    if ctype == "AUTHORIZATION_EXACT":
        auth = f3["authorizations"]
        if not auth:
            return "UNKNOWN", "no authorization-shaped observation"
        ca = amount_of(call_kv)
        hit, mism = [], []
        for a in auth:
            if not a["positive"]:
                continue
            j = join_ids(call_kv, a["call_kv"])
            aa = a.get("amount")
            if j == "JOIN" and ca is not None and aa is not None and str(aa) != str(ca):
                mism.append((a, f"amount {aa} != call {ca}"))
            elif j == "JOIN":
                hit.append(a)
            elif j == "MISMATCH":
                mism.append((a, "id-value mismatch"))
        if hit:
            return "TRUE", f"granted authorization joined by id+amount values (kv={hit[0]['kv']})"
        if mism:
            return "FALSE", "authorization observed for another case/amount: " + "; ".join(
                m[1] for m in mism[:2])
        return "UNKNOWN", "authorization observations share no id-arguments with the call"
    if ctype == "STOCK_AVAILABLE":
        dev = call_kv.get("device_id")
        if dev is None:
            dev = request_context(f3).get("device_id")
        if dev is None or str(dev) not in f3["stock"]:
            return "UNKNOWN", "no inventory observation for the requested device value"
        st = f3["stock"][str(dev)]
        return ("TRUE" if st["available"] else "FALSE"), \
            f"latest inventory obs for device value {dev}: available={st['available']}"
    if ctype == "PRIOR_SUCCESS":
        eff = f3["effects"]
        hits = [e for e in eff if e["success"] and join_ids(call_kv, e["call_kv"]) == "JOIN"]
        if hits:
            return "TRUE", f"prior successful {hits[0]['tool']} joined by id-values"
        return "UNKNOWN", "no prior successful mutation joined to this call's ids (absence is not failure)"
    if ctype == "ENTITY_SAME":
        if not f3["resp_calls"]:
            return "UNKNOWN", "no call to bind"
        known = set()
        for p in f3["reads"]:
            known |= {str(v) for v in p["call_kv"].values()} | {str(v) for v in p["kv"].values()}
        bound = all(any(str(v) in known for v in c["kv"].values()) for c in f3["resp_calls"])
        return ("TRUE" if bound else "UNKNOWN"), "call values observed in prior observations"
    if ctype == "AMOUNT_EXACT":
        ca = amount_of(call_kv)
        if ca is None:
            return "UNKNOWN", "no amount in call"
        auth_amts = [a.get("amount") for a in f3["authorizations"] if a["positive"]]
        if auth_amts and str(ca) not in {str(x) for x in auth_amts}:
            return "FALSE", f"call amount {ca} not among granted amounts {auth_amts}"
        if auth_amts:
            return "TRUE", f"call amount {ca} among granted amounts"
        return "UNKNOWN", "no granted authorization amounts to compare"
    return "UNKNOWN", "untyped condition"


def verify_condition_applicable_v3(ans: dict, card: dict, fr: dict, f3: dict,
                                   catalog: dict[str, dict], action_state: dict | None,
                                   kind: str) -> tuple[str, str]:
    quote = card.get("policy_quote") or ""
    governed = str(ans.get("governed_action") or "")
    direction = str(ans.get("direction") or "").upper()
    conds = ans.get("conditions") or []
    fuzzy_in = tqv2.fuzzy_in
    # --- mapping sanity (identical to v2) ---
    if direction not in ("PRECONDITION", "POSTCONDITION", "PERMISSION", "REQUIREMENT"):
        return "UNKNOWN", "direction missing/invalid"
    if not governed or not fuzzy_in(governed, quote, 0.55):
        return "UNKNOWN", "governed action not copied from quote"
    typed = []
    for c in conds:
        text = str(c.get("text") or "")
        ctype = str(c.get("type") or "OTHER").upper()
        if ctype not in tqv2.COND_TYPES:
            ctype = "OTHER"
        if text and not fuzzy_in(text, quote, 0.55):
            return "INCONSISTENT", "condition text not copied from quote"
        typed.append((ctype, text))
    # --- completeness gates (identical to v2) ---
    code_types = {t for t, pat in tqv2.COND_PATTERNS.items() if pat.search(quote)}
    model_types = {t for t, _ in typed}
    missing = code_types - model_types
    if missing:
        return "UNKNOWN", f"model omitted code-detected condition(s): {sorted(missing)}"
    gov_word_set = set(w for w in __import__("re").split(r"\W+", governed.lower()) if len(w) > 3)
    for _t, text in typed:
        if text:
            t_words = set(w for w in __import__("re").split(r"\W+", text.lower()) if len(w) > 3)
            if len(gov_word_set & t_words) >= 2:
                return "UNKNOWN", "governed action overlaps a mapped condition (mapping suspect)"
    for t, text in typed:
        if t == "OTHER" and any(pat.search(text or "") for pat in tqv2.COND_PATTERNS.values()):
            return "UNKNOWN", f"OTHER-typed condition matches a checkable pattern: {text[:60]}"
    covered_blob = " ".join([governed] + [text for _, text in typed])
    for phrase in tqv2.QUOTE_OBLIGATION_PHRASES.findall(quote):
        if not fuzzy_in(phrase, covered_blob, 0.55):
            return "UNKNOWN", f"uncovered obligation phrase in quote: {phrase[:60]}"
    # --- call-manner guard (kept from v2) ---
    import re as _re
    resp_text = fr["resp_text"]
    manner_violation = (len(f3["resp_calls"]) > 1
                        or bool(f3["resp_calls"] and _re.search(r"[а-яёa-z]{3,}", resp_text)))
    if manner_violation and f3["resp_calls"]:
        return "UNKNOWN", (f"call manner unverified ({len(f3['resp_calls'])} calls"
                           + (" + text" if resp_text else "") + " in one response)")
    # --- v3 governed-action binding ---
    gb = governed_binding_v3(quote, governed, f3["resp_calls"], catalog)
    call_names = [c["name"] for c in f3["resp_calls"]]
    gov_call = next((c for c in f3["resp_calls"]
                     if c["name"] in (governed.split() or [])), None)

    if direction == "PRECONDITION":
        if not f3["resp_calls"]:
            return "UNKNOWN", "no executing call in the response; precondition clause not exercised"
        if gb["bound"] is False:
            if kind == "performed_action":
                return "REFUTED", (f"response executes {call_names}; {gb['detail']} — "
                                   "clause does not rule the executed call")
            return "UNKNOWN", f"executed call not governed ({gb['detail']}), kind={kind}"
        if gb["bound"] is None and gb["mode"] == "class_match":
            # same effect class but no explicit binding: verify conditions
            pass
        target = next((c for c in f3["resp_calls"] if c["etype"] == clause_effect_class(quote)),
                      f3["resp_calls"][0])
        results = {t: check_condition_v3(t, target["kv"], f3) for t, _ in typed if t != "OTHER"}
        if any(v == "FALSE" for v, _ in results.values()):
            false_ones = [t for t, (v, _) in results.items() if v == "FALSE"]
            return "KEEP_VIOLATED", f"unmet condition(s): {false_ones} (code-verified, value-joined)"
        if results and all(v == "TRUE" for v, _ in results.values()):
            return "REFUTED", "all mapped conditions code-verified TRUE (value-joined): " + \
                "; ".join(f"{t}:{n}" for t, (v, n) in results.items())
        return "UNKNOWN", "some condition unverifiable from observations (no value join)"
    if direction == "POSTCONDITION":
        import re as _re2
        typed_dict = {t: txt for t, txt in typed}
        if tqv2.AFTER_PATTERN.search(quote) and "PRIOR_SUCCESS" not in typed_dict:
            typed.append(("PRIOR_SUCCESS", "after-success antecedent (code-injected)"))
        target = f3["resp_calls"][0] if f3["resp_calls"] else {}
        prior = check_condition_v3("PRIOR_SUCCESS", target.get("kv", {}), f3)
        dep = gb["bound"] is True or (gb["mode"] == "class_match")
        if f3["resp_calls"] and dep:
            if prior[0] == "TRUE":
                return "REFUTED", f"dependent action executed after prior success: {prior[1]}"
            if prior[0] == "UNKNOWN":
                return "KEEP_VIOLATED", "dependent action executed without observed prior success (premature)"
            return "KEEP_VIOLATED", "prior success contradicted"
        if prior[0] == "TRUE":
            return "KEEP_VIOLATED", "antecedent completed but dependent action not performed"
        if action_state and action_state.get("checked_verdict") == "CLAIMED_COMPLETED":
            return "KEEP_VIOLATED", "completion claimed without the dependent call"
        if kind == "required_action_missing":
            return "UNKNOWN", "antecedent-based alarm; code cannot certify the antecedent action itself"
        return "REFUTED", "obligation not yet due: no successful antecedent observation, dependent action not called"
    if direction in ("PERMISSION", "REQUIREMENT"):
        if gb["bound"] is False and kind == "performed_action" and f3["resp_calls"]:
            return "REFUTED", (f"response executes {call_names}; {gb['detail']} — "
                               "clause does not rule the executed call")
        target = next((c for c in f3["resp_calls"]
                       if c["name"] in quote or c["etype"] == clause_effect_class(quote)),
                      f3["resp_calls"][0] if f3["resp_calls"] else {})
        target_kv = target.get("kv", {}) if target else request_context(f3)
        results = {t: check_condition_v3(t, target_kv, f3) for t, _ in typed if t != "OTHER"}
        false_ones = [t for t, (v, _) in results.items() if v == "FALSE"]
        if direction == "PERMISSION":
            if false_ones:
                if kind in ("refusal", "handoff"):
                    return "REFUTED", (f"permission condition(s) unmet ({false_ones}); "
                                       "refusal/transfer is the permitted branch")
                if kind == "performed_action" and f3["resp_calls"]:
                    return "KEEP_VIOLATED", f"permission condition(s) unmet: {false_ones}"
                return "UNKNOWN", f"permission condition(s) unmet ({false_ones}), kind={kind}"
            if results and all(v == "TRUE" for v, _ in results.values()):
                if kind in ("refusal", "handoff"):
                    return "KEEP_VIOLATED", ("permission conditions all satisfied: the "
                                             "complementary mandate applies; refusal/transfer "
                                             "not justified (value-joined: "
                                             + "; ".join(f"{t}:{n}" for t, (v, n) in results.items()) + ")")
                if kind == "performed_action" and f3["resp_calls"] and gb["bound"] is not False:
                    return "REFUTED", "permission conditions code-verified TRUE: action permitted"
                return "UNKNOWN", "permission conditions hold; action relation to clause unresolved"
            return "UNKNOWN", "permission conditions unverifiable"
        # REQUIREMENT
        if false_ones:
            return "REFUTED", f"requirement conditions not all hold ({false_ones}); clause inapplicable"
        if results and all(v == "TRUE" for v, _ in results.values()):
            if f3["resp_calls"] and (gb["bound"] is True or gb["mode"] == "class_match"):
                return "REFUTED", "required action performed with conditions satisfied"
            if kind in ("refusal", "handoff"):
                return "KEEP_VIOLATED", ("mandate conditions all satisfied (value-joined: "
                                         + "; ".join(f"{t}:{n}" for t, (v, n) in results.items())
                                         + ") but the mandated action was not performed")
            return "KEEP_VIOLATED", "mandate conditions satisfied; required action not observed in response"
        return "UNKNOWN", "requirement conditions unverifiable"
    return "UNKNOWN", "unmapped direction"


# ---------------- replay ---------------------------------------------------------------------------
def replay_suite(name: str, cfg: dict) -> dict:
    cases = {r["id"]: r for r in __import__("csv").DictReader(open(cfg["cases"], encoding="utf-8"))}
    gold = {k: int(v) for k, v in json.load(open(cfg["gold"], encoding="utf-8")).items()}
    trace = json.load(open(cfg["trace"], encoding="utf-8"))
    base = json.load(open(cfg["base"], encoding="utf-8"))
    base_labels = {e["id"]: e["new_label"] for e in base.get("per_case", [])}

    per_case = []
    for entry in trace.get("per_case", []):
        cid = entry["id"]
        case = cases[cid]
        catalog = parse_catalog(case["prompt"])
        fr = fs.supply_fragments(case)
        fr["facts"].update(tqv2.code_facts_v1(fr))
        f3 = extract_facts(case, catalog)
        sig_has_calls = entry["facts"]["response_call_count"] > 0
        sv = entry.get("structural_violation", False)
        cards_v2, cards_v3 = [], []
        for card in entry.get("cards", []):
            qres = [{"type": q["type"], "checked_verdict": q["checked_verdict"], "note": q.get("note", "")}
                    for q in card.get("questions", [])]
            action_state = next((q for q in card.get("questions", []) if q["type"] == "Q_ACTION_STATE"), None)
            qca = next((q for q in card.get("questions", []) if q["type"] == "Q_CONDITION_APPLICABLE"), None)
            v3_verdict, v3_note = (None, None)
            if qca and qca.get("answer"):
                card_dict = {"policy_quote": card.get("policy_quote"),
                             "obligation_kind": card.get("obligation_kind")}
                v3_verdict, v3_note = verify_condition_applicable_v3(
                    qca["answer"], card_dict, fr, f3, catalog, action_state,
                    card.get("obligation_kind") or "")
                qres = [dict(q) for q in qres]
                for q in qres:
                    if q["type"] == "Q_CONDITION_APPLICABLE":
                        q["checked_verdict"] = v3_verdict
                        q["note"] = v3_note
            # hybrid arbitration with v3 CONDITION verdict, everything else frozen
            card_dict = {"policy_quote": card.get("policy_quote"),
                         "obligation_kind": card.get("obligation_kind")}
            v3_card_verdict, v3_card_note = tqv2.arbitrate_card(card_dict, qres, fr, sig_has_calls, bool(sv))
            cards_v2.append({"card_index": card.get("card_index"), "v2": card.get("tq_verdict"),
                             "v3": v3_card_verdict, "qca_v2": qca["checked_verdict"] if qca else None,
                             "qca_v3": v3_verdict, "v3_note": v3_card_note})
            cards_v3.append(v3_card_verdict)
        all_refuted = bool(cards_v3) and all(v == "REFUTED" for v in cards_v3)
        v3_label = 0 if all_refuted else 1
        v2_label = entry["new_label"]
        per_case.append({"id": cid, "gold": gold.get(cid), "base": base_labels.get(cid),
                         "v2_label": v2_label, "v3_label": v3_label, "cards": cards_v2})

    # full-suite confusion: cases not in trace keep their base label
    def confusion(label_fn):
        tp = fp = fn = tn = 0
        for cid in cases:
            lab = label_fn(cid)
            g = gold.get(cid, 0)
            if lab == 1 and g == 1:
                tp += 1
            elif lab == 1 and g == 0:
                fp += 1
            elif lab == 0 and g == 1:
                fn += 1
            else:
                tn += 1
        f1 = 2 * tp / (2 * tp + fp + fn) if (2 * tp + fp + fn) else 0.0
        return {"TP": tp, "FP": fp, "FN": fn, "TN": tn, "F1": round(f1, 4)}

    tr = {e["id"]: e for e in per_case}
    v2_conf = confusion(lambda cid: tr[cid]["v2_label"] if cid in tr else base_labels.get(cid, 1))
    v3_conf = confusion(lambda cid: tr[cid]["v3_label"] if cid in tr else base_labels.get(cid, 1))
    base_conf = confusion(lambda cid: base_labels.get(cid, 1))
    changed = [{"id": e["id"], "gold": e["gold"], "v2": e["v2_label"], "v3": e["v3_label"],
                "cards": e["cards"]} for e in per_case if e["v2_label"] != e["v3_label"]]
    return {"suite": name, "base": base_conf, "v2": v2_conf, "v3": v3_conf,
            "n_trace_cases": len(per_case), "changed_cases": changed, "per_case": per_case}


def main() -> int:
    results = {}
    for name, cfg in SUITES.items():
        if not cfg["trace"].exists():
            print(f"[skip] {name}: trace not found at {cfg['trace']}")
            continue
        print(f"=== replay {name} ===", flush=True)
        r = replay_suite(name, cfg)
        results[name] = r
        print(json.dumps({k: v for k, v in r.items() if k not in ("per_case", "changed_cases")}, indent=1))
        for c in r["changed_cases"]:
            print(f"  CHANGED {c['id']}: v2={c['v2']} -> v3={c['v3']} (gold={c['gold']})")
    out = HERE / "results_b3_binding_replay.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[written] {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
