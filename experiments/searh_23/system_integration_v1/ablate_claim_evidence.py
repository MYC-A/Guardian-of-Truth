"""Offline ablation: trust every compiled factual claim without world evidence."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from eval_system_runtime import run


def _trust_claim(_query, _case, _facts):
    return {"status": "SUPPORTED", "reason": "ablation_trust_compiled_claim"}


if __name__ == "__main__":
    diagnostic = Path(__file__).resolve().parent / "outputs/system_runtime_diagnostic.json"
    ablated = diagnostic.with_name("system_runtime_no_claim_evidence.json")
    try:
        with patch("guardian_truth.integration.system_runtime.check_claim", _trust_claim):
            run()
            ablated.write_bytes(diagnostic.read_bytes())
    finally:
        run()  # Restore the standard archived diagnostic.
