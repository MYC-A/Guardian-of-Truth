"""Freeze/verify/run/score Goal v3 extraction experiment v3; no Policy calls."""

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import runpy
import subprocess

from guardian_truth.llm_client import ChatClient, ClientConfig
from guardian_truth.settings import load_env_file
from guardian_truth.vnext.goal_v3_isolation_frontend_v3 import PROMPT_SHA256, SCHEMA_SHA256, VERSION
from guardian_truth.vnext.goal_v3_isolation_runner_v3 import CONFIG, StageRunnerV3, immutable
from guardian_truth.vnext.goal_v3_isolation_scoring_v2 import score_case_v2, summarize_v2
from guardian_truth.vnext.goal_v3_isolation_stage_gates_v3 import CORE_GATES, experiment_budget_v3, core_decision_v2, smoke_decision, stress_decision_v2
from guardian_truth.vnext.integrity import digest, file_digest, prediction_seal, verify_files, write_new


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/vnext"


def path(name):
    return OUT / ("goal_v3_isolation_v3_" + name + ".json")


def read(name):
    return json.loads(path(name).read_text(encoding="utf-8"))


def freeze():
    if any(path(name).exists() for name in ("inputs", "gold", "inference_freeze")):
        raise FileExistsError("v2 freeze artifacts already exist; never overwrite")
    corpus = runpy.run_path(str(ROOT / "benchmarks/vnext/goal_v3_isolation_cases_v2.py"))
    cases = corpus["build_cases"]()
    s1 = corpus["S1_CASE_IDS"]
    core = [row["case_id"] for row in cases if row["split"] == "CORE"]
    stages = {"S1": s1, "S2": [cid for cid in core if cid not in s1],
        "S3": [row["case_id"] for row in cases if row["split"] == "STRESS"]}
    if len(cases) != 60 or [len(stages[key]) for key in ("S1", "S2", "S3")] != [12, 36, 12]:
        raise ValueError("invalid stage inventory")
    # Capture package source as well: package initialization imports legacy
    # Detector modules, but no Policy parser/verdict is executed or consumed.
    sources = sorted(name for name in subprocess.run(["rg", "--files", "src/guardian_truth"],
        cwd=ROOT, check=True, capture_output=True, text=True).stdout.splitlines() if name.endswith(".py"))
    sources += ["scripts/evaluate_goal_v3_isolation_v3.py", "scripts/audit_goal_v3_isolation_v3_receipts.py", "benchmarks/vnext/goal_v3_isolation_cases_v2.py",
        "docs/vnext/GOAL_V3_ISOLATION_V3_RUN_PROTOCOL.md",
        "docs/vnext/GOAL_V3_ISOLATION_V3_RUN_PROTOCOL.md",
        "docs/vnext/GOAL_V3_ISOLATION_V3_RUN_PROTOCOL.md"]
    sources += sorted(name for name in subprocess.run(["rg", "--files", "tests"], cwd=ROOT,
        check=True, capture_output=True, text=True).stdout.splitlines()
        if "goal_v3" in name and name.endswith(("_v2.py", "_v3.py")))
    sources = [name.replace("\\", "/") for name in sources]
    if subprocess.run(["git", "diff", "--quiet", "HEAD", "--", *sources], cwd=ROOT).returncode:
        raise ValueError("commit all experiment sources before freeze")
    for name in sources:
        if subprocess.run(["git", "ls-files", "--error-unmatch", name], cwd=ROOT, capture_output=True).returncode:
            raise ValueError("untracked freeze source")
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, check=True,
        capture_output=True, text=True).stdout.strip()
    write_new(path("inputs"), [{"case_id": row["case_id"], "source": row["source"]} for row in cases])
    write_new(path("gold"), {row["case_id"]: row["gold"] for row in cases})
    manifest = {"schema_version": "guardian-goal-v3-isolation-freeze-v3", "predecessor_freeze_sha256": file_digest(OUT / "goal_v3_isolation_v2_inference_freeze.json"), "corpus_reuse": "EXACT_V2_DEVELOPMENT_AWARE_INPUTS_AND_GOLD_FORMAT_INTERVENTION_NOT_BLIND", "architecture_commit": commit,
        "implementation_origin_commit": "48b84e3875b960d43956576735d543e8c4e5917b",
        "scope": "GOAL_ONLY_DEVELOPMENT_AWARE_CONTROLLED_CORPUS_NOT_BLIND_OR_WHOLE_CORE",
        "frontend_version": VERSION, "prompt_sha256": PROMPT_SHA256, "schema_sha256": SCHEMA_SHA256,
        "configuration": CONFIG, "configuration_sha256": digest(CONFIG), "core_gates": CORE_GATES,
        "stages": stages, "case_ids": [row["case_id"] for row in cases],
        "case_inventory": [{key: row[key] for key in ("case_id", "pair_id", "families", "split", "factor_path", "factor_description", "invariant")}
            for row in cases], "inputs_sha256": file_digest(path("inputs")), "gold_sha256": file_digest(path("gold")),
        "source_sha256": {name: file_digest(ROOT / name) for name in sources},
        "experimental_llm_calls_before_freeze": 0, "max_semantic_cases": 60, "max_physical_requests": 120,
        "partial_stage_rule": "SEAL_ATTEMPTED_PREFIX_BEFORE_GOLD_BUDGET_STOP_NOT_SEMANTIC_REJECT",
        "gold_join_rule": "VALIDATE_CURRENT_AND_PRIOR_STAGE_SEALS_BEFORE_GOLD_OPEN"}
    write_new(path("inference_freeze"), manifest)
    return {"status": "FROZEN_NOT_RUN", "cases": 60, "commit": commit}


