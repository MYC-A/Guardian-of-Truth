"""Fail-closed, format-only adapters for frozen external benchmark artifacts.

The adapters in this module do not run a model, execute tools, select examples,
or repair source data.  They only validate documented native shapes and split a
record into a label-blind model view and a harness-only label view.  A source
can be schema-ready while still being blocked from the first blind run because
its exact file subset and hashes have not been frozen.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
import ast
import hashlib
import json
from pathlib import Path
from pathlib import PurePosixPath
import re
import subprocess
from typing import Any, Callable, Mapping, Sequence


PINNED_SOURCES = {
    "ATFD": {
        "repository": "https://github.com/Galea-foo/atfd",
        "commit": "690c9962155865b3b17333bbb9354c15d3eb4170",
    },
    "tau-bench": {
        "repository": "https://github.com/sierra-research/tau-bench",
        "commit": "59a200c6d575d595120f1cb70fea53cef0632f6b",
    },
    "AgentDojo": {
        "repository": "https://github.com/sequrity-ai/agentdojo",
        "commit": "357c80dea9af34323f709c3505d9e6d224654c7e",
    },
    "ToolSandbox": {
        "repository": "https://github.com/apple/ToolSandbox",
        "commit": "c8571d7854316d2e1c5f288e59fe1e34e53f6dd1",
    },
    "BFCL": {
        "repository": "https://github.com/ShishirPatil/gorilla",
        "commit": "6ea57973c7a6097fd7c5915698c54c17c5b1b6c8",
    },
}

_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")


class ExternalAdapterError(ValueError):
    """The native record cannot be adapted without guessing or repair."""


@dataclass(frozen=True)
class ExternalCase:
    source: str
    source_revision: str
    record_id: str
    group_id: str
    benchmark_class: str
    evaluation_scope: str
    native_events: tuple[dict[str, Any], ...]
    tool_schemas: tuple[dict[str, Any], ...]
    native_context: dict[str, Any]
    label: int | None
    label_provenance: str | None
    target_event_indices: tuple[int, ...]
    failure_categories: tuple[str, ...]
    raw_record_sha256: str
    limitations: tuple[str, ...] = ()

    def model_view(self) -> dict[str, Any]:
        """Return the only fields allowed to cross the detector boundary."""
        return {
            "source": self.source,
            "record_id": self.record_id,
            "events": deepcopy(list(self.native_events)),
            "tool_schemas": deepcopy(list(self.tool_schemas)),
            "context": deepcopy(self.native_context),
        }

    def harness_view(self) -> dict[str, Any]:
        """Return labels and provenance only after prediction is frozen."""
        return {
            "label": self.label,
            "label_provenance": self.label_provenance,
            "target_event_indices": list(self.target_event_indices),
            "failure_categories": list(self.failure_categories),
        }

    def to_audit_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ToolSchemaDiagnostic:
    source: str
    source_revision: str
    artifact_path: str
    source_sha256: str
    functions: tuple[dict[str, Any], ...]
    evaluation_scope: str = "TOOL_SCHEMA_OOD_ONLY"
    label: None = None


def _require_mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ExternalAdapterError(f"{field} must be an object")
    return value


def _require_sequence(value: Any, field: str) -> Sequence[Any]:
    if not isinstance(value, (list, tuple)):
        raise ExternalAdapterError(f"{field} must be an array")
    return value


def _require_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ExternalAdapterError(f"{field} must be a non-empty string")
    return value


def _canonical_hash(record: Mapping[str, Any]) -> str:
    try:
        payload = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise ExternalAdapterError("record must be JSON serialisable") from exc
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _copy_event_dicts(events: Any, field: str) -> tuple[dict[str, Any], ...]:
    result = []
    for index, event in enumerate(_require_sequence(events, field)):
        result.append(deepcopy(dict(_require_mapping(event, f"{field}[{index}]"))))
    if not result:
        raise ExternalAdapterError(f"{field} must not be empty")
    return tuple(result)


def adapt_atfd(record: Mapping[str, Any], *, artifact_path: str) -> ExternalCase:
    """Adapt one ATFD trajectory without exposing ``ground_truth`` to a model."""
    record = _require_mapping(record, "record")
    record_id = _require_text(record.get("trajectory_id"), "trajectory_id")
    events = _copy_event_dicts(record.get("events"), "events")
    allowed_types = {"system", "user_message", "assistant_message", "tool_call", "tool_result"}
    for index, event in enumerate(events):
        if event.get("type") not in allowed_types:
            raise ExternalAdapterError(f"events[{index}].type is unsupported")
        if "content" not in event:
            raise ExternalAdapterError(f"events[{index}].content is missing")

    truth = _require_mapping(record.get("ground_truth"), "ground_truth")
    outcome = truth.get("outcome")
    if outcome not in {"pass", "fail"}:
        raise ExternalAdapterError("ground_truth.outcome must be pass or fail")
    targets_raw = _require_sequence(record.get("failure_event_indices", []), "failure_event_indices")
    if any(type(index) is not int or not 0 <= index < len(events) for index in targets_raw):
        raise ExternalAdapterError("failure_event_indices must reference native events")
    targets = tuple(targets_raw)
    if outcome == "fail" and not targets:
        raise ExternalAdapterError("failing ATFD record is not turn-localizable")
    categories_raw = _require_sequence(truth.get("failure_categories", []), "failure_categories")
    if any(not isinstance(value, str) or not value for value in categories_raw):
        raise ExternalAdapterError("failure_categories must contain non-empty strings")

    normalized_path = artifact_path.replace("\\", "/")
    benchmark_class = "SOURCE_SYNTHETIC" if "/synthetic/" in f"/{normalized_path}" else "EXTERNAL_SAME_FAMILY"
    return ExternalCase(
        source="ATFD",
        source_revision=PINNED_SOURCES["ATFD"]["commit"],
        record_id=record_id,
        group_id=f"atfd:{record_id}",
        benchmark_class=benchmark_class,
        evaluation_scope="END_TO_END_LOCALIZED",
        native_events=events,
        tool_schemas=(),
        native_context={"domain": deepcopy(record.get("domain"))},
        label=int(outcome == "fail"),
        label_provenance="ground_truth.outcome",
        target_event_indices=targets,
        failure_categories=tuple(categories_raw),
        raw_record_sha256=_canonical_hash(record),
    )


def adapt_atfd_tau_document(record: Mapping[str, Any], *, artifact_path: str) -> tuple[ExternalCase, ...]:
    """Adapt the recorded tau-family simulations bundled in pinned ATFD.

    This follows ATFD's own pinned ``TauBenchAdapter`` label mapping while
    preserving native messages instead of ATFD's timestamp/argument rewrites.
    The document-level policy remains context and is never inserted as a
    fabricated trace event.
    """
    record = _require_mapping(record, "record")
    info = _require_mapping(record.get("info"), "info")
    environment = _require_mapping(info.get("environment_info"), "info.environment_info")
    policy = _require_text(environment.get("policy"), "info.environment_info.policy")
    domain = _require_text(environment.get("domain_name"), "info.environment_info.domain_name")
    simulations = _require_sequence(record.get("simulations"), "simulations")
    if not simulations:
        raise ExternalAdapterError("simulations must not be empty")
    cases: list[ExternalCase] = []
    infrastructure = {
        "AGENT_ERROR": "infrastructure.error",
        "INFRASTRUCTURE_ERROR": "infrastructure.error",
        "UNEXPECTED_ERROR": "infrastructure.error",
        "TOO_MANY_ERRORS": "infrastructure.error",
        "MAX_STEPS": "infrastructure.max_steps",
        "TIMEOUT": "infrastructure.timeout",
    }
    for index, raw_simulation in enumerate(simulations):
        simulation = _require_mapping(raw_simulation, f"simulations[{index}]")
        simulation_id = _require_text(simulation.get("id"), f"simulations[{index}].id")
        task_id = simulation.get("task_id")
        if not isinstance(task_id, (str, int)) or isinstance(task_id, bool):
            raise ExternalAdapterError(f"simulations[{index}].task_id is invalid")
        trial = simulation.get("trial", 0)
        if not isinstance(trial, (str, int)) or isinstance(trial, bool):
            raise ExternalAdapterError(f"simulations[{index}].trial is invalid")
        events = _copy_event_dicts(simulation.get("messages"), f"simulations[{index}].messages")
        for message_index, event in enumerate(events):
            if event.get("role") not in {"system", "user", "assistant", "tool"}:
                raise ExternalAdapterError(
                    f"simulations[{index}].messages[{message_index}].role is unsupported"
                )
            if "content" not in event:
                raise ExternalAdapterError(
                    f"simulations[{index}].messages[{message_index}].content is missing"
                )
        reward_info = _require_mapping(
            simulation.get("reward_info"), f"simulations[{index}].reward_info"
        )
        reward = reward_info.get("reward", 1.0)
        if type(reward) not in {int, float} or not 0.0 <= float(reward) <= 1.0:
            raise ExternalAdapterError(f"simulations[{index}] reward is outside [0, 1]")
        breakdown = _require_mapping(
            reward_info.get("reward_breakdown", {}),
            f"simulations[{index}].reward_info.reward_breakdown",
        )
        categories: list[str] = []
        for component, category in (
            ("DB", "state.wrong_state"),
            ("ACTION", "action.wrong_tool"),
            ("COMMUNICATE", "communication.missing_info"),
        ):
            score = breakdown.get(component, 1.0)
            if type(score) not in {int, float}:
                raise ExternalAdapterError(f"simulations[{index}] {component} score is not numeric")
            if float(score) < 1.0:
                categories.append(category)
        termination = simulation.get("termination_reason", "AGENT_STOP")
        if not isinstance(termination, str):
            raise ExternalAdapterError(f"simulations[{index}].termination_reason is invalid")
        if termination in infrastructure:
            categories.append(infrastructure[termination])
        label = int(float(reward) < 1.0 or termination in infrastructure)
        cases.append(ExternalCase(
            source="ATFD",
            source_revision=PINNED_SOURCES["ATFD"]["commit"],
            record_id=f"tau_{simulation_id}",
            group_id=f"atfd:tau:{domain}:{task_id}",
            benchmark_class="EXTERNAL_SAME_FAMILY",
            evaluation_scope="END_TO_END_TRAJECTORY",
            native_events=events,
            tool_schemas=(),
            native_context={"policy": policy, "domain": domain},
            label=label,
            label_provenance="pinned ATFD TauBenchAdapter reward/termination mapping",
            target_event_indices=(),
            failure_categories=tuple(dict.fromkeys(categories)),
            raw_record_sha256=_canonical_hash({"simulation": simulation, "policy": policy}),
            limitations=("ATFD tau-family ground truth is trajectory-level and does not localize a turn.",),
        ))
    return tuple(cases)


def adapt_tau_bench(record: Mapping[str, Any], *, artifact_path: str) -> ExternalCase:
    """Adapt a historical tau-bench row; only binary rewards are accepted."""
    record = _require_mapping(record, "record")
    task_id = record.get("task_id")
    if not isinstance(task_id, (str, int)) or isinstance(task_id, bool):
        raise ExternalAdapterError("task_id must be a string or integer")
    reward = record.get("reward")
    if type(reward) not in {int, float} or float(reward) not in {0.0, 1.0}:
        raise ExternalAdapterError("reward must be exactly 0 or 1")
    events = _copy_event_dicts(record.get("traj"), "traj")
    for index, event in enumerate(events):
        if event.get("role") not in {"system", "user", "assistant", "tool"}:
            raise ExternalAdapterError(f"traj[{index}].role is unsupported")
        if "content" not in event:
            raise ExternalAdapterError(f"traj[{index}].content is missing")
    trial = record.get("trial", 0)
    if not isinstance(trial, (str, int)) or isinstance(trial, bool):
        raise ExternalAdapterError("trial must be a string or integer")
    return ExternalCase(
        source="tau-bench",
        source_revision=PINNED_SOURCES["tau-bench"]["commit"],
        record_id=f"{artifact_path}:{task_id}:{trial}",
        group_id=f"tau-bench:{artifact_path}:{task_id}",
        benchmark_class="EXTERNAL_SAME_FAMILY",
        evaluation_scope="END_TO_END_TRAJECTORY",
        native_events=events,
        tool_schemas=(),
        native_context={},
        label=int(float(reward) < 1.0),
        label_provenance="reward==1 pass; reward==0 fail",
        target_event_indices=(),
        failure_categories=(),
        raw_record_sha256=_canonical_hash(record),
        limitations=("Historical reward is trajectory-level and does not localize the failure turn.",),
    )


def _nested_strings(value: Any) -> tuple[str, ...]:
    strings: list[str] = []
    if isinstance(value, str) and value:
        strings.append(value)
    elif isinstance(value, Mapping):
        for nested in value.values():
            strings.extend(_nested_strings(nested))
    elif isinstance(value, (list, tuple)):
        for nested in value:
            strings.extend(_nested_strings(nested))
    return tuple(strings)


def adapt_agentdojo(record: Mapping[str, Any], *, artifact_path: str) -> ExternalCase:
    """Adapt only localizable AgentDojo prompt-injection security traces."""
    record = _require_mapping(record, "record")
    if record.get("error") not in {None, ""}:
        raise ExternalAdapterError("AgentDojo infrastructure/model error is not an agent-policy label")
    security = record.get("security")
    utility = record.get("utility")
    if type(security) is not bool or type(utility) is not bool:
        raise ExternalAdapterError("utility and security must be booleans")
    if not record.get("attack_type") or not record.get("injection_task_id"):
        raise ExternalAdapterError("only injected security runs are supported")
    events = _copy_event_dicts(record.get("messages"), "messages")
    for index, event in enumerate(events):
        if event.get("role") not in {"system", "user", "assistant", "tool"}:
            raise ExternalAdapterError(f"messages[{index}].role is unsupported")
        if "content" not in event:
            raise ExternalAdapterError(f"messages[{index}].content is missing")
    injection_strings = _nested_strings(_require_mapping(record.get("injections"), "injections"))
    if not injection_strings:
        raise ExternalAdapterError("injections contain no localizable text")
    target_indices = tuple(
        index for index, event in enumerate(events)
        if event.get("role") == "tool"
        and isinstance(event.get("content"), str)
        and any(text in event["content"] for text in injection_strings)
    )
    if not target_indices:
        raise ExternalAdapterError("injected span is not present verbatim in a tool result")
    suite = _require_text(record.get("suite_name"), "suite_name")
    user_task = _require_text(record.get("user_task_id"), "user_task_id")
    injection_task = _require_text(record.get("injection_task_id"), "injection_task_id")
    return ExternalCase(
        source="AgentDojo",
        source_revision=PINNED_SOURCES["AgentDojo"]["commit"],
        record_id=f"{artifact_path}:{suite}:{user_task}:{injection_task}",
        group_id=f"agentdojo:{suite}:{user_task}",
        benchmark_class="EXTERNAL_INDEPENDENT",
        evaluation_scope="SECURITY_LOCALIZED",
        native_events=events,
        tool_schemas=(),
        native_context={},
        label=int(not security),
        label_provenance="security false means injection succeeded",
        target_event_indices=target_indices,
        failure_categories=("safety.prompt_injection",) if not security else (),
        raw_record_sha256=_canonical_hash(record),
        limitations=("Utility failures are excluded; this adapter evaluates injection security only.",),
    )


def adapt_toolsandbox(record: Mapping[str, Any], *, artifact_path: str) -> ExternalCase:
    """Preserve a ToolSandbox ``conversation.json`` for OOD schema diagnostics."""
    record = _require_mapping(record, "record")
    events = _copy_event_dicts(record.get("messages"), "messages")
    for index, event in enumerate(events):
        if event.get("role") not in {"system", "user", "assistant", "tool"}:
            raise ExternalAdapterError(f"messages[{index}].role is unsupported")
    schemas = _copy_event_dicts(record.get("tools"), "tools")
    user_tools_raw = record.get("user_tools", [])
    user_tools = tuple(
        deepcopy(dict(_require_mapping(item, "user_tools[]")))
        for item in _require_sequence(user_tools_raw, "user_tools")
    )
    return ExternalCase(
        source="ToolSandbox",
        source_revision=PINNED_SOURCES["ToolSandbox"]["commit"],
        record_id=artifact_path,
        group_id=f"toolsandbox:{artifact_path}",
        benchmark_class="EXTERNAL_INDEPENDENT",
        evaluation_scope="TOOL_SCHEMA_OOD_ONLY",
        native_events=events,
        tool_schemas=schemas,
        native_context={"user_tools": list(user_tools)},
        label=None,
        label_provenance=None,
        target_event_indices=(),
        failure_categories=(),
        raw_record_sha256=_canonical_hash(record),
        limitations=("conversation.json has no native localized Guardian failure label; exclude from end-to-end score.",),
    )


def _decorator_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Call):
        return _decorator_name(node.func)
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def inspect_toolsandbox_tool_source(source_text: str, *, artifact_path: str) -> ToolSchemaDiagnostic:
    """Statically enumerate registered tools; never import or execute source."""
    if not isinstance(source_text, str):
        raise ExternalAdapterError("ToolSandbox source must be text")
    try:
        tree = ast.parse(source_text, filename=artifact_path)
    except SyntaxError as exc:
        raise ExternalAdapterError(f"invalid ToolSandbox Python source: {artifact_path}") from exc
    functions = []
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        decorators = {_decorator_name(item) for item in node.decorator_list}
        if "register_as_tool" not in decorators or node.name.startswith("_"):
            continue
        arguments = [item.arg for item in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs)]
        docstring = ast.get_docstring(node, clean=False) or ""
        functions.append({
            "name": node.name,
            "arguments": arguments,
            "is_async": isinstance(node, ast.AsyncFunctionDef),
            "docstring_sha256": hashlib.sha256(docstring.encode("utf-8")).hexdigest(),
        })
    functions.sort(key=lambda item: item["name"])
    return ToolSchemaDiagnostic(
        source="ToolSandbox",
        source_revision=PINNED_SOURCES["ToolSandbox"]["commit"],
        artifact_path=artifact_path,
        source_sha256=hashlib.sha256(source_text.encode("utf-8")).hexdigest(),
        functions=tuple(functions),
    )


def adapt_bfcl(record: Mapping[str, Any], *, artifact_path: str) -> ExternalCase:
    """Preserve one BFCL row for independent tool/capability OOD diagnostics."""
    record = _require_mapping(record, "record")
    record_id = _require_text(record.get("id"), "id")
    question = deepcopy(list(_require_sequence(record.get("question"), "question")))
    if not question:
        raise ExternalAdapterError("question must not be empty")
    schemas_raw = record.get("function", [])
    schemas = tuple(deepcopy(dict(_require_mapping(item, "function[]"))) for item in _require_sequence(schemas_raw, "function"))
    if not schemas:
        raise ExternalAdapterError("BFCL row has no inline function schemas; a frozen schema join is required")
    native_context = {"question": question}
    if "initial_config" in record:
        native_context["initial_config"] = deepcopy(record["initial_config"])
    return ExternalCase(
        source="BFCL",
        source_revision=PINNED_SOURCES["BFCL"]["commit"],
        record_id=f"{artifact_path}:{record_id}",
        group_id=f"bfcl:{record_id}",
        benchmark_class="EXTERNAL_INDEPENDENT",
        evaluation_scope="TOOL_SCHEMA_OOD_ONLY",
        native_events=(),
        tool_schemas=schemas,
        native_context=native_context,
        label=None,
        label_provenance=None,
        target_event_indices=(),
        failure_categories=(),
        raw_record_sha256=_canonical_hash(record),
        limitations=("BFCL input/answer data is not a recorded Guardian-labelled agent trajectory.",),
    )


ADAPTERS: dict[str, Callable[..., ExternalCase]] = {
    "ATFD": adapt_atfd,
    "tau-bench": adapt_tau_bench,
    "AgentDojo": adapt_agentdojo,
    "ToolSandbox": adapt_toolsandbox,
    "BFCL": adapt_bfcl,
}


def adapt_external_record(source: str, record: Mapping[str, Any], *, artifact_path: str) -> ExternalCase:
    try:
        adapter = ADAPTERS[source]
    except KeyError as exc:
        raise ExternalAdapterError(f"unknown external source: {source}") from exc
    return adapter(record, artifact_path=artifact_path)


def load_external_manifest(path: Path) -> dict[str, Any]:
    """Load and validate the pre-run freeze manifest without touching datasets."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != "guardian-next-external-freeze-v1":
        raise ExternalAdapterError("unsupported external manifest schema")
    sources = _require_sequence(data.get("sources"), "sources")
    if len(sources) != len(PINNED_SOURCES):
        raise ExternalAdapterError("manifest must contain exactly the pinned sources")
    names = [entry.get("name") for entry in sources if isinstance(entry, Mapping)]
    if set(names) != set(PINNED_SOURCES) or len(set(names)) != len(names):
        raise ExternalAdapterError("manifest source names are missing or duplicated")
    for entry in sources:
        entry = _require_mapping(entry, "sources[]")
        expected = PINNED_SOURCES[entry["name"]]
        if entry.get("repository") != expected["repository"] or entry.get("commit") != expected["commit"]:
            raise ExternalAdapterError(f"{entry['name']} pin differs from the audited source")
        if not _COMMIT_RE.fullmatch(str(entry.get("commit", ""))):
            raise ExternalAdapterError(f"{entry['name']} commit is not a full SHA")
        selected = _require_sequence(entry.get("selected_files", []), "selected_files")
        selected_paths: set[str] = set()
        for selected_file in selected:
            selected_file = _require_mapping(selected_file, "selected_files[]")
            if not isinstance(selected_file.get("path"), str) or not selected_file["path"]:
                raise ExternalAdapterError("selected file path is invalid")
            if selected_file["path"] in selected_paths:
                raise ExternalAdapterError("selected file path is duplicated")
            selected_paths.add(selected_file["path"])
            digest = selected_file.get("sha256")
            if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise ExternalAdapterError("selected file sha256 is invalid")
    return data


