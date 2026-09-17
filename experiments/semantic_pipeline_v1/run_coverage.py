"""semantic_pipeline_v1 — Phase 4 runner: measure REQUIRED_FRAGMENT_RECALL.

Writes outputs/vnext/semantic_pipeline_v1/retrieval_coverage.csv with one row
per (case, required-fragment matcher) and channel booleans:
  current_frontend_received - what the CURRENT Guardian routing delivers
                              ("yes:<module>" / "no"; module = where the text
                              physically arrives)
  current_role_usable       - whether the receiving module can use the text for
                              the fragment's ROLE (rules must reach a policy
                              reader; KB rules reaching only T2 effect proposals
                              are NOT usable as rules)
  deterministic_retrieved   - channel A (policy + declarations + response + request)
  embedding_retrieved       - channel C (top-k MiniLM cosine)
  combined_retrieved        - union A + B(lexical) + C + D(KB)
  langextract_retrieved     - channel E (filled by langextract_eval.py if usable)

The retrieval target is SOURCE COVERAGE, never the final label.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from source_segments import build_timeline, load_development_rows
from retrieval import RetrievalConfig, deterministic_channel, embedding_channel, kb_channel, lexical_channel
from coverage_annotations import REQUIRED_FRAGMENTS, NEGATIVE_AUTO_ANNOTATED, auto_requirements, resolve_matcher

REPO = HERE.parents[1]
OUT_DIR = REPO / "outputs" / "vnext" / "semantic_pipeline_v1"
PARQUET = REPO / "valid.parquet"


def current_routing(fragment, timeline, role: str) -> tuple[str, bool]:
    """(delivery string, role-usable boolean) for the incumbent architecture."""
    source_type = fragment.source_type
    paired_result_tools = _paired_result_tools(timeline)
    last_user_segment = _last_user_segment_id(timeline)
    if source_type == "SYSTEM":
        if fragment.kind.startswith("policy"):
            return "yes:policy_frontend", True
        if fragment.kind.startswith("instructions"):
            # the instructions TAIL (from the `<policy>` mention in the
            # instructions sentence onward) is part of the frontend policy
            # payload due to the first-occurrence regex semantics
            front = timeline.notes.get("frontend_policy_region")
            if front and fragment.span[0] >= front[0] and fragment.span[1] <= front[1]:
                return "yes:policy_frontend_leak", True
            return "no", False
        if fragment.kind.startswith("catalog"):
            return "partial:binding_names_only", False
        return "no", False
    if source_type in {"TOOL_SCHEMA", "TOOL_DESCRIPTION"}:
        if fragment.tool in paired_result_tools:
            # T2 receives the schema DICT (field names/kinds/enums) but never
            # the field description text or the tool description line.
            return ("partial:t2_schema_dict" if source_type == "TOOL_SCHEMA"
                    else "no"), source_type == "TOOL_SCHEMA" and role == "SCHEMA"
        return "no", False
    if source_type == "USER":
        if fragment.segment_id == last_user_segment:
            return "yes:goal_frontend", True
        return "no", False
    if source_type == "ASSISTANT":
        if fragment.document == "response":
            return "yes:claim_frontend", True
        return "no", False
    if source_type == "TOOL_CALL":
        if fragment.document == "response":
            return "yes:core", True
        paired = fragment.tool in paired_result_tools if fragment.tool else False
        return ("yes:t2_arguments" if paired else "no"), paired
    if source_type == "TOOL_RESULT":
        paired = _fragment_result_paired(fragment, timeline)
        return ("yes:t2_payload" if paired else "no"), paired
    return "no", False


def _fragment_result_paired(fragment, timeline) -> bool:
    segment = timeline.segment(fragment.segment_id)
    return segment is not None and segment.call_id is not None


def _paired_result_tools(timeline) -> set[str]:
    tools = set()
    for note in timeline.notes.get("call_result_pairs", ()):  # type: ignore[attr-defined]
        seg = timeline.segment_by_event_index(note["call_event_index"])
        if seg is not None and seg.tool:
            tools.add(seg.tool)
    return tools


def _last_user_segment_id(timeline):
    user_segments = [s for s in timeline.segments if s.source_type == "USER"]
    return user_segments[-1].segment_id if user_segments else None


def main() -> None:
    rows = load_development_rows(str(PARQUET))
    by_id = {row["id"]: row for row in rows}
    model = None
    from retrieval import load_embedding_model
    model = load_embedding_model()
    config = RetrievalConfig()

    out_rows = []
    matched_total = {"current": 0, "deterministic": 0, "embedding": 0, "combined": 0}
    required_total = 0
    unmatched_matchers: list[str] = []
    per_case_recall = []

    annotated_cases = {**{cid: reqs for cid, reqs in REQUIRED_FRAGMENTS.items()},
                       **{cid: None for cid in NEGATIVE_AUTO_ANNOTATED}}

    for case_id in sorted(annotated_cases):
        row = by_id[case_id]
        timeline = build_timeline(case_id, row["prompt"], row["response"])
        requirements = annotated_cases[case_id]
        if requirements is None:
            requirements = auto_requirements(timeline)
        det = deterministic_channel(timeline, config)
        lex = lexical_channel(timeline, config)
        kb = kb_channel(timeline)
        embed, _ = embedding_channel(timeline, config, model)
        combined_ids = set(det) | set(lex) | set(kb) | set(embed)

        case_hits = {"current": 0, "deterministic": 0, "embedding": 0, "combined": 0}
        case_required = 0
        for index, matcher in enumerate(requirements):
            fragments = resolve_matcher(timeline, matcher)
            if not fragments:
                unmatched_matchers.append(f"{case_id}#{index}:{matcher}")
                continue
            fragment_ids = {f.fragment_id for f in fragments}
            case_required += 1
            required_total += 1
            fragment = fragments[0]
            delivery, usable = current_routing(fragment, timeline, matcher.get("role", ""))
            det_hit = bool(fragment_ids & set(det))
            embed_hit = bool(fragment_ids & set(embed))
            comb_hit = bool(fragment_ids & combined_ids)
            row_out = {
                "case_id": case_id,
                "required_fragment_id": f"{case_id}#rf{index:02d}",
                "role": matcher.get("role", ""),
                "source_type": fragment.source_type,
                "matcher_note": matcher.get("note", ""),
                "current_frontend_received": delivery,
                "current_role_usable": int(usable),
                "deterministic_retrieved": int(det_hit),
                "embedding_retrieved": int(embed_hit),
                "combined_retrieved": int(comb_hit),
                "langextract_retrieved": "",
                "notes": fragment.text[:80].replace("\n", " "),
            }
            out_rows.append(row_out)
            case_hits["current"] += int(usable)
            case_hits["deterministic"] += int(det_hit)
            case_hits["embedding"] += int(embed_hit)
            case_hits["combined"] += int(comb_hit)
        if case_required:
            per_case_recall.append({"case_id": case_id, "required": case_required, **case_hits,
                                    "current_recall": round(case_hits["current"] / case_required, 4),
                                    "deterministic_recall": round(case_hits["deterministic"] / case_required, 4),
                                    "embedding_recall": round(case_hits["embedding"] / case_required, 4),
                                    "combined_recall": round(case_hits["combined"] / case_required, 4)})
            matched_total["current"] += case_hits["current"]
            matched_total["deterministic"] += case_hits["deterministic"]
            matched_total["embedding"] += case_hits["embedding"]
            matched_total["combined"] += case_hits["combined"]

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = OUT_DIR / "retrieval_coverage.csv"
    fields = ["case_id", "required_fragment_id", "role", "source_type", "matcher_note",
              "current_frontend_received", "current_role_usable",
              "deterministic_retrieved", "embedding_retrieved", "combined_retrieved",
              "langextract_retrieved", "notes"]
    with csv_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(out_rows)

    summary = {
        "rows": len(out_rows),
        "required_total": required_total,
        "unresolved_matchers": len(unmatched_matchers),
        "unresolved_matcher_list": unmatched_matchers,
        "recall": {key: round(value / required_total, 4) if required_total else 0.0
                   for key, value in matched_total.items()},
        "per_case": per_case_recall,
    }
    (OUT_DIR / "retrieval_coverage_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ("rows", "required_total", "unresolved_matchers", "recall")},
                     indent=1))
    if unmatched_matchers:
        print("UNRESOLVED MATCHERS (fix annotations):")
        for item in unmatched_matchers:
            print(" -", item)


if __name__ == "__main__":
    main()
