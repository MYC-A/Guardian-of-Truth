"""Architecture C runner — per unique policy (4 in public46, 4 in synth).

Stages per policy:
  C0: single-persona extraction (persona A only)
  C1: dual independent extraction (A: normative-complete, B: permissive-
      adversarial) — both LangExtract-anchored
  C2: clause coverage registry; uncovered clauses -> one targeted
      re-extraction pass over those clauses
  C3: disagreement arbitration vs original clause (LLM, decisive quote
      must ground in the clause)
  C4: repaired union theory

Artifacts per policy saved to results/arch_c/<policy_hash>/.
Metrics reported: coverage rate, span-exact rate, disagreements found,
kept/dropped/ambiguous after arbitration, element counts per class.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.trace_parser import parse_trace, split_policy_clauses
from arch_c.theory import (
    LX_EXAMPLES_A,
    PERSONA_A,
    PERSONA_B,
    extract_theory,
    clause_coverage,
    find_disagreements,
    review_disagreements,
    repair_theory,
)

HERE = Path(__file__).resolve().parent
RESULTS = HERE.parent / "results" / "arch_c"


def get_unique_policies(data_file: Path) -> dict[str, dict]:
    """policy_hash -> {policy_text, example_case_id}"""
    by_hash = {}
    for line in data_file.open(encoding="utf-8"):
        r = json.loads(line)
        t = parse_trace(r["prompt"], r["response"])
        pol = t.policy_text
        h = hashlib.sha256(pol.encode()).hexdigest()[:10]
        if h not in by_hash:
            by_hash[h] = {"policy_text": pol, "example_id": r["id"], "domain": r.get("domain", "")}
    return by_hash


def run_c_for_policy(h: str, info: dict, do_c1: bool, do_c3: bool) -> dict:
    out_dir = RESULTS / h
    out_dir.mkdir(parents=True, exist_ok=True)
    pol = info["policy_text"]
    clauses = split_policy_clauses(pol)

    # C0: persona A only
    theory_a, n_a = extract_theory(pol, PERSONA_A, LX_EXAMPLES_A, tag_prefix=f"C/{h}/A")
    (out_dir / "theory_a.json").write_text(json.dumps(theory_a, ensure_ascii=False, indent=1))
    cov_a = clause_coverage(clauses, theory_a)
    (out_dir / "coverage_a.json").write_text(json.dumps(cov_a, ensure_ascii=False, indent=1))

    result = {
        "policy_hash": h,
        "domain": info.get("domain"),
        "example_id": info["example_id"],
        "n_clauses": cov_a["n_clauses"],
        "C0": {
            "n_elements": len([e for e in theory_a if not e.get("dropped_unanchored")]),
            "n_unanchored_dropped": len([e for e in theory_a if e.get("dropped_unanchored")]),
            "coverage": cov_a["normative_coverage"],
            "n_normative": cov_a["n_normative"],
            "llm_calls": n_a,
        },
    }

    if not do_c1:
        return result

    # C1: persona B
    theory_b, n_b = extract_theory(pol, PERSONA_B, LX_EXAMPLES_A, tag_prefix=f"C/{h}/B")
    (out_dir / "theory_b.json").write_text(json.dumps(theory_b, ensure_ascii=False, indent=1))
    cov_b = clause_coverage(clauses, theory_b)
    (out_dir / "coverage_b.json").write_text(json.dumps(cov_b, ensure_ascii=False, indent=1))

    # C2: targeted re-extraction of uncovered clauses (union of both theories)
    union_el = [e for e in theory_a + theory_b if not e.get("dropped_unanchored")]
    cov_u = clause_coverage(clauses, union_el)
    uncovered = [c for c in clauses if c.get("clause_kind", "normative") == "normative" and not any(
        e["start"] < c["end"] and e["end"] > c["start"] for e in union_el
    )]
    n_retry = 0
    retry_elements = []
    if uncovered and not (out_dir / "retry_uncovered.json").exists():
        # one targeted pass: concatenate uncovered clause texts
        target_text = "\n".join(c["text"] for c in uncovered)
        try:
            got, n_retry = extract_theory(
                target_text, PERSONA_A, LX_EXAMPLES_A, tag_prefix=f"C/{h}/retry"
            )
            # spans are relative to target_text; keep text-only records
            retry_elements = [
                {"class": e["class"], "text": e["text"], "from_retry_pass": True}
                for e in got if not e.get("dropped_unanchored")
            ]
        except Exception as e:  # noqa: BLE001 — retry is best-effort
            retry_elements = []
            n_retry = 0
        (out_dir / "retry_uncovered.json").write_text(
            json.dumps({"n_uncovered": len(uncovered), "elements": retry_elements}, ensure_ascii=False, indent=1)
        )
    cov_after_retry = len(uncovered) - len(
        [
            c
            for c in uncovered
            if any(retry_elements)
        ]
    )  # simplified: retry found anything for some clauses

    # C3: disagreements + arbitration (incrementally resumable)
    disagreements = find_disagreements(theory_a, theory_b, clauses, policy_text=pol)
    (out_dir / "disagreements.json").write_text(json.dumps(disagreements, ensure_ascii=False, indent=1))
    reviews = []
    if do_c3 and disagreements:
        rev_dir = out_dir / "reviews"
        rev_dir.mkdir(exist_ok=True)
        todo = []
        for i, d in enumerate(disagreements):
            rf = rev_dir / f"d{i}.json"
            if rf.exists():
                reviews.append(json.loads(rf.read_text()))
            else:
                todo.append((i, d, rf))
        from arch_c.theory import review_disagreements as _rd
        for i, d, rf in todo:
            try:
                rv = _rd([d], tag_prefix=f"C/{h}")[0]
            except Exception as e:  # noqa: BLE001
                rv = {**d, "review_ok": False, "review_error": str(e)[:200]}
            rf.write_text(json.dumps(rv, ensure_ascii=False, indent=1))
            reviews.append(rv)
    repaired = repair_theory(theory_a, theory_b, reviews) if reviews else {
        "kept": [], "dropped_invented": [], "ambiguous": [], "unreviewed": []
    }

    (out_dir / "disagreements.json").write_text(json.dumps(disagreements, ensure_ascii=False, indent=1))
    (out_dir / "reviews.json").write_text(json.dumps(reviews, ensure_ascii=False, indent=1))
    (out_dir / "repaired_theory.json").write_text(json.dumps(repaired, ensure_ascii=False, indent=1))

    result["C1"] = {
        "n_elements_b": len([e for e in theory_b if not e.get("dropped_unanchored")]),
        "n_unanchored_b": len([e for e in theory_b if e.get("dropped_unanchored")]),
        "coverage_b": cov_b["normative_coverage"],
        "coverage_union": cov_u["normative_coverage"],
        "n_uncovered_clauses": len(uncovered),
        "retry_found_elements": len(retry_elements),
        "llm_calls_b": n_b,
        "llm_calls_retry": n_retry,
    }
    result["C3"] = {
        "n_disagreements": len(disagreements),
        "n_reviewed": len([r for r in reviews if r.get("review_ok")]),
        "verdicts": dict(Counter(r.get("verdict", "unreviewed") for r in reviews)),
        "decisive_quote_grounded": sum(1 for r in reviews if r.get("decisive_quote_found")),
        "kept": len(repaired["kept"]),
        "dropped_invented": len(repaired["dropped_invented"]),
        "ambiguous": len(repaired["ambiguous"]),
        "unreviewed": len(repaired["unreviewed"]),
    }
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(HERE.parent / "data" / "public46" / "public46.jsonl"))
    ap.add_argument("--stage", default="all", choices=["C0", "all"])
    ap.add_argument("--limit-policies", type=int, default=None)
    args = ap.parse_args()

    data_file = Path(args.data)
    policies = get_unique_policies(data_file)
    if args.limit_policies:
        # deterministic order for quota management
        items = sorted(policies.items())[: args.limit_policies]
    else:
        items = sorted(policies.items())
    print(f"unique policies: {len(items)}")

    out_all = []
    for h, info in items:
        print(f"=== policy {h} (domain={info.get('domain','')}, example={info['example_id']})")
        res = run_c_for_policy(h, info, do_c1=args.stage == "all", do_c3=args.stage == "all")
        out_all.append(res)
        print(json.dumps(res, ensure_ascii=False, indent=1))

    out_f = RESULTS / f"summary_{data_file.parent.name}.json"
    out_f.write_text(json.dumps(out_all, ensure_ascii=False, indent=1))
    print(f"saved {out_f}")


if __name__ == "__main__":
    main()
