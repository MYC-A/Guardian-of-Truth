"""Selftest for the absence-attested mode of scripts/build_v6_sealed_bundle.py.

All fixtures are EXPLICITLY SYNTHETIC. They verify tool mechanics only:
  - deterministic ls-inventory parsing of capture evidence,
  - the contract-complete absence bundle (case_count 0, NOT_RECORDED fields,
    no KEEP/REJECT expressed),
  - byte-identical re-emission (determinism),
  - sealed mode still REFUSES when sealed sources are absent.
They are NOT V5/V6 data and must never be reported as experimental results.
"""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "build_v6_sealed_bundle.py"

spec = importlib.util.spec_from_file_location("build_v6_sealed_bundle", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


SYNTH_CAPTURE = (
    "-rw-rw-r-- 1 z z  4208 Sep 13 16:18 policy_v5_case_000.json\n"
    "     3→-rw-rw-r-- 1 z z  3669 Sep 13 16:17 policy_v5_case_000_arm_a.json\n"
    "-rw-rw-r-- 1 z z  801 Sep 13 16:17 policy_v5_case_000_arm_a_result.json\n"
    "-rw-rw-r-- 1 z z  9173 Sep 13 16:17 policy_v5_case_000_arm_b24.json\n"
    "-rw-rw-r-- 1 z z  3774 Sep 13 16:18 policy_v5_case_000_arm_b24_adm_00.json\n"
    "-rw-rw-r-- 1 z z  3774 Sep 13 16:18 policy_v5_case_001_arm_b24_adm_01_result.json\n"
    "-rw-rw-r-- 1 z z  443 Sep 13 17:52 policy_v5_prediction_seal.json\n"
    "-rw-rw-r-- 1 z z  750862 Sep 13 17:52 policy_v5_predictions.json\n"
    "-rw-rw-r-- 1 z z  516994 Sep 13 15:40 policy_v4_predictions.json\n"
    "not an ls line at all\n"
)


def _write_capture(base: Path) -> Path:
    cap_dir = base / "caps"
    cap_dir.mkdir(parents=True, exist_ok=True)
    (cap_dir / "bash_synthetic.txt").write_text(SYNTH_CAPTURE, encoding="utf-8")
    return cap_dir


def test_parse_ls_inventory_counts_and_sizes(tmp_path):
    cap_dir = _write_capture(tmp_path)
    files = mod.parse_ls_inventory(sorted(cap_dir.glob("*.txt")))
    assert files["policy_v5_predictions.json"]["bytes"] == 750862
    assert files["policy_v5_case_000_arm_a.json"]["bytes"] == 3669
    assert files["policy_v5_case_000_arm_a.json"]["recorded_mtime"] == "Sep 13 16:17"
    # line-number prefixes are stripped and non-ls lines ignored
    assert len(files) == 9
    assert not any(n.startswith("not") for n in files)
    summary = mod.summarize_inventory(files, "policy_v5")
    assert summary["distinct_case_ids"] == 2
    assert summary["bare_case_file_count"] == 1
    # kind counts collapse request+result file pairs (arm_a: request + _result = 2 files)
    assert summary["per_case_artifact_counts"]["arm_a"] == 2
    assert "arm_a_result" not in summary["per_case_artifact_counts"]
    assert summary["per_case_artifact_counts"]["arm_b24"] == 1
    assert summary["per_case_artifact_counts"]["arm_b24_adm"] == 2
    assert summary["sealed_files_recorded_in_inventory"]["predictions.json"]["bytes"] == 750862
    v4 = mod.summarize_inventory(files, "policy_v4")
    assert v4["sealed_files_recorded_in_inventory"]["predictions.json"]["bytes"] == 516994


def test_absence_bundle_structure(tmp_path):
    repo = tmp_path / "repo"
    (repo / "outputs/vnext").mkdir(parents=True)
    (repo / "benchmarks/vnext").mkdir(parents=True)
    cap_dir = _write_capture(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    bundle = mod.build_absence_attested(repo, out, cap_dir,
                                        run_probe=False, emit_manifest=False)
    assert bundle["bundle_status"] == "ABSENCE_ATTESTED_NOT_SEALED"
    assert bundle["case_count"] == 0 and bundle["cases"] == []
    # contract-complete top level per C_ALR_CYCLE_PROTOCOL.md 4.1
    for key in ("schema", "experiment", "benchmark_name", "case_count", "cases",
                "machine_aggregates"):
        assert key in bundle
    # no verdict key anywhere at top level
    assert "verdict" not in bundle
    assert "NO KEEP/REJECT" in bundle["verdict_note"]
    aggs = bundle["machine_aggregates"]
    assert aggs["C_accuracy"] == mod.NOT_COMPUTABLE
    assert aggs["B4_accuracy"] == mod.NOT_COMPUTABLE
    assert aggs["admission_precision_overall"] == mod.NOT_RECORDED
    assert aggs["admission_precision_conditional_on_correct_primary"] == mod.NOT_RECORDED
    assert aggs["quadrants"]["status"] == mod.NOT_COMPUTABLE
    assert sum(aggs["quadrants"]["counts"].values()) == 0
    claims = bundle["user_reported_claims_UNVERIFIED"]
    assert claims["verification_status"] == "UNVERIFIED_USER_REPORTED_NO_ARTIFACT"
    # machine search recorded live (fixture repo has no sealed files)
    ev = bundle["provenance"]["absence_evidence"]
    assert ev["repo_outputs_vnext_glob"]["policy_v6*.json"] == 0
    inv = bundle["provenance"]["inventories_from_captures"]
    assert inv["policy_v5"]["distinct_case_ids"] == 2
    assert inv["policy_v6"]["files_in_surviving_inventories"] == 0
    # aggregates file exists and mirrors bundle hashes
    agg_doc = json.loads((out / "machine_verified_aggregates.json").read_text())
    assert agg_doc["bundle_file"] == "v6_sealed_bundle.json"
    assert agg_doc["bundle_sha256"] == mod.sha256_of(out / "v6_sealed_bundle.json")


def test_absence_bundle_deterministic(tmp_path):
    repo = tmp_path / "repo"
    (repo / "outputs/vnext").mkdir(parents=True)
    (repo / "benchmarks/vnext").mkdir(parents=True)
    cap_dir = _write_capture(tmp_path)
    out1, out2 = tmp_path / "out1", tmp_path / "out2"
    out1.mkdir(); out2.mkdir()
    mod.build_absence_attested(repo, out1, cap_dir, run_probe=False)
    mod.build_absence_attested(repo, out2, cap_dir, run_probe=False)
    h1 = mod.sha256_of(out1 / "v6_sealed_bundle.json")
    h2 = mod.sha256_of(out2 / "v6_sealed_bundle.json")
    assert h1 == h2, "absence bundle emission must be byte-deterministic"


def test_stage_a_refuses_absence_bundle(tmp_path):
    repo = tmp_path / "repo"
    (repo / "outputs/vnext").mkdir(parents=True)
    (repo / "benchmarks/vnext").mkdir(parents=True)
    cap_dir = _write_capture(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    bundle_path = out / "v6_sealed_bundle.json"
    mod.build_absence_attested(repo, out, cap_dir, run_probe=False)
    proc = subprocess.run(
        [sys.executable, str(mod.STAGE_A_SCRIPT), "--bundle", str(bundle_path),
         "--prereg", str(mod.PREREG)],
        capture_output=True, text=True, timeout=120)
    assert proc.returncode == 2
    assert "bundle.cases must be a non-empty list" in proc.stderr


def test_sealed_mode_still_refuses_missing_sources(tmp_path):
    repo = tmp_path / "empty_repo"
    (repo / "outputs/vnext").mkdir(parents=True)
    (repo / "benchmarks/vnext").mkdir(parents=True)
    out = tmp_path / "out"
    out.mkdir()
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--repo", str(repo), "--out-root", str(out)],
        capture_output=True, text=True, timeout=120)
    assert proc.returncode == 2, "sealed mode must refuse when sealed files are absent"
    assert "Refusing to emit" in proc.stderr
