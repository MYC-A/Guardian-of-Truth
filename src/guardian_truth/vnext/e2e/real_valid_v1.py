"""Gold-firewalled execution/scoring helpers for public competition data."""

from __future__ import annotations

from dataclasses import asdict
import csv
import hashlib
import json
from pathlib import Path
import time

from guardian_truth.parsing import parse_events

from ..adapters import AdapterMode
from ..tools import ContractRegistry
from .certificate_context_v1 import e2e_completeness_assumptions
from .competition_adapter_v1 import CompetitionInput
from .core_v1 import GuardianE2EV1
from .e2e_types_v1 import E2EArmConfig, SEMANTICS_ARMS


MODES = {
    "R0": {"description": "frozen B4h research configuration on available public inputs",
           "enable_t2": True},
    "R1": {"description": "competition prompt only; source-derived trusted subset only",
           "enable_t2": True},
    "R2": {"description": "structural-only effect ablation; no T1 and no T2 effects",
           "enable_t2": False},
}

SEMANTIC_PREMISE_FAMILIES = (
    "reads", "writes", "entity_ownership", "result_ownership", "freshness",
    "effect_guarantee", "completion_semantics", "failure_semantics",
    "state_persistence", "possible_side_effects",
)


def competition_view(row: dict) -> dict:
    """Create the only object allowed to cross the inference firewall."""
    return {key: row[key] for key in ("id", "prompt", "response")}


def _reason(value):
    return value.value if hasattr(value, "value") else str(value)


def _analysis_row(adapted: CompetitionInput, mode: str, analysis, registry, elapsed: float) -> dict:
    certificate_valid = (bool(analysis.result.certificate_check.valid)
                         if analysis.result.certificate_check is not None else None)
    claims = []
    for claim in analysis.bundle.context.claims:
        item = asdict(claim)
        for key, value in list(item.items()):
            if hasattr(value, "value"):
                item[key] = value.value
        claims.append(item)
    target_calls = []
    for event in analysis.ledger.events:
        if event.kind == "call" and event.source.document == "response":
            target_calls.append({"event_id": event.event_id,
                                 "tool": event.tool.name if event.tool else None,
                                 "payload": event.payload})
    false_witnesses = []
    for proof in analysis.result.world_proofs:
        for obligation_id, truth in proof.obligation_safety:
            if _reason(truth) == "FALSE":
                false_witnesses.append({"world_id": proof.world_id,
                                        "obligation_id": obligation_id})
    assumptions = dict(e2e_completeness_assumptions(
        analysis.bundle, analysis.ledger, registry))
    required = [key for key, value in assumptions.items() if value == "NOT_ESTABLISHED"]
    diagnostics = analysis.result.diagnostics
    return {
        "id": adapted.case.case_id,
        "mode": mode,
        "core_status": analysis.result.status.value,
        "label": analysis.product_decision.binary_label,
        "used_fallback": analysis.product_decision.used_fallback,
        "certificate_valid": certificate_valid,
        "worlds": analysis.world_count,
        "required_worlds": analysis.required_worlds,
        "frontend_failures": [
            {"component": name, "kind": kind, "detail": detail}
            for name, kind, detail in analysis.frontend_statuses],
        "component_summary": analysis.component_summary,
        "target_calls": target_calls,
        "claims": claims,
        "required_premises": required,
        "completeness_assumptions": assumptions,
        "false_witnesses": false_witnesses,
        "unknown_reasons": ([diagnostics.primary_reason.value]
                            if diagnostics.primary_reason else [])
                           + [reason.value for reason in diagnostics.contributing_reasons]
                           + list(diagnostics.missing_evidence),
        "elapsed_s": round(elapsed, 3),
        "error": None,
    }


def _error_row(adapted: CompetitionInput, mode: str, error: Exception, elapsed: float) -> dict:
    return {
        "id": adapted.case.case_id, "mode": mode,
        "core_status": "UNRESOLVED", "label": 0, "used_fallback": True,
        "certificate_valid": False, "worlds": 0, "required_worlds": 0,
        "frontend_failures": [], "component_summary": {},
        "target_calls": [], "claims": [], "required_premises": [],
        "completeness_assumptions": {}, "false_witnesses": [],
        "unknown_reasons": ["EXECUTION_ERROR"],
        "elapsed_s": round(elapsed, 3),
        "error": f"{type(error).__name__}:{str(error)[:500]}",
    }


