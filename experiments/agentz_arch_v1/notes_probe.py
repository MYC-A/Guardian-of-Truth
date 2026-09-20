"""NOTES PROBE (pre-registered design, run after C0vC3 main comparison).

Question: what semantic information does each unrepresentable_note carry, is that
information representable in RuleIR v2/v3, and could it change the decision on the
checked trajectory?

Method (per the research brief):
- E1: LangExtract source-grounded policy extraction (LX loop + Mistral) with
  capability tagging and verbatim quotes.
- E2: independent extractor = GLM via z-ai-web-dev-sdk (different vendor AND
  different mechanism: free-form JSON checklist, no LX alignment), same policy.
- Deterministic relevance probes on the trajectory evidence per capability label.
- Classification per note: D_meta / A_ambiguity / B_representable / C_unrepresentable,
  plus decision relevance (does the trajectory touch the element).
- Certificate scoping: a no-error certificate is honest ONLY as "no violations of
  the REPRESENTED rules on this trajectory"; notes with decision-relevant semantic
  content keep the case UNRESOLVED (never claimed as full absence of violations).

Usage: python3 notes_probe.py synth-dev
"""
import json, os, re, sys, time
from pathlib import Path
sys.path.insert(0, "/home/z/my-project/got-agentz/experiments/agentz_arch_v1")
from common.io_utils import load_dataset, save_result, SYSTEM_PROMPT, run_llm, extract_json
from common import timeline as T
from common import asp_lower as A1
from common import asp_lower2 as A2
from arch_c_theory import policy_text
from common import langextract_runner as LX

OUT = Path("/home/z/my-project/got-agentz/outputs/agentz")
T_START = time.time()
E2_BUDGET = 420  # seconds for the E2 phase per invocation

CAPS = ["temporal_seq", "freshness", "actor_role", "success_status",
        "value_context", "entity_scope", "concurrency", "none"]

# ---------------- step 1: offline note parsing ----------------

META_PAT = re.compile(r"theory_parse_failed|parse_failed", re.I)
AMBIG_PAT = re.compile(r"does not specify|не уточня|не указан|не специфиц|не определен|"
                       r"assumed|предполагаем|неясно|ambiguous|не задан", re.I)
CAP_PATS = {
    "temporal_seq": re.compile(r"temporal|последовательност|порядок (действий|вызовов|операций)|"
                               r"sequential|immediately|сразу после|до выполнения|после (завершения|выполнения|пополнения|списания)|"
                               r"before|after (a |the )?(deposit|withdrawal|refund)|temporal_order", re.I),
    "freshness": re.compile(r"fresh|свеж|most recent|актуальност|latest|устаревш|stale", re.I),
    "actor_role": re.compile(r"role|рол|менеджер|руководител|manager|supervisor|actor|субъект|"
                             r"approval.*(role|manager)|права", re.I),
    "success_status": re.compile(r"успешн|successful|success|статус (операции|вызова|результата)|"
                                 r"result status|failur|ошибк", re.I),
    "value_context": re.compile(r"валют|currency|RUB|руб|USD|процент|unit|единиц|контекст суммы", re.I),
    "entity_scope": re.compile(r"account|счёт|счет|cross|другого (счёта|аккаунта)|scoped|"
                               r"applies to (all|the exact)", re.I),
    "concurrency": re.compile(r"concurren|race|параллельн|одновременн|между сессиями|cross-session", re.I),
}

def label_note(text):
    labels = [c for c, pat in CAP_PATS.items() if pat.search(text)]
    return labels or ["none"]

def note_class(text, extractor_confirmed, representable):
    if META_PAT.search(text):
        return "D_meta"
    if AMBIG_PAT.search(text) and not extractor_confirmed:
        return "A_ambiguity"
    if representable:
        return "B_representable"
    if extractor_confirmed:
        return "C_unrepresentable"
    return "A_ambiguity_unconfirmed"

# v3 ontology representation map (what asp_lower2 can actually encode)
def representable_for(caps, row_events):
    """Return (representable_bool, slot_or_None). Conservative: B only when the
    v3 ontology has a real encoding for the capability."""
    tools = {e.tool_name for e in row_events if e.kind == "tool_call"}
    out = []
    for c in caps:
        if c == "freshness":
            out.append((True, "value_is_latest/fresh exception"))
        elif c == "temporal_seq":
            # only report-vs-action order is encodable (fresh exc); tool-tool strict
            # order is NOT encodable -> not representable
            out.append((False, None))
        elif c == "actor_role":
            # encodable ONLY if the role action is a tool present in trace (actpresent)
            if any(t and ("approv" in t.lower() or "confirm" in t.lower()) for t in tools):
                out.append((True, "actpresent(approval-tool)"))
            else:
                out.append((False, None))
        elif c == "entity_scope":
            out.append((True, "entity-bound latest_value/text_report"))
        else:
            out.append((False, None))
    return any(r for r, _ in out), (out or None)

# ---------------- step 2/3: extractors ----------------

