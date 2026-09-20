"""Cross-model Architecture C experiment: theory A built by GLM (z-ai) vs
theory B built by Mistral — same LangExtract grounding machinery, different
models. This is the real test of the user's central idea: two models build
different interpretations, disagreements are found and arbitrated against
the ORIGINAL text.

Runs on the unique policies of a dataset. Compares:
  - C1-same-model: GLM persona A vs GLM persona B (already measured)
  - C1-cross-model: GLM persona A vs MISTRAL persona B (this runner)
Arbitration: a THIRD voice (the reviewer provider) decides with
source-grounded decisive quotes.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.trace_parser import parse_trace, split_policy_clauses
from common.langextract_zai import run_langextract, extractions_to_records
from common.zai_client import chat, extract_json, PROVIDER_ZAI, PROVIDER_MISTRAL
from arch_c.theory import (
    LX_EXAMPLES_A,
    PERSONA_A,
    PERSONA_B,
    clause_coverage,
    find_disagreements,
    _clause_for,
)
from arch_c.theory import REVIEW_SYS

HERE = Path(__file__).resolve().parent
RESULTS = HERE.parent / "results" / "arch_c_cross"


def get_unique_policies(data_file: Path) -> dict:
    by_hash = {}
    for line in data_file.open(encoding="utf-8"):
        r = json.loads(line)
        t = parse_trace(r["prompt"], r["response"])
        pol = t.policy_text
        import hashlib

        h = hashlib.sha256(pol.encode()).hexdigest()[:10]
        if h not in by_hash:
            by_hash[h] = {"policy_text": pol, "example_id": r["id"], "domain": r.get("domain", "")}
    return by_hash


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(HERE.parent / "data" / "synth_pairs" / "synth_pairs_v1.jsonl"))
    ap.add_argument("--theorist-b", default=PROVIDER_MISTRAL, help="model building theory B")
    ap.add_argument("--arbiter", default=PROVIDER_ZAI, help="model arbitrating disagreements")
    ap.add_argument("--max-seconds", type=float, default=480)
    args = ap.parse_args()
    import time

    policies = get_unique_policies(Path(args.data))
    print(f"unique policies: {len(policies)}")

    t0 = time.time()
    for h, info in sorted(policies.items()):
        if time.time() - t0 > args.max_seconds:
            print("time budget reached")
            break
        out_dir = RESULTS / h
        out_dir.mkdir(parents=True, exist_ok=True)
        pol = info["policy_text"]
        clauses = split_policy_clauses(pol)
        print(f"=== policy {h} ({info.get('domain')})")

        # theory A (GLM) — reuse the saved theory from the earlier C run
        # (same policy text => same theory); avoids redundant API calls.
        ta_f = out_dir / "theory_a_glm.json"
        prev = HERE.parent / "results" / "arch_c" / h / "theory_a.json"
        if not ta_f.exists() and prev.exists():
            import shutil

            shutil.copy(prev, ta_f)
        if not ta_f.exists():
            ta, _ = run_langextract(pol, PERSONA_A, LX_EXAMPLES_A, tag_prefix=f"CX/{h}/Aglm")
            recs_a = extractions_to_records(ta, pol)
            ta_f.write_text(json.dumps(recs_a, ensure_ascii=False, indent=1))
        recs_a = json.loads(ta_f.read_text())

        # theory B (cross-model theorist)
        tb_f = out_dir / f"theory_b_{args.theorist_b}.json"
        if not tb_f.exists():
            tb, _ = run_langextract(
                pol, PERSONA_B, LX_EXAMPLES_A, tag_prefix=f"CX/{h}/B{args.theorist_b}",
                model_provider=args.theorist_b,
            )
            recs_b = extractions_to_records(tb, pol)
            tb_f.write_text(json.dumps(recs_b, ensure_ascii=False, indent=1))
        recs_b = json.loads(tb_f.read_text())

        cov_a = clause_coverage(clauses, recs_a)
        cov_b = clause_coverage(clauses, recs_b)
        union = [e for e in recs_a + recs_b if not e.get("dropped_unanchored") and e.get("start") is not None]
        cov_u = clause_coverage(clauses, union)

        # disagreements across models
        disagreements = find_disagreements(recs_a, recs_b, clauses, policy_text=pol)
        (out_dir / "disagreements.json").write_text(json.dumps(disagreements, ensure_ascii=False, indent=1))

        # arbitration (incrementally persisted)
        rev_dir = out_dir / "reviews"
        rev_dir.mkdir(exist_ok=True)
        reviews = []
        for i, d in enumerate(disagreements):
            rf = rev_dir / f"d{i}.json"
            if rf.exists():
                reviews.append(json.loads(rf.read_text()))
                continue
            if time.time() - t0 > args.max_seconds:
                break
            user = (
                "ОРИГИНАЛЬНАЯ КЛАУЗА ПОЛИТИКИ:\n" + d["clause"]
                + "\n\nЭЛЕМЕНТ ТЕОРИИ (side=" + d["side"] + "):\n"
                + f"class={d['element']['class']}, text={d['element']['text']}"
                + "\n\nЕсть ли этот элемент в оригинале? Ответь JSON."
            )
            resp = chat(user=user, system=REVIEW_SYS, thinking=False, provider=args.arbiter,
                        tag=f"CX/{h}/rev{i}", max_retries=1)
            rec = {**d, "review_ok": resp.ok, "review_error": resp.error}
            if resp.ok:
                data = extract_json(resp.content)
                if data and str(data.get("verdict", "")).lower() in (
                    "element_faithful", "element_invented", "ambiguous"
                ):
                    rec["verdict"] = str(data["verdict"]).lower()
                    rec["decisive_quote"] = data.get("decisive_quote", "")
                    from arch_b.fact_ledger import locate_quote
                    rec["decisive_quote_found"] = locate_quote(d["clause"], rec["decisive_quote"])["found"]
                else:
                    rec["review_ok"] = False
                    rec["review_error"] = "bad-json"
            rf.write_text(json.dumps(rec, ensure_ascii=False, indent=1))
            reviews.append(rec)

        summary = {
            "policy_hash": h,
            "domain": info.get("domain"),
            "theory_a": "glm",
            "theory_b": args.theorist_b,
            "n_elements_a": len([e for e in recs_a if not e.get("dropped_unanchored")]),
            "n_unanchored_a": len([e for e in recs_a if e.get("dropped_unanchored")]),
            "n_elements_b": len([e for e in recs_b if not e.get("dropped_unanchored")]),
            "n_unanchored_b": len([e for e in recs_b if e.get("dropped_unanchored")]),
            "coverage_a": cov_a["normative_coverage"],
            "coverage_b": cov_b["normative_coverage"],
            "coverage_union": cov_u["normative_coverage"],
            "n_disagreements": len(disagreements),
            "verdicts": dict(Counter(r.get("verdict", "unreviewed") for r in reviews)),
            "decisive_quote_grounded": sum(1 for r in reviews if r.get("decisive_quote_found")),
            "n_reviewed": len([r for r in reviews if r.get("review_ok")]),
        }
        (out_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1))
        print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
