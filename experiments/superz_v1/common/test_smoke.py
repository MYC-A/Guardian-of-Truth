"""Smoke tests for the trace parser + z-ai client bridge.

Run: python3 experiments/superz_v1/common/test_smoke.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import json

import pandas as pd

from common.trace_parser import parse_trace, split_policy_clauses

DATA = Path(__file__).resolve().parents[1] / "data" / "public46"


def load_public46():
    repo_root = Path(__file__).resolve().parents[3]
    df = pd.read_parquet(repo_root / "valid.parquet")
    out = DATA / "public46.jsonl"
    DATA.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        for _, r in df.iterrows():
            f.write(
                json.dumps(
                    {
                        "id": r["id"],
                        "prompt": r["prompt"],
                        "response": r["response"],
                        # NOTE: label/explanation NEVER used in inference; kept
                        # in this file only for local post-hoc scoring which is
                        # stored separately. Firewall: arch code must not read it.
                        "label": None,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    labels = {r["id"]: int(r["label"]) for _, r in df.iterrows()}
    (DATA / "labels_local.json").write_text(json.dumps(labels, ensure_ascii=False))
    print(f"wrote {len(df)} rows -> {out} (labels sealed separately)")
    return df


def test_parser(df):
    ok, fails = 0, []
    for _, r in df.iterrows():
        try:
            t = parse_trace(r["prompt"], r["response"])
            card = t.summary_card()
            # invariants
            assert t.response_segment is not None, "no RESPONSE segment"
            assert t.full_text[t.response_segment.start : t.response_segment.end] == t.response_segment.text
            # span verification round-trip on a tool call line
            if t.tool_events:
                e = t.tool_events[0]
                line = t.full_text[e.abs_start : e.abs_end]
                assert "TOOL" in line, f"span mismatch: {line[:80]!r}"
            # policy present
            assert len(t.policy_text) > 500, "policy too small"
            ok += 1
        except Exception as e:  # noqa: BLE001
            fails.append((r["id"], repr(e)))
    print(f"parser: {ok}/{len(df)} OK; fails: {fails[:5]}")
    return not fails


def test_clauses(df):
    r = df.iloc[0]
    t = parse_trace(r["prompt"], r["response"])
    pol = t.policy_text
    clauses = split_policy_clauses(pol)
    # verify all clause spans byte-exact
    bad = [c for c in clauses if pol[c["start"] : c["end"]] != c["text"]]
    total = sum(c["end"] - c["start"] for c in clauses)
    print(f"clauses: {len(clauses)}, byte-exact {len(clauses)-len(bad)}/{len(clauses)}, coverage {total}/{len(pol)} chars")
    assert not bad, f"{len(bad)} clause spans not byte-exact"
    return True


if __name__ == "__main__":
    df = load_public46()
    assert test_parser(df)
    assert test_clauses(df)
    print("ALL SMOKE OK")
