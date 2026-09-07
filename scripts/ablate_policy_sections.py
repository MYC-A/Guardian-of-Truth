"""Offline, model-blind policy-section delivery ablation.

This does not change production predictions.  Both readers see only prompt and
candidate response; audit spans and labels are loaded after every row has been
selected.  The candidate replaces fixed system chunks with Markdown-aligned
sections and reserves room for one response-relevant policy section.
"""

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import re

from guardian_truth.cli import read_rows, validate_rows
from guardian_truth.pipeline import Detector
from guardian_truth.reader import Chunk, EvidenceReader
from guardian_truth.semantic import SemanticResult
from guardian_truth.types import Source


WORD = re.compile(r"[\w#@.-]{3,}")
HEADING = re.compile(r"(?m)^#{1,4}\s+\S")


def _segments(text, absolute_start, limit):
    """Yield bounded exact spans, preferring complete Markdown sections."""
    starts = [match.start() for match in HEADING.finditer(text)]
    boundaries = sorted(set([0, *starts, len(text)]))
    for left, right in zip(boundaries, boundaries[1:]):
        for offset in range(left, right, limit):
            yield absolute_start + offset, absolute_start + min(offset + limit, right)


class PolicySectionReader(EvidenceReader):
    """Experimental initial selector; request/search semantics stay unchanged."""

    def __init__(self, context, *, chunk_chars=1800, max_evidence_chars=4800,
                 rolling=False):
        # Build graph indexes exactly as EvidenceReader does, but section-align
        # system chunks.  Non-system observations keep the production size.
        if (type(chunk_chars) is not int or type(max_evidence_chars) is not int
                or chunk_chars < 100 or max_evidence_chars < chunk_chars):
            raise ValueError("Invalid evidence limits")
        self.context = context
        self.rolling = rolling
        self.max_chars = max_evidence_chars
        self.chunks = {}
        self.selected = []
        self.used_chars = 0
        self.facts = {fact.id: fact for fact in context.graph.facts}
        self.neighbors = {fact.id: set(fact.previous) for fact in context.graph.facts}
        for fact in context.graph.facts:
            for previous in fact.previous:
                self.neighbors.setdefault(previous, set()).add(fact.id)
        for event_index, event in enumerate(context.history):
            if event.role == "system":
                raw = context.prompt[event.source.start:event.source.end]
                spans = _segments(raw, event.source.start, chunk_chars)
            else:
                spans = ((start, min(start + chunk_chars, event.source.end))
                         for start in range(event.source.start, event.source.end, chunk_chars))
            for start, end in spans:
                key = f"p{len(self.chunks)}"
                self.chunks[key] = Chunk(key, event_index, event.role, event.kind,
                                         event.name, Source("prompt", start, end),
                                         context.prompt[start:end])

    def _policy_rank(self, query):
        terms = set(WORD.findall(query.casefold()))
        ranked = []
        for index, chunk in enumerate(self.chunks.values()):
            if chunk.role != "system" or chunk.id in self.selected:
                continue
            words = set(WORD.findall(chunk.text.casefold()))
            overlap = terms & words
            # Longer identifiers/tool names are more discriminative.  The
            # selector never assigns truth or policy applicability itself.
            score = sum(1.0 + min(len(word), 24) / 12 for word in overlap)
            if score:
                ranked.append((score / math.sqrt(max(1, len(words))), index, chunk.id))
        ranked.sort(reverse=True)
        return [item[2] for item in ranked]

    def initialize(self, max_initial_chars=12000):
        rolling, old_limit = self.rolling, self.max_chars
        self.rolling = False
        self.max_chars = min(old_limit, max_initial_chars)
        try:
            policies = [chunk.id for chunk in self.chunks.values()
                        if chunk.role == "system"]
            self.read(policies[:1])
            users = [chunk for chunk in self.chunks.values()
                     if chunk.role == "user" and chunk.kind == "text"]
            latest_user = users[-1].text if users else ""
            # Reserve exactly one additional section for the rule most related
            # to the requested action/answer.  No annotations or row IDs enter.
            self.read(self._policy_rank(self.context.response + "\n" + latest_user)[:1])
            entity = self.response_entity_chunks(limit=1)
            self.read(entity)
            if not entity:
                results = [chunk for chunk in self.chunks.values()
                           if chunk.kind == "result"]
                if results:
                    self.read([results[-1].id])
            if users:
                event = users[-1].event
                self.read([chunk.id for chunk in users if chunk.event == event])
            ids = [key for trace in self.context.graph.arguments
                   for key in (trace.alternatives + trace.supporting)[:4]]
            self.read(self.graph_chunks(ids, limit=2))
            self.read(self.search(self.context.response, limit=3))
            self.read(policies[1:])
        finally:
            self.max_chars, self.rolling = old_limit, rolling


def _union(intervals):
    merged = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(end, merged[-1][1])
        else:
            merged.append([start, end])
    return merged


def _covered(intervals, selected):
    return sum(max(0, min(end, chosen_end) - max(start, chosen_start))
               for start, end in _union(intervals)
               for chosen_start, chosen_end in _union(selected))