def verify():
    frozen = read("inference_freeze")
    if (verify_files(ROOT, frozen["source_sha256"])
            or file_digest(path("inputs")) != frozen["inputs_sha256"]
            or file_digest(path("gold")) != frozen["gold_sha256"]
            or frozen["configuration"] != CONFIG or frozen["configuration_sha256"] != digest(CONFIG)
            or frozen["prompt_sha256"] != PROMPT_SHA256 or frozen["schema_sha256"] != SCHEMA_SHA256):
        raise ValueError("v2 experiment freeze integrity failed")
    return frozen


def sealed_stage(stage, frozen):
    rows, seal, boundary = read(stage + "_predictions"), read(stage + "_prediction_seal"), read(stage + "_boundary")
    ids = [row["case_id"] for row in rows]
    if not ids or ids != frozen["stages"][stage][:len(ids)]:
        raise ValueError("attempted stage must be exact requested prefix")
    expected = prediction_seal(rows, ids, architecture_commit=frozen["architecture_commit"], configuration_sha256=digest(frozen))
    if (seal != expected or boundary["requested_case_ids"] != frozen["stages"][stage]
            or boundary["attempted_case_ids"] != ids or boundary["seal_sha256"] != digest(seal)
            or boundary["prediction_sha256"] != digest(rows)
            or boundary["configuration_sha256"] != digest(frozen)):
        raise ValueError("stage prediction seal/boundary mismatch")
    records = [record for row in rows for record in row["request_telemetry"]]
    budget = experiment_budget_v3(records, ceiling=frozen["configuration"]["reported_token_ceilings"][stage],
        enforce_token_ceiling=frozen["configuration"]["enforce_token_ceilings"])
    if (boundary["budget"] != asdict(budget)
            or boundary["complete"] != (len(ids) == len(frozen["stages"][stage]))
            or boundary["not_run_case_ids"] != frozen["stages"][stage][len(ids):]):
        raise ValueError("stage budget/completion boundary mismatch")
    # Reconstruct cases exclusively from physical captures; no network client.
    class NoNetwork:
        def complete(self, *args, **kwargs):
            raise ValueError("sealed stage lacks physical capture")
    runner = StageRunnerV3(OUT, frozen, NoNetwork(), sleeper=lambda _: None)
    sources = {row["case_id"]: row["source"] for row in read("inputs")}
    for row in rows:
        count = row.get("physical_requests")
        if type(count) is not int or count not in {1, 2}:
            raise ValueError("invalid physical request count")
        stem = "case_" + row["case_id"].replace(":", "_").lower()
        required = [runner.path(stem)] + [runner.path(stem + f"_request_{ordinal:03d}" + suffix)
            for ordinal in range(count) for suffix in ("", "_result")]
        if not all(target.is_file() for target in required):
            raise ValueError("sealed stage lacks physical capture")
        if digest(row) != digest(runner.case(row["case_id"], sources[row["case_id"]])):
            raise ValueError("sealed prediction differs from physical replay")
    return rows, boundary