E1_PROMPT = ("Extract policy rule elements with exact verbatim quotes. For each element "
             "give attributes: element_type (obligation|prohibition|permission|exception|condition), "
             "action, threshold (number or null), capability (one of: temporal_seq, freshness, "
             "actor_role, success_status, value_context, entity_scope, concurrency, none). "
             "capability = the extra checking power needed beyond comparing a reported value to "
             "a tool result. Quote must be verbatim from the policy.")

E2_SYSTEM = ("You are a verification-capability auditor. Answer ONLY with JSON.")

def e2_prompt(policy):
    return ("List every requirement/condition/exception in this policy. For each output: "
            "quote (verbatim from the policy), capability needed to verify it "
            "(temporal_seq=fact that one action happened before/after another; "
            "freshness=reported value equals latest tool result; "
            "actor_role=permission tied to a human role rather than a tool call; "
            "success_status=whether a tool call succeeded; "
            "value_context=currency/unit/context of a number; "
            "entity_scope=which account/entity a value belongs to; "
            "concurrency=events outside this trajectory; none), "
            "explicit (true if the policy states it, false if you inferred it).\n"
            "JSON only: {\"elements\":[{\"quote\":\"...\",\"capability\":\"...\",\"explicit\":true}]}\n\n"
            "POLICY:\n" + policy[:8000])

# ---------------- step 4: deterministic relevance probes ----------------

FAIL_KEYS = {"error", "failed", "failure", "status", "ok", "success"}

def relevance_probe(caps, row, ta_reports):
    """Per capability: does the trajectory evidence touch the element such that
    formalizing it could flip the verdict? Returns {cap: bool}."""
    events = T.parse_prompt(row["prompt"])
    ra = A1.analyze_response(events, row["prompt"], row["response"])
    calls = [e for e in events if e.kind == "tool_call"]
    resps = [e for e in events if e.kind == "tool_response"]
    lv = A2.latest_tool_values(events)
    out = {}
    for c in caps:
        if c == "temporal_seq":
            out[c] = len(calls) >= 2
        elif c == "freshness":
            reports = ta_reports or []
            touched = False
            for (field, val, ent) in reports:
                cands = [str(t[2]) for t in lv if t[0] == field]
                if cands and str(val) not in cands:
                    touched = True
            out[c] = touched or bool(reports)
        elif c == "actor_role":
            pol = policy_text(row["prompt"]).lower()
            out[c] = bool(re.search(r"менеджер|руководител|manager|supervisor|старший", pol))
        elif c == "success_status":
            touched = False
            for e in resps:
                p = e.payload if isinstance(e.payload, dict) else {}
                low = {k: str(v).lower() for k, v in p.items()}
                if any(k in low and any(w in str(low[k]) for w in ("fail", "error", "false")) for k in FAIL_KEYS):
                    touched = True
            out[c] = touched
        elif c == "value_context":
            pol = policy_text(row["prompt"]).lower()
            out[c] = bool(re.search(r"руб|RUB|\$|USD|EUR|€|процент|%", pol + " " + row["response"].lower()))
        elif c == "entity_scope":
            ents = {t[1] for t in lv if t[1] and t[1] != "*"}
            ents |= {e for (_, _, e) in (ta_reports or []) if e}
            out[c] = len(ents) > 1
        elif c == "concurrency":
            out[c] = False  # outside trajectory by definition
        else:
            out[c] = False
    return out

# ---------------- main ----------------

