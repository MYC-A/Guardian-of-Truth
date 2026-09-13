"""Synthetic delivery inventories only; never read private blind labels."""

import json

import pytest

from guardian_truth.vnext.delivery_audit_v1 import audit_delivery


def contract(tmp_path):
    source = tmp_path / "contracts" / "vnext_requirements_v1.json"
    source.parent.mkdir()
    source.write_text(json.dumps({"schema_version": "guardian-vnext-requirements-v1",
        "required_json": ["freeze_manifest.json", "blind_e2e_results.json"],
        "required_jsonl": ["proof_certificates.jsonl"],
        "required_docs": ["END_TO_END_RESULTS.md", "FINAL_DECISION.md"]}), encoding="utf-8")
    (tmp_path / "outputs/vnext").mkdir(parents=True)
    (tmp_path / "docs/vnext").mkdir(parents=True)
    return source


def test_missing_required_artifacts_are_named_not_synthesized(tmp_path):
    source = contract(tmp_path)
    result = audit_delivery(tmp_path, source)
    assert len(result.missing) == 5 and not result.present and not result.complete_artifact_inventory
    assert not (tmp_path / "outputs/vnext/blind_e2e_results.json").exists()


def test_invalid_json_jsonl_and_not_run_final_docs_are_separate(tmp_path):
    source = contract(tmp_path)
    (tmp_path / "outputs/vnext/freeze_manifest.json").write_text("{bad", encoding="utf-8")
    (tmp_path / "outputs/vnext/blind_e2e_results.json").write_text("{}", encoding="utf-8")
    (tmp_path / "outputs/vnext/proof_certificates.jsonl").write_text("{}\nnot-json\n", encoding="utf-8")
    (tmp_path / "docs/vnext/END_TO_END_RESULTS.md").write_text("NOT_RUN\n", encoding="utf-8")
    (tmp_path / "docs/vnext/FINAL_DECISION.md").write_text("Decision not yet available.\n", encoding="utf-8")
    result = audit_delivery(tmp_path, source)
    assert len(result.invalid) == 2 and len(result.not_established) == 1
    assert len(result.present) == 3 and not result.complete_artifact_inventory


def test_parseable_complete_inventory_is_still_only_inventory(tmp_path):
    source = contract(tmp_path)
    (tmp_path / "outputs/vnext/freeze_manifest.json").write_text("{}", encoding="utf-8")
    (tmp_path / "outputs/vnext/blind_e2e_results.json").write_text("{}", encoding="utf-8")
    (tmp_path / "outputs/vnext/proof_certificates.jsonl").write_text('{"receipt":"synthetic"}\n', encoding="utf-8")
    (tmp_path / "docs/vnext/END_TO_END_RESULTS.md").write_text("Synthetic test only.\n", encoding="utf-8")
    (tmp_path / "docs/vnext/FINAL_DECISION.md").write_text("Synthetic test only.\n", encoding="utf-8")
    result = audit_delivery(tmp_path, source)
    assert result.complete_artifact_inventory and len(result.present) == 5
    assert result.scope.endswith("NOT_SEMANTIC_OR_PROMOTION_PROOF")


def test_unsafe_required_artifact_path_and_external_contract_are_rejected(tmp_path):
    source = contract(tmp_path)
    value = json.loads(source.read_text(encoding="utf-8"))
    value["required_json"][0] = "../secret.json"
    source.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ValueError, match="unsafe"):
        audit_delivery(tmp_path, source)
    with pytest.raises(ValueError, match="workspace-local"):
        audit_delivery(tmp_path / "outputs", source)
