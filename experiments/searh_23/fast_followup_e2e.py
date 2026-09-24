#!/usr/bin/env python3
"""Run the frozen 300dc2e E2E implementation on the follow-up's same CSV.

Only id/prompt/response enter inference. A pinned source archive prevents the
current branch's E2E code from silently replacing the measured historical arm.
Mistral is an API backend; no model is loaded locally by this stage.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

E2E_COMMIT = "300dc2edd20e631928b9997a8f581ab8659a75b2"
ARCHIVE_PATHS = ("src/guardian_truth", "scripts")


def frozen(run_dir: Path) -> tuple[dict, list[dict]]:
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    source = Path(manifest["cases"])
    if hashlib.sha256(source.read_bytes()).hexdigest() != manifest["cases_sha256"]:
        raise RuntimeError("frozen cases changed")
    csv.field_size_limit(2 ** 30)
    with source.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if set(reader.fieldnames or ()) != {"id", "prompt", "response"}:
            raise RuntimeError("inference CSV is not label free")
        cases = list(reader)
    if [row["id"] for row in cases] != manifest["ids"]:
        raise RuntimeError("frozen case order changed")
    return manifest, cases


def read_done(path: Path) -> set[str]:
    if not path.exists():
        return set()
    return {row["id"] for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and (row := json.loads(line)).get("status") == "OK"}


def append_jsonl(path: Path, row: dict) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def frozen_source(run_dir: Path) -> Path:
    root = run_dir / "e2e_source_300dc2e_v2"
    sentinel = root / "source.json"
    if sentinel.exists():
        data = json.loads(sentinel.read_text(encoding="utf-8"))
        if data.get("commit") != E2E_COMMIT:
            raise RuntimeError("E2E source pin mismatch")
        names = data.get("file_names")
        if not isinstance(names, list) or len(names) != data.get("file_count"):
            raise RuntimeError("frozen E2E source manifest incomplete")
        digest = hashlib.sha256()
        for name in names:
            path = root / name
            if not path.is_file():
                raise RuntimeError(f"frozen E2E source missing: {name}")
            digest.update(name.encode() + b"\0" + path.read_bytes())
        if digest.hexdigest() != data.get("source_sha256"):
            raise RuntimeError("frozen E2E source changed")
        return root
    root.mkdir(parents=True, exist_ok=True)
    # `git archive` on Windows rejects unrelated historical paths containing
    # colons, even with pathspecs. Read only the pinned source files instead.
    names = subprocess.check_output(
        ["git", "ls-tree", "-r", "--name-only", "-z", E2E_COMMIT,
         "--", *ARCHIVE_PATHS], cwd=REPO).decode("utf-8").split("\0")
    digest = hashlib.sha256()
    count = 0
    file_names = []
    for name in filter(None, names):
        if not (name.startswith("src/guardian_truth/") or
                name.startswith("scripts/")):
            raise RuntimeError(f"unexpected source path: {name}")
        content = subprocess.check_output(
            ["git", "show", f"{E2E_COMMIT}:{name}"], cwd=REPO)
        dest = root / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(content)
        digest.update(name.encode() + b"\0" + content)
        count += 1
        file_names.append(name)
    sentinel.write_text(json.dumps({"commit": E2E_COMMIT,
                                    "file_count": count,
                                    "file_names": file_names,
                                    "source_sha256": digest.hexdigest()}),
                        encoding="utf-8")
    return root


def run(run_dir: Path, mode: str) -> None:
    manifest, cases = frozen(run_dir)
    if not os.environ.get("MISTRAL_API_KEY"):
        raise RuntimeError("MISTRAL_API_KEY missing for frozen E2E backend")
    root = frozen_source(run_dir)
    for directory in (root / "scripts", root / "src", root):
        sys.path.insert(0, str(directory))
    from real_valid_adapter import competition_case, parse_tool_catalog
    from real_valid_common import build_backend
    from real_valid_run import guardian_for_mode
    import guardian_truth
    if not Path(guardian_truth.__file__).resolve().is_relative_to(root.resolve()):
        raise RuntimeError("E2E loaded a non-frozen guardian_truth package")

    path = run_dir / f"e2e_{mode}.jsonl"
    done = read_done(path)
    backend = build_backend(run_dir / f"e2e_{mode}_mistral_cache.json",
                            provider="mistral")
    for case in cases:
        cid = case["id"]
        if cid in done:
            continue
        started = time.monotonic()
        row = {"id": cid, "status": "ERROR", "mode": mode,
               "source_commit": E2E_COMMIT,
               "input_sha256": hashlib.sha256(
                   (case["prompt"] + "\0" + case["response"]).encode()).hexdigest(),
               "cases_sha256": manifest["cases_sha256"]}
        try:
            e2e_case = competition_case(case)
            _, schemas = parse_tool_catalog(case["prompt"])
            guardian = guardian_for_mode(
                backend, mode, schemas={item["name"]: item for item in schemas})
            analysis = guardian.analyze_e2e_v1(e2e_case)
            binary = analysis.product_decision.binary_label
            check = analysis.result.certificate_check
            row.update({"status": "OK" if binary in (0, 1) else "UNRESOLVED",
                        "label": binary, "core_status": analysis.result.status.value,
                        "certificate_valid": bool(check and check.valid) if check else None,
                        "used_fallback": analysis.product_decision.used_fallback,
                        "policy_reading_count": len(analysis.policy_readings),
                        "goal_contract_count": len(analysis.goal_contracts),
                        "frontend_failures": [
                            {"component": component, "kind": kind}
                            for component, kind, _ in analysis.frontend_statuses],
                        "diagnostics": {
                            "primary": (analysis.result.diagnostics.primary_reason.value
                                        if analysis.result.diagnostics.primary_reason else None),
                            "missing_evidence": list(
                                analysis.result.diagnostics.missing_evidence[:12])}})
        except Exception as error:  # A failed case never becomes a negative prediction.
            row["error"] = f"{type(error).__name__}: {str(error)[:300]}"
        row["elapsed_s"] = round(time.monotonic() - started, 3)
        append_jsonl(path, row)
        print(f"[e2e {mode}] {cid}: {row['status']} {row.get('label')}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--mode", choices=("R1", "R2", "both"), default="both")
    args = parser.parse_args()
    for mode in (("R1", "R2") if args.mode == "both" else (args.mode,)):
        run(args.run_dir, mode)


if __name__ == "__main__":
    main()