def run(ds):
    rows = {r["id"]: r for r in load_dataset(ds)}
    c0v3 = json.loads((OUT / f"arch_c0v3_{ds}.json").read_text())
    targets = [cid for cid, det in c0v3["details"].items()
               if det.get("pred") is None]
    print(f"notes probe on {len(targets)} UNRESOLVED cases of {ds}", flush=True)

    # --- E1: LX extraction per case (Mistral via shim env) ---
    e1, e2 = {}, {}
    e1_cache = OUT / f"notes_e1_{ds}.json"
    e2_cache = OUT / f"notes_e2_{ds}.json"
    if e1_cache.exists():
        e1 = json.loads(e1_cache.read_text())
    if e2_cache.exists():
        e2 = json.loads(e2_cache.read_text())

    for i, cid in enumerate(targets):
        row = rows[cid]
        pol = policy_text(row["prompt"])
        if cid not in e1:
            try:
                exs = LX.extract(pol, E1_PROMPT, LX.rule_element_examples())
                e1[cid] = exs
            except Exception as e:
                e1[cid] = {"error": str(e)[:200]}
            e1_cache.write_text(json.dumps(e1, ensure_ascii=False))
            print(f"E1 {i+1}/{len(targets)} {cid}: {len(e1[cid]) if not isinstance(e1[cid], dict) else 'ERR'}", flush=True)
    print("E1 done", flush=True)

    # --- E2: GLM independent extractor (unset MISTRAL key for this phase) ---
    mistral_key = os.environ.pop("MISTRAL_API_KEY", None)
    try:
        missing_e2 = [cid for cid in targets if cid not in e2]
        if missing_e2:
            print(f"E2: {len(missing_e2)} missing; GLM health probe...", flush=True)
            try:
                hp = run_llm([{"id": "health-glm", "system": "You are terse.",
                               "prompt": "Reply exactly: OK"}], concurrency=1)
                ok = hp.get("health-glm") is not None
            except Exception as e:
                ok = False
            if not ok:
                print("E2 SKIPPED: GLM unreachable; records will be e1-only "
                      "(rerun when GLM recovers for dual confirmation)", flush=True)
                mistral_skipped = True
                missing_e2 = []
        for i, cid in enumerate(missing_e2):
            if time.time() - T_START > E2_BUDGET:
                print("E2 budget reached; rerun to continue", flush=True)
                break
            row = rows[cid]
            out = run_llm([{"id": f"{cid}-e2", "system": E2_SYSTEM,
                            "prompt": e2_prompt(policy_text(row["prompt"]))}], concurrency=4)
            j = extract_json(out.get(f"{cid}-e2"))
            e2[cid] = j.get("elements", []) if isinstance(j, dict) else {"error": "parse"}
            e2_cache.write_text(json.dumps(e2, ensure_ascii=False))
            print(f"E2 {i+1}/{len(targets)} {cid}", flush=True)
    finally:
        if mistral_key:
            os.environ["MISTRAL_API_KEY"] = mistral_key
    print("E2 done", flush=True)

    # --- classify ---
    records, per_case = [], {}
    for cid in targets:
        row = rows[cid]
        det = c0v3["details"][cid]
        th = det["theory"]
        events = T.parse_prompt(row["prompt"])
        ta = A2.analyze_text_acts_lx(row["response"]) or {"reports": []}
        recs_c = []
        for note in th.get("unrepresentable_notes", []):
            note_t = note if isinstance(note, str) else json.dumps(note, ensure_ascii=False)
            caps = label_note(note_t)
            # extractor confirmation: does any extracted element carry a matching capability?
            conf_e1 = [x for x in (e1.get(cid) or []) if isinstance(x, dict) and
                       x.get("attributes", {}).get("capability") in caps
                       and x.get("attributes", {}).get("capability") not in (None, "none")]
            conf_e2 = [x for x in (e2.get(cid) or []) if isinstance(x, dict) and
                       x.get("capability") in caps and x.get("capability") != "none"]
            confirmed = bool(conf_e1 or conf_e2)
            dual = bool(conf_e1) and bool(conf_e2)
            rep, slots = representable_for(caps, events)
            rel = relevance_probe(caps, row, ta.get("reports", []))
            cls = note_class(note_t, confirmed, rep)
            rec = {
                "note": note_t[:400], "caps": caps, "class": cls,
                "confirmed_by": ("both" if dual else ("e1_lx" if conf_e1 else ("e2_glm" if conf_e2 else "none"))),
                "n_conf_quotes_e1": len(conf_e1), "n_conf_quotes_e2": len(conf_e2),
                "quotes_e1": [x.get("aligned_text") or x.get("text", "")[:120] for x in conf_e1[:3]],
                "quotes_e2": [x.get("quote", "")[:120] for x in conf_e2[:3]],
                "representable": rep, "rep_slots": slots,
                "relevance": rel,
                "decision_relevant": any(rel.get(c) for c in caps),
            }
            recs_c.append(rec)
        per_case[cid] = recs_c
        records.extend(recs_c)

    # --- aggregates ---
    from collections import Counter
    cls_c = Counter(r["class"] for r in records)
    cap_c = Counter(c for r in records for c in r["caps"])
    relevant = [r for r in records if r["decision_relevant"]]
    # certificate scoping per case
    scope = {}
    for cid, recs in per_case.items():
        blocking = [r for r in recs if r["class"].startswith(("B", "C")) and r["decision_relevant"]]
        scope[cid] = {
            "scoped_certificate_safe": not blocking,
            "n_decision_relevant_notes": len(blocking),
            "blocking_classes": sorted({r["class"] for r in blocking}),
        }
    n_safe = sum(1 for v in scope.values() if v["scoped_certificate_safe"])
    save_result(f"notes_taxonomy_{ds}.json", {
        "dataset": ds, "n_cases": len(targets), "n_notes": len(records),
        "class_counts": dict(cls_c), "capability_counts": dict(cap_c),
        "decision_relevant_notes": len(relevant),
        "certificate_scope": scope,
        "scoped_safe_share": round(n_safe / max(1, len(scope)), 3),
        "per_case": per_case,
    })
    print(f"\nNOTES TAXONOMY {ds}: {len(records)} notes / {len(targets)} cases")
    print("classes:", dict(cls_c))
    print("capabilities:", dict(cap_c))
    print(f"decision-relevant notes: {len(relevant)} | scoped-safe certificates: {n_safe}/{len(scope)}")

if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "synth-dev")
