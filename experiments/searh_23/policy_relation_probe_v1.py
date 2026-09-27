"""Conditional relation typing on manually localized original source fragments.

Action localization and fragmentation are supplied in each query. This tests
only whether the model can label the selected source relation. It says nothing
about automatically discovering all clauses or producing a contest verdict.
"""
from __future__ import annotations

import argparse
import json

import staged_policy_tree_v1 as v1
from policy_model_ab_v1 import sha


BASE = v1.ROOT / "experiments/searh_23/policy_relation_probe_v1"
OUT = v1.ROOT / "outputs/searh_23/policy_relation_probe_v1"
PUBLIC = v1.ROOT / "experiments/searh_23/source_scope_public_v1/frozen.json"
V2 = v1.ROOT / "experiments/searh_23/staged_policy_tree_v2/frozen.json"
KINDS = ("STATE_GATE", "CHECK_BEFORE", "BUSINESS_ORDER", "FORBID_IF",
         "FORBID_FACET", "PERMIT_FACET", "REQUIRE_RESPONSE", "DESCRIPTIVE")
SYSTEM = """Read ONE exact original policy fragment with ONE already located
action phrase. Classify ONLY the relation of the fragment to THAT action.
Return one JSON object with exactly one field: {"relation":"STATE_GATE|CHECK_BEFORE|BUSINESS_ORDER|FORBID_IF|FORBID_FACET|PERMIT_FACET|REQUIRE_RESPONSE|DESCRIPTIVE"}.
STATE_GATE: action is allowed/required only if a fact or approval holds.
CHECK_BEFORE: agent is explicitly told to perform a check before the action.
BUSINESS_ORDER: two distinct business operations must be executed in order.
FORBID_IF: action is forbidden under a stated condition.
FORBID_FACET: a specific facet of the action is forbidden outright.
PERMIT_FACET: a specific facet is explicitly allowed.
REQUIRE_RESPONSE: agent must ask, say, explain or remind something.
DESCRIPTIVE: states what a tool does/does not do without a command.
Only label the selected action phrase; do not create contrapositive rules or
classify an adjacent action. A check before a later action is CHECK_BEFORE,
not BUSINESS_ORDER. A statement that a tool will not check is DESCRIPTIVE,
not a prohibition on that tool. No trace verdict.
"""


ROWS = [
    ("retail_cancel", "cancel_status", "An order can only be cancelled if its status is 'pending'", "cancelled", "STATE_GATE"),
    ("retail_cancel", "cancel_check", "you should check its status before taking the action", "taking the action", "CHECK_BEFORE"),
    ("retail_modify", "modify_status", "An order can only be modified if its status is 'pending'", "modified", "STATE_GATE"),
    ("retail_exchange", "exchange_status", "An order can only be exchanged if its status is 'delivered'", "exchanged", "STATE_GATE"),
    ("retail_exchange", "exchange_reminder", "remember to remind the customer to confirm they have provided all items to be exchanged", "remind the customer", "REQUIRE_RESPONSE"),
    ("airline_baggage", "bags_add", "The user can add but not remove checked bags", "add", "PERMIT_FACET"),
    ("airline_baggage", "bags_remove", "The user can add but not remove checked bags", "remove checked bags", "FORBID_FACET"),
    ("airline_passenger_count", "passenger_modify", "The user can modify passengers but cannot modify the number of passengers", "modify passengers", "PERMIT_FACET"),
    ("airline_passenger_count", "passenger_count", "The user can modify passengers but cannot modify the number of passengers", "modify the number of passengers", "FORBID_FACET"),
    ("telecom_resume", "resume_expired", "You are not allowed to lift the suspension if the line's contract end date is in the past", "lift the suspension", "FORBID_IF"),
    ("telecom_payment_request", "payment_tool_fact", "The send payement request tool will not check if the bill is overdue", "will not check if the bill is overdue", "DESCRIPTIVE"),
    ("telecom_payment_request", "payment_check", "You should always check that the bill is overdue before sending a payment request", "sending a payment request", "CHECK_BEFORE"),
    ("hotel_cancellation_order", "cancel_refund_order", "process cancellation FIRST and the refund SECOND", "the refund SECOND", "BUSINESS_ORDER"),
    ("records_dev", "publish_approval", "A document may be published only after its owner approval check has returned approved for that document", "published", "STATE_GATE"),
    ("credit_preview_new", "credit_preview", "You may preview a credit", "preview a credit", "PERMIT_FACET"),
    ("credit_preview_new", "credit_issue", "you must never issue a credit without recorded approval", "issue a credit", "STATE_GATE"),
]


def freeze() -> None:
    public = json.loads(PUBLIC.read_text(encoding="utf-8"))
    prior = json.loads(V2.read_text(encoding="utf-8"))
    sources = {row["id"]: row["query"]["clause"] for row in public["tasks"]}
    sources.update({row["id"]: row["query"]["policy"] for row in prior["tasks"]})
    sources["credit_preview_new"] = "You may preview a credit, but you must never issue a credit without recorded approval."
    tasks = []
    for source_id, ident, fragment, action, expected in ROWS:
        if source_id not in sources or sources[source_id].count(fragment) != 1:
            raise ValueError("fragment source missing or ambiguous: " + ident)
        if v1.unique_span(fragment, action) is None:
            raise ValueError("action span missing or ambiguous: " + ident)
        tasks.append({"id": ident, "source_id": source_id,
                      "query": {"fragment": fragment, "action_quote": action},
                      "expected_relation": expected})
    protocol = {"systems": {"relation": SYSTEM}, "tasks": tasks,
                "max_tokens": 90, "note": "post-hoc, manually localized fragments; relation only; no binary verdict"}
    BASE.mkdir(parents=True, exist_ok=True)
    path = BASE / "frozen.json"
    payload = json.dumps(protocol, ensure_ascii=False, indent=2) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") != payload:
        raise ValueError("frozen relation protocol changed")
    path.write_text(payload, encoding="utf-8")
    print(json.dumps({"tasks": len(tasks), "protocol_sha256": sha(protocol)}))


def run() -> None:
    protocol = json.loads((BASE / "frozen.json").read_text(encoding="utf-8"))
    model = v1.Mistral()
    v1.OUT = OUT
    for task in protocol["tasks"]:
        v1._ask(model, protocol, task, "relation", task["query"], "__relation")


def score() -> dict:
    protocol = json.loads((BASE / "frozen.json").read_text(encoding="utf-8"))
    rows = []
    for task in protocol["tasks"]:
        record = json.loads((OUT / (task["id"] + "__relation.json")).read_text(encoding="utf-8"))
        if record["protocol_sha256"] != sha(protocol) or record["query_sha256"] != sha(task["query"]):
            raise ValueError("relation source/prompt mismatch")
        answer = record["answer"]
        relation = answer.get("relation")
        valid = record["finish_reason"] == "stop" and set(answer) == {"relation"} and relation in KINDS
        rows.append({"id": task["id"], "source_id": task["source_id"],
                     "expected": task["expected_relation"], "actual": relation,
                     "valid": valid, "exact": valid and relation == task["expected_relation"]})
    result = {"protocol_sha256": sha(protocol), "rows": rows,
              "exact": sum(row["exact"] for row in rows), "total": len(rows)}
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
