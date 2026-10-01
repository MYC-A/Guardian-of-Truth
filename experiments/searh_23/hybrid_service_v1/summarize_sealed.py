"""Post-evaluation error atlas and incremental comparisons, never inference."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

from score_sealed_complete import run as complete_score
from score_campaign import DATA


def summarize(directories, output):
    scored = complete_score(directories, output / "score.json")
    inputs = {r["id"]: r for r in map(json.loads,
        (DATA / "sealed_input.jsonl").read_text(encoding="utf-8").splitlines())}
    gold = {r["id"]: r for r in map(json.loads,
        (DATA / "sealed_gold.jsonl").read_text(encoding="utf-8").splitlines())}
    by_arm, hashes = {}, {}
    for directory in directories:
        source = directory / "results.jsonl"
        hashes[str(source)] = hashlib.sha256(source.read_bytes()).hexdigest()
        for r in map(json.loads, source.read_text(encoding="utf-8").splitlines()):
            by_arm.setdefault(r["config_id"], {})[r["case_id"]] = r
    errors, modules = {}, {}
    for arm, records in by_arm.items():
        errors[arm] = [{"case": inputs[cid], "gold": gold[cid],
                        "decision": r["decision"], "findings": r["result"]["findings"],
                        "review_trace": [t for t in r["result"]["module_trace"]
                                         if t.get("module", "").startswith("independent-counterevidence")],
                        "usage": r["usage"]}
                       for cid, r in records.items()
                       if int(r["decision"] == "ERROR") != gold[cid]["label"]]
        modules[arm] = dict(Counter(t["module"] for r in records.values()
                                    for t in r["result"]["module_trace"]))
    incremental = {}
    for reference, candidate in (("r0-refute-positive", "r2-ge-refute-positive"),
                                 ("r2-ge-refute-positive", "h3-ge-native-review"),
                                 ("r0-refute-positive", "h3-ge-native-review")):
        better, worse = [], []
        for cid in inputs:
            first = int(by_arm[reference][cid]["decision"] == "ERROR")
            second = int(by_arm[candidate][cid]["decision"] == "ERROR")
            if first != gold[cid]["label"] and second == gold[cid]["label"]:
                better.append(cid)
            elif first == gold[cid]["label"] and second != gold[cid]["label"]:
                worse.append(cid)
        incremental[candidate + " vs " + reference] = {"better": better, "worse": worse}
    result = {"schema": "sealed-error-atlas/1", "n": scored["n"],
              "prediction_sha256": hashes, "errors": errors,
              "incremental": incremental, "module_counts": modules,
              "warning": "Post-gold diagnosis only. No algorithm changes or new vote combinations."}
    (output / "error_atlas.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                                            encoding="utf-8")
    return result


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--runs", nargs="+", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    result = summarize(args.runs, args.output)
    print(json.dumps({"incremental": result["incremental"],
                      "module_counts": result["module_counts"]}, indent=2))