def verify_source_snapshot(entry: Mapping[str, Any], root: Path) -> dict[str, Any]:
    """Verify one local checkout and selected files without modifying it."""
    blockers: list[str] = []
    resolved_root = root.resolve()
    try:
        head = subprocess.check_output(
            ["git", "-C", str(resolved_root), "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        head = None
    if head != entry.get("commit"):
        blockers.append("local checkout HEAD does not match pinned commit")
    for item in entry.get("selected_files", []):
        relative = PurePosixPath(item["path"])
        if relative.is_absolute() or ".." in relative.parts:
            blockers.append(f"unsafe selected path: {item['path']}")
            continue
        candidate = (resolved_root / Path(*relative.parts)).resolve()
        try:
            candidate.relative_to(resolved_root)
        except ValueError:
            blockers.append(f"selected path escapes checkout: {item['path']}")
            continue
        if not candidate.is_file():
            blockers.append(f"selected file missing: {item['path']}")
            continue
        digest = hashlib.sha256(candidate.read_bytes()).hexdigest()
        if digest != item["sha256"]:
            blockers.append(f"selected file hash mismatch: {item['path']}")
    license_path = entry.get("license_path")
    if isinstance(license_path, str) and license_path:
        license_file = (resolved_root / license_path).resolve()
        try:
            license_file.relative_to(resolved_root)
        except ValueError:
            blockers.append("license_path escapes checkout")
        else:
            if not license_file.is_file():
                blockers.append("license file is missing from checkout")
    return {"verified": not blockers, "head": head, "blockers": blockers}


def external_readiness(
    manifest: Mapping[str, Any], *, source_roots: Mapping[str, Path] | None = None
) -> dict[str, Any]:
    """Report freeze blockers.  This function never reads source labels/files."""
    blockers: list[str] = []
    if manifest.get("first_blind_run_occurred") is not False:
        blockers.append("first_blind_run_occurred must be explicitly false before this cycle")
    guardian = manifest.get("guardian_freeze", {})
    for field in ("commit", "tree"):
        if not isinstance(guardian, Mapping) or not guardian.get(field):
            blockers.append(f"guardian_freeze.{field} is not frozen")
    config = manifest.get("evaluation_freeze", {})
    for field in ("config_sha256", "prompts_sha256", "thresholds_sha256", "model_manifest_sha256"):
        if not isinstance(config, Mapping) or not config.get(field):
            blockers.append(f"evaluation_freeze.{field} is not frozen")
    source_reports = []
    for entry in manifest.get("sources", []):
        source_blockers = []
        disposition = entry.get("run_disposition")
        allowed_dispositions = {
            "included_end_to_end", "included_diagnostic", "documented_unavailable"
        }
        if disposition not in allowed_dispositions:
            source_blockers.append("run disposition is not frozen")
        if not entry.get("selected_files"):
            source_blockers.append("selected_files is empty")
        if entry.get("license_review") not in {
            "accepted_for_local_evaluation",
            "accepted_for_local_evaluation_no_redistribution",
        }:
            source_blockers.append("license review is not accepted for local evaluation")
        if entry.get("adapter_status") != "implemented_tested":
            source_blockers.append("adapter is not implemented_tested")
        if entry.get("subset_policy_status") != "frozen":
            source_blockers.append("subset policy is not frozen")
        if entry.get("selection_rule_status") != "frozen_label_independent":
            source_blockers.append("label-independent selection rule is not frozen")
        if entry.get("split_policy_status") != "frozen_grouped":
            source_blockers.append("grouped split policy is not frozen")
        budget = entry.get("sample_budget")
        if disposition == "documented_unavailable":
            if budget != 0:
                source_blockers.append("unavailable source sample budget must be zero")
        elif type(budget) is not int or budget < 1:
            source_blockers.append("sample budget is not frozen")
        availability = entry.get("artifact_availability_status")
        expected_availability = {
            "included_end_to_end": {"native_artifacts_present"},
            "included_diagnostic": {"native_artifacts_present", "diagnostic_source_ready"},
            "documented_unavailable": {"documented_no_recorded_artifact"},
        }
        if disposition in expected_availability and availability not in expected_availability[disposition]:
            source_blockers.append("artifact availability does not match run disposition")
        if source_roots is None or entry.get("name") not in source_roots:
            source_blockers.append("local pinned snapshot was not verified")
        else:
            snapshot = verify_source_snapshot(entry, source_roots[entry["name"]])
            source_blockers.extend(snapshot["blockers"])
        blockers.extend(f"{entry.get('name')}: {item}" for item in source_blockers)
        source_reports.append({
            "name": entry.get("name"),
            "disposition": disposition,
            "ready": not source_blockers,
            "runnable": not source_blockers and disposition != "documented_unavailable",
            "blockers": source_blockers,
        })
    return {
        "schema_version": "guardian-next-external-readiness-v1",
        "manifest_sha256": _canonical_hash(manifest),
        "status": "ready" if not blockers else "not_ready",
        "safe_to_run_blind": not blockers,
        "blind_evaluation_executed": False,
        "sources": source_reports,
        "blockers": blockers,
    }
