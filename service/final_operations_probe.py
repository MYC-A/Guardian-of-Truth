"""Actual private HTTP outage/recovery and CSV CLI; no benchmark or gold."""
import argparse
import csv
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import uuid
from urllib.parse import urlsplit

from http_probe import call, run as http_smoke

REPO = Path(__file__).resolve().parents[1]


def wait_listener(base, child=None):
    parsed = urlsplit(base)
    deadline = time.monotonic() + 30
    while True:
        try:
            with socket.create_connection((parsed.hostname, parsed.port or 80), timeout=.5):
                return
        except OSError:
            if (child is not None and child.poll() is not None) or time.monotonic() > deadline:
                raise RuntimeError("private HTTP listener failed to start")
            time.sleep(.1)


def run(base, config, output):
    output.mkdir(parents=True, exist_ok=True)
    wait_listener(base)
    live = http_smoke(base, config, output / "http.json")
    assert live["passed"]
    assert live["health"]["body"]["config_id"] == config
    assert live["checks"]["long_input"]["body"]["audit_status"] == "WRITTEN"
    assert live["checks"]["model_error"]["body"]["usage"]["api_calls"] >= 1
    assert live["checks"]["model_supported"]["body"]["usage"]["api_calls"] >= 1
    if config == "r0-service-v1":
        bounded = call(base, "/v1/check", {"case_id": "ops-12001", "prompt": "x" * 12001,
                                         "response": "OK"})
        assert bounded["body"]["decision"] == "UNKNOWN"
        assert bounded["body"]["usage"]["calls"] == 0
        (output / "context_boundary.json").write_text(json.dumps(bounded, indent=2) + "\n",
                                                     encoding="utf-8")
    nonce = uuid.uuid4().hex
    prompt = (
        "⟦SYSTEM⟧\nReport the measured value for the requested item exactly as observed. "
        "Do not invent measurements. Session " + nonce + ".\n[AVAILABLE TOOLS]\n"
        "- read_sensor — Returns a measured value.\n    item_id: string!\n"
        "⟦USER⟧\nWhat is the measured value for OPS-602?\n⟦ASSISTANT⟧\n"
        '→ TOOL_CALL read_sensor: {"item_id":"OPS-602"}\n'
        '← TOOL_RESPONSE read_sensor: {"item_id":"OPS-602","value":23}\n')
    payload = {"case_id": "ops-outage-" + nonce, "prompt": prompt,
               "response": "The measured value for OPS-602 is 23."}
    # A separate throwaway process redirects only its own two providers to a
    # closed loopback port. No credentials, running service or shared env changes.
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        offline_port = sock.getsockname()[1]
    code = (
        "import sys,functools;sys.path.insert(0,'experiments/searh_23/three_architectures');"
        "import llm;llm.PROVIDERS['ollama']=('http://127.0.0.1:9/v1','ops');"
        "llm.PROVIDERS['mistral']=('http://127.0.0.1:9/v1','ops');llm._clients.clear();"
        "llm.chat=functools.partial(llm.chat,use_cache=False,transport_retries=0);"
        "import uvicorn;uvicorn.run('service.app:app',host='127.0.0.1',port="
        + str(offline_port) + ",log_level='warning')")
    env = dict(os.environ, GUARDIAN_CONFIG=config,
               GUARDIAN_AUDIT_PATH=str(output / "offline_audit.jsonl"))
    offline_base = "http://127.0.0.1:" + str(offline_port)
    with (output / "offline_stderr.log").open("w") as log:
        child = subprocess.Popen([sys.executable, "-c", code], cwd=REPO,
                                 env=env, stdout=log, stderr=log)
        try:
            wait_listener(offline_base, child)
            outage = call(offline_base, "/v1/check", payload)
            assert outage["http"] == 200
            body = outage["body"]
            assert body["decision"] == "UNKNOWN" and body["degraded"]
            assert body["audit_status"] == "WRITTEN"
            outage_ready = call(offline_base, "/ready")
            assert not outage_ready["body"]["ready"]
        finally:
            child.terminate()
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=5)
    restored = call(base, "/v1/check", payload)
    assert restored["body"]["decision"] == "NO_ERROR"
    assert not restored["body"]["degraded"]
    assert restored["body"]["usage"]["api_calls"] >= 1
    # Operational CSV, no benchmark inputs/labels. Reuse successful HTTP request
    # cache when possible; CSV labels are checked against measured semantics.
    csv_path = output / "cli_input.csv"
    rows = [{"id": "cli-supported-" + nonce, "prompt": prompt,
             "response": payload["response"]},
            {"id": "cli-structural-" + nonce, "prompt": prompt,
             "response": '→ TOOL_CALL absent_in_catalog: {}'}]
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["id", "prompt", "response"])
        writer.writeheader()
        writer.writerows(rows)
    cli = subprocess.run([sys.executable, "-m", "service.cli", "--input", str(csv_path),
                          "--config", config, "--outdir", str(output / "cli")],
                         cwd=REPO, capture_output=True, text=True, timeout=250)
    (output / "cli_stdout.log").write_text(cli.stdout, encoding="utf-8")
    (output / "cli_stderr.log").write_text(cli.stderr, encoding="utf-8")
    assert cli.returncode == 0
    results = [json.loads(x) for x in (output / "cli/results.jsonl").read_text().splitlines()]
    assert [r["decision"] for r in results] == ["NO_ERROR", "ERROR"]
    assert all(r["audit_status"] == "WRITTEN" for r in results)
    with (output / "cli/predictions.csv").open() as fh:
        assert [r["label"] for r in csv.DictReader(fh)] == ["0", "1"]
    report = {"passed": True, "config_id": config, "outage": outage,
              "outage_ready": outage_ready, "restored": restored,
              "cli_decisions": [r["decision"] for r in results],
              "outage_scope": "Actual HTTP process with both upstream URLs redirected to closed loopback. "
                              "Production service and shared credentials untouched; recovery uses live providers."}
    (output / "operations.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                                           encoding="utf-8")
    return report


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--base", default="http://127.0.0.1:18090")
    p.add_argument("--config", default="r0-service-v1")
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    result = run(args.base, args.config, args.output)
    print(json.dumps({"passed": result["passed"], "config_id": result["config_id"],
                      "outage": result["outage"]["body"]["decision"],
                      "restored": result["restored"]["body"]["decision"],
                      "cli": result["cli_decisions"]}))
