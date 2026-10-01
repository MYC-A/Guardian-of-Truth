"""Freeze existing dev decisions for incremental review without rerunning J.

No gold or relabeling. Replay only matches identical case source hashes; a
new request uses the live judge. Review cost and baseline logical cost remain
separate. This is a diagnostic reuse of observed predictions.
"""
import argparse
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
DATA = HERE / "dataset/fresh_v1"


def freeze(folder: Path):
    config = json.loads((folder / "run_config.json").read_text(encoding="utf-8"))
    status = json.loads((folder / "status.json").read_text(encoding="utf-8"))
    if status["state"] != "SUCCEEDED":
        raise ValueError("incomplete source campaign")
    source = DATA / f'{config["split"]}_input.jsonl'
    if hashlib.sha256(source.read_bytes()).hexdigest() != config["input_sha256"]:
        raise ValueError("source input mismatch")
    inputs = {r["id"]: r for r in map(json.loads,
        source.read_text(encoding="utf-8").splitlines())}
    records = [json.loads(line) for line in
        (folder / "results.jsonl").read_text(encoding="utf-8").splitlines()]
    output = HERE / "frozen_judges" / status["run_id"]
    output.mkdir(parents=True, exist_ok=True)
    for arm, variants in (("g0-direct", ("r0-refute-positive", "r1-review-all")),
                          ("g3-ge-gp-surface", ("r2-ge-refute-positive", "r3-ge-review-all"))):
        selected = [r for r in records if r["config_id"] == arm]
        if [r["case_id"] for r in selected] != config["case_ids"]:
            raise ValueError("incomplete or reordered source arm")
        out = []
        for row in selected:
            if row["status"] != "COMPLETED" or row["run_id"] != status["run_id"]:
                raise ValueError("invalid source record")
            case = inputs[row["case_id"]]
            out.append({"id": row["case_id"], "decision": row["decision"],
                        "findings": row["result"]["findings"],
                        "degraded": row["result"]["degraded"],
                        "usage": row["usage"], "source_config": arm,
                        "source_run_id": status["run_id"],
                        "source_sha256": hashlib.sha256((case["prompt"] + "\x00" +
                            case["response"]).encode("utf-8")).hexdigest()})
        blob = "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n"
                       for r in out).encode("utf-8")
        file = output / f"{arm}.jsonl"
        if file.exists() and file.read_bytes() != blob:
            raise ValueError("refusing to overwrite changed replay")
        file.write_bytes(blob)
        for variant in variants:
            path = ROOT / "service/configs" / f"{variant}.json"
            cfg = json.loads(path.read_text(encoding="utf-8"))
            cfg["stages"]["judge_replay"] = {
                "results_file": file.relative_to(ROOT).as_posix(),
                "sha256": hashlib.sha256(blob).hexdigest(),
                "source_config": arm, "source_run_id": status["run_id"]}
            path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output / "manifest.json").write_text(json.dumps({"source_config": config,
        "source_run_id": status["run_id"], "source_journal_sha256": hashlib.sha256(
            (folder / "results.jsonl").read_bytes()).hexdigest(),
        "transformation": "baseline decisions unchanged; input fingerprint attached"},
        ensure_ascii=False, indent=2), encoding="utf-8")
    return str(output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    print(freeze(parser.parse_args().directory))
