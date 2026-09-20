"""Model-backed bidirectional critique and own-author repair generation."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Protocol

from .contracts import (CaseInput, CritiqueIssue, TheoryCandidate, TheoryCritique,
                        TheoryElement)
from .grounding import resolve_unique_quote, validate_link
from .run_b_theory import _candidate_map, _rows, _sha


NUEXTRACT_CRITIQUE_TEMPLATE = {
    "issues": [{"target_element_id": "verbatim-element-id",
                "problem_type": ["missing_condition", "missing_exception",
                                 "wrong_modality", "wrong_actor", "wrong_time",
                                 "wrong_scope", "invented_requirement", "wrong_relation",
                                 "other"],
                "source_id": "verbatim-source-id", "start": "integer", "end": "integer",
                "quote": "verbatim-source-quote", "explanation": "string"}],
    "unresolved": ["string"],
}

NUEXTRACT_REPAIR_TEMPLATE = {
    "changes": [{"element_id": "existing-target-element-id",
                 "interpretation": "string", "source_links": [{
                     "source_id": "verbatim-source-id", "start": "integer",
                     "end": "integer", "quote": "verbatim-source-quote"}],
                 "rule_ir": "object-or-null", "unresolved_components": ["string"]}],
    "additions": [{"element_id": "new-element-id", "interpretation": "string",
                   "source_links": [{"source_id": "verbatim-source-id", "start": "integer",
                                     "end": "integer", "quote": "verbatim-source-quote"}],
                   "rule_ir": "object-or-null", "unresolved_components": ["string"]}],
    "unresolved": ["string"],
}


@dataclass(frozen=True)
class ModelResult:
    parsed: dict | None
    raw_response: dict | None
    error: str | None = None


class ReviewBackend(Protocol):
    provider: str
    model_id: str
    dependency: str

    def critique(self, case: CaseInput, target: TheoryCandidate) -> ModelResult: ...
    def repair(self, case: CaseInput, parent: TheoryCandidate,
               critique: TheoryCritique) -> ModelResult: ...


def _payload(case: CaseInput, theory: TheoryCandidate) -> dict:
    return {"policy_sources": [asdict(item) for item in case.sources],
            "theory": asdict(theory)}


class MistralReviewBackend:
    provider = "mistral"
    dependency = "MISTRAL_API"

    def __init__(self, model_id="ministral-14b-latest", api_key_env="MISTRAL_API_KEY",
                 client=None):
        if model_id != "ministral-14b-latest":
            raise ValueError("B3 Mistral reviewer must use ministral-14b-latest")
        self.model_id = model_id
        if client is None:
            from guardian_truth.llm_client import ChatClient, ClientConfig
            client = ChatClient(ClientConfig(base_url="https://api.mistral.ai/v1",
                                model=model_id, api_key_env=api_key_env,
                                timeout_seconds=120, max_output_tokens=4096,
                                max_retries=1, strict_schema=False,
                                response_format_mode="auto"))
        self.client = client

    def _call(self, instruction: str, payload: dict) -> ModelResult:
        try:
            from guardian_truth.semantic_pipeline_v1.models.common import extract_json_object
            completion = self.client.complete([
                {"role": "system", "content": instruction},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ])
            parsed = extract_json_object(completion.content)
            return ModelResult(parsed, {"completion_content": completion.content,
                                        "parsed_object": parsed})
        except Exception as exc:
            return ModelResult(None, None, f"{type(exc).__name__}: {exc}")

    def critique(self, case, target):
        return self._call(
            "Critique only the supplied other-provider theory against the original policy. "
            "Return JSON matching this schema: " + json.dumps(NUEXTRACT_CRITIQUE_TEMPLATE) +
            ". Every issue must quote exact source text with exact zero-based offsets.",
            _payload(case, target))

    def repair(self, case, parent, critique):
        return self._call(
            "Repair your own parent theory only where the grounded critique targets it. "
            "Never delete or rename parent elements. Return patch JSON matching: " +
            json.dumps(NUEXTRACT_REPAIR_TEMPLATE),
            {**_payload(case, parent), "critique": asdict(critique)})


class NuExtractReviewBackend:
    provider = "nuextract"
    dependency = "NUEXTRACT_LOCAL_MODEL"

    def __init__(self, *, model_id: str, model, processor, max_new_tokens=4096):
        self.model_id, self.model, self.processor = model_id, model, processor
        self.max_new_tokens = max_new_tokens

    @classmethod
    def load(cls, model_id: str, device: str):
        from guardian_truth.semantic_pipeline_v1.models.nuextract import NuExtractRuleExtractor
        model, processor = NuExtractRuleExtractor.load(model_id, device)
        return cls(model_id=model_id, model=model, processor=processor)

    def _call(self, payload: dict, template: dict) -> ModelResult:
        try:
            import torch
            from guardian_truth.semantic_pipeline_v1.models.common import extract_json_object
            text = json.dumps(payload, ensure_ascii=False)
            messages = [{"role": "user", "content": [{"type": "text", "text": text}]}]
            inputs = self.processor.apply_chat_template(
                messages, add_generation_prompt=True, tokenize=True, return_dict=True,
                return_tensors="pt", template=json.dumps(template, indent=4),
                enable_thinking=False).to(self.model.device)
            with torch.inference_mode():
                output = self.model.generate(**inputs, do_sample=False,
                                             max_new_tokens=self.max_new_tokens)
            generated = output[:, inputs["input_ids"].shape[1]:]
            decoded = self.processor.batch_decode(
                generated, skip_special_tokens=True,
                clean_up_tokenization_spaces=False)[0].strip()
            parsed = extract_json_object(decoded)
            return ModelResult(parsed, {"decoded_text": decoded, "parsed_template": parsed})
        except Exception as exc:
            return ModelResult(None, None, f"{type(exc).__name__}: {exc}")

    def critique(self, case, target):
        return self._call({"task": "critique other-provider theory against original policy; "
                                   "use exact zero-based source offsets",
                           **_payload(case, target)}, NUEXTRACT_CRITIQUE_TEMPLATE)

    def repair(self, case, parent, critique):
        return self._call({"task": "patch own parent only; never delete or rename elements",
                           **_payload(case, parent), "critique": asdict(critique)},
                          NUEXTRACT_REPAIR_TEMPLATE)


def _digest(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":")).encode("utf-8")).hexdigest()


def _redact(value):
    secrets = [item for key, item in os.environ.items() if "KEY" in key.upper() and item]
    if isinstance(value, str):
        for secret in secrets:
            value = value.replace(secret, "[REDACTED]")
        return value
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, dict):
        return {key: _redact(item) for key, item in value.items()
                if "api_key" not in str(key).casefold()}
    return value


def _critique(case: CaseInput, backend: ReviewBackend, target: TheoryCandidate,
              result: ModelResult) -> tuple[TheoryCritique, list[dict]]:
    if result.parsed is None:
        raise ValueError(result.error or "model returned no parsed critique")
    raw_issues = result.parsed.get("issues")
    if not isinstance(raw_issues, list):
        raise ValueError("model critique issues must be a list")
    issues, bindings, technical = [], [], []
    sources = {item.source_id: item for item in case.sources}
    for index, item in enumerate(raw_issues):
        if not isinstance(item, dict):
            raise ValueError("critique issue is not an object")
        wire = dict(item)
        wire["issue_id"] = wire.get("issue_id") or (
            f"{backend.provider}:{target.candidate_id}:{index}")
        supplied = wire.get("source_link") or wire
        link, method = resolve_unique_quote(
            source_id=supplied.get("source_id"), quote=supplied.get("quote"),
            start=supplied.get("start"), end=supplied.get("end"), sources=sources)
        bindings.append({"issue_id": wire["issue_id"], "status": method,
                         "technical": link is None})
        if link is None:
            technical.append(f"TECHNICAL_QUOTE_BINDING:{wire['issue_id']}:{method}")
            continue
        wire["source_link"] = asdict(link)
        problem_types = wire.get("problem_type")
        if isinstance(problem_types, list):
            if not problem_types or any(not isinstance(value, str) for value in problem_types):
                raise ValueError(f"{wire['issue_id']}: invalid problem_type list")
            for ordinal, problem_type in enumerate(dict.fromkeys(problem_types)):
                typed = {**wire, "issue_id": f"{wire['issue_id']}:{ordinal}",
                         "problem_type": problem_type}
                issues.append(CritiqueIssue.parse(typed))
        else:
            issues.append(CritiqueIssue.parse(wire))
    unresolved = result.parsed.get("unresolved", [])
    unresolved = unresolved if isinstance(unresolved, list) else [str(unresolved)]
    if raw_issues and not issues:
        raise ValueError("TECHNICAL_BINDING_ISSUE:" + ";".join(technical))
    critique = TheoryCritique.parse({
        "critique_id": f"{backend.provider}:critique:{target.candidate_id}",
        "reviewer_provider": backend.provider, "target_candidate_id": target.candidate_id,
        "issues": [{**asdict(item), "problem_type": item.problem_type.value}
                   for item in issues],
        "unresolved": [*unresolved, *technical],
    })
    return critique, bindings


def _build_repair(case: CaseInput, parent: TheoryCandidate, critique: TheoryCritique,
                  result: ModelResult) -> tuple[TheoryCandidate | None, dict]:
    if result.parsed is None:
        raise ValueError(result.error or "model returned no parsed repair")
    sources = {item.source_id: item for item in case.sources}
    grounded_targets = {issue.target_element_id for issue in critique.issues
                        if issue.target_element_id != "__theory__" and
                        validate_link(issue.source_link, sources)[0]}
    addition_authorized = any(
        issue.target_element_id == "__theory__" and validate_link(issue.source_link, sources)[0]
        for issue in critique.issues)
    parent_map = {item.element_id: item for item in parent.elements}
    changed, rejected = {}, []
    for raw in result.parsed.get("changes", []):
        try:
            element = TheoryElement.parse(raw)
        except (TypeError, ValueError) as exc:
            rejected.append(f"INVALID_CHANGE:{exc}")
            continue
        if element.element_id not in grounded_targets or element.element_id not in parent_map:
            rejected.append(f"UNAUTHORIZED_CHANGE:{element.element_id}")
        elif not element.source_links or not all(validate_link(link, sources)[0]
                                                 for link in element.source_links):
            rejected.append(f"UNGROUNDED_CHANGE:{element.element_id}")
        else:
            changed[element.element_id] = element
    additions = []
    for raw in result.parsed.get("additions", []):
        try:
            element = TheoryElement.parse(raw)
        except (TypeError, ValueError) as exc:
            rejected.append(f"INVALID_ADDITION:{exc}")
            continue
        if (not addition_authorized or element.element_id in parent_map or
                not element.source_links or not all(
                validate_link(link, sources)[0] for link in element.source_links)):
            rejected.append(f"INVALID_OR_UNGROUNDED_ADDITION:{element.element_id}")
        else:
            additions.append(element)
    raw_changes, raw_additions = result.parsed.get("changes", []), result.parsed.get("additions", [])
    if not raw_changes and not raw_additions:
        declined = bool(critique.issues)
        return None, {"parent_candidate_id": parent.candidate_id,
                      "provider": parent.provider,
                      "status": ("REPAIR_DECLINED_WITH_ISSUES" if declined
                                 else "SKIPPED_NOT_NEEDED"), "changed_element_ids": [],
                      "added_elements": [], "retained_unchanged_element_ids": [
                          item.element_id for item in parent.elements],
                      "rejected_operations": [],
                      "unresolved": [*result.parsed.get("unresolved", []),
                                     *(["MODEL_PROPOSED_NO_CHANGE_DESPITE_GROUNDED_ISSUES"]
                                       if declined else [])]}
    if not changed and not additions:
        raise ValueError("model produced no authorized grounded repair operation")
    elements = tuple(changed.get(item.element_id, item) for item in parent.elements) + tuple(additions)
    repair_id = f"{parent.provider}:repair:{parent.candidate_id}:{_digest(result.parsed)[:12]}"
    repair = replace(parent, candidate_id=repair_id, elements=elements,
                     parent_candidate_id=parent.candidate_id)
    return repair, {
        "parent_candidate_id": parent.candidate_id,
        "provider": parent.provider,
        "changed_element_ids": sorted(changed),
        "added_elements": [{"element_id": item.element_id,
                            "marker": "MODEL_PROPOSED_ADDITION"} for item in additions],
        "retained_unchanged_element_ids": [item.element_id for item in parent.elements
                                            if item.element_id not in changed],
        "rejected_operations": rejected,
        "unresolved": result.parsed.get("unresolved", []),
        "status": "REPAIR_BUILT",
    }


def _run_metadata(backend, operation, result, started):
    source_raw, raw = result.raw_response, _redact(result.raw_response)
    return {"provider": backend.provider, "model_id": backend.model_id,
            "dependency": backend.dependency, "operation": operation,
            "status": "EXECUTED" if result.parsed is not None else "CAPABILITY_FAILURE",
            "error": _redact(result.error),
            "latency_seconds": round(time.perf_counter() - started, 6),
            "raw_response": raw,
            "source_raw_sha256": _digest(source_raw) if source_raw is not None else None,
            "raw_sha256": _digest(raw) if raw is not None else None}


def generate_case(case: CaseInput, originals: list[TheoryCandidate], *,
                  mistral: ReviewBackend, nuextract: ReviewBackend) -> dict:
    by_provider = {item.provider: item for item in originals}
    if len(originals) != 2 or set(by_provider) != {"mistral", "nuextract"}:
        raise ValueError("model runner requires one Mistral and one NuExtract original")
    backends = {"mistral": mistral, "nuextract": nuextract}
    critiques, repairs, builds, runs, failures, technical_issues = [], [], [], [], [], []
    review_bindings = []
    technical_targets = set()
    for reviewer, target_provider in (("mistral", "nuextract"),
                                      ("nuextract", "mistral")):
        backend, target = backends[reviewer], by_provider[target_provider]
        started = time.perf_counter()
        result = backend.critique(case, target)
        runs.append(_run_metadata(backend, "CRITIQUE", result, started))
        try:
            critique, bindings = _critique(case, backend, target, result)
            sources = {item.source_id: item for item in case.sources}
            if not all(validate_link(item.source_link, sources)[0] for item in critique.issues):
                raise ValueError("critique contains non-exact source quote/offset")
            critiques.append(critique)
            review_bindings.extend(bindings)
            if any(item["technical"] for item in bindings):
                runs[-1]["status"] = "EXECUTED_WITH_BINDING_ISSUES"
        except (TypeError, ValueError) as exc:
            reason = _redact(f"{type(exc).__name__}: {exc}")
            runs[-1]["status"] = ("TECHNICAL_BINDING_ISSUE"
                                  if "TECHNICAL_BINDING_ISSUE" in reason
                                  else "CAPABILITY_FAILURE")
            runs[-1]["error"] = reason
            record = {"provider": reviewer, "operation": "CRITIQUE", "reason": reason}
            if "TECHNICAL_BINDING_ISSUE" in reason:
                technical_issues.append(record)
                technical_targets.add(target.candidate_id)
            else:
                failures.append(record)
    critique_by_target = {item.target_candidate_id: item for item in critiques}
    for provider in ("mistral", "nuextract"):
        backend, parent = backends[provider], by_provider[provider]
        critique = critique_by_target.get(parent.candidate_id)
        if critique is None:
            if parent.candidate_id in technical_targets:
                technical_issues.append({"provider": provider, "operation": "REPAIR",
                                         "reason": "CROSS_CRITIQUE_BINDING_UNRESOLVED"})
                runs.append({"provider": backend.provider, "model_id": backend.model_id,
                             "dependency": backend.dependency, "operation": "REPAIR",
                             "status": "SKIPPED_BINDING_UNRESOLVED", "error": None,
                             "latency_seconds": 0.0, "raw_response": None,
                             "source_raw_sha256": None, "raw_sha256": None})
            else:
                failures.append({"provider": provider, "operation": "REPAIR",
                                 "reason": "NO_VALID_CROSS_PROVIDER_CRITIQUE"})
            continue
        if not critique.issues:
            runs.append({"provider": backend.provider, "model_id": backend.model_id,
                         "dependency": backend.dependency, "operation": "REPAIR",
                         "status": "SKIPPED_NOT_NEEDED", "error": None,
                         "latency_seconds": 0.0, "raw_response": None,
                         "source_raw_sha256": None, "raw_sha256": None})
            builds.append({"parent_candidate_id": parent.candidate_id,
                           "provider": parent.provider,
                           "status": "SKIPPED_NOT_NEEDED", "changed_element_ids": [],
                           "added_elements": [], "retained_unchanged_element_ids": [
                               item.element_id for item in parent.elements],
                           "rejected_operations": [], "unresolved": []})
            continue
        started = time.perf_counter()
        result = backend.repair(case, parent, critique)
        runs.append(_run_metadata(backend, "REPAIR", result, started))
        try:
            repair, build = _build_repair(case, parent, critique, result)
            builds.append(build)
            if repair is None:
                runs[-1]["status"] = build["status"]
                if build["status"] == "REPAIR_DECLINED_WITH_ISSUES":
                    failures.append({"provider": provider, "operation": "REPAIR",
                                     "reason": "MODEL_PROPOSED_NO_CHANGE_DESPITE_GROUNDED_ISSUES"})
            else:
                repairs.append(repair)
        except (TypeError, ValueError) as exc:
            reason = _redact(f"{type(exc).__name__}: {exc}")
            runs[-1]["status"] = "CAPABILITY_FAILURE"
            runs[-1]["error"] = reason
            failures.append({"provider": provider, "operation": "REPAIR",
                             "reason": reason})
    reviews_complete = len(critiques) == 2
    return {"case_id": case.case_id, "critiques": critiques, "repairs": repairs,
            "repair_builds": builds, "model_runs": runs,
            "critique_binding_results": review_bindings,
            "technical_issues": technical_issues,
            "capability_failures": failures,
            "cycle_generation_status": ("BIDIRECTIONAL_COMPLETE" if reviews_complete and
                                        all(item["status"] in {"REPAIR_BUILT",
                                            "SKIPPED_NOT_NEEDED"} for item in builds)
                                        and len(builds) == 2 else
                                        "ONE_SIDED_OR_UNRESOLVED")}


def _wire(value):
    if isinstance(value, (TheoryCandidate, TheoryCritique)):
        return asdict(value)
    raise TypeError(type(value).__name__)


def run_cli(args, *, mistral=None, nuextract=None) -> int:
    input_path = Path(args.input).resolve(strict=True)
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    cases = [CaseInput.parse(row) for row in _rows(input_path)]
    if not 3 <= len(cases) <= 5:
        raise ValueError("B3 model pilot requires 3 to 5 cases")
    if len({case.case_id for case in cases}) != len(cases):
        raise ValueError("duplicate case_id in B3 model pilot")
    originals, hashes = _candidate_map(args.original_output)
    if set(originals) - {case.case_id for case in cases}:
        raise ValueError("original output contains unknown case_id")
    if mistral is None:
        mistral = MistralReviewBackend(args.mistral_model, args.api_key_env)
    if nuextract is None:
        nuextract = NuExtractReviewBackend.load(args.nuextract_model, args.device)
    fingerprint = _digest({"input": _sha(input_path), "originals": hashes,
                           "mistral_model": mistral.model_id,
                           "nuextract_model": nuextract.model_id})
    all_path = output_dir / "model_cycle.jsonl"
    existing = _rows(all_path) if all_path.exists() else []
    if any(row.get("run_fingerprint") != fingerprint for row in existing):
        raise ValueError("resume fingerprint differs from existing run")
    completed = {row["case_id"] for row in existing}
    with all_path.open("a", encoding="utf-8", newline="\n") as destination:
        for case in cases:
            if case.case_id in completed:
                continue
            generated = generate_case(case, originals.get(case.case_id, []),
                                      mistral=mistral, nuextract=nuextract)
            row = {**generated, "critiques": [_wire(item) for item in generated["critiques"]],
                   "repairs": [_wire(item) for item in generated["repairs"]],
                   "run_fingerprint": fingerprint}
            destination.write(json.dumps(row, ensure_ascii=False, sort_keys=True,
                                         default=lambda value: value.value) + "\n")
            destination.flush()
    rows = _rows(all_path)
    critique_rows, repair_rows = [], {"mistral": [], "nuextract": []}
    for row in rows:
        raw_by_operation = {}
        for run in row["model_runs"]:
            raw_by_operation.setdefault(run["operation"], []).append(run)
        critique_rows.append({"case_id": row["case_id"], "critiques": row["critiques"],
                              "raw_responses": raw_by_operation.get("CRITIQUE", []),
                              "technical_issues": row.get("technical_issues", []),
                              "capability_failures": row["capability_failures"]})
        for provider in repair_rows:
            candidates = [item for item in row["repairs"] if item["provider"] == provider]
            repair_rows[provider].append({
                "case_id": row["case_id"], "candidates": candidates,
                "raw_responses": [item for item in raw_by_operation.get("REPAIR", [])
                                  if item["provider"] == provider],
                "repair_builds": [item for item in row["repair_builds"]
                                  if item.get("provider") == provider],
            })
    for path, rows_to_write in ((output_dir / "critiques.jsonl", critique_rows),
                                (output_dir / "mistral_repairs.jsonl", repair_rows["mistral"]),
                                (output_dir / "nuextract_repairs.jsonl", repair_rows["nuextract"])):
        path.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
                                for row in rows_to_write), encoding="utf-8")
    return 0


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    parser.add_argument("--original-output", action="append", required=True,
                        metavar="PROVIDER=PATH")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--mistral-model", default="ministral-14b-latest")
    parser.add_argument("--nuextract-model", default="numind/NuExtract3-W4A16")
    parser.add_argument("--api-key-env", default="MISTRAL_API_KEY")
    parser.add_argument("--device", default="cuda")
    return parser.parse_args(argv)


if __name__ == "__main__":
    try:
        raise SystemExit(run_cli(parse_args()))
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(f"b3_model_runner: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(2)
