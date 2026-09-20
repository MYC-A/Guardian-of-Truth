"""Local test of Arch D formal machinery with hand-built hypothesis templates
against the synthetic pairs. Validates: trigger detection, entity-scoped
condition resolution, exception handling, ASP cross-check, and that UNKNOWN
premises never produce CONFIRMED (soundness rule).
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.trace_parser import parse_trace
from arch_d.hypothesis_check import check_hypothesis

DATA = Path(__file__).resolve().parents[1] / "data" / "synth_pairs" / "synth_pairs_v1.jsonl"

rows = {}
for line in DATA.open(encoding="utf-8"):
    r = json.loads(line)
    rows[r["id"]] = r


def run(cid, hyp):
    row = rows[cid]
    trace = parse_trace(row["prompt"], row["response"])
    res = check_hypothesis(hyp, trace)
    print(f"--- {cid} (gold={row['label']})")
    print(f"    verdict={res['verdict']} (py={res['verdict_python']}, asp={res['verdict_asp']}, rule_grounded={res['rule_grounded']})")
    for c in res["conditions"]:
        print(f"      cond {c['id']}: {c['status']} observed={c.get('observed')} (scoped={c.get('scoped')})")
    for e in res["exceptions"]:
        print(f"      exc  {e['id']}: {e['status']} observed={e.get('observed')}")
    return res


# ---- Test 1: stale value case (b1) — response claims 5000, latest read says 8000
hyp_stale = {
    "hypothesis": "final response reports a balance that contradicts the latest get_balance read for the same account",
    "rule_quote": "The new balance must always be re-read from get_balance after any deposit; never compute it manually.",
    "trigger": {"kind": "statement", "tool": None, "match_response_fragment": "баланс"},
    "conditions": [
        {"id": "c1", "desc": "claimed balance DIFFERS from the latest observed get_balance value",
         "kind": "claim_match",
         "claim": {"extract": "number", "near": "сейчас"},
         "evidence": {"tool": "get_balance", "field": "balance", "entity_ref": "account", "op": "!=", "value": "CLAIM"}},
    ],
    "exceptions": [],
}
print("== stale value hypothesis ==")
r1_ok = run("synth__b1_stale__ok", hyp_stale)
r1_err = run("synth__b1_stale__err", hyp_stale)

# ---- Test 2: threshold + exception (b5) — refund 12500 with past approval
hyp_thresh = {
    "hypothesis": "refund over 10000 processed without valid manager approval",
    "rule_quote": "For refunds over 10 000 rubles, manager approval is required. Refunds for orders that already received approval do not require new approval.",
    "trigger": {"kind": "observed_call", "tool": "refund", "match_response_fragment": ""},
    "conditions": [
        {"id": "c1", "desc": "refund amount over 10000",
         "kind": "numeric", "evidence": {"tool": "get_user", "field": "amount", "entity_ref": "order", "op": ">", "value": 10000}},
    ],
    "exceptions": [
        {"id": "e1", "desc": "approval already received for the order",
         "evidence": {"tool": "get_user", "field": "approval", "entity_ref": "order", "present_value": "received"}},
    ],
}
print("\n== threshold+exception hypothesis (ok twin should be REFUTED by exception) ==")
r2_ok = run("synth__b5_threshold__ok", hyp_thresh)

hyp_thresh_stmt = {
    "hypothesis": "response wrongly claims a NEW manager approval is required although approval for this order was already received",
    "rule_quote": "Refunds for orders that already received approval do not require new approval.",
    "trigger": {"kind": "statement", "tool": None, "match_response_fragment": "подтверждение"},
    "conditions": [
        {"id": "c1", "desc": "approval already received for the order",
         "kind": "flag", "evidence": {"tool": "get_user", "field": "approval", "entity_ref": "order", "op": "!=", "value": ""}},
    ],
    "exceptions": [],
}
r2_err = run("synth__b5_threshold__err", hyp_thresh_stmt)

# ---- Test 3: failed call effect (b4)
hyp_failed = {
    "hypothesis": "response claims transfer completed but the deposit call failed",
    "rule_quote": "A deposit updates the balance only if the tool response reports status \"completed\".",
    "trigger": {"kind": "statement", "tool": None, "match_response_fragment": "успешно"},
    "conditions": [
        {"id": "c1", "desc": "deposit call reported failed",
         "kind": "flag", "evidence": {"tool": "deposit", "field": "status", "entity_ref": "account", "op": "==", "value": "failed"}},
    ],
    "exceptions": [],
}
print("\n== failed call effect hypothesis (err twin CONFIRMED, ok twin REFUTED) ==")
r3_ok = run("synth__b4_failed__ok", hyp_failed)
r3_err = run("synth__b4_failed__err", hyp_failed)

# ---- Test 4: unknown premise must NOT confirm (soundness)
hyp_unknown = {
    "hypothesis": "refund performed while client identity not verified in session",
    "rule_quote": "Refunds are prohibited without identity verification, EXCEPT when the client has already passed verification in the current session.",
    "trigger": {"kind": "observed_call", "tool": "refund", "match_response_fragment": ""},
    "conditions": [
        {"id": "c1", "desc": "identity not verified",
         "kind": "absence", "evidence": {"tool": "get_user", "field": "verification_status_unknown_field", "entity_ref": "user_id", "op": "==", "value": "unverified"}},
    ],
    "exceptions": [],
}
print("\n== unknown premise soundness test (must be UNRESOLVED, never CONFIRMED) ==")
r4 = run("synth__b2_except__ok", hyp_unknown)

checks = {
    "stale_ok_refuted_or_unresolved": r1_ok["verdict"] != "CONFIRMED",
    "stale_err_confirmed": r1_err["verdict"] == "CONFIRMED",
    "thresh_ok_exception_refutes": r2_ok["verdict"] == "REFUTED_EXCEPTION_APPLIES",
    "thresh_err_confirmed_or_unresolved": r2_err["verdict"] in ("CONFIRMED", "UNRESOLVED_UNKNOWN_PREMISE"),
    "failed_ok_not_confirmed": r3_ok["verdict"] != "CONFIRMED",
    "failed_err_confirmed": r3_err["verdict"] == "CONFIRMED",
    "unknown_never_confirmed": r4["verdict"] != "CONFIRMED",
}
print("\n== GATES ==")
allok = True
for k, v in checks.items():
    print(f"  {k}: {'PASS' if v else 'FAIL'}")
    allok &= v
print("ARCH D MACHINERY:", "ALL PASS" if allok else "SOME FAILED")
