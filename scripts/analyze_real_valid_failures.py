"""Post-seal failure decomposition for the public development set.

This script is deliberately outside inference.  It refuses to read gold until
all requested prediction files match their recorded seals, then joins the
sealed audit with labels/explanations and emits diagnostic artifacts only.
Nothing produced here is imported by the Guardian decision path.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import json
import math
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]


def _verify_seals(output_dir: Path, suffix: str) -> dict:
    seals = json.loads((output_dir / f"prediction_seals{suffix}.json").read_text(encoding="utf-8"))
    for mode in ("R0", "R1", "R2"):
        seal = seals.get(mode)
        if not isinstance(seal, dict):
            raise ValueError(f"missing {mode} prediction seal")
        path = ROOT / seal["path"]
        if hashlib.sha256(path.read_bytes()).hexdigest() != seal["sha256"]:
            raise ValueError(f"{mode} prediction seal mismatch")
    return seals


def _failure_family(explanation: str) -> str:
    """Coarse diagnostic taxonomy from gold explanations, never inference."""
    text = explanation.lower()
    if not text:
        return "NO_GOLD_ERROR"
    if any(token in text for token in (
            "нет в списке [available tools]", "нет в его списке [available tools]",
            "нет в его [available tools]",
            "инструмента `get_bank_account_transactions", "которых нет в его блоке [available tools]")):
        return "UNAVAILABLE_TOOL_OR_WRONG_EXECUTOR"
    if ("схем" in text and any(token in text for token in
                               ("обязательн", "поля", "аргумент", "сигнатур"))):
        return "SCHEMA_ARGUMENT_MISMATCH"
    if any(token in text for token in ("строка-заглушка", "значение zip не выводимо",
                                       "часть email за почтовый индекс")):
        return "UNSUPPORTED_ARGUMENT_PROVENANCE"
    if "действий, которых в ходе нет" in text or "сами действия, и их «результаты» вымышлены" in text:
        return "FABRICATED_ACTION_OR_RESULT"
    if "подтвержден" in text and ("перед" in text or "явное" in text):
        return "CONFIRMATION_PREREQUISITE"
    if "верификац" in text and ("2" in text or "дв" in text):
        return "IDENTITY_VERIFICATION"
    if any(token in text for token in ("преждевременн", "ложный отказ", "перевод на человека")):
        return "PREMATURE_ESCALATION"
    if any(token in text for token in ("повтор ранее провалившегося вызова", "зацикливание")):
        return "FAILED_CALL_REPEAT"
    if "предстоящ" in text and any(token in text for token in ("дат", "текущ")):
        return "STALE_OR_TEMPORAL_STATE"
    if "дата уже есть в истории" in text or "данные уже доступны" in text:
        return "AVAILABLE_EVIDENCE_IGNORED"
    if "nonfree_baggages" in text or "gift_card" in text:
        return "ARGUMENT_BINDING_OR_PROVENANCE"
    if any(token in text for token in ("одного и того же заказа", "идентичных old/new",
                                       "contract_end_date", "обязательные проверки")):
        return "POLICY_PRECONDITION_OR_SEQUENCE"
    return "POLICY_OR_GOAL_REASONING"


ROOT_CAUSE = {
    "SCHEMA_ARGUMENT_MISMATCH": "TOOL_SPEC_PARSE",
    "UNAVAILABLE_TOOL_OR_WRONG_EXECUTOR": "TOOL_BINDING",
    "UNSUPPORTED_ARGUMENT_PROVENANCE": "ARGUMENT_PROVENANCE",
    "FABRICATED_ACTION_OR_RESULT": "CLAIM_PARSE",
    "CONFIRMATION_PREREQUISITE": "TEMPORAL_REASONING",
    "IDENTITY_VERIFICATION": "ARGUMENT_BINDING",
    "PREMATURE_ESCALATION": "POLICY_PARSE",
    "FAILED_CALL_REPEAT": "TEMPORAL_REASONING",
    "STALE_OR_TEMPORAL_STATE": "TEMPORAL_REASONING",
    "AVAILABLE_EVIDENCE_IGNORED": "STATE_EVIDENCE",
    "ARGUMENT_BINDING_OR_PROVENANCE": "ARGUMENT_PROVENANCE",
    "POLICY_PRECONDITION_OR_SEQUENCE": "POLICY_PARSE",
    "POLICY_OR_GOAL_REASONING": "POLICY_PARSE",
}


def _negative_root_cause(row: dict) -> str:
    failures = row["R0"]["frontend_failures"]
    if any(item["component"].startswith("policy") for item in failures):
        return "POLICY_PARSE"
    if any(item["component"].startswith("goal") for item in failures):
        return "GOAL_PARSE"
    required = set(row["R0"]["required_premises"])
    if "MATERIAL_RESPONSE_COVERED" in required:
        return "CLAIM_PARSE"
    if "SEMANTIC_CANDIDATES_COVERED" in required:
        return "POLICY_PARSE"
    return "CERTIFICATE"


def _dependency(root_cause: str, family: str, status: str) -> str:
    if status == "PROVED_ERROR":
        return "Works without T1"
    if root_cause in {"STATE_EVIDENCE", "EFFECT_REASONING", "MISSING_T1",
                      "ORACLE_T1_DEPENDENCY"}:
        # The public examples still expose the relevant values in prompt
        # history; no case in this baseline proves an oracle-only dependency.
        return "Needs prompt-derived semantics"
    if family == "NO_GOLD_ERROR" and root_cause == "CERTIFICATE":
        return "Blocked by state/effect evidence"
    if root_cause == "POLICY_PARSE":
        return "Blocked by Policy parsing"
    if root_cause in {"GOAL_PARSE", "TOOL_BINDING", "ARGUMENT_BINDING",
                      "ARGUMENT_PROVENANCE", "TOOL_SPEC_PARSE"}:
        return "Blocked by Goal/binding"
    if root_cause == "CLAIM_PARSE":
        return "Blocked by claims"
    return "Needs prompt-derived semantics"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=ROOT / "valid.parquet")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "outputs/vnext/real_valid")
    parser.add_argument("--run-label")
    args = parser.parse_args()
    output_dir = args.output_dir.resolve()
    suffix = ("__" + re.sub(r"[^A-Za-z0-9_.-]+", "_", args.run_label)
              if args.run_label else "")
    _verify_seals(output_dir, suffix)

    import pandas as pd
    gold = pd.read_parquet(args.input.resolve(), columns=["id", "label", "explanation"])
    gold_rows = {row["id"]: row for row in gold.to_dict("records")}
    cases = [json.loads(line) for line in
             (output_dir / f"cases{suffix}.jsonl").read_text(encoding="utf-8").splitlines()]
    if set(gold_rows) != {row["id"] for row in cases}:
        raise ValueError("case/gold id mismatch")

    details = []
    for row in cases:
        gold_row = gold_rows[row["id"]]
        raw_explanation = gold_row.get("explanation")
        explanation = "" if raw_explanation is None or (
            isinstance(raw_explanation, float) and math.isnan(raw_explanation)) else str(raw_explanation)
        family = _failure_family(explanation)
        root_cause = (ROOT_CAUSE[family] if int(gold_row["label"]) == 1
                      else _negative_root_cause(row))
        primary = row["R0"]
        details.append({
            "id": row["id"], "gold_label": int(gold_row["label"]),
            "predicted_label": primary["label"],
            "outcome": row["scoring"]["by_mode"]["R0"]["outcome"],
            "core_status": primary["core_status"], "root_cause": root_cause,
            "failure_family": family,
            "dependency": _dependency(root_cause, family, primary["core_status"]),
            "unknown_reasons": json.dumps(primary["unknown_reasons"], ensure_ascii=False),
            "frontend_failures": json.dumps(primary["frontend_failures"], ensure_ascii=False),
            "required_premises": json.dumps(primary["required_premises"], ensure_ascii=False),
            "explanation": explanation.replace("\r", " ").replace("\n", " "),
        })

    fields = list(details[0])
    with (output_dir / f"failure_decomposition{suffix}.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(details)

    root_table = defaultdict(lambda: Counter({"FP": 0, "FN": 0, "UNRESOLVED": 0, "total": 0}))
    for row in details:
        counts = root_table[row["root_cause"]]
        if row["outcome"] in {"FP", "FN"}:
            counts[row["outcome"]] += 1
        if row["core_status"] == "UNRESOLVED":
            counts["UNRESOLVED"] += 1
        counts["total"] += 1
    summary = {
        "rows": len(details),
        "root_causes": {key: dict(root_table[key]) for key in sorted(root_table)},
        "dependencies": dict(sorted(Counter(row["dependency"] for row in details).items())),
        "failure_families_positive": dict(sorted(Counter(
            row["failure_family"] for row in details if row["gold_label"] == 1).items())),
        "internal_statuses": dict(sorted(Counter(row["core_status"] for row in details).items())),
        "note": "Development diagnostics from public valid only; classifications are post-seal and never used by inference.",
    }
    (output_dir / f"failure_decomposition{suffix}.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