def run_mode(adapted_cases: list[CompetitionInput], backend, mode: str, progress_path: Path,
             *, registry_builder=None, max_worlds: int = 4096) -> list[dict]:
    if mode not in MODES:
        raise ValueError("unknown real-valid mode")
    rows = json.loads(progress_path.read_text(encoding="utf-8")) if progress_path.exists() else []
    done = {row["id"] for row in rows}
    for position, adapted in enumerate(adapted_cases, 1):
        if adapted.case.case_id in done:
            continue
        registry = registry_builder(adapted) if registry_builder else ContractRegistry(())
        guardian = GuardianE2EV1(
            backend, registry=registry,
            arm=E2EArmConfig("B4h", ("h0_hist",), ("conservative",)),
            max_worlds=max_worlds, adapter_mode=AdapterMode.COMPETITION,
            enable_t2=MODES[mode]["enable_t2"], semantics=SEMANTICS_ARMS["B3"])
        started = time.monotonic()
        try:
            analysis = guardian.analyze_e2e_v1(adapted.case)
            row = _analysis_row(adapted, mode, analysis, registry, time.monotonic() - started)
        except Exception as error:  # crashes are explicit UNRESOLVED, never verdicts
            row = _error_row(adapted, mode, error, time.monotonic() - started)
        rows.append(row)
        progress_path.parent.mkdir(parents=True, exist_ok=True)
        progress_path.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"{mode} {position}/{len(adapted_cases)} {row['id']} "
              f"{row['core_status']} live_or_cached", flush=True)
    return rows


def write_predictions(rows: list[dict], path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["id", "label", "core_status",
                                                    "certificate_valid", "used_fallback"])
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row[key] for key in writer.fieldnames})
    return hashlib.sha256(path.read_bytes()).hexdigest()


def score(rows: list[dict], gold: dict[str, int]) -> dict:
    tp = sum(row["label"] == 1 and gold[row["id"]] == 1 for row in rows)
    fp = sum(row["label"] == 1 and gold[row["id"]] == 0 for row in rows)
    fn = sum(row["label"] == 0 and gold[row["id"]] == 1 for row in rows)
    tn = sum(row["label"] == 0 and gold[row["id"]] == 0 for row in rows)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    statuses = {name: sum(row["core_status"] == name for row in rows)
                for name in ("PROVED_ERROR", "PROVED_NO_ERROR", "UNRESOLVED", "INCONSISTENT")}
    definitive = [row for row in rows if row["core_status"] in {"PROVED_ERROR", "PROVED_NO_ERROR"}]
    certified = [row for row in definitive if row["certificate_valid"] is True]
    return {
        "rows": len(rows), "TP": tp, "FP": fp, "FN": fn, "TN": tn,
        "precision": round(precision, 6), "recall": round(recall, 6), "F1": round(f1, 6),
        "statuses": statuses,
        "certified_definitive_count": len(certified),
        "certified_definitive_coverage": round(len(certified) / len(rows), 6) if rows else 0.0,
        "false_certified_ERROR": sum(row["core_status"] == "PROVED_ERROR"
                                     and row["certificate_valid"] is True
                                     and gold[row["id"]] == 0 for row in rows),
        "false_certified_NO_ERROR": sum(row["core_status"] == "PROVED_NO_ERROR"
                                        and row["certificate_valid"] is True
                                        and gold[row["id"]] == 1 for row in rows),
        "uncertified_definitive": len(definitive) - len(certified),
        "execution_errors": sum(bool(row.get("error")) for row in rows),
    }


