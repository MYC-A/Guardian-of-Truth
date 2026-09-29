"""F6 rename invariance — extraction stability under entity renames.

The 6 renamed cases (f6r) differ from their originals ONLY in entity
nouns/IDs (same structure). Measures, per case:
  - mention count agreement (|A| == |A_ren|);
  - span alignment: each original mention span maps through the frozen
    rename map; fraction of renamed-extraction mentions that align 1:1
    with the original extraction mentions (after applying the map);
  - type agreement on aligned mentions;
  - structure verdict: same aligned span multiset + same types.

Run: python3 en_f6_rename.py
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
IE = HERE.parent / "event_ie_frontends_v1"
from en_f6_cf import F6_RENAMES  # noqa: E402
from en_f6_build import _ren_text  # noqa: E402

RAW = HERE / "outputs" / "raw"
OUT = HERE / "outputs" / "score"
OUT.mkdir(parents=True, exist_ok=True)


def load_mentions(model_key, suite, cid):
    f = RAW / model_key / "A" / f"{cid}.json"
    if not f.exists():
        return []
    d = json.loads(f.read_text(encoding="utf-8"))
    return [m for m in d["mentions"] if m.get("grounded")]


def main():
    rows = []
    tot = Counter()
    for orig_id, spec in F6_RENAMES.items():
        ren_id = spec["case_id_new"]
        for model_key in ("mistral", "codestral"):
            A = load_mentions(model_key, "f6", orig_id)
            B = load_mentions(model_key, "f6r", ren_id)
            # map each original mention's expected renamed form
            expect = {}
            for a in A:
                mapped = _ren_text(a["quote"], spec["map"])
                expect.setdefault(mapped, []).append(a.get("type"))
            matched = 0
            type_ok = 0
            used = Counter()
            for b in B:
                key = b["quote"]
                if expect.get(key) and used[key] < len(expect[key]):
                    used[key] += 1
                    matched += 1
                    if b.get("type") in expect[key]:
                        type_ok += 1
            structural = (len(A) == len(B) and
                          matched == len(B) and
                          type_ok == len(B))
            tot[f"{model_key}_cases"] += 1
            tot[f"{model_key}_structural"] += int(structural)
            tot[f"{model_key}_span_align"] += matched
            tot[f"{model_key}_n_ren"] += len(B)
            rows.append({"case": orig_id, "model": model_key,
                         "n_orig": len(A), "n_ren": len(B),
                         "aligned": matched, "type_ok": type_ok,
                         "structural_identity": structural})
    out = {"per_case": rows,
           "structural_mistral": f"{tot['mistral_structural']}/"
                                 f"{tot['mistral_cases']}",
           "structural_codestral": f"{tot['codestral_structural']}/"
                                   f"{tot['codestral_cases']}",
           "span_alignment_mistral": round(
               tot["mistral_span_align"] / max(1, tot["mistral_n_ren"]), 3),
           "span_alignment_codestral": round(
               tot["codestral_span_align"] /
               max(1, tot["codestral_n_ren"]), 3)}
    (OUT / "rename.json").write_text(
        json.dumps(out, indent=1, ensure_ascii=False) + "\n",
        encoding="utf-8")
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
