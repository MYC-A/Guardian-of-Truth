"""Integrated v1 phase0: Read original46 and saved predictions; rescore with a declaration guard.

No model/raw re-admission or source edits. --output only creates new files.
"""
from __future__ import annotations
import argparse
from collections import defaultdict
import hashlib
import json
from numbers import Integral
from pathlib import Path
import socket
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

def blocked(*args, **kwargs):
    raise RuntimeError("OFFLINE_REPLAY_NETWORK_FORBIDDEN")

def metrics(gold, predictions):
    tp = sum(gold[i] == 1 and predictions[i] == 1 for i in gold)
    fp = sum(gold[i] == 0 and predictions[i] == 1 for i in gold)
    fn = sum(gold[i] == 1 and predictions[i] == 0 for i in gold)
    tn = sum(gold[i] == 0 and predictions[i] == 0 for i in gold)
    return dict(n=len(gold), tp=tp, fp=fp, fn=fn, tn=tn,
                f1=2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else 0)

def is_binary_integer(value):
    return isinstance(value, Integral) and not isinstance(value, bool) and value in (0, 1)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.output is not None and args.output.exists():
        parser.error("Existing report cannot be overwritten")
    socket.create_connection = blocked
    socket.socket.connect = blocked
    urllib.request.urlopen = blocked
    import pandas as pd
    from experiments.whole_move_v1.mechanical import check as old_check
    from guardian_truth.integrated.declarations import check
    from guardian_truth.integrated.relations import compute
    from guardian_truth.source_search.store import SourceStore
    data = pd.read_parquet(ROOT / "valid.parquet")
    rows = data.to_dict("records")
    if len(rows) != 46 or data.id.nunique() != 46:
        raise ValueError("INVALID_ORIGINAL46_INVENTORY")
    if any(not is_binary_integer(r["label"]) for r in rows):
        raise ValueError("INVALID_BINARY_GOLD_TYPE")
    flags = {r["id"]: int(check({k: r[k] for k in ("prompt", "response")})[
        "mechanically_established_error"]) for r in rows}
    old_flags = {r["id"]: int(old_check({k: r[k] for k in ("prompt", "response")})[
        "mechanically_established_error"]) for r in rows}
    relation_decisive = {r["id"]: len(compute(SourceStore({k: r[k] for k in ("prompt", "response")}))["decisive"]) for r in rows}
    gold = {r["id"]: int(r["label"]) for r in rows}
    if set(gold.values()) != {0, 1}:
        raise ValueError("INVALID_BINARY_GOLD")
    cache = ROOT / "outputs/evidence_packer_v2/llm/decisions.jsonl"
    groups = defaultdict(list)
    for line in cache.read_text(encoding="utf-8").splitlines():
        if line.strip():
            record = json.loads(line)
            groups[record["run"], record["arm"]].append(record)
    expected = {(run, arm) for run in (1, 2, 3)
                for arm in ("FULL", "U2_20k", "U2_48k", "FC2_48k")}
    if set(groups) != expected:
        raise ValueError("INVALID_CACHE_GROUP_INVENTORY")
    results = []
    for (run, arm), records in sorted(groups.items()):
        if len(records) != 46 or {r["id"] for r in records} != set(gold):
            raise ValueError("DUPLICATE_MISSING_OR_FOREIGN_CACHE_ID")
        for record in records:
            status = record.get("admission")
            if not isinstance(status, str) or not status:
                raise ValueError("INVALID_CACHED_ADMISSION_STATUS")
            if status == "ADMITTED" and record.get("decision") not in ("ERROR", "NO_ERROR", "UNKNOWN"):
                raise ValueError("INVALID_ADMITTED_CACHE_DECISION")
        before = {r["id"]: int(r["admission"] == "ADMITTED" and r["decision"] == "ERROR")
                  for r in records}
        after = {i: before[i] | flags[i] for i in gold}
        after_old = {i: before[i] | old_flags[i] for i in gold}
        results.append(dict(run=run, arm=arm, unique_original_ids=46,
            before=metrics(gold, before), mechanical_overlay=metrics(gold, after),
            old_guard_overlay=metrics(gold, after_old),
            changed_cases=[dict(id=i, gold=gold[i], before=before[i], after=after[i])
                           for i in gold if before[i] != after[i]],
            admitted_unknown=sum(r["admission"] == "ADMITTED" and r["decision"] == "UNKNOWN"
                                 for r in records),
            technical=sum(r["admission"] != "ADMITTED" for r in records)))
    archive = pd.read_csv(ROOT / "outputs/searh_23/baseline_frozen/control_repro_percase.csv")
    if len(archive) != 46 or archive.id.nunique() != 46 or set(archive.id) != set(gold):
        raise ValueError("INVALID_ARCHIVED_BASELINE_INVENTORY")
    if any(not is_binary_integer(r.gold) or r.gold != gold[r.id] for r in archive.itertuples()):
        raise ValueError("ARCHIVED_GOLD_MISMATCH")
    if any(not is_binary_integer(v) for col in ("baseline", "granite_repro") for v in archive[col]):
        raise ValueError("INVALID_ARCHIVED_PREDICTION")
    archived = {r.id: max(int(r.baseline), int(r.granite_repro)) for r in archive.itertuples()}
    report = dict(new_model_http=0, scope="known original46 development, saved-prediction replay",
        cache_records=552, groups=results, archived_guardian_or_granite=metrics(gold, archived),
        mechanical_only=metrics(gold, flags), old_mechanical_only=metrics(gold, old_flags),
        guard_flag_changes=[dict(id=i, old=old_flags[i], new=flags[i]) for i in gold if old_flags[i] != flags[i]],
        relation_shadow=dict(rows_with_decisive_facts=sum(v > 0 for v in relation_decisive.values()),
                             positives=sum(v > 0 and gold[i] for i, v in relation_decisive.items()),
                             note="shadow count only; relation facts are never a standalone ERROR"),
        guard_profile="guardian_truth.integrated.declarations (post-repair parser) vs experiments.whole_move_v1.mechanical at the same checkout", binary_projection="ADMITTED ERROR ->1; UNKNOWN/rejection ->0",
        limitation="Derived predictions, not raw/wire re-admission; no new semantic model evaluation",
        valid_sha256=hashlib.sha256((ROOT / "valid.parquet").read_bytes()).hexdigest(),
        prediction_cache_sha256=hashlib.sha256(cache.read_bytes()).hexdigest())
    serialized = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output is None:
        print(serialized, end="")
    else:
        with args.output.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(serialized)
        print(json.dumps(dict(original_cases=46, cache_groups=12, cache_records=552,
            new_model_http=0, report=str(args.output))))

if __name__ == "__main__":
    main()
