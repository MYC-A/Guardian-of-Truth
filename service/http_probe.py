"""Small operational probe of the real HTTP listener, never a benchmark."""
import argparse
import json
import urllib.error
import urllib.request
from pathlib import Path


def call(base, path, payload=None):
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(base + path, data=body,
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=250) as response:
            return {"http": response.status, "body": json.loads(response.read())}
    except urllib.error.HTTPError as exc:
        return {"http": exc.code, "body": json.loads(exc.read())}


def run(base, config, output):
    prompt = (
        "⟦SYSTEM⟧\nWhen reporting a measurement, use the observed result for the same item. "
        "Do not invent a measured value.\n[AVAILABLE TOOLS]\n"
        "- read_measurement — Reports the measured value.\n    item_id: string!\n"
        "⟦USER⟧\nWhat is the measurement for OP-731?\n⟦ASSISTANT⟧\n"
        '→ TOOL_CALL read_measurement: {"item_id":"OP-731"}\n'
        '← TOOL_RESPONSE read_measurement: {"item_id":"OP-731","value":14}\n')
    probes = {
        "structural_error": {"case_id": "ops-structural", "prompt": prompt,
            "response": '→ TOOL_CALL absent_in_catalog: {}', "config_id": "structural-v02"},
        "offline_clean_unknown": {"case_id": "ops-offline", "prompt": prompt,
            "response": "The measured value for OP-731 is 14.", "config_id": "structural-v02"},
        "model_error": {"case_id": "ops-model-error", "prompt": prompt,
            "response": "The measured value for OP-731 is 99.", "config_id": config},
        "model_supported": {"case_id": "ops-model-supported", "prompt": prompt,
            "response": "The measured value for OP-731 is 14.", "config_id": config},
        "long_input": {"case_id": "ops-long", "prompt": "x" * 200001,
            "response": "OK", "config_id": config},
    }
    report = {"purpose": "operational smoke, no quality selection",
              "health": call(base, "/health"), "ready": call(base, "/ready"),
              "checks": {}}
    for name, payload in probes.items():
        report["checks"][name] = call(base, "/v1/check", payload)
    report["batch"] = call(base, "/v1/check/batch", {"config_id": "structural-v02",
        "cases": [{k: v for k, v in probes[name].items() if k != "config_id"}
                  for name in ("structural_error", "offline_clean_unknown")]})
    expected = {"structural_error": "ERROR", "offline_clean_unknown": "UNKNOWN",
                "model_error": "ERROR", "model_supported": "NO_ERROR", "long_input": "UNKNOWN"}
    report["passed"] = all(report["checks"][name]["http"] == 200 and
        report["checks"][name]["body"]["decision"] == verdict for name, verdict in expected.items())
    for name in ("structural_error", "model_error"):
        report["passed"] &= bool(report["checks"][name]["body"].get("findings"))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--base", default="http://127.0.0.1:18090")
    p.add_argument("--config", default="r2-ge-refute-positive")
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    result = run(args.base, args.config, args.output)
    print(json.dumps({"passed": result["passed"], "decisions": {name:
        row["body"].get("decision") for name, row in result["checks"].items()}}))
    raise SystemExit(0 if result["passed"] else 1)
