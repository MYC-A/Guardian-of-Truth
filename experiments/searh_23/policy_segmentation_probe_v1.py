"""Source-exhaustive, non-overlapping clause segmentation probe.

This is a post-hoc component test on viewed policies plus two authored ones.
It does not identify target tools or judge violations. The model sees no gold
segment count. Code checks literal spans and uncovered source words.
"""
from __future__ import annotations

import argparse
import json
import re

import staged_policy_tree_v1 as v1
from policy_model_ab_v1 import sha
from staged_policy_heads_v3 import BASE as V3_BASE


BASE = v1.ROOT / "experiments/searh_23/policy_segmentation_probe_v1"
OUT = v1.ROOT / "outputs/searh_23/policy_segmentation_probe_v1"
EXPECTED_COUNTS = {
    "retail_cancel": 2, "retail_modify": 2, "retail_exchange": 3,
    "airline_baggage": 2, "airline_passenger_count": 2,
    "telecom_resume": 1, "telecom_payment_request": 2,
    "records_dev": 2, "hotel_cancellation_order": 2,
    "parcel_handover_transfer": 2, "credit_preview_new": 2,
    "archive_release_new": 3,
}
IGNORABLE_CONNECTORS = {"and", "but", "or"}
SYSTEM = """Split ONE ORIGINAL policy text into every independent directive
or descriptive assertion. Return one JSON object only:
{"segments":[{"quote":"exact continuous source substring"},...]}.
Copy exact continuous substrings of the ORIGINAL source in their source order.
Segments must not overlap. Cover every content word; only punctuation and
standalone connecting words AND/BUT/OR may remain outside quotes.
Split a contrast such as 'may add but not remove' into permission and
prohibition segments. Split two independent sentences. Keep multiple checks
that jointly qualify the SAME action inside their parent directive. Preserve
the source's if/only-if/never/before/after words in the appropriate segment.
Do not restate logical contrapositives or invent a new rule. Do not choose
tools, formalize truth conditions, or judge any agent action.
"""


def segment_spans(policy: str, segments: object) -> tuple[list[dict] | None, list[str]]:
    if (not isinstance(segments, list) or not segments or
            any(not isinstance(item, dict) or set(item) != {"quote"} for item in segments)):
        return None, []
    spans = [v1.unique_span(policy, item["quote"]) for item in segments]
    if any(span is None for span in spans):
        return None, []
    if any(spans[index]["start"] >= spans[index + 1]["start"]
           or spans[index]["end"] > spans[index + 1]["start"]
           for index in range(len(spans) - 1)):
        return None, []
    uncovered = [match.group() for match in re.finditer(r"\b\w+\b", policy, re.UNICODE)
                 if match.group().casefold() not in IGNORABLE_CONNECTORS
                 and not any(span["start"] <= match.start() and match.end() <= span["end"]
                             for span in spans)]
    return spans, uncovered


def freeze() -> None:
    source = json.loads((V3_BASE / "frozen.json").read_text(encoding="utf-8"))
    tasks = [{"id": item["id"], "split": item["split"],
              "query": {"policy": item["query"]["policy"]},
              "expected_directives": EXPECTED_COUNTS[item["id"]]}
             for item in source["tasks"]]
    if {task["id"] for task in tasks} != set(EXPECTED_COUNTS):
        raise ValueError("count annotations do not cover exact source set")
    protocol = {"systems": {"segments": SYSTEM}, "tasks": tasks, "max_tokens": 500,
                "note": "post-hoc viewed source and authored controls; component segmentation only"}
    BASE.mkdir(parents=True, exist_ok=True)
    path = BASE / "frozen.json"
    payload = json.dumps(protocol, ensure_ascii=False, indent=2) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") != payload:
        raise ValueError("frozen segmentation protocol changed")
    path.write_text(payload, encoding="utf-8")
    print(json.dumps({"tasks": len(tasks), "protocol_sha256": sha(protocol)}))


def run() -> None:
    protocol = json.loads((BASE / "frozen.json").read_text(encoding="utf-8"))
    model = v1.Mistral()
    v1.OUT = OUT
    for task in protocol["tasks"]:
        v1._ask(model, protocol, task, "segments", task["query"], "__segments")


def score() -> dict:
    protocol = json.loads((BASE / "frozen.json").read_text(encoding="utf-8"))
    rows = []
    for task in protocol["tasks"]:
        record = json.loads((OUT / (task["id"] + "__segments.json")).read_text(encoding="utf-8"))
        if record["protocol_sha256"] != sha(protocol) or record["query_sha256"] != sha(task["query"]):
            raise ValueError("segmentation source/prompt mismatch")
        segments = record["answer"].get("segments")
        spans, uncovered = segment_spans(task["query"]["policy"], segments)
        literal = record["finish_reason"] == "stop" and spans is not None
        count_exact = literal and len(segments) == task["expected_directives"]
        rows.append({"id": task["id"], "expected_directives": task["expected_directives"],
                     "actual_directives": len(segments) if isinstance(segments, list) else None,
                     "literal_nonoverlap": literal, "uncovered_words": uncovered,
                     "source_covered": literal and not uncovered, "count_exact": count_exact,
                     "mechanical_candidate": count_exact and not uncovered,
                     "segments": segments, "global_verdict": "UNKNOWN"})
    result = {"protocol_sha256": sha(protocol), "rows": rows,
              "literal_nonoverlap": sum(row["literal_nonoverlap"] for row in rows),
              "source_covered": sum(row["source_covered"] for row in rows),
              "count_exact": sum(row["count_exact"] for row in rows),
              "mechanical_candidate": sum(row["mechanical_candidate"] for row in rows),
              "total": len(rows)}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "score.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {key: value for key, value in result.items() if key != "rows"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("freeze", "run", "score"))
    phase = parser.parse_args().phase
    if phase == "freeze":
        freeze()
    elif phase == "run":
        run()
    else:
        print(json.dumps(score()))
