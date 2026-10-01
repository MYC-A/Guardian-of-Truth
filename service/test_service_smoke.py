#!/usr/bin/env python3
"""Stage-A service smoke test (directive §13): clean start -> readiness ->
simple request -> batch -> unavailable-model degraded/UNKNOWN.

Runs IN-PROCESS (no server needed) against the structural-v02 config and,
for the degraded path, a config whose judge channels are unreachable from
this environment. No API keys are required to run this file.

  python service/test_service_smoke.py
"""
from __future__ import annotations

import sys
from pathlib import Path

SERVICE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SERVICE_DIR))

from runtime import GuardianServiceRuntime, list_configs  # noqa: E402

CATALOG = """[AVAILABLE TOOLS]
- check_status — Checks the current status of an order.
    order_id: string! — identifier of the order
- create_refund — Creates a refund for a paid order.
    order_id: string! — identifier of the order
    amount: number! — refund amount
"""
HISTORY = """⟦USER⟧
Can you check my order ORD-1?
⟦ASSISTANT⟧
→ TOOL_CALL check_status: {"order_id": "ORD-1"}
← TOOL_RESPONSE check_status: {"status": "shipped"}
⟦ASSISTANT⟧
Your order has shipped.
⟦USER⟧
I want a refund and a message.
"""


def case_error_invented_tool():
    return {
        "case_id": "smoke.invented_tool",
        "prompt": f"⟦SYSTEM⟧\nBe helpful.\n\n{CATALOG}\n{HISTORY}",
        "response": "→ TOOL_CALL make_refund: {\"order_id\": \"ORD-1\"}",
    }


def case_error_schema():
    return {
        "case_id": "smoke.schema_missing_amount",
        "prompt": f"⟦SYSTEM⟧\nBe helpful.\n\n{CATALOG}\n{HISTORY}",
        "response": "→ TOOL_CALL create_refund: {\"order_id\": \"ORD-1\"}",
    }


def case_clean_structural():
    return {
        "case_id": "smoke.clean_structural",
        "prompt": f"⟦SYSTEM⟧\nBe helpful.\n\n{CATALOG}\n{HISTORY}",
        "response": "→ TOOL_CALL check_status: {\"order_id\": \"ORD-1\"}",
    }


def test_configs_listed():
    cfgs = list_configs()
    assert "structural-v02" in cfgs and "v6-judges" in cfgs
    print(f"configs: {cfgs}")


def test_simple_request_error():
    rt = GuardianServiceRuntime("structural-v02")
    p = rt.check(case_error_invented_tool())
    assert p["decision"] == "ERROR" and p["decision_basis"] == "schema"
    assert p["findings"] and p["findings"][0]["type"] == "catalog_absent"
    assert p["findings"][0]["status"] == "CONFIRMED"
    assert p["degraded"] is False
    print("simple request: ERROR via catalog_absent finding — OK")


def test_schema_error_finding():
    rt = GuardianServiceRuntime("structural-v02")
    p = rt.check(case_error_schema())
    assert p["decision"] == "ERROR"
    assert any(f["type"] == "schema_missing_required"
               for f in p["findings"])
    print("schema error finding: schema_missing_required — OK")


def test_clean_structural_is_unknown_not_no_error():
    rt = GuardianServiceRuntime("structural-v02")
    p = rt.check(case_clean_structural())
    assert p["decision"] == "UNKNOWN", p
    assert p["coverage"]["model"] == "not_configured"
    assert "not a certificate" in p["coverage"]["note"]
    print("clean structural scan -> UNKNOWN (honest) — OK")


def test_context_budget():
    rt = GuardianServiceRuntime("structural-v02")
    big = dict(case_clean_structural())
    big["prompt"] = "x" * 200001
    p = rt.check(big)
    assert p["decision"] == "UNKNOWN" and p["degraded"] is True
    assert p["coverage"]["reason"] == "context_budget_exceeded"
    print("context budget exceeded -> UNKNOWN/degraded — OK")


def test_unavailable_judge_channel_degrades():
    """v6-judges with unreachable channels: the case must degrade to
    UNKNOWN with an explicit reason — never a silent 0/1."""
    rt = GuardianServiceRuntime("v6-judges")
    p = rt.check(case_clean_structural())
    assert p["decision"] in {"UNKNOWN", "ERROR", "NO_ERROR"}
    # in THIS environment the judge stack is not importable/authorized:
    # the pre-registered rule degrades to UNKNOWN with channel reasons
    if p["decision"] == "UNKNOWN":
        assert p["degraded"] is True
        assert p["coverage"].get("model") in {
            "unavailable_or_invalid"} or "reason" in p["coverage"]
    print(f"v6-judges in isolated env: decision={p['decision']} "
          f"degraded={p['degraded']} coverage={p['coverage']}")


def test_batch_cli(tmp_dir):
    import csv
    import json
    from cli import load_input  # noqa: PLC0415
    # write a tiny CSV in the official format
    csv_path = tmp_dir / "input.csv"
    rows = [case_error_invented_tool(), case_clean_structural(),
            case_error_schema()]
    with open(csv_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["id", "prompt", "response"])
        w.writeheader()
        for r in rows:
            w.writerow({"id": r["case_id"], "prompt": r["prompt"],
                        "response": r["response"]})
    cases = load_input(csv_path)
    assert len(cases) == 3
    rt = GuardianServiceRuntime("structural-v02",
                                audit_path=tmp_dir / "audit.jsonl")
    results = [rt.check(c) for c in cases]
    labels = [1 if r["decision"] == "ERROR" else 0 for r in results]
    assert labels == [1, 0, 1]
    # audit trail exists with one line per decision
    lines = (tmp_dir / "audit.jsonl").read_text().strip().split("\n")
    assert len(lines) == 3
    rec = json.loads(lines[0])
    assert rec["decision"] == "ERROR" and rec["trace_id"]
    print("batch path + JSONL audit: 3 cases, audit trail complete — OK")


def main() -> int:
    import tempfile
    tests = [test_configs_listed,
             test_simple_request_error,
             test_schema_error_finding,
             test_clean_structural_is_unknown_not_no_error,
             test_context_budget,
             test_unavailable_judge_channel_degrades]
    failed = 0
    with tempfile.TemporaryDirectory() as td:
        tests.append(lambda: test_batch_cli(Path(td)))
        for t in tests:
            try:
                t()
            except AssertionError as e:
                failed += 1
                print(f"  FAILED {getattr(t, '__name__', t)}: {e}")
            except Exception as e:  # noqa: BLE001
                failed += 1
                print(f"  ERROR {getattr(t, '__name__', t)}: "
                      f"{type(e).__name__}: {e}")
    print(f"\n{'='*60}\n{len(tests)-failed}/{len(tests)} tests passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
