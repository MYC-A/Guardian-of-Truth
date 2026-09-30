"""Offline temporal ablation: freeze the first observed value per fact key.

This deliberately removes supersession by newer observations. It is a
diagnostic counterfactual, never a production implementation or prompt change.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from eval_system_runtime import run

ROOT = Path(__file__).resolve().parents[2]
import sys
sys.path.insert(0, str(ROOT / "src"))

from guardian_truth.step2.ledger import FactLedger


_latest = FactLedger.latest


def _first_prior(self, entity_type, entity_id, predicate, *, as_of=None):
    events = [e for e in self._ordered(entity_type, entity_id, predicate)
              if as_of is None or e.index <= as_of]
    if not events:
        return _latest(self, entity_type, entity_id, predicate, as_of=as_of)
    first = FactLedger()
    first.append(events[0])
    return _latest(first, entity_type, entity_id, predicate, as_of=as_of)


if __name__ == "__main__":
    diagnostic = Path(__file__).resolve().parent / "outputs/system_runtime_diagnostic.json"
    ablated = diagnostic.with_name("system_runtime_first_prior.json")
    try:
        with patch.object(FactLedger, "latest", _first_prior):
            run()
            ablated.write_bytes(diagnostic.read_bytes())
    finally:
        run()  # Restore the standard archived diagnostic after patch removal.
