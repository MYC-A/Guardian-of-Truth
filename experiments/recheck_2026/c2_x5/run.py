"""Test saved C2 claims inside X5 without inventing missing predicates."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from guardian_truth.cycle2.x5 import core_review
from guardian_truth.next.claims import extract_claims_with_coverage
from guardian_truth.next.records import (
    Claim, ClaimCoverageItem, ClaimExtraction, ClaimKind, Span,
)
from guardian_truth.pipeline import Detector
from experiments.recheck_2026.shared import (
    DEFAULT_CASES, DEFAULT_GOLD, REPO, cases, digest, labels, new_output,
    score, write_json, write_jsonl,
)

PROPOSALS = REPO / "outputs/cycle2/claim_proposals_checkpoint.json"
CLAIM_CASES = REPO / "outputs/cycle2/claim_cases.json"
ENTITY = re.compile(r"\b([A-Za-z][A-Za-z0-9_]*_id)\s*[:=]\s*([\w.-]+)")
KIND = {"ACTION_COMPLETED": ClaimKind.ACTION, "STATE": ClaimKind.STATE,
        "ATTRIBUTION": ClaimKind.ATTRIBUTION, "INTENT": ClaimKind.INTENT,
        "REFUSAL": ClaimKind.REFUSAL, "FACT": ClaimKind.FACT,
        "ABSENCE": ClaimKind.ABSENCE}


def extraction_from_c2(response: str, proposal: dict) -> tuple[ClaimExtraction, dict]:
    if proposal.get("arm") != "C2" or proposal.get("schema_status") != "VALID":
        raise ValueError("C2 proposal is not schema-valid")
    claims = []
    coverage = []
    generic_action = 0
    for index, item in enumerate(proposal["coverage"]):
        start, end = item["start"], item["end"]
        if not (type(start) is int and type(end) is int and 0 <= start < end <= len(response)):
            raise ValueError("C2 span outside source response")
        span = Span("response", start, end)
        coverage.append(ClaimCoverageItem(span, item["status"], "C2 response inventory"))
    for index, item in enumerate(proposal["claims"]):
        start, end = item["start"], item["end"]
        if not (type(start) is int and type(end) is int and 0 <= start < end <= len(response)):
            raise ValueError("C2 claim outside source response")
        text = response[start:end]
        kind = KIND.get(item["kind"], ClaimKind.FACT)
        entities = tuple(sorted(set(ENTITY.findall(text))))
        predicate = item["kind"].casefold()
        if kind is ClaimKind.ACTION:
            # C2 provides a span/type but no executable action predicate. Reuse
            # a deterministic predicate only if it parses this exact text and
            # the source text names a concrete entity. Otherwise bind UNKNOWN.
            local = extract_claims_with_coverage(text)
            parsed = [c for c in local.claims if c.kind is ClaimKind.ACTION]
            if parsed and entities:
                predicate = parsed[0].predicate
            else:
                kind = ClaimKind.FACT
                generic_action += 1
        claims.append(Claim(f"c2:{index}", kind, "assistant", predicate,
                            text, Span("response", start, end),
                            entities=entities, extractor="C2_saved_span_type"))
    return ClaimExtraction(tuple(claims), tuple(coverage), "C2_saved_span_type"), {
        "n_typed_claims": len(claims), "n_generic_actions_without_predicate": generic_action}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    ap.add_argument("--gold", type=Path, default=DEFAULT_GOLD)
    ap.add_argument("--proposals", type=Path, default=PROPOSALS)
    ap.add_argument("--claim-cases", type=Path, default=CLAIM_CASES)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    input_cases = cases(args.cases)
    proposals_file = json.loads(args.proposals.read_text(encoding="utf-8"))
    proposals = {r["case_id"]: r for r in proposals_file["proposals"] if r["arm"] == "C2"}
    response_sources = {r["id"]: r["response"] for r in json.loads(
        args.claim_cases.read_text(encoding="utf-8"))["cases"]}
    ids = sorted(set(input_cases) & set(proposals))
    if args.limit:
        ids = ids[:args.limit]
    output = new_output(args.out)
    write_json(output / "config.json", {"experiment": "c2_x5_handoff_v1",
        "case_sha256": digest(args.cases), "proposals_sha256": digest(args.proposals),
        "claim_cases_sha256": digest(args.claim_cases), "gold_sha256": digest(args.gold),
        "ids": ids, "policy": "LF-canonical source response and valid C2 schema required; missing predicate stays unknown",
        "response_normalization": "CRLF to LF only; all paired arms receive the same canonical text"})
    gold = labels(args.gold)
    rows = []
    for cid in ids:
        case = input_cases[cid]
        row = {"id": cid, "gold": gold.get(cid), "status": "excluded",
               "X0": None, "X5_C0": None, "X5_C2": None}
        try:
            response = case["response"].replace("\r\n", "\n")
            if response_sources[cid] != response:
                raise ValueError("C2 source response differs from input response")
            extraction, bridge = extraction_from_c2(response, proposals[cid])
            old = core_review(case["prompt"], response)
            new = core_review(case["prompt"], response,
                              claim_extraction=extraction)
            x0 = int(Detector().review(case["prompt"], response).status == "violation")
            row.update({"status": "paired", "X0": x0,
                        "X5_C0": old["label"], "X5_C2": new["label"],
                        "X5_C0_verdict": old["internal_verdict"],
                        "X5_C2_verdict": new["internal_verdict"],
                        "C0_telemetry": old["telemetry"],
                        "C2_telemetry": new["telemetry"], "bridge": bridge})
        except (ValueError, KeyError) as exc:
            row["reason"] = f"{type(exc).__name__}: {exc}"
        rows.append(row)
        write_jsonl(output / "records.jsonl", rows)
    paired = [r for r in rows if r["status"] == "paired"]
    write_json(output / "summary.json", {"n_input": len(rows),
        "n_paired": len(paired), "exclusions": [{"id": r["id"], "reason": r.get("reason")}
                                              for r in rows if r["status"] != "paired"],
        "X0": score(paired, "X0"), "X5_C0": score(paired, "X5_C0"),
        "X5_C2": score(paired, "X5_C2"),
        "changed_labels": [{"id": r["id"], "gold": r["gold"],
                            "C0": r["X5_C0"], "C2": r["X5_C2"]}
                           for r in paired if r["X5_C0"] != r["X5_C2"]],
        "changed_solver_verdicts": [{"id": r["id"],
                            "C0": r["X5_C0_verdict"], "C2": r["X5_C2_verdict"]}
                           for r in paired if r["X5_C0_verdict"] != r["X5_C2_verdict"]]})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
