"""Controlled model comparison: frozen atoms + real source-clause scopes.

No cases/gold are sent to the provider. Records requested AND returned model,
raw message, prompt hash and input hash. One attempt per request, no retries.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

from policy_atoms_probe_v1 import SYSTEM, fixture, query, signature, valid_atom
from build_policy_atoms_v1 import ROOT, SPECS
from tq_questions import json_object, mistral_settings

BASE = ROOT / "experiments/searh_23/policy_model_ab_v1"
OUT = ROOT / "outputs/searh_23/policy_model_ab_v1"
MODELS = {"small": "ministral-14b-2512", "medium": "mistral-medium-2604"}
SCOPE_SYSTEM = '''Read one original precondition clause and the declared tool catalog. Return JSON only: {"scope_tools":["tool_name"],"action_quote":"exact continuous substring of the clause identifying the action constrained"}. Scope belongs to the WHOLE clause, shared by all its prerequisites. Include the current tools which perform the action subject to the prerequisite. A tool merely looking up the prerequisite does not perform that later action. Select from declared tools using their descriptions. Do not evaluate any trajectory, rewrite the source policy, or issue SAFE. If the clause does not define a precondition you can map, return {"scope_tools":[],"action_quote":""}.'''


def sha(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def freeze() -> None:
    service = json.loads((ROOT / "outputs/searh_23/call_condition_probe/service_desk_v1_renamed/input.json").read_text(encoding="utf-8"))["inputs"][0]
    hotel = json.loads((ROOT / "outputs/searh_23/call_condition_probe/hotel_v2_calls/input.json").read_text(encoding="utf-8"))["inputs"][0]
    def bullets(text: str) -> list[str]:
        import re
        return [" ".join(x.split()) for x in re.findall(r"(?m)^- (.*(?:\n  [^\n]+)*)", text)]
    sb, hb = bullets(service["policy"]), bullets(hotel["policy"])
    choices = [("service_identity",service,sb[0],["perform_swap","issue_fee_credit"]),
               ("service_authorization",service,sb[1],["perform_swap"]),
               ("hotel_identity",hotel,hb[0],["modify_reservation","cancel_reservation"]),
               ("hotel_approval",hotel,hb[2],["process_refund"]),
               ("hotel_cancellation_order",hotel,hb[6],["process_refund"])]
    tasks = []
    for name in SPECS:
        data, digest = fixture(name)
        tasks.append({"id": "atoms/"+name, "kind": "atoms", "system": SYSTEM,
                      "query": query(data), "fixture_sha256": digest})
    for name, source, clause, gold in choices:
        if clause not in " ".join(source["policy"].split()):
            raise ValueError("source clause mismatch")
        tasks.append({"id": "scope/"+name, "kind": "scope", "system": SCOPE_SYSTEM,
                      "query": {"clause": clause, "tools": source["tools"]},
                      "expected_scope": gold})
    protocol = {"models": MODELS, "temperature": 0, "max_tokens": 1100,
                "scope": "seen diagnostic cases; capacity/scope comparison, not new benchmark",
                "tasks": tasks}
    BASE.mkdir(parents=True, exist_ok=True)
    path=BASE / "frozen.json"
    payload=json.dumps(protocol,ensure_ascii=False,indent=2)+"\n"
    if path.exists() and path.read_text(encoding="utf-8") != payload:
        raise ValueError("frozen protocol changed")
    path.write_text(payload,encoding="utf-8")
    print(json.dumps({"tasks":len(tasks),"protocol_sha256":sha(protocol)}))


def run(arm: str) -> None:
    protocol=json.loads((BASE/"frozen.json").read_text(encoding="utf-8"))
    key=mistral_settings()["MISTRAL_API_KEY"]
    if not key: raise RuntimeError("missing API key")
    folder=OUT/arm
    folder.mkdir(parents=True,exist_ok=True)
    for task in protocol["tasks"]:
        path=folder/(task["id"].replace("/","__")+".json")
        if path.exists():
            saved=json.loads(path.read_text(encoding="utf-8"))
            if saved["protocol_sha256"] != sha(protocol): raise ValueError("protocol changed")
            continue
        payload={"model":protocol["models"][arm],"temperature":0,"max_tokens":1100,
                 "response_format":{"type":"json_object"},
                 "messages":[{"role":"system","content":task["system"]},
                             {"role":"user","content":json.dumps(task["query"],ensure_ascii=False)}]}
        record={"id":task["id"],"protocol_sha256":sha(protocol),"request_sha256":sha(payload),
                "requested_model":payload["model"],"request_parameters":{"temperature":0,"max_tokens":1100}}
        started=time.monotonic()
        req=urllib.request.Request("https://api.mistral.ai/v1/chat/completions",
            data=json.dumps(payload,ensure_ascii=False).encode(),
            headers={"Authorization":"Bearer "+key,"Content-Type":"application/json"})
        try:
            with urllib.request.urlopen(req,timeout=180) as response: body=json.load(response)
            choice=body["choices"][0]
            content=choice["message"].get("content")
            record.update(returned_model=body.get("model"),response_id=body.get("id"),
                          usage=body.get("usage"),finish_reason=choice.get("finish_reason"),raw_content=content)
            try: record["answer"]=json_object(content)
            except (ValueError,TypeError,AttributeError): record["parse_error"]="not_json_object"
        except urllib.error.HTTPError as exc:
            record["http_status"]=exc.code
        except Exception as exc:
            record["transport_error"]=type(exc).__name__
        record["seconds"]=round(time.monotonic()-started,3)
        path.write_text(json.dumps(record,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        print(json.dumps({"arm":arm,"id":task["id"],"model":record.get("returned_model"),
                          "finish":record.get("finish_reason"),"http_status":record.get("http_status")}),flush=True)
        if "http_status" in record or "transport_error" in record: break
        time.sleep(2)


def score(arm: str) -> dict:
    protocol=json.loads((BASE/"frozen.json").read_text(encoding="utf-8"))
    rows=[]
    for task in protocol["tasks"]:
        path=OUT/arm/(task["id"].replace("/","__")+".json")
        if not path.exists(): raise ValueError("incomplete run")
        record=json.loads(path.read_text(encoding="utf-8"))
        if record["protocol_sha256"]!=sha(protocol):raise ValueError("protocol mismatch")
        answer=record.get("answer",{})
        valid=record.get("finish_reason")=="stop"
        if task["kind"]=="atoms":
            data,_=fixture(task["id"].split("/")[1])
            atoms=answer.get("atoms")
            unsupported=answer.get("unsupported")
            valid=valid and type(unsupported) is bool and isinstance(atoms,list)
            valid=valid and (atoms==[] if unsupported else bool(atoms) and all(valid_atom(a,data) for a in atoms))
            actual=[signature(a) for a in atoms] if valid and not unsupported else []
            expected=[signature(a) for a in data["gold_atoms"]]
            exact=valid and unsupported==data["expected_unsupported"] and sorted(actual)==sorted(expected)
        else:
            scopes=answer.get("scope_tools")
            quote=answer.get("action_quote")
            valid=valid and isinstance(scopes,list) and all(isinstance(s,str) for s in scopes)
            valid=valid and isinstance(quote,str) and bool(quote) and quote in task["query"]["clause"]
            exact=valid and sorted(scopes)==sorted(task["expected_scope"])
        rows.append({"id":task["id"],"valid":bool(valid),"exact":bool(exact),
                     "requested_model":record["requested_model"],"returned_model":record.get("returned_model"),
                     "response_sha256":sha(record),"answer":answer})
    report={"arm":arm,"protocol_sha256":sha(protocol),"rows":rows,
            "atoms_exact":sum(r["exact"] for r in rows if r["id"].startswith("atoms/")),
            "scope_exact":sum(r["exact"] for r in rows if r["id"].startswith("scope/"))}
    (OUT/arm/"score.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return {k:v for k,v in report.items() if k!="rows"}


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("phase",choices=("freeze","run","score"))
    parser.add_argument("arm",nargs="?",choices=tuple(MODELS))
    args=parser.parse_args()
    if args.phase=="freeze":freeze()
    elif args.phase=="run":run(args.arm)
    else:print(json.dumps(score(args.arm)))
