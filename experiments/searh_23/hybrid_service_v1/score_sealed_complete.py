"""Gate the ENTIRE preregistered sealed shortlist before opening any gold."""
import argparse
import hashlib
import json
from pathlib import Path

from score_campaign import DATA, score, _family_bootstrap_delta

HERE = Path(__file__).resolve().parent


def run(directories, output):
    protocol_file = HERE / "dataset/sealed_hybrid_v1/protocol.json"
    protocol = json.loads(protocol_file.read_text(encoding="utf-8"))
    input_file = DATA / "sealed_input.jsonl"
    if hashlib.sha256(input_file.read_bytes()).hexdigest() != protocol["input_sha256"]:
        raise ValueError("sealed input hash mismatch")
    expected_ids = [r["id"] for r in map(json.loads,
        input_file.read_text(encoding="utf-8").splitlines())]
    configs, by_arm = [], {}
    # This pass never loads labels. Validate both full input sets and all arms.
    for directory in directories:
        status = json.loads((directory / "status.json").read_text(encoding="utf-8"))
        summary = json.loads((directory / "summary.json").read_text(encoding="utf-8"))
        if status["state"] != "SUCCEEDED" or summary["state"] != "SUCCEEDED":
            raise ValueError("all planned sealed runs must be complete before gold")
        config = json.loads((directory / "run_config.json").read_text(encoding="utf-8"))
        if (config["split"] != "sealed" or config["input_sha256"] != protocol["input_sha256"]
                or config["case_ids"] != expected_ids
                or len(set(config["case_ids"])) != protocol["n"]):
            raise ValueError("not the registered sealed input set")
        configs.append(config)
        for line in (directory / "results.jsonl").read_text(encoding="utf-8").splitlines():
            record = json.loads(line)
            if record["status"] != "COMPLETED" or record["run_id"] != status["run_id"]:
                raise ValueError("invalid or wrong-run prediction")
            arm, cid = record["config_id"], record["case_id"]
            group = by_arm.setdefault(arm, {})
            if cid in group:
                raise ValueError("duplicate sealed prediction")
            group[cid] = record
    if any(config["case_ids"] != configs[0]["case_ids"] for config in configs):
        raise ValueError("different sealed input IDs/order")
    ids = configs[0]["case_ids"]
    if set(by_arm) != set(protocol["arms"]) or any(set(g) != set(ids) for g in by_arm.values()):
        raise ValueError("missing or extra registered arms/cases")
    # The complete set is now established. Gold can enter these scorers.
    scores = {}
    for directory in directories:
        scores.update(score(directory)["arms"])
    gold = {r["id"]: r for r in map(json.loads,
        (DATA / "sealed_gold.jsonl").read_text(encoding="utf-8").splitlines())}
    baseline = by_arm["g0-direct"]
    paired = {}
    for arm, candidate in by_arm.items():
        if arm == "g0-direct":
            continue
        recovered, harmed, same_wrong = [], [], []
        for cid in ids:
            first = int(baseline[cid]["decision"] == "ERROR")
            second = int(candidate[cid]["decision"] == "ERROR")
            y = gold[cid]["label"]
            if first != y and second == y:
                recovered.append(cid)
            elif first == y and second != y:
                harmed.append(cid)
            elif first != y and second != y:
                same_wrong.append(cid)
        paired[arm] = {"recovered": recovered, "harmed": harmed, "same_wrong": same_wrong,
                      **_family_bootstrap_delta(gold, baseline, candidate, ids)}
    result = {"schema": "sealed-complete-comparison/1", "protocol": protocol,
        "protocol_sha256": hashlib.sha256(protocol_file.read_bytes()).hexdigest(),
        "runs": [str(d) for d in directories], "n": len(ids), "arms": scores,
        "paired_vs_g0": paired,
        "limitations": [protocol["scope"], "Constructed gold, not independent human labels.",
            "API names are fixed but hosted weight revisions are not independently verified.",
            "Cache-hit latency and logical tokens are reported separately from live API usage."]}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--runs", nargs="+", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    result = run(args.runs, args.output)
    print(json.dumps({arm: {key: value[key] for key in
        ("tp", "fp", "fn", "tn", "unknown", "f1", "api_calls", "api_tokens")}
        for arm, value in result["arms"].items()}, indent=2))