def cost(rows):
    records = [record for row in rows for record in row["request_telemetry"]]
    totals = {key: sum(record.get("usage", {}).get(key, 0) for record in records)
        for key in ("prompt_tokens", "completion_tokens", "total_tokens")}
    complete = all(all(type(record.get("usage", {}).get(key)) is int
        and record["usage"][key] >= 0 for key in totals) for record in records)
    return {"semantic_cases_attempted": len(rows), "admitted_physical_requests": len(records),
        "transport_retries": len(records) - len(rows),
        "successful_deliveries": sum(record["transport_status"] == "SUCCESS" for record in records),
        "usage_complete": complete, "reported_usage": totals,
        "unreported_usage_requests": sum(not all(type(record.get("usage", {}).get(key)) is int
            and record["usage"][key] >= 0 for key in totals) for record in records),
        "reported_usage_scope": "AVAILABLE_REQUESTS_ONLY_NOT_TOTAL_BILLING" if not complete else "ALL_REQUESTS",
        "tokens_per_case": totals["total_tokens"] / len(rows) if complete else None,
        "financial_cost": None, "financial_cost_reason": "NOT_PROVIDED_NOT_ESTIMATED"}


def score(stage):
    frozen = verify()
    stage_names = ["S1", "S2", "S3"][:["S1", "S2", "S3"].index(stage) + 1]
    captured = {name: sealed_stage(name, frozen) for name in stage_names}
    # No gold read above this line. Prior admission uses sealed re-scoring.
    if stage != "S1" and score("S1")["admission"]["verdict"] != "ADMIT_S2":
        raise ValueError("S1 did not admit S2")
    if stage == "S3" and score("S2")["admission"]["verdict"] != "ADMIT_S3":
        raise ValueError("core did not admit stress")
    gold = read("gold")
    inputs = {row["case_id"]: row["source"] for row in read("inputs")}
    inventory = {row["case_id"]: row for row in frozen["case_inventory"]}
    current, boundary = captured[stage]
    all_predictions = [row for name in stage_names for row in captured[name][0]]
    predictions = all_predictions if stage == "S2" else current
    scored = [score_case_v2(row["case_id"], inputs[row["case_id"]], gold[row["case_id"]], row, inventory[row["case_id"]])
        for row in predictions]
    metrics = summarize_v2(scored)
    physical = [record for row in current for record in row["request_telemetry"]]
    if not boundary["budget"]["admit_next_request"]:
        admission = {"verdict": "BUDGET_STOP", "reason": boundary["budget"]["stop_reason"]}
    elif stage == "S1":
        admission = asdict(smoke_decision(scored, physical,
            enforce_token_ceiling=frozen["configuration"]["enforce_token_ceilings"]))
    elif stage == "S2":
        admission = core_decision_v2(metrics)
    else:
        admission = stress_decision_v2(metrics)
    report = {"experiment": "goal_v3_isolation_v3", "stage": stage,
        "implementation_commit": frozen["architecture_commit"], "frontend_version": VERSION,
        "inference_freeze_sha256": file_digest(path("inference_freeze")),
        "prediction_seal_sha256": file_digest(path(stage + "_prediction_seal")),
        "metrics": metrics, "case_scores": scored, "admission": admission,
        "cost": cost(current), "cumulative_cost": cost(all_predictions),
        "not_run_case_ids": [cid for cid in frozen["case_ids"] if cid not in {row["case_id"] for row in all_predictions}]}
    immutable(path(stage + "_results"), report)
    return report


def run(stage, env_file):
    frozen = verify()
    if stage == "S2" and score("S1")["admission"]["verdict"] != "ADMIT_S2":
        raise ValueError("S1 rejected S2")
    if stage == "S3" and score("S2")["admission"]["verdict"] != "ADMIT_S3":
        raise ValueError("core rejected stress")
    if env_file is None or not load_env_file(env_file):
        raise ValueError("explicit existing env file required")
    client = ChatClient(ClientConfig(base_url=CONFIG["base_url"], model=CONFIG["model"],
        api_key_env=CONFIG["api_key_env"], timeout_seconds=CONFIG["timeout_seconds"],
        max_output_tokens=CONFIG["max_output_tokens"], max_retries=0, response_format_mode="auto"))
    client.validate_configuration()  # local validation only, never an API ping
    inputs = {row["case_id"]: row["source"] for row in read("inputs")}
    return StageRunnerV3(OUT, frozen, client).run(stage, inputs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("freeze", "verify", "run", "score", "batch"))
    parser.add_argument("--stage", choices=("S1", "S2", "S3"))
    parser.add_argument("--env-file", type=Path)
    args = parser.parse_args()
    if args.phase == "freeze":
        result = freeze()
    elif args.phase == "verify":
        frozen = verify()
        result = {"status": "FREEZE_INTACT", "commit": frozen["architecture_commit"]}
    else:
        if args.stage is None:
            parser.error("--stage required")
        result = run(args.stage, args.env_file) if args.phase in {"run", "batch"} else score(args.stage)
        if args.phase == "batch":
            result = score(args.stage)
        if args.phase in {"score", "batch"}:
            result = {"stage": args.stage, "admission": result["admission"], "cost": result["cost"]}
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
