"""Freeze completed Φ output as portable, source-bound advisory configs.

The original journal stays unchanged. Source fingerprints are derived from
the hashed input manifest for legacy records that predate this field. No gold
is read; no semantic repair is applied to the translations.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
DATA = HERE / "dataset/fresh_v1"


def freeze(folder: Path, *, config_suffix=""):
    if config_suffix and not config_suffix.replace("-", "").isalnum():
        raise ValueError("unsafe config suffix")
    config = json.loads((folder / "run_config.json").read_text(encoding="utf-8"))
    status = json.loads((folder / "status.json").read_text(encoding="utf-8"))
    if status["state"] != "SUCCEEDED":
        raise ValueError("formal journal incomplete")
    source = DATA / f'{config["split"]}_input.jsonl'
    if hashlib.sha256(source.read_bytes()).hexdigest() != config["input_sha256"]:
        raise ValueError("frozen input mismatch")
    cases = {row["id"]: row for row in map(json.loads,
        source.read_text(encoding="utf-8").splitlines())}
    records = [json.loads(line) for line in
        (folder / "results.jsonl").read_text(encoding="utf-8").splitlines()]
    if [row["id"] for row in records] != config["case_ids"]:
        raise ValueError("journal ID mismatch")
    if set(config["case_ids"]) != set(cases):
        raise ValueError("service advisory freeze requires a complete split")
    for row in records:
        if row["run_id"] != status["run_id"]:
            raise ValueError("journal run ID mismatch")
        case = cases[row["id"]]
        digest = hashlib.sha256((case["prompt"] + "\x00" + case["response"])
                                .encode("utf-8")).hexdigest()
        if "source_sha256" in row and row["source_sha256"] != digest:
            raise ValueError("journal source mismatch")
        row["source_sha256"] = digest
    output = HERE / "frozen_phi" / status["run_id"]
    output.mkdir(parents=True, exist_ok=True)
    journal = output / "results.jsonl"
    blob = "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
                   for row in records).encode("utf-8")
    if journal.exists() and journal.read_bytes() != blob:
        raise ValueError("refusing to overwrite different frozen journal")
    journal.write_bytes(blob)
    (output / "status.json").write_text(json.dumps(status, sort_keys=True), encoding="utf-8")
    (output / "manifest.json").write_text(json.dumps({
        "original_config": config, "original_journal_sha256": hashlib.sha256(
            (folder / "results.jsonl").read_bytes()).hexdigest(),
        "advisory_journal_sha256": hashlib.sha256(blob).hexdigest(),
        "transformation": "source fingerprint only; translations unchanged",
        "n": len(records)}, indent=2), encoding="utf-8")
    ids = []
    for name, base in (("m01-phi", "g0-direct"), ("m11-ge-gp-phi", "g3-ge-gp-surface")):
        name += config_suffix
        conf = json.loads((ROOT / "service/configs" / f"{base}.json").read_text(encoding="utf-8"))
        conf["config_id"] = name
        conf["description"] = "Frozen bounded model-proposed Phi advisory; verify against original."
        conf["stages"]["formal_advisory"] = {
            "results_file": journal.relative_to(ROOT).as_posix(),
            "sha256": hashlib.sha256(blob).hexdigest(), "run_id": status["run_id"]}
        (ROOT / "service/configs" / f"{name}.json").write_text(json.dumps(conf,
            ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        ids.append(name)
    return {"configs": ids, "advisory_file": str(journal), "n": len(records)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    parser.add_argument("--config-suffix", default="")
    args = parser.parse_args()
    print(json.dumps(freeze(args.directory, config_suffix=args.config_suffix), ensure_ascii=False))
