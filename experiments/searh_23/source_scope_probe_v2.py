"""Clause-level action scope probe using server MISTRAL_MODEL and MISTRAL_API_KEY.

This asks what *action* an original clause restricts. No history or labels are
sent to the model. Five previously viewed clauses are development; five other
clauses from the same two policies are a limited clause holdout.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

from build_policy_atoms_v1 import ROOT
from policy_model_ab_v1 import sha
from tq_questions import Mistral, mistral_settings


BASE = ROOT / "experiments/searh_23/source_scope_probe_v2"
OUT = ROOT / "outputs/searh_23/source_scope_probe_v2"
SYSTEM = """Read ONE original policy clause and the declared tool catalog. Identify the tool calls that perform the action which the clause restricts. For 'A requires B', A is the restricted action; B supplies a prerequisite. For 'do A only after B', A is restricted. A tool that only checks, reads, submits a request, or records B is not restricted merely because B is mentioned. Return a single JSON OBJECT: {"scope_tools":["exact tool name"],"action_quote":"exact continuous substring from the clause naming the restricted action"}. If the clause restricts several actions, include all of them. If none of the declared tools performs the restricted action, return empty list and empty quote. Never classify whether the clause is violated, and do not use trace or gold labels."""


def read_source(suite: str) -> dict:
    return json.loads((ROOT / "outputs/searh_23/call_condition_probe" / suite / "input.json").read_text(encoding="utf-8"))["inputs"][0]


def bullets(policy: str) -> list[str]:
    return [" ".join(x.split()) for x in re.findall(r"(?m)^- (.*(?:\n  [^\n]+)*)", policy)]


def freeze() -> None:
    service = read_source("service_desk_v1_renamed")
    hotel = read_source("hotel_v2_calls")
    selected = [
        ("service_identity", service, 0, ["perform_swap", "issue_fee_credit"], "development"),
        ("service_authorization", service, 1, ["perform_swap"], "development"),
        ("hotel_identity", hotel, 0, ["modify_reservation", "cancel_reservation"], "development"),
        ("hotel_approval", hotel, 2, ["process_refund"], "development"),
        ("hotel_cancellation_order", hotel, 6, ["process_refund"], "development"),
        ("service_audit", service, 2, ["log_completion"], "clause_holdout"),
        ("service_inventory", service, 3, ["perform_swap"], "clause_holdout"),
        ("hotel_incident", hotel, 1, ["issue_compensation"], "clause_holdout"),
        ("hotel_charge_retry", hotel, 3, ["charge_card"], "clause_holdout"),
        ("hotel_late_checkout", hotel, 4, ["grant_late_checkout"], "clause_holdout"),
    ]
    tasks=[]
    for ident, source, idx, expected, split in selected:
        clause=bullets(source["policy"])[idx]
        short_tools={name: desc.splitlines()[0] for name,desc in source["tools"].items()}
        tasks.append({"id":ident,"split":split,"query":{"clause":clause,"tools":short_tools},
                      "expected_scope":expected})
    protocol={"system":SYSTEM,"source":"original service desk and hotel clauses",
              "tasks":tasks,"max_tokens":350}
    BASE.mkdir(parents=True,exist_ok=True)
    path=BASE/"frozen.json"
    payload=json.dumps(protocol,ensure_ascii=False,indent=2)+"\n"
    if path.exists() and path.read_text(encoding="utf-8")!=payload:
        raise ValueError("frozen protocol changed")
    path.write_text(payload,encoding="utf-8")
    print(json.dumps({"tasks":len(tasks),"protocol_sha256":sha(protocol)}))


def run() -> None:
    protocol=json.loads((BASE/"frozen.json").read_text(encoding="utf-8"))
    model=Mistral()
    OUT.mkdir(parents=True,exist_ok=True)
    for task in protocol["tasks"]:
        path=OUT/(task["id"]+".json")
        if path.exists():
            old=json.loads(path.read_text(encoding="utf-8"))
            if old["protocol_sha256"]!=sha(protocol) or old["requested_model"]!=model.model:
                raise ValueError("existing prediction uses different protocol/model")
            continue
        try:
            response=model.ask(SYSTEM,json.dumps(task["query"],ensure_ascii=False),max_tokens=350)
        except ValueError as exc:
            if str(exc)!="model returned non-object JSON": raise
            response={"value":{},"finish_reason":"non_object_json","usage":{}}
        record={"id":task["id"],"protocol_sha256":sha(protocol),
                "query_sha256":sha(task["query"]),"requested_model":model.model,
                "answer":response["value"],"finish_reason":response["finish_reason"],
                "usage":response["usage"]}
        path.write_text(json.dumps(record,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        print(json.dumps({"id":task["id"],"requested_model":model.model,
                          "finish_reason":record["finish_reason"]}),flush=True)


def score() -> dict:
    protocol=json.loads((BASE/"frozen.json").read_text(encoding="utf-8"))
    rows=[]
    for task in protocol["tasks"]:
        record=json.loads((OUT/(task["id"]+".json")).read_text(encoding="utf-8"))
        if record["protocol_sha256"]!=sha(protocol) or record["query_sha256"]!=sha(task["query"]):
            raise ValueError("source or prompt mismatch")
        ans=record["answer"]
        scope=ans.get("scope_tools")
        quote=ans.get("action_quote")
        valid=(record["finish_reason"]=="stop" and isinstance(scope,list)
               and len(set(map(str,scope)))==len(scope)
               and all(isinstance(x,str) and x in task["query"]["tools"] for x in scope)
               and isinstance(quote,str) and bool(quote) and quote in task["query"]["clause"])
        exact=valid and sorted(scope)==sorted(task["expected_scope"])
        rows.append({"id":task["id"],"split":task["split"],"valid":valid,"exact":exact,
                     "expected":task["expected_scope"],"actual":scope,
                     "action_quote":quote,"requested_model":record["requested_model"]})
    result={"protocol_sha256":sha(protocol),"rows":rows,
            "development_exact":sum(r["exact"] for r in rows if r["split"]=="development"),
            "clause_holdout_exact":sum(r["exact"] for r in rows if r["split"]=="clause_holdout")}
    (OUT/"score.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return {k:v for k,v in result.items() if k!="rows"}


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("phase",choices=("freeze","run","score"))
    args=parser.parse_args()
    if args.phase=="freeze":freeze()
    elif args.phase=="run":run()
    else:print(json.dumps(score()))
