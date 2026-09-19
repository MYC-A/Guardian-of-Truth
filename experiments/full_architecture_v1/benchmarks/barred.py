"""full_architecture_v1 — external benchmark #2: BARRED (directive §26).

plurai-ai/BARRED — free-text policy predicate + dialogue / agent plan +
binary ground truth.  Configurations evaluated separately (per directive):
  message_repetition, gps_disclosure, health-advice (healthe):
     rule + transcript + label (both classes present)
  plan_verification:
     rule + violating plan output; the split is violation-focused (all rows
     are violations) -> RECALL-ONLY evaluation, documented as such

Adapter = the SAME semantic frontend and core as real46/SafePyramid (no
domain-specific logic; structural normalization only):
  rule/predicate text  -> Mistral RuleIR extraction (payload-keyed cache)
  transcript           -> utterance-observation facts
  rule refs            -> bound to utterance anchors (binder)
  core                 -> cautious Clingo (split program); binary =
                          PROVED_ERROR
Label-blind deterministic sampling BEFORE any label is read (sha256 rank).
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import sys
import time
from pathlib import Path

_FULLARCH = Path(__file__).resolve().parents[1]
_BAKEOFF = _FULLARCH.parent / "core_engine_bakeoff_v1"
_SEMANTIC = _FULLARCH.parent / "semantic_pipeline_v1"
_REPO = _FULLARCH.parents[1]
for p in (str(_BAKEOFF), str(_BAKEOFF / "backends"), str(_FULLARCH),
          str(_REPO / "src"), str(_SEMANTIC)):
    if p not in sys.path:
        sys.path.insert(0, p)

from neutral_types import (  # noqa: E402
    NeutralCoreInput, NeutralFact, NeutralInterpretation,
)
from evidence.clingo_backend import evaluate as clingo_evaluate  # noqa: E402
from benchmarks.safepyramid import (  # noqa: E402
    _bind_to_utterances, _mistral_extract, deterministic_sample)

DATA = Path("/tmp/BARRED/data")
OUT = _REPO / "outputs" / "full_architecture_v1" / "barred"
_TAG = re.compile(r"<(User|Agent)>\s*(.*?)\s*</\1>", re.DOTALL)
_PLAIN = re.compile(r"(User|Agent|Assistant|Chatbot)\s*:\s*", re.IGNORECASE)


def parse_transcript(text: str) -> list[dict]:
    turns = []
    for match in _TAG.finditer(text):
        role = "user" if match.group(1).lower() == "user" else "assistant"
        turns.append({"role": role, "text": match.group(2).strip()})
    if not turns:
        marks = list(_PLAIN.finditer(text))
        for index, mark in enumerate(marks):
            end = marks[index + 1].start() if index + 1 < len(marks) \
                else len(text)
            role = "user" if mark.group(1).lower() == "user" else "assistant"
            turns.append({"role": role,
                          "text": text[mark.end():end].strip()})
    return turns


def utterance_facts(turns: list[dict]) -> tuple[tuple[NeutralFact, ...], list]:
    from benchmarks.safepyramid import utterance_facts as sp_facts
    return sp_facts(turns)


def _sample(rows: list[dict], count: int, namespace: str) -> list[dict]:
    ranked = sorted(rows, key=lambda row: hashlib.sha256(
        (namespace + row["predicate"][:80]).encode()).hexdigest())
    return ranked[:count]


def run_dialogue_subtask(name: str, rows: list[dict], count: int) -> dict:
    rows = _sample(rows, count, f"barred-{name}")
    predictions_path = OUT / f"predictions__{name}.jsonl"
    done = set()
    predictions = []
    if predictions_path.exists():
        for line in predictions_path.read_text(encoding="utf-8").splitlines():
            record = json.loads(line)
            predictions.append(record)
            done.add(record["predicate"][:80])
    with predictions_path.open("a", encoding="utf-8") as handle:
        for row in rows:
            key = row["predicate"][:80]
            if key in done:
                continue
            try:
                turns = parse_transcript(row["transcript"])
                facts, bundle = utterance_facts(turns)
                anchors = bundle["anchors"]
                rule_id = f"{name}:{hashlib.sha256(key.encode()).hexdigest()[:10]}"
                rules = _mistral_extract(row["predicate"], rule_id)
                if not rules:
                    ci = NeutralCoreInput(
                        case_id=rule_id, facts=facts,
                        interpretations=(NeutralInterpretation(
                            "i0", (), ("frontend:no-rules-extracted",)),),
                        history_complete=True,
                        completeness_basis="benchmark transcript complete",
                        source_refs={}, notes="barred")
                    result = clingo_evaluate(ci)
                    extracted = 0
                else:
                    resolutions = {}
                    for rule in rules:
                        for key_, resolution in _bind_to_utterances(
                                rule, anchors).items():
                            resolutions.setdefault(key_, resolution)
                    from policy.compiler import compile_rule_set
                    interpretations, _stats = compile_rule_set(
                        rules, resolutions, case_id=rule_id)
                    ci = NeutralCoreInput(
                        case_id=rule_id, facts=facts,
                        interpretations=interpretations,
                        history_complete=True,
                        completeness_basis="benchmark transcript complete",
                        source_refs={}, notes="barred")
                    result = clingo_evaluate(ci)
                    extracted = len(rules)
                record = {"predicate": row["predicate"][:200],
                          "label": int(row["predicate_label"]),
                          "status": result.status,
                          "binary": 1 if result.status == "PROVED_ERROR" else 0,
                          "extracted_rules": extracted}
            except Exception as error:
                record = {"predicate": row["predicate"][:200],
                          "label": int(row["predicate_label"]),
                          "status": "ERROR", "binary": 0,
                          "error": f"{type(error).__name__}: {error}"[:200]}
            predictions.append(record)
            handle.write(json.dumps(record, ensure_ascii=False,
                                    sort_keys=True) + "\n")
            handle.flush()
            print(".", end="", flush=True)
    print()
    tp = sum(1 for p in predictions if p["binary"] == 1 and p["label"] == 1)
    fp = sum(1 for p in predictions if p["binary"] == 1 and p["label"] == 0)
    fn = sum(1 for p in predictions if p["binary"] == 0 and p["label"] == 1)
    tn = sum(1 for p in predictions if p["binary"] == 0 and p["label"] == 0)
    unres = sum(1 for p in predictions if p.get("status") == "UNRESOLVED")
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return {"subtask": name, "pairs": len(predictions), "tp": tp, "fp": fp,
            "fn": fn, "tn": tn, "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(2 * precision * recall / (precision + recall), 4)
            if precision + recall else 0.0,
            "unresolved_rate": round(unres / max(len(predictions), 1), 4),
            "extraction_failure_rate": round(
                sum(1 for p in predictions if p.get("extracted_rules") == 0)
                / max(len(predictions), 1), 4)}


def _sample_rows(rows: list[dict], count: int, namespace: str) -> list[dict]:
    ranked = sorted(rows, key=lambda row: hashlib.sha256(
        (namespace + json.dumps(row, sort_keys=True)[:120]).encode()).hexdigest())
    return ranked[:count]


def run_plan_verification(count: int) -> dict:
    """All rows are violations by construction -> recall-only evaluation."""
    with (DATA / "plan_verification_test.csv").open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    rows = _sample_rows(rows, count, "barred-plan")
    predictions_path = OUT / "predictions__plan_verification.jsonl"
    predictions = []
    done = set()
    if predictions_path.exists():
        for line in predictions_path.read_text(encoding="utf-8").splitlines():
            record = json.loads(line)
            predictions.append(record)
            done.add(record["violation_type"])
    with predictions_path.open("a", encoding="utf-8") as handle:
        for row in rows:
            if row["violation_type"] in done:
                continue
            try:
                # the plan under audit is the violating output; the rule is
                # the predicate text; treat the plan as a single assistant
                # utterance observation
                turns = [{"role": "assistant",
                          "text": row["violating_task_output"]}]
                facts, bundle = utterance_facts(turns)
                anchors = bundle["anchors"]
                rule_id = "barred-plan:" + hashlib.sha256(
                    row["violation_type"].encode()).hexdigest()[:10]
                rules = _mistral_extract(row["rule"], rule_id)
                if not rules:
                    ci = NeutralCoreInput(
                        case_id=rule_id, facts=facts,
                        interpretations=(NeutralInterpretation(
                            "i0", (), ("frontend:no-rules-extracted",)),),
                        history_complete=True,
                        completeness_basis="plan artifact complete",
                        source_refs={}, notes="barred-plan")
                    result = clingo_evaluate(ci)
                else:
                    resolutions = {}
                    for rule in rules:
                        for key_, resolution in _bind_to_utterances(
                                rule, anchors).items():
                            resolutions.setdefault(key_, resolution)
                    from policy.compiler import compile_rule_set
                    interpretations, _stats = compile_rule_set(
                        rules, resolutions, case_id=rule_id)
                    ci = NeutralCoreInput(
                        case_id=rule_id, facts=facts,
                        interpretations=interpretations,
                        history_complete=True,
                        completeness_basis="plan artifact complete",
                        source_refs={}, notes="barred-plan")
                    result = clingo_evaluate(ci)
                record = {"violation_type": row["violation_type"],
                          "label": 1, "status": result.status,
                          "binary": 1 if result.status == "PROVED_ERROR" else 0,
                          "extracted_rules": len(rules)}
            except Exception as error:
                record = {"violation_type": row["violation_type"], "label": 1,
                          "status": "ERROR", "binary": 0,
                          "error": f"{type(error).__name__}: {error}"[:200]}
            predictions.append(record)
            handle.write(json.dumps(record, ensure_ascii=False,
                                    sort_keys=True) + "\n")
            handle.flush()
            print(".", end="", flush=True)
    print()
    detected = sum(1 for p in predictions if p["binary"] == 1)
    unres = sum(1 for p in predictions if p.get("status") == "UNRESOLVED")
    return {"subtask": "plan_verification", "pairs": len(predictions),
            "detected": detected,
            "recall": round(detected / max(len(predictions), 1), 4),
            "unresolved_rate": round(unres / max(len(predictions), 1), 4),
            "note": "violation-focused split: all rows are violations; "
                    "RECALL-ONLY (no negatives in the test csv)"}


def main(count: int = 40) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    results = {}
    started = time.time()
    for name, filename in (("message_repetition",
                            "message_repetition_test.csv"),
                           ("gps_disclosure", "gps_disclosure_test.csv"),
                           ("health_advice", "healthe_test.csv")):
        with (DATA / filename).open(encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        results[name] = run_dialogue_subtask(name, rows, count)
        print(name, json.dumps(results[name]), flush=True)
    results["plan_verification"] = run_plan_verification(min(count, 58))
    print("plan_verification", json.dumps(results["plan_verification"]))
    results["_meta"] = {
        "sample_per_subtask": count,
        "sampling": "label-blind deterministic sha256 rank",
        "frontend": "same Mistral RuleIR frontend (payload-keyed cache)",
        "wall_time_s": round(time.time() - started, 1)}
    (OUT / "metrics.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(results, indent=1))


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=40)
    args = parser.parse_args()
    main(args.count)
