#!/usr/bin/env python3
"""E3a — A1R post-hoc re-anchoring of the frozen Codex A1 suspicion records.

Reuses the sealed full run records produced by the previous agent at
`/mnt/data/guardian/Guardian-research-a-83bbbb2/outputs/research_mistral_a_20260920/public46_full_A1/records.jsonl`
with NO new model calls.

Repair being measured (general, not example-specific):
  The producer emitted (quote, start, end) triples whose offsets almost never
  address the quoted bytes (114/120 source mismatches). The validator already
  supports a unique-quote admission path, but the response schema forced the
  model to always emit offsets, which were then checked byte-exactly.

A1R anchor rules (strict provenance is preserved):
  R1 offsets are IGNORED entirely (model-emitted positions are not trusted);
  R2 the quote must occur VERBATIM, exactly once, in exactly one of the two
     documents (prompt/response). If the model named the wrong document but the
     quote is unique in the other one, the document label is repaired and the
     suspicion stays anchored (misattribution repair);
  R3 if no verbatim match exists, an emphasis-tolerant pass is tried:
     both sides are normalized (strip `**`/`__`/`*`/backtick emphasis, collapse
     whitespace) and the normalized quote must be unique in exactly one
     normalized document; the anchor then maps back to a real original span;
  R4 anything else stays UNANCHORED (no threshold relaxation, no fuzzy match).

Outputs: per-suspicion re-anchor report, per-case labels, gold join and metrics,
comparison vs A0 / broken A1 / pre-grounding A1.
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SRC_RECORDS = Path(
    "/mnt/data/guardian/Guardian-research-a-83bbbb2/outputs/"
    "research_mistral_a_20260920/public46_full_A1/records.jsonl"
)
INPUT_CSV = REPO / "outputs" / "superz_fullcycle" / "input" / "input.csv"
GOLD_PARQUET = REPO / "valid.parquet"
OUT_DIR = REPO / "outputs" / "superz_fullcycle" / "e3a_a1r_posthoc"
POSITIVE_THRESHOLD = 0.5

_EMPHASIS = re.compile(r"(\*\*|__|\*|`)+")
_WS = re.compile(r"\s+")


def normalize(text: str) -> str:
    return _WS.sub(" ", _EMPHASIS.sub("", text)).strip()


def find_unique(text: str, quote: str) -> tuple[int, int] | None:
    """Verbatim unique occurrence of quote in text -> (start, end)."""
    if not quote:
        return None
    first = text.find(quote)
    if first < 0:
        return None
    if text.find(quote, first + 1) >= 0:
        return None  # ambiguous
    return first, first + len(quote)


def find_unique_normalized(text: str, quote: str) -> tuple[int, int] | None:
    """Emphasis/whitespace-tolerant unique occurrence -> original span."""
    if not quote:
        return None
    n_text = normalize(text)
    n_quote = normalize(quote)
    if not n_quote:
        return None
    first = n_text.find(n_quote)
    if first < 0 or n_text.find(n_quote, first + 1) >= 0:
        return None
    # Map back to the original string: walk the original accumulating a
    # normalized buffer until it covers n_text[first:first+len(n_quote)].
    target = n_text[first:first + len(n_quote)]
    buf = []
    out_start = None
    pos = 0
    i = 0
    while i < len(text):
        ch = text[i]
        if _EMPHASIS.match(ch):
            i += 1
            continue
        if ch.isspace():
            if buf and buf[-1] != " ":
                buf.append(" ")
            i += 1
            continue
        buf.append(ch)
        if out_start is None and "".join(buf).strip():
            out_start = i
        if "".join(buf).strip() == target and out_start is not None:
            # find the end: consume following emphasis/whitespace-adjacent chars
            j = i + 1
            while j < len(text) and (_EMPHASIS.match(text[j]) or text[j].isspace()):
                if text[j].isspace() and j + 1 < len(text) and not _EMPHASIS.match(text[j + 1]) and not text[j + 1].isspace():
                    break
                j += 1
            return out_start, j
        i += 1
    return None


def reanchor_span(span: dict, sources: dict[str, str], name: str) -> tuple[str, int | None, int | None, list[str]]:
    """Try R2 then R3 for one span. Returns (status, start, end, issues)."""
    issues: list[str] = []
    quote = span.get("quote") or ""
    claimed_doc = span.get("document")
    if not quote:
        return "UNANCHORED", None, None, [f"{name}_empty_quote"]
    if claimed_doc not in sources:
        issues.append(f"{name}_unknown_document")

    # R2: verbatim unique in exactly one document (document repair allowed)
    verbatim_hits = {}
    for doc, text in sources.items():
        hit = find_unique(text, quote)
        if hit is not None:
            verbatim_hits[doc] = hit
    if len(verbatim_hits) == 1:
        doc, (s, e) = next(iter(verbatim_hits.items()))
        repaired = [] if doc == claimed_doc else [f"{name}_document_repaired"]
        return "ANCHORED", s, e, repaired
    if len(verbatim_hits) > 1:
        return "UNANCHORED", None, None, [f"{name}_quote_ambiguous_multi_doc"]

    # R3: emphasis-tolerant unique in exactly one document
    norm_hits = {}
    for doc, text in sources.items():
        hit = find_unique_normalized(text, quote)
        if hit is not None:
            norm_hits[doc] = hit
    if len(norm_hits) == 1:
        doc, (s, e) = next(iter(norm_hits.items()))
        repaired = [] if doc == claimed_doc else [f"{name}_document_repaired"]
        return "ANCHORED", s, e, repaired + [f"{name}_emphasis_tolerant"]
    if len(norm_hits) > 1:
        return "UNANCHORED", None, None, [f"{name}_normalized_ambiguous"]

    return "UNANCHORED", None, None, [f"{name}_quote_not_found"] + issues


def main() -> int:
    csv.field_size_limit(64 * 1024 * 1024)
    if not SRC_RECORDS.is_file():
        print(f"ERROR: source records not found: {SRC_RECORDS}")
        return 1
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    INPUT_CSV.parent.mkdir(parents=True, exist_ok=True)

    # label-free input (fixed for the whole research line)
    if not INPUT_CSV.is_file():
        import pandas as pd
        df = pd.read_parquet(GOLD_PARQUET)
        with open(INPUT_CSV, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["id", "prompt", "response"])
            for _, r in df.iterrows():
                w.writerow([r["id"], r["prompt"], r["response"]])

    sources_by_id = {}
    with open(INPUT_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            sources_by_id[row["id"]] = {"prompt": row["prompt"], "response": row["response"]}

    # gold join AFTER inference-only logic
    import pandas as pd
    gold = {r["id"]: int(r["label"]) for _, r in pd.read_parquet(GOLD_PARQUET).iterrows()}

    per_case = {}
    susp_stats = Counter()
    anchor_issue_stats = Counter()
    n_susp = 0
    out_rows = []

    with open(SRC_RECORDS, encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            if rec.get("status") != "OK":
                continue
            cid = rec["id"]
            sources = sources_by_id.get(cid)
            if sources is None:
                continue
            case_rows = []
            for gs in rec.get("grounded_suspicions", []):
                susp = gs.get("suspicion", {})
                n_susp += 1
                src_status, ss, se, src_issues = reanchor_span(susp.get("source", {}), sources, "source")
                tgt_status, ts, te, tgt_issues = ("ANCHORED", None, None, [])
                if susp.get("target"):
                    tgt_status, ts, te, tgt_issues = reanchor_span(susp["target"], sources, "target")
                anchored = src_status == "ANCHORED"  # target optional, kept informational
                score = float(susp.get("score", 0.0))
                label = int(anchored and score >= POSITIVE_THRESHOLD)
                for i in src_issues + tgt_issues:
                    anchor_issue_stats[i] += 1
                susp_stats["anchored" if anchored else "unanchored"] += 1
                susp_stats["anchored_and_positive" if label else "anchored_below_threshold"] += 0 if not anchored else 0
                case_rows.append({
                    "reason_type": susp.get("reason_type"),
                    "score": score,
                    "src_anchored": src_status,
                    "src_start": ss, "src_end": se,
                    "src_issues": src_issues,
                    "tgt_anchored": tgt_status,
                    "label": label,
                })
            case_label = int(any(r["label"] == 1 for r in case_rows))
            per_case[cid] = case_label
            out_rows.append({
                "id": cid,
                "variant": rec.get("variant"),
                "n_suspicions": len(case_rows),
                "n_anchored": sum(1 for r in case_rows if r["src_anchored"] == "ANCHORED"),
                "a1r_label": case_label,
                "suspicions": case_rows,
            })

    # metrics
    tp = fp = fn = tn = 0
    mism = []
    for cid, pred in per_case.items():
        g = gold.get(cid)
        if g is None:
            continue
        if pred == 1 and g == 1:
            tp += 1
        elif pred == 1 and g == 0:
            fp += 1
            mism.append(cid)
        elif pred == 0 and g == 1:
            fn += 1
        else:
            tn += 1
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec_ = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * prec * rec_ / (prec + rec_) if prec + rec_ else 0.0

    summary = {
        "experiment": "E3a_a1r_posthoc",
        "source_records": str(SRC_RECORDS),
        "source_records_sha256": hashlib.sha256(SRC_RECORDS.read_bytes()).hexdigest(),
        "input_csv_sha256": hashlib.sha256(INPUT_CSV.read_bytes()).hexdigest(),
        "n_cases_scored": len(per_case),
        "n_suspicions_total": n_susp,
        "suspicion_anchor_stats": dict(susp_stats),
        "anchor_issue_stats": dict(anchor_issue_stats),
        "positive_threshold": POSITIVE_THRESHOLD,
        "metrics": {"TP": tp, "FP": fp, "FN": fn, "TN": tn,
                    "precision": round(prec, 4), "recall": round(rec_, 4), "F1": round(f1, 4)},
        "comparison": {
            "A0_mistral": {"TP": 22, "FP": 16, "FN": 1, "TN": 7, "F1": .7213},
            "A1_broken_strict": {"TP": 0, "FP": 0, "FN": 23, "TN": 23, "F1": 0.0},
            "A1_pre_grounding_diagnostic": {"TP": 21, "FP": 20, "FN": 2, "TN": 3, "F1": .6563},
        },
        "fp_case_ids": mism,
        "notes": "Anchoring ignores model-emitted offsets; requires unique verbatim or emphasis-tolerant unique quote in exactly one document; document misattribution repaired; no threshold relaxation.",
    }

    with open(OUT_DIR / "a1r_cases.jsonl", "w", encoding="utf-8") as f:
        for row in out_rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    with open(OUT_DIR / "summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(json.dumps({k: summary[k] for k in
                      ("n_cases_scored", "n_suspicions_total", "suspicion_anchor_stats",
                       "anchor_issue_stats", "metrics", "fp_case_ids")}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
