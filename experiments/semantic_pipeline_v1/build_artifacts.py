"""semantic_pipeline_v1 — Phase 17/18 artifact assembly.

Builds:
  outputs/vnext/semantic_pipeline_v1/ablations.json       (A0..A8)
  outputs/vnext/semantic_pipeline_v1/example_traces.json  (8 semantic families)
  outputs/vnext/semantic_pipeline_v1/final_summary.json

Ablation semantics (dev unless noted):
  A0 incumbent frontend, fresh cache (final Guardian)          - measured
  A1 retrieval-augmented incumbent frontend                    - measured
  A2 correct fragment + Mistral RuleIR                         - stage B per-extractor
  A3 correct fragment + NuExtract RuleIR                       - stage B per-extractor
  A4 correct fragment + GLiNER2 relations                      - stage B per-extractor
  A5 Mistral + NuExtract candidate union                       - stage B union + Phi sizes
  A6 Mistral + NuExtract + GLiNER candidate union              - stage B union + Phi sizes
  A7 A6 + NLI filtering (contradiction removal)                - Phi filtered sizes
  A8 A7 + binding -> final Guardian (dev + synthetic)          - measured
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO / "src"))

OUT = REPO / "outputs" / "vnext" / "semantic_pipeline_v1"


def _load_json(name: str):
    path = OUT / name
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _load_jsonl(name: str) -> list[dict]:
    path = OUT / name
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8").strip()
    if text.startswith("["):
        return json.loads(text)
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def _progress_score(name: str, gold: dict) -> dict:
    rows = _load_jsonl(name)
    tp = sum(r["label"] == 1 and gold.get(r["id"]) == 1 for r in rows)
    fp = sum(r["label"] == 1 and gold.get(r["id"]) == 0 for r in rows)
    fn = sum(r["label"] == 0 and gold.get(r["id"]) == 1 for r in rows)
    tn = sum(r["label"] == 0 and gold.get(r["id"]) == 0 for r in rows)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"TP": tp, "FP": fp, "FN": fn, "TN": tn, "precision": round(precision, 4),
            "recall": round(recall, 4), "F1": round(f1, 4)}


def build_ablations() -> dict:
    import pandas as pd
    dev = pd.read_parquet(REPO / "valid.parquet")
    dev_gold = {row["id"]: int(row["label"]) for row in dev.to_dict(orient="records")}
    from synthetic_cases import load_synthetic_cases
    syn_gold = {case["id"]: int(case["label"]) for case in load_synthetic_cases()}
    stage = _load_json("stage_metrics.json")
    phi_rows = _load_jsonl("phi.jsonl")
    phi_sizes_dev = [r["interpretations"] for r in phi_rows if not r["case_id"].startswith("syn")]
    phi_sizes_syn = [r["interpretations"] for r in phi_rows if r["case_id"].startswith("syn")]
    contradicted = sum(1 for r in phi_rows for c in r["candidates"]
                       if c.get("flags", {}).get("contradicted_by_nli"))
    total_candidates = sum(len(r["candidates"]) for r in phi_rows)
    agg = stage.get("B_semantic_extraction", {}).get("aggregate", {})

    def preservation(extractor):
        return {key: value["rate"] for key, value in agg.get(extractor, {}).items()}

    return {
        "protocol": "46 development rows (VIEWED DATA) + 17 synthetic held-out rows; "
                    "Mistral cache keyed by payload; local models loaded per stage",
        "A0_incumbent_fresh_cache": _progress_score("final_guardian_A0_progress.json", dev_gold),
        "A0_note": "incumbent h0_hist/conservative/claims/T2/binding stack at HEAD production "
                   "defaults (closure premises OFF), fresh semantic cache; the frozen-lineage "
                   "baseline (audit C3) was TP=3",
        "A1_retrieval_augmented_incumbent": _progress_score("final_guardian_A1_progress.json", dev_gold),
        "A1_note": "policy frontend input extended with retrieved KB document text; same TPs as A0",
        "A2_mistral_on_correct_fragment": {"semantic_preservation": preservation("mistral")},
        "A3_nuextract_on_correct_fragment": {"semantic_preservation": preservation("nuextract")},
        "A4_gliner_on_correct_fragment": {"semantic_preservation": preservation("gliner2")},
        "A5_mistral_nuextract_union": {
            "semantic_preservation_union": preservation("union"),
            "note": "per-extractor rows above; union = Phi dedupe by semantic_key"},
        "A6_all_three_union": {
            "phi_size_dev_mean": round(sum(phi_sizes_dev) / len(phi_sizes_dev), 1),
            "phi_size_synthetic_mean": round(sum(phi_sizes_syn) / len(phi_sizes_syn), 1),
            "total_candidates": total_candidates,
            "semantic_preservation_union": preservation("union")},
        "A7_nli_filtering": {
            "contradicted_candidates": contradicted,
            "contradiction_rate": round(contradicted / total_candidates, 3) if total_candidates else 0,
            "note": "CONTRADICTION candidates cannot be the only accepted interpretation; "
                    "they are removed before lowering (A8) but remain recorded in Phi"},
        "A8_full_pipeline_final_guardian": {
            "dev": _progress_score("final_guardian_A8_progress.json", dev_gold),
            "synthetic_heldout": _progress_score("final_guardian_A8_synthetic_progress.json", syn_gold)},
        "A8_note": "Phi (admission: non-contradicted, non-UNKNOWN modality/target, tool-exact "
                   "action key, bound) -> incumbent compiler -> incumbent core; goal/claims/T2 "
                   "cache shared with A0",
    }


FAMILY_CASES = {
    "temporal": "syn_library__temporal_before",
    "conditional": "syn_permit__conditional_only_if",
    "exception": "syn_dispatch__exception_unless",
    "numeric": "syn_gym__numeric_below",
    "cardinality": "syn_claims__cardinality_at_least",
    "preservation": "syn_parking__preservation",
    "provenance-like": "syn_saas__provenance_user_provided",
    "kb-derived": "syn_warehouse__kb_derived_rule",
}


def build_traces() -> list[dict]:
    from source_segments import build_timeline
    from synthetic_cases import load_synthetic_cases
    from coverage_annotations import REQUIRED_FRAGMENTS, resolve_matcher
    cases = {case["id"]: case for case in load_synthetic_cases()}
    extraction = _load_jsonl("semantic_extraction_results.jsonl")
    nli = {(row["case_id"], row["rule_id"]): row for row in _load_jsonl("nli_results.jsonl")}
    bindings = {(row["case_id"], row["rule_id"]): row for row in _load_jsonl("binding_results.jsonl")}
    phi_by_case = {row["case_id"]: row for row in _load_jsonl("phi.jsonl")}

    # dev KB-derived trace: banking task_051 (KB rules in search results)
    dev_kb_case = "banking_knowledge__task_051::t15"

    traces = []
    for family, case_id in FAMILY_CASES.items():
        case = cases[case_id]
        timeline = build_timeline(case_id, case["prompt"], case["response"])
        # the required fragment (the rule-carrying source unit)
        required = next((f for f in timeline.fragments
                         if case["required_contains"].lower() in f.text.lower()),
                        timeline.fragments[0])
        rule_rows = [row for row in extraction
                     if row["case_id"] == case_id and row.get("unit_kind") == "policy_paragraph"
                     and required.text[:80] in row.get("rule", {}).get("source_spans", [{}])[0]
                     .get("quote", "")]
        if not rule_rows:
            rule_rows = [row for row in extraction if row["case_id"] == case_id and "rule_id" in row][:6]
        candidates = []
        for row in rule_rows:
            rule_id = row.get("rule_id")
            if not rule_id:
                continue
            candidates.append({
                "extractor": row["extractor"],
                "modality": row["rule"]["modality"],
                "target": row["rule"]["target"],
                "rendered": row.get("rendered"),
                "nli": {k: v for k, v in nli.get((case_id, rule_id), {}).items()
                        if k in ("label", "scores")},
                "binding": {k: v for k, v in bindings.get((case_id, rule_id), {}).items()
                            if k in ("status", "candidates")},
            })
        phi = phi_by_case.get(case_id, {})
        compiled = _load_jsonl("final_guardian_A8_synthetic_progress.json")
        outcome = next((r for r in compiled if r["id"] == case_id), {})
        traces.append({
            "family": family, "case_id": case_id,
            "raw_source": required.text,
            "source_metadata": {"fragment_id": required.fragment_id,
                                "source_type": required.source_type,
                                "span": list(required.span), "document": required.document},
            "expected": case["expected"],
            "extractor_outputs": candidates,
            "phi_interpretations": phi.get("interpretations"),
            "phi_provenance": phi.get("provenance_counts"),
            "compiled_guardian_verdict": {
                "core_status": outcome.get("core_status"),
                "false_witnesses": outcome.get("false_witnesses", [])[:2]},
        })
    # dev KB-derived trace
    dev_rows = [row for row in extraction if row["case_id"] == dev_kb_case
                and row.get("unit_kind") == "kb_doc" and "rule_id" in row][:4]
    dev_phi = phi_by_case.get(dev_kb_case, {})
    dev_outcome = next((r for r in _load_jsonl("final_guardian_A8_progress.json")
                        if r["id"] == dev_kb_case), {})
    traces.append({
        "family": "kb-derived (development data)", "case_id": dev_kb_case,
        "raw_source": (dev_rows[0]["rule"]["source_spans"][0]["quote"][:400]
                       if dev_rows else "KB rule fragment"),
        "source_metadata": {"unit_kind": "kb_doc"},
        "expected": "KB rule (logistics_007/005 thresholds) inside search results",
        "extractor_outputs": [{
            "extractor": row["extractor"], "modality": row["rule"]["modality"],
            "target": row["rule"]["target"], "rendered": row.get("rendered"),
            "nli": {k: v for k, v in nli.get((dev_kb_case, row["rule_id"]), {}).items()
                    if k in ("label", "scores")},
            "binding": {k: v for k, v in bindings.get((dev_kb_case, row["rule_id"]), {}).items()
                        if k in ("status", "candidates")}} for row in dev_rows],
        "phi_interpretations": dev_phi.get("interpretations"),
        "phi_provenance": dev_phi.get("provenance_counts"),
        "compiled_guardian_verdict": {
            "core_status": dev_outcome.get("core_status"),
            "false_witnesses": dev_outcome.get("false_witnesses", [])[:2]},
    })
    return traces


def build_final_summary() -> dict:
    stage = _load_json("stage_metrics.json")
    coverage = _load_json("retrieval_coverage_summary.json")
    nli_demo = _load_json("nli_adversarial_demo.json")
    phi_rows = _load_jsonl("phi.jsonl")
    dev_phi = [r for r in phi_rows if not r["case_id"].startswith("syn")]
    ablations = _load_json("ablations.json")
    return {
        "branch": "codex-update-run @ 4639b46f2e6995ea7036aef73a01ebbc723c0e14 (start)",
        "phase_A_source_coverage": {
            "current_guardian_routing": coverage.get("recall", {}).get("current"),
            "deterministic_only": coverage.get("recall", {}).get("deterministic"),
            "embeddings_only": coverage.get("recall", {}).get("embedding"),
            "deterministic_lexical_kb_embeddings": coverage.get("recall", {}).get("combined")},
        "phase_B_semantic_preservation_synth": stage.get("B_semantic_extraction", {}).get("aggregate"),
        "phase_C_grounding_synth": stage.get("C_grounding"),
        "phase_D_final_guardian": {
            "A0_incumbent": ablations.get("A0_incumbent_fresh_cache"),
            "A1_retrieval_augmented": ablations.get("A1_retrieval_augmented_incumbent"),
            "A8_pipeline_dev": ablations.get("A8_full_pipeline_final_guardian", {}).get("dev"),
            "A8_pipeline_synthetic": ablations.get("A8_full_pipeline_final_guardian", {}).get("synthetic_heldout")},
        "phi_statistics": {
            "dev_mean_interpretations": round(
                sum(r["interpretations"] for r in dev_phi) / len(dev_phi), 1),
            "candidates_total": sum(len(r["candidates"]) for r in phi_rows)},
        "phase10_embeddings_vs_nli": {
            "mean_cosine_of_reversed_pairs": nli_demo.get("mean_cosine_of_reversed_pairs"),
            "nli_contradiction_detection": nli_demo.get("contradiction_detection_rate")},
        "models": _load_json("hardware.json").get("local_models"),
        "decision": "see docs/vnext/e2e/SEMANTIC_PIPELINE_V1.md (final section)",
    }


def main() -> None:
    ablations = build_ablations()
    (OUT / "ablations.json").write_text(json.dumps(ablations, ensure_ascii=False, indent=1),
                                        encoding="utf-8")
    traces = build_traces()
    (OUT / "example_traces.json").write_text(json.dumps(traces, ensure_ascii=False, indent=1),
                                             encoding="utf-8")
    summary = build_final_summary()
    (OUT / "final_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1),
                                            encoding="utf-8")
    print("ablations.json, example_traces.json, final_summary.json written")
    print(json.dumps({key: ablations[key] for key in
                      ("A0_incumbent_fresh_cache", "A1_retrieval_augmented_incumbent",
                       "A8_full_pipeline_final_guardian")}, indent=1))


if __name__ == "__main__":
    main()
