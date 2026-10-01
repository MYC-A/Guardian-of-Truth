"""One bounded live ASGI/API smoke for the Stage-A service.

This is a smoke, not a benchmark. It retains response payloads but redacts
credentials by never writing the environment or provider client objects.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "service"))

from fastapi.testclient import TestClient  # noqa: E402
from service import app as service_app  # noqa: E402
from service.runtime import GuardianServiceRuntime  # noqa: E402

OUT = Path(__file__).resolve().parent / "outputs" / "http_live_smoke"
OUT.mkdir(parents=True, exist_ok=True)

PROMPT = (
    "⟦SYSTEM⟧\nReport account balances exactly as returned by the latest "
    "get_balance result. Do not invent amounts.\n\n"
    "[AVAILABLE TOOLS]\n"
    "- get_balance — Returns the current balance of an account.\n"
    "    account_id: string! — account identifier\n\n"
    "⟦USER⟧\nWhat is the balance of account A-77?\n"
    "⟦ASSISTANT⟧\n→ TOOL_CALL get_balance: {\"account_id\": \"A-77\"}\n"
    "← TOOL_RESPONSE get_balance: {\"account_id\": \"A-77\", "
    "\"balance\": 120.5}\n"
)


def _post(client, case_id: str, response: str, config_id: str):
    start = time.monotonic()
    http = client.post("/v1/check", json={
        "case_id": case_id, "prompt": PROMPT, "response": response,
        "config_id": config_id,
    })
    data = http.json()
    return {"http_status": http.status_code,
            "elapsed_s": round(time.monotonic() - start, 3),
            "result": data}


def main():
    import judge

    service_app.AUDIT_PATH = OUT / "audit.jsonl"
    service_app._runtime = GuardianServiceRuntime(
        "v6-judges", audit_path=service_app.AUDIT_PATH)
    with TestClient(service_app.app) as client:
        report = {"health": client.get("/health").json(),
                  "ready": client.get("/ready").json()}
        report["structural_error"] = _post(
            client, "live.structural", "→ TOOL_CALL transfer_funds: {}",
            "structural-v02")
        report["model_error"] = _post(
            client, "live.model_error",
            "The balance of account A-77 is 999.", "v6-judges")
        report["model_no_error"] = _post(
            client, "live.model_no_error",
            "The balance of account A-77 is 120.5.", "v6-judges")
        report["long_input"] = _post(
            client, "live.long_input", "x" * 200001, "v6-judges")
        batch = client.post("/v1/check/batch", json={
            "config_id": "structural-v02",
            "cases": [
                {"case_id": "batch.error", "prompt": PROMPT,
                 "response": "→ TOOL_CALL transfer_funds: {}"},
                {"case_id": "batch.clean", "prompt": PROMPT,
                 "response": "The balance of account A-77 is 120.5."},
            ]})
        report["batch"] = {"http_status": batch.status_code,
                           "result": batch.json()}
        original = judge.ask_vote
        try:
            judge.ask_vote = lambda *a, **kw: (_ for _ in ()).throw(
                ConnectionError("injected channel outage"))
            report["degraded"] = _post(
                client, "live.degraded",
                "The balance of account A-77 is 120.5.", "v6-judges")
        finally:
            judge.ask_vote = original
        report["recovered"] = _post(
            client, "live.recovered",
            "The balance of account A-77 is 120.5.", "v6-judges")

    (OUT / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    for name in ("structural_error", "model_error", "model_no_error",
                 "long_input", "degraded", "recovered"):
        result = report[name]["result"]
        print(name, report[name]["http_status"], result.get("decision"),
              len(result.get("findings") or []), result.get("degraded"),
              report[name]["elapsed_s"], flush=True)
    print("report:", OUT / "report.json", flush=True)


if __name__ == "__main__":
    main()
