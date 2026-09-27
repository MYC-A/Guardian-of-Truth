"""Policy-head inventory with a separate action-source locator.

Exploratory V3 follows inspected V1/V2/public failures. The new probes and
their expected heads/quotes are frozen before this V3 API run. This is NOT a
complete policy compiler, case judge, or unseen benchmark evaluation.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter

import staged_policy_tree_v1 as v1
from policy_model_ab_v1 import sha


BASE = v1.ROOT / "experiments/searh_23/staged_policy_heads_v3"
OUT = v1.ROOT / "outputs/searh_23/staged_policy_heads_v3"
PUBLIC = v1.ROOT / "experiments/searh_23/source_scope_public_v1/frozen.json"
V2 = v1.ROOT / "experiments/searh_23/staged_policy_tree_v2/frozen.json"

KINDS = {"PRECONDITION", "PROHIBITION", "PROHIBITION_IF", "PERMISSION",
         "ORDERING", "REQUIRE_RESPONSE", "DESCRIPTIVE", "UNSUPPORTED"}

HEAD_SYSTEM = """Read ONE ORIGINAL policy clause and the declared tool catalog.
Inventory EVERY independent normative direction. Return JSON only:
{"heads":[{"kind":"PRECONDITION|PROHIBITION|PROHIBITION_IF|PERMISSION|ORDERING|REQUIRE_RESPONSE|DESCRIPTIVE|UNSUPPORTED","governed_tools":["exact declared tool name"],"prerequisite_tools":["exact declared tool name"],"action_meaning":"brief distinct action/facet, no verdict"}]}.
PRECONDITION: a fact/check/approval must hold before doing governed action.
ORDERING: TWO distinct executable business operations must occur in order;
governed_tools are SECOND operations, prerequisite_tools are FIRST operations.
A read/check/lookup before an action is a PRECONDITION, not ORDERING.
PROHIBITION_IF: governed action is forbidden under a stated condition.
PROHIBITION: unconditionally forbidden action. PERMISSION: explicitly allowed.
If a sentence allows one facet but forbids another, return TWO heads even if
the same tool implements both; distinguish facets in action_meaning.
If one action can be performed by several declared tools, list ALL of them.
REQUIRE_RESPONSE: duty to say/ask/remind something; governed_tools is [].
DESCRIPTIVE: relevant statement about what a tool does/does not do, with no
independent command. Preserve it as a head with governed_tools [].
UNSUPPORTED: material rule whose kind you cannot represent; never discard it.
Requests, lookups, and audit-writing are not execution of a later operation.
Do not infer tool effects from a name. Do not inspect any trace or decide a case.
"""

ANCHOR_SYSTEM = """Given ONE candidate policy head and the ORIGINAL clause,
copy the SHORTEST exact continuous substring naming the head's restricted,
allowed, forbidden, required or described action. Return JSON only:
{"action_quote":"exact substring or empty if no exact action span"}.
Do not copy a condition, approval, lookup or result in place of the action.
Preserve original inflection and spelling, including typos. Never paraphrase.
Do not change the head's kind or tool set. No case verdict.
"""


def _gold(kind: str, tools: list[str], quote: str, *, before: list[str] | None = None) -> dict:
    return {"kind": kind, "governed_tools": tools,
            "prerequisite_tools": before or [], "action_quote": quote}


PUBLIC_GOLD = {
    "retail_cancel": [_gold("PRECONDITION", ["cancel_pending_order"], "cancelled")],
    "retail_modify": [_gold("PRECONDITION", ["modify_pending_order_address",
                                            "modify_pending_order_items",
                                            "modify_pending_order_payment"], "modified")],
    "retail_exchange": [_gold("PRECONDITION", ["exchange_delivered_order_items"], "only be exchanged"),
                        _gold("REQUIRE_RESPONSE", [], "remind the customer to confirm they have provided all items to be exchanged")],
    "airline_baggage": [_gold("PERMISSION", ["update_reservation_baggages"], "add"),
                        _gold("PROHIBITION", ["update_reservation_baggages"], "remove checked bags")],
    "airline_passenger_count": [_gold("PERMISSION", ["update_reservation_passengers"], "modify passengers"),
                                _gold("PROHIBITION", ["update_reservation_passengers"], "modify the number of passengers")],
    "telecom_resume": [_gold("PROHIBITION_IF", ["resume_line"], "lift the suspension")],
    "telecom_payment_request": [_gold("DESCRIPTIVE", [], "will not check if the bill is overdue"),
                                _gold("PRECONDITION", ["send_payment_request"], "sending a payment request")],
}

V2_GOLD = {
    "records_dev": [_gold("PRECONDITION", ["publish_document"], "published")],
    "parcel_handover_transfer": [_gold("PRECONDITION", ["handover_parcel"], "handed over")],
    "hotel_cancellation_order": [_gold("ORDERING", ["process_refund"], "the refund SECOND",
                                        before=["cancel_reservation"])],
}

NEW_TASKS = [
    {"id": "credit_preview_new", "split": "v3_new_authored",
     "query": {"policy": "You may preview a credit, but you must never issue a credit without recorded approval.",
               "tools": {"preview_credit": "Show a draft credit without posting it.",
                         "check_approval": "Read recorded credit approval; does not post credit.",
                         "issue_credit": "Post a credit to the customer's balance."}},
     "expected": [_gold("PERMISSION", ["preview_credit"], "preview a credit"),
                  _gold("PRECONDITION", ["issue_credit"], "issue a credit")]},
    {"id": "archive_release_new", "split": "v3_new_authored",
     "query": {"policy": "An archive may only be released after its retention status is checked. Release through either publish_archive or publish_public_copy; filing a release request is not release.",
               "tools": {"check_retention": "Read archive retention status; no release.",
                         "publish_archive": "Release an archive.",
                         "publish_public_copy": "Release a public archive copy.",
                         "file_release_request": "File a request for a future release."}},
     "expected": [_gold("PRECONDITION", ["publish_archive", "publish_public_copy"], "released"),
                  _gold("DESCRIPTIVE", [], "filing a release request is not release")]},
]


def signature(head: dict) -> tuple:
    return (head.get("kind"), tuple(sorted(head.get("governed_tools", []))),
            tuple(sorted(head.get("prerequisite_tools", []))))


def valid_head(head: object, tools: dict) -> bool:
    if not isinstance(head, dict) or set(head) != {"kind", "governed_tools",
                                                 "prerequisite_tools", "action_meaning"}:
        return False
    governed, before = head["governed_tools"], head["prerequisite_tools"]
    if (not isinstance(head["kind"], str) or head["kind"] not in KINDS
            or not isinstance(governed, list)
            or not isinstance(before, list) or not isinstance(head["action_meaning"], str)
            or not head["action_meaning"].strip()):
        return False
    if (any(not isinstance(name, str) or name not in tools for name in governed + before)
            or len(set(governed)) != len(governed) or len(set(before)) != len(before)):
        return False
    return ((head["kind"] == "ORDERING" and bool(governed) and bool(before)
             and not set(governed) & set(before)) or
            (head["kind"] in {"DESCRIPTIVE", "REQUIRE_RESPONSE", "UNSUPPORTED"}
             and not governed and not before) or
            (head["kind"] in KINDS - {"ORDERING", "DESCRIPTIVE", "REQUIRE_RESPONSE", "UNSUPPORTED"}
             and bool(governed) and not before))


def freeze() -> None:
    public = json.loads(PUBLIC.read_text(encoding="utf-8"))
    prior = json.loads(V2.read_text(encoding="utf-8"))
    tasks = [{"id": row["id"], "split": "viewed_public46_clause",
              "query": {"policy": row["query"]["clause"], "tools": row["query"]["tools"]},
              "expected": PUBLIC_GOLD[row["id"]]} for row in public["tasks"]]
    tasks += [{"id": row["id"], "split": "viewed_prior_clause",
               "query": {"policy": row["query"]["policy"], "tools": row["query"]["tools"]},
               "expected": V2_GOLD[row["id"]]} for row in prior["tasks"] if row["id"] in V2_GOLD]
    tasks += NEW_TASKS
    for task in tasks:
        for expected in task["expected"]:
            if not set(expected["governed_tools"] + expected["prerequisite_tools"]) <= set(task["query"]["tools"]):
                raise ValueError("gold tool missing from source catalog: " + task["id"])
            if v1.unique_span(task["query"]["policy"], expected["action_quote"]) is None:
                raise ValueError("gold quote is not unique literal source: " + task["id"])
    protocol = {"systems": {"head": HEAD_SYSTEM, "anchor": ANCHOR_SYSTEM},
                "tasks": tasks, "max_tokens": 650,
                "note": "post-hoc after V1/V2/public review; two new authored contrasts; scope only"}
    BASE.mkdir(parents=True, exist_ok=True)
    path = BASE / "frozen.json"
    payload = json.dumps(protocol, ensure_ascii=False, indent=2) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") != payload:
        raise ValueError("frozen V3 changed")
    path.write_text(payload, encoding="utf-8")
    print(json.dumps({"tasks": len(tasks), "protocol_sha256": sha(protocol)}))


def run() -> None:
    protocol = json.loads((BASE / "frozen.json").read_text(encoding="utf-8"))
    v1.OUT = OUT
    model = v1.Mistral()
    for task in protocol["tasks"]:
        query = task["query"]
        record = v1._ask(model, protocol, task, "head", query, "__head")
        heads = record["answer"].get("heads")
        if not isinstance(heads, list) or len(heads) > 8 or not all(valid_head(h, query["tools"]) for h in heads):
            continue
        for index, head in enumerate(heads):
            if head["kind"] == "UNSUPPORTED":
                continue
            v1._ask(model, protocol, task, "anchor",
                    {"policy": query["policy"], "head": head}, f"__anchor_{index}")


def score() -> dict:
    protocol = json.loads((BASE / "frozen.json").read_text(encoding="utf-8"))
    rows = []
    for task in protocol["tasks"]:
        policy, tools = task["query"]["policy"], task["query"]["tools"]
        head_record = json.loads((OUT / (task["id"] + "__head.json")).read_text(encoding="utf-8"))
        if head_record["protocol_sha256"] != sha(protocol) or head_record["query_sha256"] != sha(task["query"]):
            raise ValueError("head source/prompt mismatch: " + task["id"])
        heads = head_record["answer"].get("heads")
        heads_valid = (head_record["finish_reason"] == "stop" and isinstance(heads, list)
                       and len(heads) <= 8 and all(valid_head(h, tools) for h in heads))
        signatures = Counter(signature(h) for h in heads) if heads_valid else Counter()
        expected = Counter(signature(h) for h in task["expected"])
        heads_exact = bool(heads_valid and signatures == expected)
        anchors = []
        if heads_valid:
            for index, head in enumerate(heads):
                if head["kind"] == "UNSUPPORTED":
                    continue
                anchor_query = {"policy": policy, "head": head}
                path = OUT / (task["id"] + f"__anchor_{index}.json")
                record = json.loads(path.read_text(encoding="utf-8"))
                if record["protocol_sha256"] != sha(protocol) or record["query_sha256"] != sha(anchor_query):
                    raise ValueError("anchor source/prompt mismatch: " + task["id"])
                quote = record["answer"].get("action_quote")
                anchor = {"head_index": index, "kind": head["kind"], "governed_tools": head["governed_tools"],
                          "action_quote": quote, "source_span": v1.unique_span(policy, quote),
                          "valid_literal": record["finish_reason"] == "stop" and v1.unique_span(policy, quote) is not None}
                gold_matches = [g for g in task["expected"] if signature(g) == signature(head)]
                anchor["expected_quote"] = gold_matches[0]["action_quote"] if len(gold_matches) == 1 else None
                anchor["semantic_exact"] = anchor["valid_literal"] and quote == anchor["expected_quote"]
                anchors.append(anchor)
        exact = bool(heads_exact and len(anchors) == len([h for h in task["expected"] if h["kind"] != "UNSUPPORTED"])
                     and all(anchor["semantic_exact"] for anchor in anchors))
        rows.append({"id": task["id"], "split": task["split"], "heads_valid": heads_valid,
                     "heads_exact": heads_exact, "anchored_exact": exact,
                     "expected_signatures": sorted(map(str, expected.elements())),
                     "actual_signatures": sorted(map(str, signatures.elements())),
                     "anchors": anchors, "global_verdict": "UNKNOWN"})
    result = {"protocol_sha256": sha(protocol), "rows": rows,
              "heads_exact": sum(row["heads_exact"] for row in rows),
              "anchored_exact": sum(row["anchored_exact"] for row in rows), "total": len(rows)}
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
