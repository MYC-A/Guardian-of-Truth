"""Bounded, label-blind execution of frozen external evaluations.

This module deliberately keeps selection, detector execution, and label joining
as three separate phases.  The detector receives only the adapter's
``model_view`` plus a deterministic Guardian prompt/response rendering.  Native
labels are accessed only after every detector prediction has been hashed.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Mapping, Sequence

from .external_adapters import (
    ExternalAdapterError,
    ExternalCase,
    adapt_atfd_tau_document,
    adapt_bfcl,
    adapt_tau_bench,
    external_readiness,
    inspect_toolsandbox_tool_source,
)
from .statistics import binary_metrics


class ExternalEvaluationError(RuntimeError):
    """The frozen external run cannot continue without weakening its contract."""


@dataclass(frozen=True)
class BlindDetectorInput:
    """The complete and exclusive payload crossing the detector boundary."""

    model_view: dict[str, Any]
    prompt: str
    response: str


Detector = Callable[[BlindDetectorInput], int]
ReadinessChecker = Callable[..., Mapping[str, Any]]
TextReader = Callable[[Path], str]


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def render_guardian_input(model_view: Mapping[str, Any]) -> tuple[str, str]:
    """Render an adapter model view without introducing benchmark labels.

    The last native assistant event is rendered as the response.  Everything
    else, including policy context and tool schemas, remains in the prompt.  A
    diagnostic case without an assistant event has an empty response document.
    """
    view = deepcopy(dict(model_view))
    events = view.get("events", [])
    if not isinstance(events, list):
        raise ExternalEvaluationError("model_view.events must be an array")
    response_index: int | None = None
    for index, event in enumerate(events):
        if not isinstance(event, Mapping):
            raise ExternalEvaluationError("model_view.events entries must be objects")
        if event.get("role") == "assistant" or event.get("type") == "assistant_message":
            response_index = index
    if response_index is None:
        raise ExternalEvaluationError("end-to-end case has no assistant response")
    if response_index != len(events) - 1:
        raise ExternalEvaluationError("native events after selected assistant response are unsupported")

    def content(event: Mapping[str, Any]) -> str:
        value = event.get("content", "")
        return value if isinstance(value, str) else _canonical_json(value)

    context = view.get("context", {})
    context = context if isinstance(context, Mapping) else {}
    policy = context.get("policy")
    if not isinstance(policy, str) or not policy.strip():
        system_parts = [content(event) for event in events
                        if event.get("role") == "system" or event.get("type") == "system"]
        policy = "\n\n".join(part for part in system_parts if part.strip())
    if not policy.strip():
        raise ExternalEvaluationError("end-to-end case has no policy text")

    parts = [f"⟦SYSTEM⟧\n<policy>{policy}</policy>"]
    schemas = view.get("tool_schemas", [])
    if schemas:
        parts.append("[AVAILABLE TOOLS]\n" + _canonical_json(schemas) + "\n[/AVAILABLE TOOLS]")
    role_tags = {
        "user": "USER", "user_message": "USER",
        "assistant": "ASSISTANT", "assistant_message": "ASSISTANT",
        "tool": "TOOL", "tool_call": "ASSISTANT", "tool_result": "TOOL",
    }
    for event in events[:response_index]:
        role = event.get("role") or event.get("type")
        if role == "system":
            continue
        tag = role_tags.get(str(role))
        if tag is None:
            raise ExternalEvaluationError(f"unsupported native event role/type: {role}")
        event_content = content(event)
        residual = {key: value for key, value in event.items()
                    if key not in {"role", "type", "content"}}
        if residual:
            event_content = event_content + ("\n" if event_content else "") + _canonical_json(residual)
        parts.append(f"⟦{tag}⟧\n{event_content}")
    response_event = events[response_index]
    response = content(response_event)
    residual = {key: value for key, value in response_event.items()
                if key not in {"role", "type", "content"}}
    if residual:
        response = response + ("\n" if response else "") + _canonical_json(residual)
    if not response.strip():
        raise ExternalEvaluationError("selected assistant response is empty")
    return "\n".join(parts), response


def _safe_path(root: Path, relative_text: str) -> Path:
    relative = PurePosixPath(relative_text)
    if relative.is_absolute() or ".." in relative.parts:
        raise ExternalEvaluationError(f"unsafe selected path: {relative_text}")
    resolved_root = root.resolve()
    candidate = (resolved_root / Path(*relative.parts)).resolve()
    try:
        candidate.relative_to(resolved_root)
    except ValueError as exc:
        raise ExternalEvaluationError(f"selected path escapes source root: {relative_text}") from exc
    return candidate


def _json_document(text: str, artifact_path: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ExternalEvaluationError(f"invalid JSON artifact: {artifact_path}") from exc


def _json_rows(text: str, artifact_path: str) -> list[Mapping[str, Any]]:
    try:
        loaded = json.loads(text)
    except json.JSONDecodeError:
        loaded = None
    if isinstance(loaded, list):
        rows: Sequence[Any] = loaded
    elif isinstance(loaded, Mapping):
        rows = [loaded]
    else:
        try:
            rows = [json.loads(line) for line in text.splitlines() if line.strip()]
        except json.JSONDecodeError as exc:
            raise ExternalEvaluationError(f"invalid JSON/JSONL artifact: {artifact_path}") from exc
    result: list[Mapping[str, Any]] = []
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise ExternalEvaluationError(f"{artifact_path} row {index} is not an object")
        result.append(row)
    return result


def _ordered_groups(
    records: Sequence[Mapping[str, Any]], *, group_field: str, group_limit: int
) -> list[Mapping[str, Any]]:
    """Select only by group id, then use non-label identifiers for stable order."""
    groups: dict[str, list[Mapping[str, Any]]] = {}
    for record in records:
        group = record.get(group_field)
        if not isinstance(group, (str, int)) or isinstance(group, bool):
            raise ExternalEvaluationError(f"selection field {group_field} is invalid")
        groups.setdefault(str(group), []).append(record)
    selected_groups = sorted(groups)[:group_limit]

    def tie_key(record: Mapping[str, Any]) -> tuple[str, str]:
        # These are identifiers only; rewards, outcomes, categories and text are
        # intentionally absent from the selection key.
        return str(record.get("trial", "")), str(record.get("id", ""))

    return [record for group in selected_groups for record in sorted(groups[group], key=tie_key)]


def _entry_files(entry: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    files = entry.get("selected_files", [])
    if not isinstance(files, list):
        raise ExternalEvaluationError("selected_files must be an array")
    checked = []
    for item in files:
        if not isinstance(item, Mapping) or not isinstance(item.get("path"), str):
            raise ExternalEvaluationError("selected_files entry is invalid")
        checked.append(item)
    return sorted(checked, key=lambda item: item["path"])


def _load_end_to_end_cases(
    entry: Mapping[str, Any], root: Path, read_text: TextReader
) -> tuple[list[ExternalCase], list[dict[str, Any]]]:
    name = entry.get("name")
    cases: list[ExternalCase] = []
    audit: list[dict[str, Any]] = []
    if name == "ATFD":
        for item in _entry_files(entry):
            path = _safe_path(root, item["path"])
            document = _json_document(read_text(path), item["path"])
            if not isinstance(document, Mapping) or not isinstance(document.get("simulations"), list):
                raise ExternalEvaluationError("selected ATFD artifact is not a tau-family document")
            simulations = _ordered_groups(
                document["simulations"], group_field="task_id", group_limit=4
            )
            selected_document = dict(document)
            selected_document["simulations"] = simulations
            adapted = list(adapt_atfd_tau_document(selected_document, artifact_path=item["path"]))
            cases.extend(adapted)
            audit.append({
                "artifact_path": item["path"],
                "selected_group_ids": sorted({str(row["task_id"]) for row in simulations}),
                "selected_records": len(simulations),
            })
        budget = entry.get("sample_budget")
        if type(budget) is not int or len(cases) > budget:
            raise ExternalEvaluationError("ATFD selected trajectory count exceeds frozen budget")
    elif name == "tau-bench":
        selected_groups_total = 0
        for item in _entry_files(entry):
            path = _safe_path(root, item["path"])
            rows = _json_rows(read_text(path), item["path"])
            selected = _ordered_groups(rows, group_field="task_id", group_limit=12)
            group_ids = sorted({str(row["task_id"]) for row in selected})
            selected_groups_total += len(group_ids)
            adapted = [adapt_tau_bench(row, artifact_path=item["path"]) for row in selected]
            cases.extend(adapted)
            audit.append({
                "artifact_path": item["path"],
                "selected_group_ids": group_ids,
                "selected_records": len(selected),
            })
        budget = entry.get("sample_budget")
        if type(budget) is not int or selected_groups_total > budget:
            raise ExternalEvaluationError("tau-bench selected group count exceeds frozen budget")
    else:
        raise ExternalEvaluationError(f"unsupported end-to-end source: {name}")
    return cases, audit


def _toolsandbox_diagnostic(
    entry: Mapping[str, Any], root: Path, read_text: TextReader
) -> dict[str, Any]:
    discovered = []
    artifacts = 0
    for item in _entry_files(entry):
        diagnostic = inspect_toolsandbox_tool_source(
            read_text(_safe_path(root, item["path"])), artifact_path=item["path"]
        )
        artifacts += 1
        for function in diagnostic.functions:
            discovered.append((diagnostic.artifact_path, function))
    discovered.sort(key=lambda pair: (pair[0], pair[1]["name"]))
    budget = entry.get("sample_budget")
    if type(budget) is not int or budget < 1:
        raise ExternalEvaluationError("ToolSandbox diagnostic budget is invalid")
    evaluated = discovered[:budget]
    return {
        "source": "ToolSandbox",
        "evaluation_scope": "TOOL_SCHEMA_OOD_ONLY",
        "guardian_label_equivalence": False,
        "labels_available": False,
        "static_only": True,
        "modules": artifacts,
        "registered_functions_discovered": len(discovered),
        "registered_functions_evaluated": len(evaluated),
        "functions_with_docstrings": sum(
            pair[1]["docstring_sha256"] != hashlib.sha256(b"").hexdigest() for pair in evaluated
        ),
        "functions_with_arguments": sum(bool(pair[1]["arguments"]) for pair in evaluated),
    }


def _bfcl_diagnostic(
    entry: Mapping[str, Any], root: Path, read_text: TextReader
) -> tuple[dict[str, Any], list[ExternalCase]]:
    cases: list[ExternalCase] = []
    per_file = []
    for item in _entry_files(entry):
        rows = _json_rows(read_text(_safe_path(root, item["path"])), item["path"])
        if any(not isinstance(row.get("id"), str) for row in rows):
            raise ExternalEvaluationError("BFCL selection id must be text")
        selected = sorted(rows, key=lambda row: row["id"])[:10]
        adapted = [adapt_bfcl(row, artifact_path=item["path"]) for row in selected]
        cases.extend(adapted)
        per_file.append({"artifact_path": item["path"], "selected_rows": len(adapted)})
    budget = entry.get("sample_budget")
    if type(budget) is not int or len(cases) > budget:
        raise ExternalEvaluationError("BFCL selected row count exceeds frozen budget")
    schemas = [schema for case in cases for schema in case.tool_schemas]
    parameter_properties = 0
    required_parameters = 0
    for schema in schemas:
        parameters = schema.get("parameters", {})
        if isinstance(parameters, Mapping):
            properties = parameters.get("properties", {})
            required = parameters.get("required", [])
            parameter_properties += len(properties) if isinstance(properties, Mapping) else 0
            required_parameters += len(required) if isinstance(required, list) else 0
    return ({
        "source": "BFCL",
        "evaluation_scope": "TOOL_SCHEMA_OOD_ONLY",
        "guardian_label_equivalence": False,
        "labels_available": False,
        "rows_evaluated": len(cases),
        "function_schemas": len(schemas),
        "parameter_properties": parameter_properties,
        "required_parameters": required_parameters,
        "per_file": per_file,
    }, cases)


def _run_detectors_blind(
    cases: Sequence[ExternalCase], detectors: Mapping[str, Detector]
) -> tuple[list[dict[str, Any]], str]:
    predictions: list[dict[str, Any]] = []
    for detector_name in sorted(detectors):
        detector = detectors[detector_name]
        for case_index, case in enumerate(cases):
            model_view = case.model_view()
            prompt, response = render_guardian_input(model_view)
            detector_input = BlindDetectorInput(deepcopy(model_view), prompt, response)
            try:
                prediction = detector(detector_input)
            except Exception as exc:  # callback failures cannot become abstentions silently
                raise ExternalEvaluationError(
                    f"detector {detector_name!r} failed for {case.record_id}"
                ) from exc
            if type(prediction) is not int or prediction not in (0, 1):
                raise ExternalEvaluationError(
                    f"detector {detector_name!r} returned a non-binary prediction"
                )
            predictions.append({
                "detector": detector_name,
                "case_index": case_index,
                "source": model_view["source"],
                "record_id": model_view["record_id"],
                "prediction": prediction,
                "model_view_sha256": _sha256_json(model_view),
                "rendered_input_sha256": _sha256_json(
                    {"prompt": prompt, "response": response}
                ),
            })
    return predictions, _sha256_json(predictions)


def _join_labels_and_score(
    cases: Sequence[ExternalCase], predictions: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    rows_by_detector: dict[str, list[dict[str, Any]]] = {}
    for prediction in predictions:
        case_index = prediction.get("case_index")
        if type(case_index) is not int or not 0 <= case_index < len(cases):
            raise ExternalEvaluationError("prediction case index is invalid")
        case = cases[case_index]
        if (prediction.get("source"), prediction.get("record_id")) != (
            case.source, case.record_id
        ):
            raise ExternalEvaluationError("prediction identity differs from frozen case")
        harness = case.harness_view()  # first label access in the execution path
        rows_by_detector.setdefault(str(prediction["detector"]), []).append({
            **dict(prediction),
            "group_id": case.group_id,
            "evaluation_scope": case.evaluation_scope,
            **harness,
        })
    reports = {}
    for detector_name, rows in rows_by_detector.items():
        trajectory = [
            row for row in rows
            if row["evaluation_scope"] == "END_TO_END_TRAJECTORY" and row["label"] in (0, 1)
        ]
        labels = [int(row["label"]) for row in trajectory]
        values = [int(row["prediction"]) for row in trajectory]
        reports[detector_name] = {
            "trajectory_proxy_metrics": binary_metrics(labels, values),
            "metric_semantics": "trajectory_outcome_proxy_not_guardian_turn_localized",
            "guardian_localized_label_equivalence": False,
            "limitations": [
                "A trajectory reward/outcome cannot identify which response turn violated policy.",
                "These metrics must not be pooled with Guardian turn-localized test metrics.",
            ],
        }
    return reports


def run_external_evaluation(
    manifest: Mapping[str, Any],
    *,
    source_roots: Mapping[str, Path],
    detectors: Mapping[str, Detector],
    readiness_checker: ReadinessChecker = external_readiness,
    read_text: TextReader | None = None,
) -> dict[str, Any]:
    """Execute one bounded frozen run, or return before any dataset parsing.

    ``readiness_checker`` and ``read_text`` are injectable for contract tests.
    Production callers should use the defaults.
    """
    readiness = dict(readiness_checker(manifest, source_roots=source_roots))
    if not readiness.get("safe_to_run_blind"):
        return {
            "schema_version": "guardian-next-external-evaluation-v1",
            "status": "blocked_not_ready",
            "blind_evaluation_executed": False,
            "readiness": readiness,
            "prediction_freeze": None,
            "labels_joined": False,
        }

    reader = read_text or (lambda path: path.read_text(encoding="utf-8"))
    cases: list[ExternalCase] = []
    selection_audit: dict[str, Any] = {}
    diagnostics: dict[str, Any] = {}
    unavailable: dict[str, Any] = {}
    for entry in manifest.get("sources", []):
        if not isinstance(entry, Mapping):
            raise ExternalEvaluationError("manifest sources entries must be objects")
        name = str(entry.get("name"))
        disposition = entry.get("run_disposition")
        if disposition == "documented_unavailable":
            unavailable[name] = {
                "status": "documented_unavailable",
                "executed": False,
                "reason": "pinned repository has no frozen recorded evaluation artifact",
            }
            continue
        if name not in source_roots:
            raise ExternalEvaluationError(f"missing verified source root: {name}")
        if disposition == "included_end_to_end":
            loaded, audit = _load_end_to_end_cases(entry, source_roots[name], reader)
            cases.extend(loaded)
            selection_audit[name] = audit
        elif disposition == "included_diagnostic" and name == "ToolSandbox":
            diagnostics[name] = _toolsandbox_diagnostic(entry, source_roots[name], reader)
        elif disposition == "included_diagnostic" and name == "BFCL":
            diagnostics[name], _ = _bfcl_diagnostic(entry, source_roots[name], reader)
        else:
            raise ExternalEvaluationError(f"unsupported source disposition: {name}/{disposition}")

    # Freeze every prediction before calling harness_view on any case.
    predictions, prediction_sha256 = _run_detectors_blind(cases, detectors)
    prediction_freeze = {
        "sha256": prediction_sha256,
        "records": len(predictions),
        "frozen_before_label_join": True,
    }
    detector_reports = _join_labels_and_score(cases, predictions)
    return {
        "schema_version": "guardian-next-external-evaluation-v1",
        "status": "completed",
        "blind_evaluation_executed": True,
        "readiness": readiness,
        "selection_audit": selection_audit,
        "prediction_freeze": prediction_freeze,
        "labels_joined": True,
        "labels_joined_after_prediction_freeze": True,
        "detectors": detector_reports,
        "diagnostics": diagnostics,
        "unavailable_sources": unavailable,
    }
