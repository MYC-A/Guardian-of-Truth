"""Read-only Git-blob audit of the frozen Qwen binding experiment.

No inference, network, checkout, or historical output writes. The optional receipt
must be a new file. All-label binary projections are explicitly separated from
the original scorer's usable subset and a stricter admitted-review subset.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]
csv.field_size_limit(10_000_000)

QPATH = ("outputs/guardian_local_a100/llamacpp/"
         "qwen3.8-27b@71bc7b627595:Q8_0:llamacpp-b11459/runs")
GOLD = {
    "ext_tau2": "outputs/verification_v4/external/tau2v2/GOLD_eval_only.json",
    "hold_tau2h": "outputs/universal_repair/holdout/tau2h/GOLD_frozen.json",
    "hold_holdout2": "outputs/guardian_v6/holdout2/GOLD_frozen.json",
    **{s: f"outputs/verification_v2/{k}/long/GOLD_eval_only.json" for s, k in
       (("lb_long", "lockbox"), ("lb2_long", "lockbox2"), ("lb3_long", "lockbox3"))},
}
POOLS = {"dev": ["valid46", "ext_tau2", "hold_tau2h", "hold_holdout2"],
         "test": ["lb2_long", "lb3_long", "lb_long"]}


def metric(gold, prediction):
    c = Counter()
    for key, label in gold.items():
        value = prediction.get(key)
        if value not in (0, 1):
            c["undecided"] += 1
        else:
            c[("tp" if value else "fn") if label else ("fp" if value else "tn")] += 1
    out = {k: c[k] for k in ("tp", "fp", "fn", "tn", "undecided")}
    den = 2 * c["tp"] + c["fp"] + c["fn"]
    out.update(expected_labelled=len(gold), decided=sum(c[k] for k in ("tp", "fp", "fn", "tn")),
               f1_on_decided=(round(2 * c["tp"] / den, 6) if den else None))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ref", default="51160fcd0b7b9354f8a63615430aeae0c95b591a")
    ap.add_argument("--out", type=Path, help="New receipt JSON, never overwritten")
    args = ap.parse_args()
    commit = subprocess.check_output(["git", "rev-parse", args.ref], cwd=ROOT).decode().strip()
    hashes = {}

    def blob(path):
        data = subprocess.check_output(["git", "show", f"{commit}:{path}"], cwd=ROOT)
        hashes[path] = hashlib.sha256(data).hexdigest()
        return data

    def js(path):
        return json.loads(blob(path))

    # The packet builder is local, but every imported project source is checked
    # against the frozen revision below. This prevents silently using a repair.
    from guardian_truth.repair.v5 import packet_for
    from experiments.guardian_binding.idcheck import check as repaired_discovery
    from experiments.guardian_binding.eval_idcheck import project as repaired_project
    namespace = {"__file__": str(ROOT / "experiments/guardian_local_a100/score_local.py"),
                 "__name__": "frozen_offline_scorer"}
    exec(compile(blob("experiments/guardian_local_a100/score_local.py"), "frozen_score_local", "exec"), namespace)
    checker = {}
    exec(compile(blob("experiments/guardian_binding/idcheck.py"), "frozen_idcheck", "exec"), checker)
    import pandas as pd
    valid = {r.id: int(r.label) for r in pd.read_parquet(io.BytesIO(blob("valid.parquet"))).itertuples()}
    receipt = {"ref": commit, "network_calls": 0, "sets": {}, "pools": {},
               "definitions": {
                   "all_label_binary_projection": "Saved binary field, including rejected/invalid reviews; missing stays undecided.",
                   "original_scorer_usable": "Frozen classify_row returns verdict or fallback; its REJECTED-prefix blind spot is preserved.",
                   "primary_review_admitted": "Original usable row AND all primary review steps have admission ADMITTED.",
                   "duplicates": "Last row as frozen combiner; conflicting binary values abort this audit.",
                   "test_scope": "Observed rows only; expected missing IDs are explicitly undecided. This is not a complete test run."}}
    all_rows = {}
    repair_comparison = dict(inputs_checked=0, discovery_mismatches=[], safe_projection_changes=[],
                             hypothesis_authority_failures=[])
    for pool, sets in POOLS.items():
        for name in sets:
            gold = valid if name == "valid46" else {k: v["label"] for k, v in js(GOLD[name]).items() if v.get("label") in (0, 1)}
            inputs = list(csv.DictReader(io.StringIO(blob(f"outputs/guardian_complementarity/inputs/{name}.csv").decode("utf-8"))))
            expected = [r["id"] for r in inputs]
            if len(expected) != len(set(expected)):
                raise AssertionError(f"Duplicate input IDs: {name}")
            if set(gold) - set(expected):
                raise AssertionError(f"Labelled IDs absent from expected inputs: {name}/{sorted(set(gold) - set(expected))}")
            raw = [json.loads(line) for line in blob(f"{QPATH}/{name}/B2_rep1.jsonl").decode("utf-8").splitlines() if line.strip()]
            groups = defaultdict(list)
            for row in raw:
                groups[row["id"]].append(row)
            conflicts = [i for i, rr in groups.items() if len({r.get("binary") for r in rr}) > 1]
            if conflicts:
                raise AssertionError(f"Conflicting duplicate binary values, cannot select a winner: {name}/{conflicts}")
            selected = {i: rr[-1] for i, rr in groups.items()}
            classes, admissions = Counter(), Counter()
            finding_rows = []
            records = {}
            for row in inputs:
                key = row["id"]
                rec = selected.get(key)
                cls = namespace["classify_row"](rec, "B2", "binary")
                classes[cls] += 1
                steps = (((rec or {}).get("rec") or {}).get("A") or {}).get("steps") or []
                primary = [s for s in steps if s.get("tag") == "review"]
                for step in primary:
                    admissions[str(step.get("admission"))] += 1
                admitted = bool(primary) and all(s.get("admission") == "ADMITTED" for s in primary)
                packet = packet_for(row, 400000) or {}
                findings = checker["check"](packet)
                repaired = repaired_discovery(packet)
                stripped = [{k: v for k, v in f.items() if k not in
                             ('status', 'verified', 'binding_status', 'applicability_status', 'final_authority')}
                            for f in repaired]
                canonical = lambda ff: sorted(json.dumps(f, sort_keys=True) for f in ff)
                repair_comparison['inputs_checked'] += 1
                if canonical(findings) != canonical(stripped):
                    repair_comparison['discovery_mismatches'].append(f'{name}/{key}')
                if any(f.get('verified') is not False or f.get('status') != 'HYPOTHESIS' for f in repaired):
                    repair_comparison['hypothesis_authority_failures'].append(f'{name}/{key}')
                base = (rec or {}).get('binary') if cls not in ('no_solution', 'missing') else None
                if repaired_project(base, repaired) != base:
                    repair_comparison['safe_projection_changes'].append(f'{name}/{key}')
                records[key] = dict(label=gold.get(key), binary=(rec or {}).get("binary"),
                                    frozen_class=cls, primary_review_admitted=admitted, findings=findings)
                if findings:
                    finding_rows.append(dict(id=key, **records[key]))
            all_rows[name] = records
            pred = {k: r["binary"] for k, r in records.items()}
            receipt["sets"][name] = dict(
                expected_input_count=len(expected), labelled_count=len(gold), unlabelled_ids=sorted(set(expected) - set(gold)),
                raw_lines=len(raw), unique_saved_ids=len(selected),
                missing_ids=sorted(set(expected) - set(selected)), unexpected_ids=sorted(set(selected) - set(expected)),
                duplicate_ids={i: len(rr) for i, rr in groups.items() if len(rr) > 1},
                frozen_classes=dict(classes), primary_admission_counts=dict(admissions),
                all_label_binary_projection=metric(gold, pred), finding_rows=finding_rows)
    # Validate all imported repository modules used to build/classify packets.
    dependencies = {}
    for name, module in list(sys.modules.items()):
        if not name.startswith(("guardian_truth.", "experiments.research_records")):
            continue
        file = getattr(module, "__file__", None)
        if not file or not file.endswith(".py"):
            continue
        path = Path(file).resolve()
        try:
            rel = path.relative_to(ROOT).as_posix()
        except ValueError:
            raise AssertionError(f"Unexpected project module source: {path}")
        physical = path.read_text(encoding="utf-8").replace("\r\n", "\n")
        frozen = blob(rel).decode("utf-8").replace("\r\n", "\n")
        if physical != frozen:
            raise AssertionError(f"Packet/scorer dependency changed since frozen ref: {rel}")
        dependencies[rel] = hashes[rel]
    receipt["verified_packet_dependencies"] = dependencies
    if any(repair_comparison[k] for k in ('discovery_mismatches', 'safe_projection_changes', 'hypothesis_authority_failures')):
        raise AssertionError(f'Repair comparison failed: {repair_comparison}')
    receipt['repair_shadow_comparison'] = repair_comparison
    receipt['repair_sources_sha256'] = {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
        for path in ('experiments/guardian_binding/idcheck.py', 'experiments/guardian_binding/eval_idcheck.py')}
    for pool, sets in POOLS.items():
        records = {f"{s}/{i}": r for s in sets for i, r in all_rows[s].items() if r["label"] in (0, 1)}
        gold = {k: r["label"] for k, r in records.items()}
        variants = {}
        for scope in ("all_label_binary_projection", "original_scorer_usable", "primary_review_admitted"):
            if scope == "all_label_binary_projection":
                subset = records
            else:
                subset = {k: r for k, r in records.items() if r["frozen_class"] in ("verdict", "fallback")
                          and (scope != "primary_review_admitted" or r["primary_review_admitted"])}
            sg = {k: gold[k] for k in subset}
            base = {k: r["binary"] for k, r in subset.items()}
            result = {"included_ids": sorted(subset), "excluded_ids": sorted(set(records) - set(subset)),
                      "QB2": metric(sg, base)}
            for rule in ("A", "B", "C", "ABC"):
                combined = {k: (None if r["binary"] not in (0, 1) else int(r["binary"] or any(f["rule"] in rule for f in r["findings"]))) for k, r in subset.items()}
                result["QB2|" + rule] = metric(sg, combined)
                result["changes_" + rule] = [dict(id=k, label=sg[k], before=base[k], after=combined[k], findings=subset[k]["findings"])
                                             for k in subset if combined[k] != base[k]]
            variants[scope] = result
        receipt["pools"][pool] = variants
    receipt["git_blob_sha256"] = hashes
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with args.out.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(receipt, stream, ensure_ascii=False, indent=2)
    for pool, scopes in receipt["pools"].items():
        for scope, result in scopes.items():
            print(pool, scope, "QB2", result["QB2"], "QB2|ABC", result["QB2|ABC"])
    return receipt


if __name__ == "__main__":
    main()
