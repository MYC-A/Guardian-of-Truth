import json
from pathlib import Path

from guardian_truth.next.external_evaluation import (
    BlindDetectorInput,
    run_external_evaluation,
)


def _ready(manifest, *, source_roots):
    return {"safe_to_run_blind": True, "status": "ready", "blockers": []}


def _blocked(manifest, *, source_roots):
    return {"safe_to_run_blind": False, "status": "not_ready", "blockers": ["freeze missing"]}


def _entry(name, disposition, path, budget):
    return {
        "name": name,
        "run_disposition": disposition,
        "sample_budget": budget,
        "selected_files": [{"path": path}],
    }


def _tau_row(task_id, reward, trial=0):
    return {
        "task_id": task_id,
        "trial": trial,
        "reward": reward,
        "traj": [
            {"role": "system", "content": "Complete only supported tasks."},
            {"role": "user", "content": f"request-{task_id}"},
            {"role": "assistant", "content": "done"},
        ],
    }


def test_readiness_gate_precedes_any_selected_file_read(tmp_path):
    reads = []
    result = run_external_evaluation(
        {"sources": [_entry("tau-bench", "included_end_to_end", "data.json", 1)]},
        source_roots={"tau-bench": tmp_path},
        detectors={"d": lambda payload: 0},
        readiness_checker=_blocked,
        read_text=lambda path: reads.append(path) or "[]",
    )
    assert result["status"] == "blocked_not_ready"
    assert result["blind_evaluation_executed"] is False
    assert result["labels_joined"] is False
    assert reads == []


def test_detector_boundary_is_label_blind_and_hash_precedes_join(tmp_path):
    path = tmp_path / "data.json"
    path.write_text(json.dumps([_tau_row("a", 0), _tau_row("b", 1)]), encoding="utf-8")
    observed = []

    def detector(payload):
        assert isinstance(payload, BlindDetectorInput)
        observed.append(payload)
        assert "label" not in payload.model_view
        assert "reward" not in payload.model_view
        assert "ground_truth" not in payload.model_view
        assert "label" not in payload.prompt
        assert "reward" not in payload.prompt
        return int("request-a" in payload.prompt)

    manifest = {"sources": [_entry("tau-bench", "included_end_to_end", "data.json", 12)]}
    result = run_external_evaluation(
        manifest,
        source_roots={"tau-bench": tmp_path},
        detectors={"blind": detector},
        readiness_checker=_ready,
    )
    assert len(observed) == 2
    assert result["prediction_freeze"]["frozen_before_label_join"] is True
    assert result["labels_joined_after_prediction_freeze"] is True
    report = result["detectors"]["blind"]
    assert report["guardian_localized_label_equivalence"] is False
    assert report["trajectory_proxy_metrics"]["n"] == 2
    assert "not_guardian_turn_localized" in report["metric_semantics"]


def test_selection_is_deterministic_and_uses_first_twelve_text_groups(tmp_path):
    path = tmp_path / "data.json"
    records = [_tau_row(task, task % 2) for task in reversed(range(13))]
    path.write_text(json.dumps(records), encoding="utf-8")
    manifest = {"sources": [_entry("tau-bench", "included_end_to_end", "data.json", 12)]}

    def execute():
        return run_external_evaluation(
            manifest,
            source_roots={"tau-bench": tmp_path},
            detectors={"zero": lambda payload: 0},
            readiness_checker=_ready,
        )

    first = execute()
    path.write_text(json.dumps(list(reversed(records))), encoding="utf-8")
    second = execute()
    expected_groups = sorted(str(value) for value in range(13))[:12]
    assert first["selection_audit"]["tau-bench"][0]["selected_group_ids"] == expected_groups
    assert first["prediction_freeze"]["sha256"] == second["prediction_freeze"]["sha256"]


def test_static_toolsandbox_bfcl_diagnostics_and_agentdojo_unavailable(tmp_path):
    tools_root = tmp_path / "tools"
    bfcl_root = tmp_path / "bfcl"
    dojo_root = tmp_path / "dojo"
    tools_root.mkdir()
    bfcl_root.mkdir()
    dojo_root.mkdir()
    (tools_root / "tool.py").write_text(
        "@register_as_tool()\ndef send_message(recipient, text):\n    \"\"\"Send it.\"\"\"\n    return True\n",
        encoding="utf-8",
    )
    bfcl_row = {
        "id": "simple_0",
        "question": [[{"role": "user", "content": "add"}]],
        "function": [{
            "name": "add",
            "description": "add",
            "parameters": {
                "type": "object",
                "properties": {"x": {"type": "integer"}},
                "required": ["x"],
            },
        }],
    }
    (bfcl_root / "cases.jsonl").write_text(json.dumps(bfcl_row) + "\n", encoding="utf-8")
    manifest = {"sources": [
        _entry("ToolSandbox", "included_diagnostic", "tool.py", 32),
        _entry("BFCL", "included_diagnostic", "cases.jsonl", 10),
        _entry("AgentDojo", "documented_unavailable", "unused.json", 0),
    ]}
    result = run_external_evaluation(
        manifest,
        source_roots={"ToolSandbox": tools_root, "BFCL": bfcl_root, "AgentDojo": dojo_root},
        detectors={},
        readiness_checker=_ready,
    )
    tool = result["diagnostics"]["ToolSandbox"]
    assert tool["static_only"] is True
    assert tool["registered_functions_evaluated"] == 1
    assert tool["functions_with_docstrings"] == 1
    bfcl = result["diagnostics"]["BFCL"]
    assert bfcl["rows_evaluated"] == 1
    assert bfcl["function_schemas"] == 1
    assert bfcl["parameter_properties"] == 1
    assert bfcl["guardian_label_equivalence"] is False
    assert result["unavailable_sources"]["AgentDojo"]["executed"] is False


def test_rendering_rejects_post_response_events_instead_of_reordering_them():
    from guardian_truth.next.external_evaluation import (
        ExternalEvaluationError, render_guardian_input,
    )
    view = {
        "source": "test", "record_id": "r", "tool_schemas": [], "context": {},
        "events": [
            {"role": "system", "content": "Policy."},
            {"role": "assistant", "content": "done"},
            {"role": "tool", "content": "late result"},
        ],
    }
    try:
        render_guardian_input(view)
    except ExternalEvaluationError as error:
        assert "after selected assistant" in str(error)
    else:
        raise AssertionError("post-response events must fail closed")
