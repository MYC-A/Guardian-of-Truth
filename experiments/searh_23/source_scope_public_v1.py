"""Public46 policy-clause transfer with the unchanged source-scope prompt."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import source_scope_probe_v2 as prior
from build_policy_atoms_v1 import ROOT
from call_condition_probe import input_record, load_cases
from policy_model_ab_v1 import sha


BASE = ROOT / "experiments/searh_23/source_scope_public_v1"
OUT = ROOT / "outputs/searh_23/source_scope_public_v1"


def freeze() -> None:
    rows = load_cases(ROOT / "outputs/full21/input/public46_label_free.csv")
    domains = {}
    for row in rows:
        for name in ("retail", "airline", "telecom"):
            if row["id"].startswith(name) and name not in domains:
                item = input_record(row)
                if item:
                    domains[name] = item
    if set(domains) != {"retail", "airline", "telecom"}:
        raise ValueError("missing public domain")
    selected = [
        ("retail_cancel", "retail", "An order can only be cancelled if its status is 'pending', and you should check its status before taking the action.", ["cancel_pending_order"]),
        ("retail_modify", "retail", "An order can only be modified if its status is 'pending', and you should check its status before taking the action.", ["modify_pending_order_address", "modify_pending_order_items", "modify_pending_order_payment"]),
        ("retail_exchange", "retail", "An order can only be exchanged if its status is 'delivered', and you should check its status before taking the action. In particular, remember to remind the customer to confirm they have provided all items to be exchanged.", ["exchange_delivered_order_items"]),
        ("airline_baggage", "airline", "- The user can add but not remove checked bags.", ["update_reservation_baggages"]),
        ("airline_passenger_count", "airline", "- The user can modify passengers but cannot modify the number of passengers.", ["update_reservation_passengers"]),
        ("telecom_resume", "telecom", "You are not allowed to lift the suspension if the line's contract end date is in the past, even if the user has paid all their overdue bills.", ["resume_line"]),
        ("telecom_payment_request", "telecom", "- The send payement request tool will not check if the bill is overdue. You should always check that the bill is overdue before sending a payment request.", ["send_payment_request"]),
    ]
    tasks = []
    for ident, domain, clause, expected in selected:
        source=domains[domain]
        if clause not in source["policy"]:
            raise ValueError(f"source clause mismatch: {ident}")
        tools={name:desc.splitlines()[0] for name,desc in source["tools"].items()}
        if not set(expected)<=set(tools):
            raise ValueError(f"missing expected tool: {ident}")
        tasks.append({"id":ident,"split":"public46_policy_clauses",
                      "query":{"clause":clause,"tools":tools},
                      "expected_scope":expected})
    protocol={"system":prior.SYSTEM,"source":"original public46 system policy clauses",
              "tasks":tasks,"max_tokens":350}
    BASE.mkdir(parents=True,exist_ok=True)
    path=BASE/"frozen.json"
    payload=json.dumps(protocol,ensure_ascii=False,indent=2)+"\n"
    if path.exists() and path.read_text(encoding="utf-8")!=payload:
        raise ValueError("frozen public protocol changed")
    path.write_text(payload,encoding="utf-8")
    print(json.dumps({"tasks":len(tasks),"protocol_sha256":sha(protocol)}))


def main() -> None:
    parser=argparse.ArgumentParser()
    parser.add_argument("phase",choices=("freeze","run","score"))
    args=parser.parse_args()
    if args.phase=="freeze":
        freeze()
        return
    prior.BASE=BASE
    prior.OUT=OUT
    if args.phase=="run":
        prior.run()
    else:
        print(json.dumps(prior.score()))


if __name__=="__main__":
    main()
