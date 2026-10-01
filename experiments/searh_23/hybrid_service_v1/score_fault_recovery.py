"""Tagged injection recovery, kept separate from natural upstream error rates."""
import argparse
import json
from pathlib import Path

from score_campaign import DATA, score

HERE = Path(__file__).resolve().parent


def report(directories, output):
    protocol = json.loads((HERE / "dataset/fault_injections_v1/protocol.json").read_text(
        encoding="utf-8"))
    # Ensure every planned journal is complete before labels enter this scorer.
    for folder in directories:
        status = json.loads((folder / "status.json").read_text(encoding="utf-8"))
        if status["state"] != "SUCCEEDED":
            raise ValueError("fault campaign incomplete")
    gold = {r["id"]: r for r in map(json.loads,
        (DATA / "dev_gold.jsonl").read_text(encoding="utf-8").splitlines())}
    combined = {}
    for folder in directories:
        score(folder)
        rows = [json.loads(line) for line in (folder / "results.jsonl").read_text(
            encoding="utf-8").splitlines()]
        for row in rows:
            key = (row["config_id"], row["case_id"])
            if key in combined:
                raise ValueError("duplicate injection outcome")
            combined[key] = row
    arms = sorted({arm for arm, _ in combined})
    matrix = []
    for spec in protocol["cases"]:
        cid = spec["id"]
        line = dict(spec, label=gold[cid]["label"], outcomes={})
        before_wrong = int(spec["synthetic_first_decision"] == "ERROR") != line["label"]
        for arm in arms:
            row = combined[(arm, cid)]
            review = row["result"]["module_trace"][-1]
            right = int(row["decision"] == "ERROR") == line["label"]
            line["outcomes"][arm] = {"decision": row["decision"],
                "recovered": before_wrong and right,
                "harmed": not before_wrong and not right,
                "valid": review["valid"], "reason": review["reason"],
                "calls": row["usage"].get("calls"), "tokens": row["usage"].get("tokens")}
        matrix.append(line)
    result = {"schema": "fault-recovery-matrix/1", "warning": protocol["warning"],
              "not_covered": protocol["not_covered"], "rows": matrix,
              "summary": {arm: {"recovered": sum(r["outcomes"][arm]["recovered"] for r in matrix),
                 "harmed": sum(r["outcomes"][arm]["harmed"] for r in matrix),
                 "invalid": sum(not r["outcomes"][arm]["valid"] for r in matrix)} for arm in arms}}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--runs", nargs="+", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    print(json.dumps(report(args.runs, args.output)["summary"], indent=2))
