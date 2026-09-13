"""Named stage result pointer; versioned scored reports are never replaced."""

import json
from pathlib import Path

from guardian_truth.vnext.integrity import file_digest, write_new

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/vnext"


def main():
    report_path = OUT / "binding_temporal_v2_results.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    write_new(OUT / "binding_temporal_results.json", {
        "schema_version": "guardian-binding-stage-summary-v1",
        "status": "COMPLETE_TYPED_SOURCE_STAGE_NATIVE_CORE_PENDING",
        "scope": report["scope"], "selected_experiment": "binding_temporal_v2",
        "metrics": report["metrics"],
        "experiments": {
            "symbolic_v1": {"status": "NOT_RUN", "source_grounding": "NOT_ESTABLISHED",
                "source_audit_sha256": file_digest(OUT / "binding_temporal_v1_source_audit.json")},
            "source_backed_v2": {"status": "COMPLETE",
                "implementation_commit": report["architecture_commit"],
                "freeze_sha256": report["freeze_sha256"], "report_sha256": file_digest(report_path),
                "failure_audit_sha256": file_digest(OUT / "binding_temporal_v2_failure_audit.json")},
        },
        "native_frontend_evaluation": "NOT_RUN", "whole_core_end_to_end_gain": "NOT_ESTABLISHED",
        "core_certificate_validation": None, "api_requests": 0, "blind_gold_opened": False,
    })
    print(json.dumps({"status": "COMPLETE_TYPED_SOURCE_STAGE_NATIVE_CORE_PENDING", "api_requests": 0}))


if __name__ == "__main__":
    main()