def write_case_audit(adapted_cases: list[CompetitionInput], by_mode: dict[str, list[dict]],
                     path: Path) -> None:
    mode_rows = {mode: {row["id"]: row for row in rows} for mode, rows in by_mode.items()}
    with path.open("w", encoding="utf-8") as stream:
        for adapted in adapted_cases:
            case = adapted.case
            declarations = list(adapted.tool_declarations)
            premises = premise_rows(adapted)
            modes = {mode: mode_rows[mode][case.case_id] for mode in mode_rows}
            primary = modes.get("R1") or next(iter(modes.values()))
            row = {
                "id": case.case_id,
                "input": {"prompt_sha256": hashlib.sha256(case.raw_prompt.encode()).hexdigest(),
                          "response_sha256": hashlib.sha256(case.target_response.encode()).hexdigest(),
                          "prompt_chars": len(case.raw_prompt),
                          "response_chars": len(case.target_response)},
                "environment": {"tools": [item["name"] for item in declarations],
                                "tool_count": len(declarations),
                                "schemas_available": all(item["schema_understood"] for item in declarations),
                                "descriptions_available": all(bool(item["description"]) for item in declarations)},
                "target": {"tool_calls": primary["target_calls"], "claims": primary["claims"]},
                "required_premises": primary["required_premises"],
                "premises": premises,
                **modes,
                "proof": {"core_status": primary["core_status"],
                          "certificate_valid": primary["certificate_valid"],
                          "false_witnesses": primary["false_witnesses"],
                          "unknown_reasons": primary["unknown_reasons"]},
                "manual_t1_required": None,
                "manual_only_premises": [],
            }
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_premise_coverage(adapted_cases: list[CompetitionInput], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        fields = ["id", "tool", "premise", "fact", "origin", "assessment", "trusted",
                  "source_document", "source_start", "source_end", "quote", "derivation"]
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for adapted in adapted_cases:
            for row in premise_rows(adapted):
                output = {key: row.get(key) for key in fields}
                # Preserve exact multiline source text while keeping one
                # physical CSV record per premise and a diff-safe artifact.
                quote = output.get("quote")
                output["quote"] = (json.dumps(quote, ensure_ascii=False)
                                   if isinstance(quote, str) else "")
                writer.writerow(output)


def _premise(adapted: CompetitionInput, *, tool: str = "", premise: str, fact: str,
             origin: str, assessment: str, trusted: bool, source: dict | None = None,
             derivation: str = "literal_source") -> dict:
    source = source or {}
    return {
        "id": adapted.case.case_id, "tool": tool, "premise": premise, "fact": fact,
        "origin": origin, "assessment": assessment, "trusted": trusted,
        "source_document": source.get("document"), "source_start": source.get("start"),
        "source_end": source.get("end"), "quote": source.get("quote"),
        "derivation": derivation,
    }


def premise_rows(adapted: CompetitionInput) -> list[dict]:
    """Inventory source availability without promoting prose to effect facts."""
    prompt = adapted.case.raw_prompt or ""
    rows = []
    if adapted.policy_source is not None:
        source = {"document": adapted.policy_source.document,
                  "start": adapted.policy_source.start, "end": adapted.policy_source.end,
                  "quote": prompt[adapted.policy_source.start:adapted.policy_source.end]}
        rows.append(_premise(adapted, premise="system_policy",
                             fact="normative_policy_text_present",
                             origin="EXPLICIT_SYSTEM_POLICY", assessment="EXPLICIT",
                             trusted=True, source=source))
    for event in parse_events(prompt, "prompt"):
        if event.kind not in {"call", "result"}:
            continue
        source = {"document": event.source.document, "start": event.source.start,
                  "end": event.source.end, "quote": prompt[event.source.start:event.source.end]}
        rows.append(_premise(
            adapted, tool=event.name or "", premise="observed_" + event.kind,
            fact=f"trajectory_{event.kind}_present", origin="OBSERVED_TRAJECTORY",
            assessment="EXPLICIT", trusted=True, source=source))
    for item in adapted.tool_declarations:
        tool = item["name"]
        rows.append(_premise(adapted, tool=tool, premise="tool_existence",
                             fact=f"declared_tool:{tool}", origin="EXPLICIT_SCHEMA",
                             assessment="EXPLICIT", trusted=True, source=item["source"]))
        for argument in item["arguments"]:
            path = ".".join(argument["path"])
            detail = f"declared_argument:{path}:{argument['kind']}"
            if argument["required"]:
                detail += ":required"
            if argument["enum"]:
                detail += ":enum=" + "|".join(argument["enum"])
            rows.append(_premise(adapted, tool=tool, premise="argument_existence",
                                 fact=detail, origin="EXPLICIT_SCHEMA", assessment="EXPLICIT",
                                 trusted=True, source=argument["source"]))
            rows.append(_premise(
                adapted, tool=tool, premise="argument_meaning",
                fact=f"argument_meaning_candidate:{path}", origin="SOURCE_DERIVABLE",
                assessment="UNSTRUCTURED_SOURCE_ONLY", trusted=False,
                source=argument["source"], derivation="requires_validated_semantic_extraction"))
        description_source = item.get("description_source")
        if description_source:
            rows.append(_premise(adapted, tool=tool, premise="tool_description",
                                 fact="tool_description_present",
                                 origin="EXPLICIT_TOOL_DESCRIPTION", assessment="EXPLICIT_TEXT_ONLY",
                                 trusted=True, source=description_source))
        for family in SEMANTIC_PREMISE_FAMILIES:
            rows.append(_premise(
                adapted, tool=tool, premise=family,
                fact=f"{family}:not_structured", origin=("AMBIGUOUS" if description_source
                                                          else "NOT_AVAILABLE"),
                assessment="UNSTRUCTURED_SOURCE_ONLY" if description_source else "ABSENT",
                trusted=False, source=description_source,
                derivation="requires_source_grounded_extraction_and_deterministic_validation"))
    return rows