def _coverage(spans, selected):
    counts = Counter({"full": 0, "partial": 0, "not_delivered": 0})
    for start, end in spans:
        amount = _covered([(start, end)], selected)
        counts["full" if amount == end - start else
               "partial" if amount else "not_delivered"] += 1
    total = sum(end - start for start, end in _union(spans))
    delivered = _covered(spans, selected)
    return dict(counts, spans=len(spans), union_chars=total,
                covered_union_chars=delivered,
                union_character_coverage=delivered / total if total else None)


class SelectionProbe:
    name = "policy_section_ablation"

    def analyze(self, context):
        self.selection = {}
        for name, cls in (("baseline", EvidenceReader),
                          ("policy_section", PolicySectionReader)):
            reader = cls(context, chunk_chars=1800, max_evidence_chars=4800,
                         rolling=False)
            reader.initialize()
            packet = reader.packet()
            self.selection[name] = {
                "ids": list(reader.selected), "chars": reader.used_chars,
                "spans": [[item["start"], item["end"]] for item in packet],
                "system_spans": [[item["start"], item["end"]]
                                 for item in packet if item["role"] == "system"],
            }
            assert reader.used_chars <= 4800
        return SemanticResult()


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("valid.parquet"))
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    output = args.output_dir / "report.json"
    if output.exists():
        parser.error("Refusing to overwrite an existing report")
    rows = read_rows(args.input)
    validate_rows(rows)
    probe = SelectionProbe()
    detector = Detector(semantic=probe)
    selections = {}
    for row in rows:
        detector.review(row["prompt"], row["response"])
        selections[str(row["id"])] = probe.selection

    # Annotations are deliberately loaded only after all model-blind selections.
    positive_path = Path("docs/v2_positive_reason_audit.json")
    unknown_path = Path("docs/v2_unknown_reason_audit.json")
    baseline_path = Path("outputs/claim_gate_20b_full/audit.jsonl")
    positive = json.loads(positive_path.read_text(encoding="utf-8"))
    unknown = json.loads(unknown_path.read_text(encoding="utf-8"))
    baseline = {item["id"]: item for item in map(json.loads,
        baseline_path.read_text(encoding="utf-8").splitlines())}
    spans = {str(row["id"]): set() for row in rows}
    for row_id, sources in ([(item["id"], item["evidence"])
                             for item in positive["annotations"]] +
                            [(item["id"], item["source_evidence"])
                             for item in unknown["rows"]]):
        for source in sources:
            if row_id in spans and source.get("document", "prompt") == "prompt":
                spans[row_id].add((source["start"], source["end"]))

    details = []
    for row in rows:
        row_id = str(row["id"])
        tags = ["all_annotated"] if spans[row_id] else []
        old = baseline.get(row_id)
        if old:
            gold, prediction = old["label"], old["strict"]["label"]
            if gold != prediction:
                tags.append("strict_errors")
            if gold == prediction == 1 and not old["skipped_mechanical"]:
                tags.append("semantic_tp")
            if old["strict"]["used_fallback"]:
                tags.append("strict_fallback")
        pair = selections[row_id]
        details.append({
            "id": row_id, "tags": tags, "audit_spans": sorted(spans[row_id]),
            "selection_changed": pair["baseline"]["spans"] != pair["policy_section"]["spans"],
            "coverage": {name: _coverage(spans[row_id], value["spans"])
                         for name, value in pair.items()},
            "selection": pair,
        })
    groups = {}
    for tag in ("all_annotated", "strict_errors", "semantic_tp", "strict_fallback"):
        members = [item for item in details if tag in item["tags"] and item["audit_spans"]]
        groups[tag] = {"rows": len(members), "variants": {}}
        for variant in ("baseline", "policy_section"):
            totals = {name: sum(item["coverage"][variant][name] for item in members)
                      for name in ("spans", "full", "partial", "not_delivered",
                                   "union_chars", "covered_union_chars")}
            totals["union_character_coverage"] = (totals["covered_union_chars"] /
                totals["union_chars"] if totals["union_chars"] else None)
            groups[tag]["variants"][variant] = totals
    report = {
        "configuration": {
            "experiment": "offline_model_blind_policy_section_delivery",
            "rows": len(rows), "chunk_chars": 1800, "max_evidence_chars": 4800,
            "source_hashes": {str(path): _sha(path) for path in
                (args.input, positive_path, unknown_path, baseline_path, Path(__file__))},
        },
        "groups": groups,
        "changed_ids": [item["id"] for item in details if item["selection_changed"]],
        "rows": details,
        "limitations": [
            "Offline source-delivery measurement; no model calls, predictions or F1.",
            "Manual audit spans are incomplete development diagnostics, not full evidence gold.",
            "Full text delivery does not prove that a model applies a rule correctly.",
            "Section selection sees prompt and response only; labels and annotations are loaded later.",
        ],
    }
    args.output_dir.mkdir(parents=True, exist_ok=False)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    print(json.dumps({"rows": len(rows), "changed": len(report["changed_ids"]),
                      "groups": groups}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
