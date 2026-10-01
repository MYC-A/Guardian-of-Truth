"""Frozen synthetic suite integrity; these checks do not score a detector."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments/searh_23/hybrid_service_v1"))

from fresh_suite_v1 import OUT  # noqa: E402
from structural_v02 import parse_case_v02  # noqa: E402


def _rows(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_fresh_suite_integrity():
    manifest = json.loads((OUT / "manifest.json").read_text(encoding="utf-8"))
    ids = set()
    families = {}
    for split, expected_n in (("dev", 80), ("sealed", 160)):
        spec = manifest["splits"][split]
        input_file = OUT / f"{split}_input.jsonl"
        gold_file = OUT / f"{split}_gold.jsonl"
        assert hashlib.sha256(input_file.read_bytes()).hexdigest() == spec["input_sha256"]
        assert hashlib.sha256(gold_file.read_bytes()).hexdigest() == spec["gold_sha256"]
        inputs, gold = _rows(input_file), _rows(gold_file)
        assert len(inputs) == len(gold) == expected_n
        assert [r["id"] for r in inputs] == [r["id"] for r in gold]
        for case, answer in zip(inputs, gold):
            assert case["id"] not in ids
            ids.add(case["id"])
            assert answer["policy_quote"] in case["prompt"]
            assert answer["response_quote"] == case["response"]
            assert answer["label"] in (0, 1)
            assert "gold" not in case and "label" not in case
            family = answer["policy_family_id"]
            families.setdefault(split, {}).setdefault(family, []).append(answer["label"])
            ctx = parse_case_v02(case["id"], case["prompt"], case["response"])
            assert ctx.catalog.section_found
            assert not ctx.parse_warnings, (case["id"], ctx.parse_warnings)
    assert set(families["dev"]).isdisjoint(families["sealed"])
    assert len(families["dev"]) == 8 and len(families["sealed"]) == 16
    assert all(0 in values and 1 in values
               for split in families.values() for values in split.values())
