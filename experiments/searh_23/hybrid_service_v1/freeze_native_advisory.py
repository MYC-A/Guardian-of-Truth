"""Freeze a completed native pass into source-bound helper configs; no gold."""
import argparse
import hashlib
import json
from pathlib import Path

from candidate_bank import BANK

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def freeze(folder: Path):
    config = json.loads((folder / "run_config.json").read_text(encoding="utf-8"))
    status = json.loads((folder / "status.json").read_text(encoding="utf-8"))
    if status["state"] != "SUCCEEDED":
        raise ValueError("native run incomplete")
    bank_path = BANK / f'{config["split"]}.jsonl'
    if hashlib.sha256(bank_path.read_bytes()).hexdigest() != config["bank_sha256"]:
        raise ValueError("native bank mismatch")
    bank = {r["id"]: r for r in map(json.loads,
        bank_path.read_text(encoding="utf-8").splitlines())}
    scores = [json.loads(line) for line in
        (folder / "scores.jsonl").read_text(encoding="utf-8").splitlines()]
    if [r["id"] for r in scores] != config["case_ids"]:
        raise ValueError("native scores incomplete or reordered")
    for record in scores:
        if record["run_id"] != status["run_id"]:
            raise ValueError("native run identity mismatch")
        row = bank[record["id"]]
        record.update({"model": config["model"], "source_sha256": row["source_sha256"],
                       "claim": row["claim"]})
    folder_out = HERE / "frozen_native" / status["run_id"]
    folder_out.mkdir(parents=True, exist_ok=True)
    out = folder_out / "scores.jsonl"
    blob = "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n"
                   for r in scores).encode("utf-8")
    if out.exists() and out.read_bytes() != blob:
        raise ValueError("refusing to overwrite changed native replay")
    out.write_bytes(blob)
    (folder_out / "manifest.json").write_text(json.dumps(config,
        ensure_ascii=False, indent=2), encoding="utf-8")
    for name, base in (("h3-native-review", "r0-refute-positive"),
                       ("h3-ge-native-review", "r2-ge-refute-positive")):
        path = ROOT / "service/configs" / f"{base}.json"
        cfg = json.loads(path.read_text(encoding="utf-8"))
        cfg["config_id"] = name
        cfg["description"] = "Direct J, native advisory to independent B; no support-score-to-label override."
        cfg["stages"]["native_advisory"] = {"model": config["model"],
            "position": "independent_reviewer_only", "max_source_words": 500,
            "replay": {"results_file": out.relative_to(ROOT).as_posix(),
                       "sha256": hashlib.sha256(blob).hexdigest()}}
        (ROOT / "service/configs" / f"{name}.json").write_text(json.dumps(cfg,
            ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return str(out)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    print(freeze(parser.parse_args().directory))
