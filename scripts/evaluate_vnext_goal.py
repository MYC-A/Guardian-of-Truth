"""Freeze, sequentially predict, seal, then score all controlled Goal/Plan cases."""

from datetime import datetime, timezone
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys

from guardian_truth.llm_client import ChatClient, ClientConfig
from guardian_truth.runtime import provider_config
from guardian_truth.settings import load_env_file
from guardian_truth.vnext.experiment import PersistedSemanticBackend, ProviderPause
from guardian_truth.vnext.integrity import digest, file_digest, prediction_seal, verify_files, write_new
from guardian_truth.vnext.semantic import ChatSemanticBackend
from guardian_truth.vnext.stage_goal import METRIC_RULES, predict_goal, stage_input
from guardian_truth.vnext.stage_results import summarize_goal


ROOT = Path(__file__).resolve().parents[1]
INCUMBENT = ROOT.parent / "Guardian of Truth"
EXPECTED_X0 = "afb7906c3a3244fbc4196fe5cb2ea18ee86e0d96"


def git_head(root):
    return subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], check=True,
        capture_output=True, text=True).stdout.strip()


def baseline_x0(value):
    data = stage_input(value)
    program = (
        "import json,sys; from guardian_truth.pipeline import Detector; "
        "p=json.load(sys.stdin); r=Detector().review(p['prompt'],p['response']); "
        "print(json.dumps({'status':r.status,'binary_label':int(r.status=='violation'),"
        "'findings':[f.code for f in r.findings],'unresolved':r.unresolved,"
        "'mapping':'fixed violation=1; otherwise0 is incumbent fallback, not safety proof'}))"
    )
    environment = {key: os.environ[key] for key in ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP") if key in os.environ}
    environment.update(PYTHONPATH=str(INCUMBENT / "src"), PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1")
    result = subprocess.run([sys.executable, "-B", "-c", program], cwd=INCUMBENT, env=environment,
        input=json.dumps({"prompt": data.prompt, "response": data.response}, ensure_ascii=False).encode("utf-8"),
        capture_output=True, check=True)
    return json.loads(result.stdout.decode("utf-8"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--gate", type=Path, default=ROOT / "outputs/vnext/provider_gate_v1.json")
    args = parser.parse_args()
    if not re.fullmatch(r"v[1-9][0-9]*", args.version):
        raise ValueError("versioned stage required")
    prefix = "goal_plan_" + args.version
    output = ROOT / "outputs/vnext"
    freeze_path, predictions_path = output / (prefix + "_freeze.json"), output / (prefix + "_predictions.json")
    report_path, seal_path = output / (prefix + "_results.json"), output / (prefix + "_prediction_seal.json")
    if report_path.exists():
        raise FileExistsError("joined stage result is immutable; do not rerun the same version")
    if git_head(INCUMBENT) != EXPECTED_X0:
        raise ValueError("protected incumbent commit changed")
    if subprocess.run(["git", "diff", "--quiet", "HEAD", "--", "src"], cwd=INCUMBENT).returncode:
        raise ValueError("incumbent source has uncommitted changes")
    benchmark_path = ROOT / "benchmarks/vnext/goal_plan_v1.json"
    benchmark = json.loads(benchmark_path.read_text(encoding="utf-8"))
    if digest(benchmark["cases"]) != benchmark["cases_sha256"]:
        raise ValueError("controlled benchmark hash mismatch")
    # Explicitly separate only-input request processing from post-prediction gold.
    cases = [{"case_id": case["case_id"], "input": case["input"]} for case in benchmark["cases"]]
    ids = [case["case_id"] for case in cases]
    gate = json.loads(args.gate.read_text(encoding="utf-8"))
    if gate["status"] != "PASSED" or gate["attempted"] != 12:
        raise ValueError("development provider reliability gate not admitted")
    definition = {"provider": "bai", "model": "qwen3.8-flash", "temperature": 0,
        "timeout_seconds": 180, "max_output_tokens": 2048, "max_retries": 0,
        "response_format_mode": "none", "interval_seconds": 10,
        "metric_rules": METRIC_RULES, "max_worlds": 4096, "escalation_steps": 0,
        "binary_mapping": "guardian-vnext-product-mapping-v1: competition",
        "baseline_x0": EXPECTED_X0, "random_seed": 260913,
        "scope": "controlled dev stage; no blind data; no model confidence adjudication"}
    source_files = [path.relative_to(ROOT).as_posix() for path in (ROOT / "src/guardian_truth").rglob("*.py")]
    source_files += ["scripts/evaluate_vnext_goal.py"]
    if freeze_path.exists():
        freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
        if (freeze["definition_sha256"] != digest(definition) or freeze["case_ids"] != ids
                or freeze["benchmark_sha256"] != file_digest(benchmark_path)
                or verify_files(ROOT, freeze["source_sha256"])
                or verify_files(INCUMBENT, freeze["baseline_source_sha256"])):
            raise ValueError("resumed stage implementation/input/configuration changed")
    else:
        freeze = {"schema_version": "guardian-vnext-goal-stage-freeze-v1",
            "architecture_commit": git_head(ROOT), "definition": definition, "definition_sha256": digest(definition),
            "source_sha256": {name: file_digest(ROOT / name) for name in sorted(source_files)},
            "baseline_source_sha256": {path.relative_to(INCUMBENT).as_posix(): file_digest(path)
                for path in (INCUMBENT / "src/guardian_truth").rglob("*.py")},
            "case_ids": ids, "benchmark_sha256": file_digest(benchmark_path),
            "gate_sha256": file_digest(args.gate), "case_input_sha256": digest(cases),
            "prompt_hash_policy": "each exact task payload/schema/messages hash persisted BEFORE transport",
            "frozen_utc": datetime.now(timezone.utc).isoformat()}
        write_new(freeze_path, freeze)
    load_env_file(args.env_file)
    config = provider_config(ClientConfig(timeout_seconds=180, max_output_tokens=2048,
        max_retries=0, response_format_mode="none"), "bai", model="qwen3.8-flash")
    live_records = []
    delegate = ChatSemanticBackend(ChatClient(config), interval_seconds=10, checkpoint=live_records.append)
    predictions = []
    try:
        for index, case in enumerate(cases):
            path = output / f"{prefix}_case_{index:03d}.json"
            if path.exists():
                row = json.loads(path.read_text(encoding="utf-8"))
                if row["case_id"] != case["case_id"] or row["configuration_sha256"] != digest(freeze):
                    raise ValueError("cached case belongs to another experiment")
            else:
                backend = PersistedSemanticBackend(delegate, output, f"{prefix}_case_{index:03d}",
                    configuration_sha256=digest(freeze), live_records=live_records)
                prediction = predict_goal(case["input"], backend)
                row = {"case_id": case["case_id"], "configuration_sha256": digest(freeze),
                    "prediction": prediction, "request_telemetry": backend.records,
                    "baseline_x0": baseline_x0(case["input"])}
                write_new(path, row)
                print(json.dumps({"completed": index + 1, "total": len(cases), "case_id": case["case_id"],
                    "core_status": prediction["core_result"]["status"], "requests": len(backend.records)}), flush=True)
            predictions.append(row)
    except ProviderPause as error:
        print(json.dumps({"status": "PROVIDER_PAUSED", "reason": str(error), "completed": len(predictions),
            "total": len(cases), "same_experiment_resumable": True}), flush=True)
        return 2
    if predictions_path.exists():
        if digest(json.loads(predictions_path.read_text(encoding="utf-8"))) != digest(predictions):
            raise ValueError("prediction artifact changed")
    else:
        write_new(predictions_path, predictions)
    seal = prediction_seal(predictions, ids, architecture_commit=freeze["architecture_commit"],
        configuration_sha256=digest(freeze))
    if seal_path.exists():
        if json.loads(seal_path.read_text(encoding="utf-8")) != seal:
            raise ValueError("prediction seal changed")
    else:
        write_new(seal_path, seal)
    # Full predictions and a separate hash seal exist before controlled gold joins.
    if digest(json.loads(predictions_path.read_text(encoding="utf-8"))) != seal["prediction_sha256"]:
        raise ValueError("prediction seal invalid")
    report = {"schema_version": "guardian-vnext-goal-stage-result-v1", "experiment": prefix,
        "architecture_commit": freeze["architecture_commit"], "freeze_sha256": file_digest(freeze_path),
        "predictions_sha256": file_digest(predictions_path), "prediction_seal_sha256": file_digest(seal_path),
        "scope": "CONTROLLED_DEVELOPMENT_EXTENSION", **summarize_goal(benchmark["cases"], predictions),
        "created_utc": datetime.now(timezone.utc).isoformat(), "blind_cases_read": 0}
    write_new(report_path, report)
    write_new(output / (prefix + "_failure_audit.json"), {"experiment": prefix,
        "source_report_sha256": file_digest(report_path), "cases": report["failure_taxonomy"]})
    print(json.dumps({key: report[key] for key in ("experiment", "case_count", "core", "provider")}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
