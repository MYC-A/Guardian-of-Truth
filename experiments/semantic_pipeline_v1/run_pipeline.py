"""semantic_pipeline_v1 — pipeline runner (Phases 6, 9, 11, 13, 15).

Stages (separate processes for RAM discipline; all artifacts under
outputs/vnext/semantic_pipeline_v1/):

  mistral    - Phase 6A: Mistral RuleIR extraction (remote, cached)
  gliner     - Phase 6C: GLiNER2.5 extraction (local, 74M)
  nuextract  - Phase 6B: NuExtract-1.5-tiny extraction (local, 494M, slow:
               runs on required fragments + synthetic only - CPU throughput)
  nli        - Phase 9: NLI firewall for every extracted rule
  binding    - Phase 11: tool/field binding for every rule target
  phi        - Phase 13: Phi assembly (no voting)
  metrics    - Phase 15 stage-level measurements (A/B/C)

Unit modes: full (policy+instructions+KB paragraphs), required (annotated
required fragments only - A2/A3/A4 ablations), synthetic (held-out cases).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))

from source_segments import build_timeline, load_development_rows
from units import extraction_units, units_for_required_fragments
from coverage_annotations import REQUIRED_FRAGMENTS, NEGATIVE_AUTO_ANNOTATED, auto_requirements, resolve_matcher
from retrieval import RetrievalConfig, retrieve, load_embedding_model
from synthetic_cases import load_synthetic_cases

OUT = REPO / "outputs" / "vnext" / "semantic_pipeline_v1"
PARQUET = REPO / "valid.parquet"

EXTRACTION_RESULTS = OUT / "semantic_extraction_results.jsonl"
NLI_RESULTS = OUT / "nli_results.jsonl"
BINDING_RESULTS = OUT / "binding_results.jsonl"
PHI_RESULTS = OUT / "phi.jsonl"


def load_cases(dataset: str) -> list[dict]:
    if dataset == "dev":
        return load_development_rows(str(PARQUET))
    if dataset == "synthetic":
        return load_synthetic_cases()
    return load_development_rows(str(PARQUET)) + load_synthetic_cases()


def _required_unit_fragments(timeline, per_matcher: int = 1) -> set[str]:
    requirements = REQUIRED_FRAGMENTS.get(timeline.case_id)
    if requirements is None and timeline.case_id in NEGATIVE_AUTO_ANNOTATED:
        requirements = auto_requirements(timeline)
    if requirements is None:
        # synthetic cases: required fragment identified by required_contains
        return set()
    ids: set[str] = set()
    for matcher in requirements:
        # the canonical required fragment(s): first `per_matcher` matches
        for fragment in resolve_matcher(timeline, matcher)[:per_matcher]:
            ids.add(fragment.fragment_id)
    return ids


def units_for(dataset: str, unit_mode: str, timeline, retrieved_ids=None) -> list:
    if unit_mode == "required":
        fragments = _required_unit_fragments(timeline)
        return units_for_required_fragments(timeline, fragments)
    units = extraction_units(timeline, retrieved_ids)
    if unit_mode == "full":
        # rules live in policy / instructions / KB documents; trajectory cue
        # fragments are offered only in 'required' mode (user-stated
        # conditions belong to the goal/claim stages, not rule extraction)
        units = [u for u in units if u.kind in {"policy_paragraph", "instructions", "kb_doc"}]
    return units


def _append_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")


def _rule_records(rules, failures, case_id, unit, extractor, elapsed_ms) -> list[dict]:
    from rule_ir import rule_to_json, render_rule
    records = []
    for rule in rules:
        records.append({"case_id": case_id, "unit_id": unit.unit_id, "unit_kind": unit.kind,
                        "extractor": extractor, "rule_id": rule.rule_id,
                        "semantic_key": rule.semantic_key(),
                        "rendered": render_rule(rule),
                        "rule": json.loads(rule_to_json(rule)),
                        "elapsed_ms": round(elapsed_ms, 1)})
    for failure in failures:
        records.append({"case_id": case_id, "unit_id": unit.unit_id, "unit_kind": unit.kind,
                        "extractor": extractor, "failure": failure})
    return records


def _existing_keys(path: Path) -> set[tuple]:
    if not path.exists():
        return set()
    keys = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if "no_result" in row:
            keys.add((row["case_id"], row["unit_id"], row["extractor"], "no_result"))
        elif "rule_id" in row or "failure" in row:
            keys.add((row["case_id"], row["unit_id"], row["extractor"],
                      row.get("rule_id", row.get("failure", {}).get("kind", ""))))
    return keys


# ------------------------------------------------------------------- stages

def stage_mistral(dataset: str, unit_mode: str) -> None:
    from extractors_mistral import MistralExtractor
    extractor = MistralExtractor()
    done = _existing_keys(EXTRACTION_RESULTS)
    total = 0
    for case in load_cases(dataset):
        timeline = build_timeline(case["id"], case["prompt"], case["response"])
        tool_names = timeline.notes.get("catalog_tools", [])
        units = units_for(dataset, unit_mode, timeline)
        rows = []
        for unit in units:
            key = (case["id"], unit.unit_id, "mistral", "")
            marker_keys = {k for k in done if k[0] == case["id"] and k[1] == unit.unit_id and k[2] == "mistral"}
            if marker_keys:
                continue
            started = time.monotonic()
            rules, failures = extractor.extract(unit, tool_names)
            rows.extend(_rule_records(rules, failures, case["id"], unit, "mistral",
                                      (time.monotonic() - started) * 1000))
            if not rules and not failures:
                rows.append({"case_id": case["id"], "unit_id": unit.unit_id,
                             "unit_kind": unit.kind, "extractor": "mistral", "no_result": True})
            total += 1
        _append_jsonl(EXTRACTION_RESULTS, rows)
        print(f"mistral {case['id']} units={len(units)} live={extractor.live_calls}", flush=True)
    print(f"TOTAL mistral extractions this run: {total}")


def stage_gliner(dataset: str, unit_mode: str) -> None:
    from extractors_gliner import GlinerExtractor
    extractor = GlinerExtractor()
    done = _existing_keys(EXTRACTION_RESULTS)
    for case in load_cases(dataset):
        timeline = build_timeline(case["id"], case["prompt"], case["response"])
        tool_names = timeline.notes.get("catalog_tools", [])
        units = units_for(dataset, unit_mode, timeline)
        rows = []
        for unit in units:
            if any(k[0] == case["id"] and k[1] == unit.unit_id and k[2] == "gliner2" for k in done):
                continue
            started = time.monotonic()
            rules, failures = extractor.extract(unit, tool_names)
            rows.extend(_rule_records(rules, failures, case["id"], unit, "gliner2",
                                      (time.monotonic() - started) * 1000))
        _append_jsonl(EXTRACTION_RESULTS, rows)
        print(f"gliner {case['id']} units={len(units)}", flush=True)


def stage_nuextract(dataset: str, unit_mode: str) -> None:
    from extractors_nuextract import NuExtractExtractor
    extractor = NuExtractExtractor()
    done = _existing_keys(EXTRACTION_RESULTS)
    import os
    only = set(filter(None, os.environ.get("CASES_ONLY", "").split(",")))
    for case in load_cases(dataset):
        if only and case["id"] not in only:
            continue
        timeline = build_timeline(case["id"], case["prompt"], case["response"])
        tool_names = timeline.notes.get("catalog_tools", [])
        units = units_for(dataset, unit_mode, timeline)
        rows = []
        for unit in units:
            if any(k[0] == case["id"] and k[1] == unit.unit_id and k[2] == "nuextract" for k in done):
                continue
            started = time.monotonic()
            rules, failures = extractor.extract(unit, tool_names)
            rows.extend(_rule_records(rules, failures, case["id"], unit, "nuextract",
                                      (time.monotonic() - started) * 1000))
            if not rules and not failures:
                # resumability marker: the unit produced no rules and no
                # failures (NuExtract found nothing template-worthy)
                rows.append({"case_id": case["id"], "unit_id": unit.unit_id,
                             "unit_kind": unit.kind, "extractor": "nuextract", "no_result": True})
        _append_jsonl(EXTRACTION_RESULTS, rows)
        print(f"nuextract {case['id']} units={len(units)} new={len(rows)}", flush=True)


def _load_extraction() -> list[dict]:
    rows = []
    if EXTRACTION_RESULTS.exists():
        for line in EXTRACTION_RESULTS.read_text(encoding="utf-8").splitlines():
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
    return rows


def stage_nli() -> None:
    from nli_check import NliChecker
    from rule_ir import RuleIR
    checker = NliChecker()
    rows = _load_extraction()
    done_ids = set()
    if NLI_RESULTS.exists():
        for line in NLI_RESULTS.read_text(encoding="utf-8").splitlines():
            try:
                done_ids.add(json.loads(line)["rule_id"])
            except (ValueError, KeyError):
                continue
    pending = [row for row in rows if "rule_id" in row and row["rule_id"] not in done_ids]
    print(f"nli pending: {len(pending)} rules")
    out = []
    for index, row in enumerate(pending):
        rule = RuleIR.model_validate(row["rule"])
        unit_text = rule.source_spans[0].quote if rule.source_spans else ""
        if not unit_text:
            continue
        result = checker.check_rule(unit_text, row["rendered"])
        out.append({"case_id": row["case_id"], "rule_id": row["rule_id"],
                    "extractor": row["extractor"], "unit_kind": row.get("unit_kind"),
                    "premise": unit_text[:400], "hypothesis": row["rendered"],
                    "label": result["label"], "scores": result["scores"]})
        if (index + 1) % 200 == 0:
            _append_jsonl(NLI_RESULTS, out)
            print(f"nli {index + 1}/{len(pending)}", flush=True)
            out = []
    _append_jsonl(NLI_RESULTS, out)
    print(f"nli done: +{len(pending)}")


def stage_binding() -> None:
    from binding import Binder, tool_description_map, state_field_names
    from rule_ir import RuleIR
    binder = Binder()
    rows = _load_extraction()
    done_ids = set()
    if BINDING_RESULTS.exists():
        for line in BINDING_RESULTS.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
                done_ids.add((row["case_id"], row["rule_id"]))
            except (ValueError, KeyError):
                continue
    by_case: dict[str, list[dict]] = {}
    for row in rows:
        if "rule_id" in row and (row["case_id"], row["rule_id"]) not in done_ids:
            by_case.setdefault(row["case_id"], []).append(row)
    out = []
    for case in load_cases("all"):
        timeline = build_timeline(case["id"], case["prompt"], case["response"])
        descriptions = tool_description_map(timeline)
        tool_names = timeline.notes.get("catalog_tools", [])
        fields = state_field_names(timeline)
        case_rows = by_case.pop(case["id"], [])
        for row in case_rows:
            rule = RuleIR.model_validate(row["rule"])
            action = binder.bind(rule.target.text, tool_names, descriptions, kind="action")
            result = action.as_dict()
            result.update({"case_id": case["id"], "rule_id": row["rule_id"],
                           "extractor": row["extractor"]})
            out.append(result)
        print(f"binding {case['id']} rules={len(case_rows)}", flush=True)
        _append_jsonl(BINDING_RESULTS, out)
        out = []


def stage_phi(nli_filter: bool) -> None:
    from phi import assemble_phi
    from rule_ir import RuleIR
    extraction = _load_extraction()
    # rule_ids are unique only WITHIN a case (unit numbering restarts per
    # case); all joins are therefore keyed by (case_id, rule_id)
    nli: dict[tuple[str, str], dict] = {}
    if NLI_RESULTS.exists():
        for line in NLI_RESULTS.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
                nli[(row["case_id"], row["rule_id"])] = row
            except ValueError:
                continue
    bindings: dict[tuple[str, str], dict] = {}
    if BINDING_RESULTS.exists():
        for line in BINDING_RESULTS.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
                bindings[(row["case_id"], row["rule_id"])] = row
            except ValueError:
                continue
    rules_by_case: dict[str, list[RuleIR]] = {}
    for row in extraction:
        if "rule" not in row:
            continue
        rules_by_case.setdefault(row["case_id"], []).append(RuleIR.model_validate(row["rule"]))
    with PHI_RESULTS.open("w", encoding="utf-8") as stream:
        for case in load_cases("all"):
            case_id = case["id"]
            rules = rules_by_case.get(case_id, [])
            case_nli = {rule_id: row for (cid, rule_id), row in nli.items() if cid == case_id}
            case_bindings = {rule_id: row for (cid, rule_id), row in bindings.items()
                             if cid == case_id}
            phi = assemble_phi(case_id, rules, nli_results=case_nli, bindings=case_bindings,
                               nli_filter=nli_filter)
            stream.write(json.dumps(phi.as_dict(), ensure_ascii=False) + "\n")
            print(f"phi {case_id} interpretations={len(phi.candidates)} "
                  f"provenance={phi.provenance_counts}", flush=True)


def stage_metrics() -> dict:
    """Phase 15 A/B/C stage measurements."""
    metrics = {}
    coverage = json.loads((OUT / "retrieval_coverage_summary.json").read_text(encoding="utf-8"))
    metrics["A_source_coverage"] = {
        "current_routing_recall": coverage["recall"]["current"],
        "deterministic_recall": coverage["recall"]["deterministic"],
        "embedding_recall": coverage["recall"]["embedding"],
        "combined_recall": coverage["recall"]["combined"],
        "required_total": coverage["required_total"],
    }
    # B: semantic preservation on synthetic (ground truth available)
    b_rows = _semantic_preservation()
    metrics["B_semantic_extraction"] = b_rows
    # C: grounding on synthetic + dev
    c_rows = _grounding_accuracy()
    metrics["C_grounding"] = c_rows
    (OUT / "stage_metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=1),
                                            encoding="utf-8")
    print(json.dumps(metrics, indent=1)[:3000])
    return metrics


def _semantic_preservation() -> dict:
    """For each synthetic case: does Phi contain a candidate matching the
    ground-truth semantics per dimension?  Per-extractor breakdown included."""
    from phi import assemble_phi
    from rule_ir import RuleIR
    synthetic = {case["id"]: case for case in load_synthetic_cases()}
    nli, bindings = {}, {}
    if NLI_RESULTS.exists():
        for line in NLI_RESULTS.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
                nli[row["rule_id"]] = row
            except ValueError:
                continue
    if BINDING_RESULTS.exists():
        for line in BINDING_RESULTS.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
                bindings[row["rule_id"]] = row
            except ValueError:
                continue
    rules_by_case: dict[str, list[RuleIR]] = {}
    for row in _load_extraction():
        if "rule" not in row:
            continue
        rules_by_case.setdefault(row["case_id"], []).append(RuleIR.model_validate(row["rule"]))

    def dimensions_match(rule: RuleIR, expected: dict) -> dict:
        dims = {}
        dims["modality"] = rule.modality == expected.get("modality")
        target_ref = rule.target.ref
        if expected.get("target_ref"):
            dims["target"] = (target_ref == expected["target_ref"]
                              or expected["target_ref"].lower() in (rule.target.text.lower()
                                                                    + " " + target_ref.lower()))
        if expected.get("temporal"):
            dims["temporal"] = rule.temporal.relation == expected["temporal"]
        if expected.get("condition_ref"):
            leaves = [atom.text.lower() + " " + (atom.ref or "").lower()
                      for atom in (rule.conditions.leaves() if rule.conditions else [])
                      + [atom for node in rule.exceptions for atom in node.leaves()]]
            dims["condition"] = any(expected["condition_ref"].lower() in leaf for leaf in leaves)
        if expected.get("condition_refs"):
            leaves = " ".join(atom.text.lower() for atom in (rule.conditions.leaves() if rule.conditions else []))
            dims["conditions_all"] = all(ref.lower() in leaves for ref in expected["condition_refs"])
        if expected.get("exception_ref"):
            leaves = " ".join(atom.text.lower() for node in rule.exceptions for atom in node.leaves())
            dims["exception"] = expected["exception_ref"].lower() in leaves
        if expected.get("comparison_op"):
            found = [atom for atom in (rule.conditions.leaves() if rule.conditions else [])
                     + [atom for node in rule.exceptions for atom in node.leaves()]
                     if atom.comparison]
            dims["comparison"] = any(atom.comparison.op == expected["comparison_op"] for atom in found)
            if expected.get("comparison_rhs"):
                rhs = str(expected["comparison_rhs"])
                dims["comparison_value"] = any(rhs in atom.comparison.rhs_literal for atom in found)
        if expected.get("cardinality_op"):
            found = [atom for atom in (rule.conditions.leaves() if rule.conditions else [])
                     + [atom for node in rule.exceptions for atom in node.leaves()]
                     if atom.cardinality and atom.cardinality.op != "NONE"]
            dims["cardinality"] = any(
                atom.cardinality.op == expected["cardinality_op"]
                and (expected.get("cardinality_count") is None
                     or atom.cardinality.count == expected["cardinality_count"]) for atom in found)
        if expected.get("preserved_field"):
            wanted = expected["preserved_field"].replace("_", " ").lower()
            dims["preservation_field"] = wanted in (
                rule.target.text.lower() + " " + " ".join(
                    atom.text.lower() for atom in (rule.conditions.leaves() if rule.conditions else [])))
        return dims

    per_case = []
    for case_id, case in synthetic.items():
        expected = case["expected"]
        rules = rules_by_case.get(case_id, [])
        by_extractor = {"mistral": None, "nuextract": None, "gliner2": None, "union": None}
        for extractor in ("mistral", "nuextract", "gliner2"):
            subset = [rule for rule in rules if rule.provenance.extractor == extractor
                      or ":unless_mirror" in rule.rule_id and rule.provenance.extractor == extractor]
            dims_all = {}
            for rule in subset:
                for dim, ok in dimensions_match(rule, expected).items():
                    dims_all[dim] = dims_all.get(dim, False) or ok
            by_extractor[extractor] = dims_all
        dims_all = {}
        for rule in rules:
            for dim, ok in dimensions_match(rule, expected).items():
                dims_all[dim] = dims_all.get(dim, False) or ok
        by_extractor["union"] = dims_all
        per_case.append({"case_id": case_id, "family": case_id.rsplit("__", 1)[-1],
                         "by_extractor": by_extractor})
    # aggregate over APPLICABLE cases only (a dimension applies to a case when
    # the ground truth defines it; e.g. temporal applies to 2 of 17 cases)
    def agg(extractor) -> dict:
        applicable: dict[str, int] = {}
        hits: dict[str, int] = {}
        for row in per_case:
            for key, value in (row["by_extractor"][extractor] or {}).items():
                applicable[key] = applicable.get(key, 0) + 1
                if value:
                    hits[key] = hits.get(key, 0) + 1
        return {key: {"hit": hits.get(key, 0), "applicable": applicable[key],
                      "rate": round(hits.get(key, 0) / applicable[key], 3)}
                for key in sorted(applicable)}
    return {"cases": len(per_case), "per_case": per_case,
            "aggregate": {extractor: agg(extractor)
                          for extractor in ("mistral", "nuextract", "gliner2", "union")}}


def _grounding_accuracy() -> dict:
    """Binding correctness: synthetic expected target_ref + dev annotated tools."""
    from rule_ir import RuleIR
    synthetic = {case["id"]: case for case in load_synthetic_cases()}
    bindings = {}
    if BINDING_RESULTS.exists():
        for line in BINDING_RESULTS.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
                bindings.setdefault(row["case_id"], []).append(row)
            except ValueError:
                continue
    rules_by_case: dict[str, dict[str, RuleIR]] = {}
    for row in _load_extraction():
        if "rule" not in row:
            continue
        rules_by_case.setdefault(row["case_id"], {})[row["rule_id"]] = RuleIR.model_validate(row["rule"])
    hits = {"BOUND_correct": 0, "BOUND_wrong": 0, "AMBIGUOUS": 0, "UNKNOWN": 0}
    total = 0
    for case_id, case in synthetic.items():
        expected_ref = case["expected"].get("target_ref")
        if not expected_ref:
            continue
        for row in bindings.get(case_id, []):
            rule = rules_by_case.get(case_id, {}).get(row["rule_id"])
            if rule is None or rule.target.ref != expected_ref and rule.modality != case["expected"].get("modality"):
                continue
            total += 1
            status = row.get("status")
            names = [candidate["name"] for candidate in row.get("candidates", [])]
            if status == "BOUND":
                hits["BOUND_correct" if expected_ref in names else "BOUND_wrong"] += 1
            elif status == "AMBIGUOUS":
                hits["AMBIGUOUS"] += 1
            else:
                hits["UNKNOWN"] += 1
    return {"synthetic_binding_of_matching_rules": {"total": total, **hits,
                                                    "bound_correct_rate": round(
                                                        hits["BOUND_correct"] / total, 3) if total else None}}


# -------------------------------------------------------------------- main

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=["mistral", "gliner", "nuextract", "nli", "binding",
                                          "phi", "metrics", "phi_filtered"])
    parser.add_argument("--dataset", default="dev", choices=["dev", "synthetic", "all"])
    parser.add_argument("--units", default="full", choices=["full", "required"])
    parser.add_argument("--nli-filter", action="store_true")
    args = parser.parse_args()
    if args.stage == "mistral":
        stage_mistral(args.dataset, args.units)
    elif args.stage == "gliner":
        stage_gliner(args.dataset, args.units)
    elif args.stage == "nuextract":
        stage_nuextract(args.dataset, args.units)
    elif args.stage == "nli":
        stage_nli()
    elif args.stage == "binding":
        stage_binding()
    elif args.stage == "phi":
        stage_phi(False)
    elif args.stage == "phi_filtered":
        stage_phi(True)
    elif args.stage == "metrics":
        stage_metrics()


if __name__ == "__main__":
    main()
