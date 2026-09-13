"""Replay the preserved public v3 source counterexample through the new envelope."""

from dataclasses import asdict
import json
from pathlib import Path

from guardian_truth.vnext.integrity import file_digest, verify_files, write_new
from guardian_truth.vnext.source_envelope_v4 import SourceEnvelope, SourceFrame, normalize_envelope
from guardian_truth.vnext.types import Span, ToolIdentity

ROOT = Path(__file__).resolve().parents[1]


def main():
    input_path = ROOT / "outputs/vnext/source_delimiter_v3_counterexample_v1.json"
    old = json.loads(input_path.read_text(encoding="utf-8"))
    if verify_files(ROOT, old["source_sha256"]):
        raise ValueError("preserved legacy source implementation changed")
    rows = []
    for case in old["cases"]:
        prompt = case["synthetic_prompt"]
        frame = SourceFrame(Span("prompt", 0, len(prompt)),
            Span("prompt", prompt.index("\n") + 1, len(prompt)), "tool", "result", ToolIdentity("diagnostic.get"))
        # This adapter-owned fixture metadata is explicit outside body text. It
        # is not an interpretation of an embedded marker or a real-provider claim.
        envelope = SourceEnvelope(prompt, "", (frame,), "public-counterexample-fixture", "1",
            "explicit source fixture: one TOOL_RESULT body; tool/caller effects unknown")
        normalized = normalize_envelope(envelope)
        rows.append({"case": case["case"], "legacy_system_events": case["system_events"],
            "new_system_events": sum(event.actor == "system" for event in normalized.ledger.events),
            "event_count": len(normalized.ledger.events),
            "observation_count": len(normalized.ledger.observations),
            "confirmed_effect_count": len(normalized.ledger.effects),
            "envelope_source_sha256": normalized.source_sha256,
            "framing_complete": normalized.framing_complete,
            "reasons": [reason.value for reason in normalized.reasons],
            "source_envelope": asdict(envelope)})
    if any(row["new_system_events"] or row["confirmed_effect_count"] for row in rows):
        raise ValueError("new source envelope failed the public counterexample")
    if rows[0]["observation_count"]:
        raise ValueError("malformed result became observed facts")
    paths = ("src/guardian_truth/vnext/source_envelope_v4.py", "scripts/audit_vnext_source_envelope_v4.py")
    report = {"scope": "PUBLIC_SYNTHETIC_SOURCE_BOUNDARY_REPLAY_NOT_MODEL_OR_CORE_EVALUATION",
        "input_counterexample_sha256": file_digest(input_path),
        "source_sha256": {path: file_digest(ROOT / path) for path in paths},
        "api_requests": 0, "private_data_read": False,
        "new_path_result": "PRESERVED_COUNTEREXAMPLE_PASSES_UNDER_EXPLICIT_ADAPTER_METADATA",
        "legacy_path": "UNCHANGED_COUNTEREXAMPLE_REMAINS",
        "authorship_limit": "application must authenticate source metadata; checksums alone are not authentication",
        "cases": rows}
    write_new(ROOT / "outputs/vnext/source_delimiter_envelope_v4_audit_v1.json", report)
    print(json.dumps({"scope": report["scope"], "new_system_events": [row["new_system_events"] for row in rows],
        "api_requests": 0}))


if __name__ == "__main__":
    main()
