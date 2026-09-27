"""Frozen, paired comparison of four source-policy parsing architectures.

This is an architecture probe, not a Guardian prediction path.  The runner
never opens the gold file.  Raw API responses and every recursive decision are
cached by protocol hash, arm, case and call index.  See the accompanying report
for the precise adaptations of Req2LTL and NL2Logic.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "experiments/searh_23/policy_architecture_abcd_v1"
OUT = ROOT / "outputs/searh_23/policy_architecture_abcd_v1"
PRIOR = ROOT / "experiments/searh_23/staged_policy_heads_v3/frozen.json"
ARMS = ("A_one_shot", "B_staged", "C_onionl", "D_nl2logic")
KINDS = {"GATE", "FORBID", "PERMIT", "ORDER", "REQUIRE_RESPONSE", "DESCRIPTIVE"}
OPS = {"ATOM", "AND", "OR", "NOT"}


def digest(obj: object) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def atom(quote: str, temporal: str = "NONE") -> dict:
    return {"op": "ATOM", "quote": quote, "temporal": temporal}


def connective(op: str, *children: dict) -> dict:
    return {"op": op, "children": list(children)}


def directive(kind: str, action: str, tools: list[str], condition: dict | None = None,
              *, before: str = "", exception: str = "", exception_type: str = "NONE",
              scope: str = "") -> dict:
    return {"kind": kind, "action_quote": action, "governed_tools": tools,
            "condition": condition, "before_quote": before,
            "exception_quote": exception, "exception_type": exception_type,
            "scope_quote": scope}


def cases() -> list[dict]:
    """Fixed policy selection and hand annotation; not imported during run."""
    prior = {x["id"]: x["query"] for x in json.loads(PRIOR.read_text(encoding="utf-8"))["tasks"]}
    gold = {
        "retail_cancel": [directive("GATE", "cancelled", ["cancel_pending_order"],
             connective("AND", atom("its status is 'pending'", "LATEST"),
                        atom("check its status before taking the action", "PRIOR_TRUE")))],
        "retail_exchange": [directive("GATE", "only be exchanged", ["exchange_delivered_order_items"],
             connective("AND", atom("its status is 'delivered'", "LATEST"),
                        atom("check its status before taking the action", "PRIOR_TRUE"))),
             directive("REQUIRE_RESPONSE", "remind the customer to confirm they have provided all items to be exchanged", [])],
        "airline_baggage": [directive("PERMIT", "add", ["update_reservation_baggages"]),
                            directive("FORBID", "remove checked bags", ["update_reservation_baggages"])],
        "telecom_resume": [directive("FORBID", "lift the suspension", ["resume_line"],
             atom("the line's contract end date is in the past"),
             exception="even if the user has paid all their overdue bills", exception_type="EVEN_IF")],
        "records_dev": [directive("GATE", "published", ["publish_document"],
             connective("AND", atom("its owner approval check has returned approved for that document", "PRIOR_TRUE"),
                        atom("the latest classification check for the same document reports public", "LATEST"))),
             directive("DESCRIPTIVE", "Submitting a publication request does not publish it", [])],
        "hotel_cancellation_order": [directive("ORDER", "the refund SECOND", ["process_refund"],
             before="process cancellation FIRST", scope="For paid reservations")],
        "parcel_handover_transfer": [directive("GATE", "handed over", ["handover_parcel"],
             connective("AND", atom("its barcode check has returned valid", "PRIOR_TRUE"),
                        atom("its latest custody check reports ready", "LATEST"))),
             directive("DESCRIPTIVE", "Filing a handover request does not hand it over", [])],
        "credit_preview_new": [directive("PERMIT", "preview a credit", ["preview_credit"]),
             directive("GATE", "issue a credit", ["issue_credit"], atom("recorded approval", "PRIOR_TRUE"))],
    }
    authored = [
        {"id": "dispatch_or_authored", "query": {"policy":
         "Release a shipment only if either customs clearance is recorded or a supervisor waiver is approved.",
         "tools": {"check_customs": "Read recorded customs clearance; no release.",
                   "check_waiver": "Read supervisor waiver approval; no release.",
                   "release_shipment": "Release the shipment now."}},
         "gold": [directive("GATE", "Release a shipment", ["release_shipment"],
                            connective("OR", atom("customs clearance is recorded", "PRIOR_TRUE"),
                                       atom("a supervisor waiver is approved", "PRIOR_TRUE")))]},
        {"id": "draft_exception_authored", "query": {"policy":
         "Never publish a draft, except when its owner has approved a public preview.",
         "tools": {"check_preview_approval": "Read owner approval for a public preview.",
                   "publish_draft": "Publish a draft now."}},
         "gold": [directive("FORBID", "publish a draft", ["publish_draft"],
                            exception="its owner has approved a public preview", exception_type="EXCEPT")]},
        {"id": "device_nested_authored", "query": {"policy":
         "For replacement devices, verify approval before performing the swap, and notify the customer after the swap.",
         "tools": {"lookup_approval": "Look up approval; does not replace a device.",
                   "perform_swap": "Replace the device.",
                   "notify_customer": "Send a customer notification."}},
         "gold": [directive("GATE", "performing the swap", ["perform_swap"],
                            atom("verify approval", "PRIOR_TRUE"), scope="For replacement devices"),
                  directive("ORDER", "notify the customer", ["notify_customer"],
                            before="performing the swap", scope="For replacement devices")]},
        {"id": "archive_multitool_authored", "query": {"policy":
         "After the latest retention review says cleared, release an archive with either publication tool. Filing a request is not release.",
         "tools": {"review_retention": "Read latest retention status.",
                   "publish_archive": "Release the archive.",
                   "publish_public_copy": "Release a public copy of the archive.",
                   "file_request": "Request a future release; no release."}},
         "gold": [directive("GATE", "release an archive", ["publish_archive", "publish_public_copy"],
                            atom("the latest retention review says cleared", "LATEST")),
                  directive("DESCRIPTIVE", "Filing a request is not release", [])]},
    ]
    rows = [{"id": name, "origin": "viewed_prior_clause", "query": prior[name], "gold": gold[name]}
            for name in gold]
    rows.extend({**row, "origin": "new_authored"} for row in authored)
    return rows


DIRECT_IR = """Return one JSON object {"directives":[...]}. Each independent policy direction is:
{"kind":"GATE|FORBID|PERMIT|ORDER|REQUIRE_RESPONSE|DESCRIPTIVE",
 "action_quote":"exact continuous source substring naming the governed action or response",
 "governed_tools":["exact declared tool names"],
 "condition":null or {"op":"ATOM","quote":"exact source substring","temporal":"NONE|LATEST|PRIOR_TRUE"} or
   {"op":"AND|OR|NOT","children":[condition,...]},
 "before_quote":"exact source substring of required earlier action, or empty",
 "exception_quote":"exact source substring after exception/concession marker, or empty",
 "exception_type":"NONE|EXCEPT|EVEN_IF",
 "scope_quote":"exact source substring of contextual scope, or empty"}.
GATE means a required state/check/approval constrains the action. ORDER means one separate business operation must precede another. A check before an action is GATE. FORBID and PERMIT can name facets of the same tool. Preserve independent response duties and explanatory non-equivalence as separate directives. Do not turn a derived logical contrapositive into another source directive. Copy source wording exactly; no case verdict."""

SYSTEMS = {
    "A": "Read the whole policy and tool catalog. Compile the complete policy directly. " + DIRECT_IR,
    "B_inventory": "Read the whole policy. List ALL independent source directions, including permission and prohibition facets, response duties and descriptive non-equivalence. No derived directions. Return JSON {\"heads\":[{\"kind\":\"GATE|FORBID|PERMIT|ORDER|REQUIRE_RESPONSE|DESCRIPTIVE\",\"head_quote\":\"exact continuous source quote identifying the direction\"}]}. Do not compile conditions or bind tools yet.",
    "B_detail": "Given ONE extracted policy head, compile only that head using the full original policy and tool catalog. " + DIRECT_IR + " Return exactly one directive inside directives; preserve shared context when it applies.",
    "C_macro": "Req2LTL/OnionL stage I: identify the GLOBAL temporal/mode scope before decomposing the clause. Return JSON {\"scope\":\"GLOBAL|MODE|EVENTUAL\",\"scope_quote\":\"exact source substring or empty\",\"clause\":\"the remaining natural-language clause\"}. Default GLOBAL when no overarching scope. A local BEFORE or ONLY IF is a relation within the clause, not a global scope.",
    "C_node": "Req2LTL/OnionL stage II: examine ONLY the outermost semantic construct of this clause. Return JSON {\"op\":\"ATOM|AND|OR|GATE|ORDER|PERMIT|FORBID|EXCEPT|EVEN_IF\",\"left\":\"standalone child clause or empty\",\"right\":\"standalone child clause or empty\"}. ATOM has no children. PERMIT/FORBID unary: left is the governed action. AND/OR combine independent or condition clauses. GATE: left is governed action, right is required condition. ORDER: left is earlier operation, right is governed later operation. EXCEPT: left is base direction, right is exception. EVEN_IF: left is base direction, right is concession that does not cancel it. Choose outermost relation; recurse on children later. Preserve negation and the original scope; do not infer a new directive from a necessary condition.",
    "D_rephrase": "NL2Logic preprocessing: rephrase the policy into clear natural language ONLY where an explicit quantifier or pronoun needs disambiguation. Keep every independent directive, condition, exception and temporal relation. Do not simplify a prohibition into permission. Return JSON {\"rephrased\":\"complete policy in natural language\"}. If no rephrase is needed, copy the input unchanged. This is an input-normalization step, not a logic translation.",
    "D_select": "NL2Logic-style parser selector: classify ONLY this current clause as ATOMIC, QUANTIFIED, LOGICAL or NEGATION. A logical clause has an outermost AND/OR/ONLY_IF/IF/BEFORE/EXCEPT/EVEN_IF/PERMIT/FORBID relation. QUANTIFIED is an explicit all/every/each/no entity scope, not merely an indefinite noun. Return JSON {\"type\":\"ATOMIC|QUANTIFIED|LOGICAL|NEGATION\"}.",
    "D_logical": "NL2Logic-style specialized logical parser: identify ONLY the outermost operator and rewrite its operands as standalone child clauses. Return JSON {\"op\":\"AND|OR|GATE|ORDER|PERMIT|FORBID|EXCEPT|EVEN_IF\",\"left\":\"child clause or empty\",\"right\":\"child clause or empty\"}. GATE: left governed action, right necessary condition. ORDER: left earlier operation, right later governed operation. PERMIT/FORBID unary: left governed action. EXCEPT and EVEN_IF: left base direction, right exception/concession. Do not parse nested operators here; children will be parsed recursively. Never treat a lookup as executing a later action.",
    "D_quantified": "NL2Logic-style quantified parser: extract only the outermost explicit quantifier and rewrite the remaining clause using a variable if needed. Return JSON {\"quantifier\":\"FORALL|EXISTS\",\"variable\":\"x\",\"clause\":\"remaining standalone clause\"}. Preserve inner conditions for later recursive parsing.",
    "D_negation": "NL2Logic-style unary parser: remove only the outermost logical negation; return JSON {\"op\":\"NOT\",\"clause\":\"remaining positive standalone clause\"}.",
    "leaf": "Atomic proposition normalization shared by recursive arms. Read ONE terminal clause and the original policy/tool catalog. Return JSON {\"role\":\"ACTION|CONDITION|RESPONSE|DESCRIPTIVE\",\"source_quote\":\"one exact continuous substring from original policy corresponding to this clause\",\"tools\":[\"declared names that EXECUTE this action; no lookup tools for an action\"],\"temporal\":\"NONE|LATEST|PRIOR_TRUE\"}. For a condition, RESPONSE or DESCRIPTIVE, tools must be empty. A check that has returned is PRIOR_TRUE; latest/current is LATEST. Preserve exact source spelling. If no unique source substring supports the clause, use empty source_quote. No verdict.",
}


def freeze() -> None:
    rows = cases()
    for row in rows:
        policy = row["query"]["policy"]
        for d in row["gold"]:
            for quote in all_quotes(d):
                if quote and policy.count(quote) != 1:
                    raise ValueError(f"gold quote not unique and literal: {row['id']}: {quote}")
            if not set(d["governed_tools"]) <= set(row["query"]["tools"]):
                raise ValueError("gold tool absent: " + row["id"])
    protocol = {"version": 1, "model_source": "MISTRAL_MODEL in server env",
                "temperature": 0, "max_tokens": 1300, "max_nodes": 18,
                "max_depth": 6, "arms": list(ARMS), "systems": SYSTEMS,
                "cases": [{k: v for k, v in row.items() if k != "gold"} for row in rows],
                "source_references": {
                    "req2ltl": "https://arxiv.org/html/2512.17334",
                    "req2ltl_repo": "https://github.com/Meng-Nan-MZ/Req2LTL",
                    "nl2logic": "https://aclanthology.org/2026.findings-eacl.317/",
                    "nl2logic_repo": "https://github.com/peng-gao-lab/nl2logic"}}
    gold = {row["id"]: row["gold"] for row in rows}
    BASE.mkdir(parents=True, exist_ok=True)
    for name, data in (("frozen.json", protocol), ("gold.json", gold)):
        path = BASE / name
        payload = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
        if path.exists() and path.read_text(encoding="utf-8") != payload:
            raise ValueError(f"refusing to change frozen {name}")
        path.write_text(payload, encoding="utf-8")
    print(json.dumps({"cases": len(rows), "protocol_sha256": digest(protocol),
                      "gold_sha256": digest(gold)}))


def all_quotes(obj: object) -> list[str]:
    if isinstance(obj, list):
        return sum((all_quotes(x) for x in obj), [])
    if isinstance(obj, dict):
        return [v for k, v in obj.items() if k in {"action_quote", "quote", "before_quote", "exception_quote", "scope_quote"} and isinstance(v, str) and v] + sum((all_quotes(v) for k, v in obj.items() if k not in {"action_quote", "quote", "before_quote", "exception_quote", "scope_quote"}), [])
    return []


class MistralRaw:
    def __init__(self) -> None:
        sys.path.insert(0, str(ROOT / "experiments/searh_23"))
        from tq_questions import mistral_settings
        config = mistral_settings()
        self.model = config["MISTRAL_MODEL"]
        self.key = config["MISTRAL_API_KEY"]
        if not self.key:
            raise RuntimeError("MISTRAL_API_KEY missing")
        self.next_call = 0.0

    def ask(self, system: str, query: dict, max_tokens: int,
            response_format: dict | None = None) -> dict:
        payload = {"model": self.model, "temperature": 0, "max_tokens": max_tokens,
                   "response_format": response_format or {"type": "json_object"},
                   "messages": [{"role": "system", "content": system},
                                {"role": "user", "content": json.dumps(query, ensure_ascii=False)}]}
        for attempt in range(4):
            if self.next_call > time.monotonic():
                time.sleep(self.next_call - time.monotonic())
            self.next_call = time.monotonic() + 2.0
            request = urllib.request.Request("https://api.mistral.ai/v1/chat/completions",
                data=json.dumps(payload, ensure_ascii=False).encode(),
                headers={"Authorization": "Bearer " + self.key, "Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(request, timeout=180) as response:
                    body = json.load(response)
                break
            except urllib.error.HTTPError as exc:
                if exc.code != 429 or attempt == 3:
                    detail = exc.read(1200).decode("utf-8", "replace")
                    raise RuntimeError(f"Mistral HTTP {exc.code}: {detail}") from None
                time.sleep(min(120, max(20, float(exc.headers.get("Retry-After", "30")))))
        choice = body["choices"][0]
        raw = choice["message"].get("content") or ""
        try:
            value = json.loads(raw)
            error = "" if isinstance(value, dict) else "non_object_json"
        except (ValueError, TypeError):
            value, error = {}, "invalid_json"
        return {"raw": raw, "answer": value if isinstance(value, dict) else {},
                "error": error, "finish_reason": choice.get("finish_reason"),
                "usage": body.get("usage", {})}


class Recorder:
    def __init__(self, protocol: dict, model: MistralRaw, arm: str, case: dict):
        self.protocol, self.model, self.arm, self.case = protocol, model, arm, case
        self.count = 0
        self.calls = []

    def ask(self, stage: str, query: dict) -> dict:
        index = self.count
        self.count += 1
        path = OUT / "raw" / self.arm / self.case["id"] / f"{index:03d}_{stage}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        signature = digest({"protocol": digest(self.protocol), "model": self.model.model,
                            "stage": stage, "query": query})
        if path.exists():
            record = json.loads(path.read_text(encoding="utf-8"))
            if record["signature"] != signature:
                raise ValueError("cached call mismatch: " + str(path))
        else:
            result = self.model.ask(self.protocol["systems"][stage], query,
                                    self.protocol["max_tokens"],
                                    self.protocol.get("schemas", {}).get(stage))
            record = {"signature": signature, "stage": stage,
                      "model": self.model.model, "query": query, **result}
            path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        self.calls.append({"stage": stage, "path": str(path.relative_to(OUT)),
                           "error": record["error"], "finish_reason": record["finish_reason"]})
        return record["answer"] if not record["error"] and record["finish_reason"] == "stop" else {}


def literal(policy: str, quote: object) -> str:
    return quote if isinstance(quote, str) and quote and policy.count(quote) == 1 else ""


def leaf(rec: Recorder, clause: str) -> dict:
    answer = rec.ask("leaf", {"clause": clause, **rec.case["query"]})
    policy = rec.case["query"]["policy"]
    role = answer.get("role") if answer.get("role") in {"ACTION", "CONDITION", "RESPONSE", "DESCRIPTIVE"} else "UNKNOWN"
    tools = answer.get("tools") if isinstance(answer.get("tools"), list) else []
    tools = [x for x in tools if isinstance(x, str) and x in rec.case["query"]["tools"]]
    return {"op": "ATOM", "role": role, "quote": literal(policy, answer.get("source_quote")),
            "tools": sorted(set(tools)) if role == "ACTION" else [],
            "temporal": answer.get("temporal") if answer.get("temporal") in {"NONE", "LATEST", "PRIOR_TRUE"} else "NONE"}


def recurse(rec: Recorder, text: str, method: str, depth: int = 0) -> dict:
    if depth >= rec.protocol["max_depth"] or rec.count >= rec.protocol["max_nodes"] * 3 or not text.strip():
        return {"op": "ERROR", "reason": "recursion_limit_or_empty", "text": text}
    if method == "C":
        answer = rec.ask("C_node", {"clause": text, **rec.case["query"]})
        op = answer.get("op")
    else:
        select = rec.ask("D_select", {"clause": text})
        typ = select.get("type")
        if typ == "ATOMIC":
            return leaf(rec, text)
        if typ == "QUANTIFIED":
            q = rec.ask("D_quantified", {"clause": text})
            child = q.get("clause")
            if not isinstance(child, str) or not child or child == text:
                return {"op": "ERROR", "reason": "bad_quantifier", "text": text}
            return {"op": q.get("quantifier", "FORALL"), "child": recurse(rec, child, method, depth + 1)}
        if typ == "NEGATION":
            q = rec.ask("D_negation", {"clause": text})
            child = q.get("clause")
            if not isinstance(child, str) or not child or child == text:
                return {"op": "ERROR", "reason": "bad_negation", "text": text}
            return {"op": "NOT", "child": recurse(rec, child, method, depth + 1)}
        if typ != "LOGICAL":
            return {"op": "ERROR", "reason": "bad_selector", "text": text}
        answer = rec.ask("D_logical", {"clause": text, **rec.case["query"]})
        op = answer.get("op")
    if op == "ATOM":
        return leaf(rec, text)
    if op not in {"AND", "OR", "GATE", "ORDER", "PERMIT", "FORBID", "EXCEPT", "EVEN_IF"}:
        return {"op": "ERROR", "reason": "bad_operator", "text": text, "answer": answer}
    left, right = answer.get("left"), answer.get("right")
    if not isinstance(left, str) or not left.strip() or left.strip() == text.strip():
        return {"op": "ERROR", "reason": "no_progress_left", "text": text, "answer": answer}
    unary = op in {"PERMIT", "FORBID"}
    if not unary and (not isinstance(right, str) or not right.strip() or right.strip() == text.strip()):
        return {"op": "ERROR", "reason": "no_progress_right", "text": text, "answer": answer}
    node = {"op": op, "left": recurse(rec, left, method, depth + 1)}
    if not unary:
        node["right"] = recurse(rec, right, method, depth + 1)
    return node


def condition(node: dict) -> dict | None:
    op = node.get("op")
    if op == "ATOM" and node.get("quote"):
        return atom(node["quote"], node.get("temporal", "NONE"))
    if op in {"AND", "OR"}:
        left, right = condition(node.get("left", {})), condition(node.get("right", {}))
        return connective(op, left, right) if left and right else None
    if op == "NOT":
        child = condition(node.get("child", {}))
        return connective("NOT", child) if child else None
    return None


def action(node: dict) -> tuple[str, list[str]]:
    if node.get("op") == "ATOM" and node.get("role") in {"ACTION", "RESPONSE", "DESCRIPTIVE"}:
        return node.get("quote", ""), node.get("tools", [])
    return "", []


def compile_tree(node: dict, scope: str = "") -> tuple[list[dict], list[str]]:
    op = node.get("op")
    if op in {"GLOBAL", "FORALL", "EXISTS"}:
        return compile_tree(node.get("child", {}), scope)
    if op == "SCOPE":
        return compile_tree(node.get("child", {}), node.get("quote", ""))
    if op == "AND":
        l, le = compile_tree(node.get("left", {}), scope)
        r, re = compile_tree(node.get("right", {}), scope)
        return l + r, le + re
    if op in {"GATE", "ORDER", "PERMIT", "FORBID", "EXCEPT", "EVEN_IF"}:
        left, right = node.get("left", {}), node.get("right", {})
        if op in {"EXCEPT", "EVEN_IF"}:
            ds, errors = compile_tree(left, scope)
            q = condition(right)
            quote = q.get("quote", "") if q and q.get("op") == "ATOM" else ""
            if not quote:
                errors.append("exception_or_concession_unbound")
            for d in ds:
                d["exception_quote"] = quote
                d["exception_type"] = op
            return ds, errors
        if op in {"PERMIT", "FORBID"}:
            quote, tools = action(left)
            return ([directive(op, quote, tools, scope=scope)] if quote else [],
                    [] if quote else ["unbound_" + op.lower()])
        if op == "GATE":
            quote, tools = action(left)
            cond = condition(right)
            return ([directive("GATE", quote, tools, cond, scope=scope)] if quote and cond else [],
                    [] if quote and cond else ["unbound_gate"])
        before, _ = action(left)
        quote, tools = action(right)
        return ([directive("ORDER", quote, tools, before=before, scope=scope)] if before and quote else [],
                [] if before and quote else ["unbound_order"])
    if op == "ATOM":
        role = node.get("role")
        if role in {"RESPONSE", "DESCRIPTIVE"} and node.get("quote"):
            return [directive("REQUIRE_RESPONSE" if role == "RESPONSE" else "DESCRIPTIVE",
                              node["quote"], [], scope=scope)], []
        return [], ["orphan_atom:" + str(role)]
    return [], ["uncompiled:" + str(op)]


def normalize_directives(answer: object, policy: str, catalog: dict) -> tuple[list[dict], list[str]]:
    values = answer.get("directives") if isinstance(answer, dict) else None
    if not isinstance(values, list):
        return [], ["no_directives_array"]
    result, errors = [], []
    for i, row in enumerate(values[:12]):
        if not isinstance(row, dict) or row.get("kind") not in KINDS:
            errors.append(f"bad_directive_{i}")
            continue
        tools = row.get("governed_tools")
        if not isinstance(tools, list) or any(not isinstance(x, str) or x not in catalog for x in tools):
            errors.append(f"bad_tools_{i}")
            tools = []
        normalized = {"kind": row["kind"], "action_quote": literal(policy, row.get("action_quote")),
                      "governed_tools": sorted(set(tools)),
                      "condition": normalize_condition(row.get("condition"), policy),
                      "before_quote": literal(policy, row.get("before_quote")),
                      "exception_quote": literal(policy, row.get("exception_quote")),
                      "exception_type": row.get("exception_type") if row.get("exception_type") in {"NONE", "EXCEPT", "EVEN_IF"} else "NONE",
                      "scope_quote": literal(policy, row.get("scope_quote"))}
        if not normalized["action_quote"]:
            errors.append(f"bad_action_span_{i}")
        result.append(normalized)
    if len(values) > 12:
        errors.append("too_many_directives")
    return result, errors


def normalize_condition(value: object, policy: str) -> dict | None:
    if not isinstance(value, dict):
        return None
    op = value.get("op")
    if op == "ATOM":
        quote = literal(policy, value.get("quote"))
        temporal = value.get("temporal")
        return atom(quote, temporal if temporal in {"NONE", "LATEST", "PRIOR_TRUE"} else "NONE") if quote else None
    if op in {"AND", "OR", "NOT"} and isinstance(value.get("children"), list):
        children = [normalize_condition(x, policy) for x in value["children"]]
        if len(children) >= (1 if op == "NOT" else 2) and all(children):
            return connective(op, *children)
    return None


def run_one(protocol: dict, model: MistralRaw, arm: str, case: dict) -> dict:
    rec = Recorder(protocol, model, arm, case)
    query, policy = case["query"], case["query"]["policy"]
    errors: list[str] = []
    if arm == "A_one_shot":
        answer = rec.ask("A", query)
        directives, errors = normalize_directives(answer, policy, query["tools"])
        tree = None
    elif arm == "B_staged":
        heads = rec.ask("B_inventory", query).get("heads")
        directives, tree = [], None
        if not isinstance(heads, list):
            errors.append("invalid_inventory")
        else:
            for index, head in enumerate(heads[:12]):
                if not isinstance(head, dict) or head.get("kind") not in KINDS or not literal(policy, head.get("head_quote")):
                    errors.append(f"invalid_head_{index}")
                    continue
                answer = rec.ask("B_detail", {**query, "head": head})
                ds, es = normalize_directives(answer, policy, query["tools"])
                if len(ds) != 1:
                    errors.append(f"detail_count_{index}:{len(ds)}")
                directives.extend(ds)
                errors.extend(es)
            if len(heads) > 12:
                errors.append("too_many_heads")
    elif arm == "C_onionl":
        macro = rec.ask("C_macro", query)
        clause = macro.get("clause")
        if not isinstance(clause, str) or not clause.strip():
            clause = policy
            errors.append("invalid_macro_clause")
        scope = literal(policy, macro.get("scope_quote"))
        tree = recurse(rec, clause, "C")
        if scope:
            tree = {"op": "SCOPE", "quote": scope, "child": tree}
        directives, es = compile_tree(tree)
        errors.extend(es)
    else:
        rephrased = rec.ask("D_rephrase", {"policy": policy}).get("rephrased")
        if not isinstance(rephrased, str) or not rephrased.strip():
            rephrased = policy
            errors.append("invalid_rephrase")
        tree = recurse(rec, rephrased, "D")
        directives, es = compile_tree(tree)
        errors.extend(es)
    result = {"case_id": case["id"], "arm": arm, "model": model.model,
              "protocol_sha256": digest(protocol), "query_sha256": digest(query),
              "directives": directives, "tree": tree, "errors": errors, "calls": rec.calls}
    path = OUT / "results" / arm / (case["id"] + ".json")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        old = json.loads(path.read_text(encoding="utf-8"))
        if old != result:
            raise ValueError("result changed on resume: " + str(path))
    else:
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def run() -> None:
    protocol = json.loads((BASE / "frozen.json").read_text(encoding="utf-8"))
    model = MistralRaw()
    print(json.dumps({"model": model.model, "cases": len(protocol["cases"]),
                      "protocol_sha256": digest(protocol)}), flush=True)
    for case in protocol["cases"]:
        for arm in protocol["arms"]:
            result = run_one(protocol, model, arm, case)
            print(json.dumps({"case": case["id"], "arm": arm,
                              "directives": len(result["directives"]),
                              "errors": result["errors"], "calls": len(result["calls"])}), flush=True)


def cond_shape(value: dict | None, *, temporal: bool) -> object:
    if not value:
        return None
    if value.get("op") == "ATOM":
        return ("ATOM", value.get("quote"), value.get("temporal") if temporal else None)
    return (value.get("op"), tuple(cond_shape(x, temporal=temporal) for x in value.get("children", [])))


def exact(d: dict) -> tuple:
    return (d.get("kind"), d.get("action_quote"), tuple(sorted(d.get("governed_tools", []))),
            cond_shape(d.get("condition"), temporal=True), d.get("before_quote"),
            d.get("exception_quote"), d.get("exception_type"), d.get("scope_quote"))


def score() -> dict:
    protocol = json.loads((BASE / "frozen.json").read_text(encoding="utf-8"))
    gold = json.loads((BASE / "gold.json").read_text(encoding="utf-8"))
    rows = []
    for case in protocol["cases"]:
        expected = gold[case["id"]]
        for arm in protocol["arms"]:
            result = json.loads((OUT / "results" / arm / (case["id"] + ".json")).read_text(encoding="utf-8"))
            if result["protocol_sha256"] != digest(protocol) or result["query_sha256"] != digest(case["query"]):
                raise ValueError("result/protocol mismatch")
            found = result["directives"]
            used: set[int] = set()
            matches = []
            for g in expected:
                candidates = [(i, p) for i, p in enumerate(found) if i not in used and
                              p.get("kind") == g["kind"] and p.get("action_quote") == g["action_quote"]]
                if candidates:
                    i, p = max(candidates, key=lambda ip: (ip[1].get("action_quote") == g["action_quote"],
                                                          bool(set(ip[1].get("governed_tools", [])) & set(g["governed_tools"]))))
                    used.add(i)
                    matches.append((g, p))
            spans = set(all_quotes(found))
            required = set(all_quotes(expected))
            temporal_gold = {q for g in expected for q in temporal_atoms(g.get("condition"))}
            temporal_found = {q for p in found for q in temporal_atoms(p.get("condition"))}
            temporal_gold |= {("BEFORE", g["action_quote"], g["before_quote"]) for g in expected if g["before_quote"]}
            temporal_found |= {("BEFORE", p["action_quote"], p["before_quote"]) for p in found if p["before_quote"]}
            row = {"case_id": case["id"], "origin": case["origin"], "arm": arm,
                   "gold_directives": len(expected), "found_directives": len(found),
                   "directive_match": len(matches),
                   "scope_match": sum(set(g["governed_tools"]) == set(p.get("governed_tools", [])) and
                                      g["scope_quote"] == p.get("scope_quote") for g, p in matches),
                   "logic_match": sum(cond_shape(g.get("condition"), temporal=False) ==
                                      cond_shape(p.get("condition"), temporal=False) and
                                      g.get("exception_quote") == p.get("exception_quote") and
                                      g.get("exception_type") == p.get("exception_type") for g, p in matches),
                   "temporal_match": len(temporal_gold & temporal_found),
                   "temporal_total": len(temporal_gold),
                   "span_hit": len(required & spans), "span_total": len(required),
                   "exact_ir": Counter(map(exact, expected)) == Counter(map(exact, found)),
                   "missing_directives": [g for g in expected if exact(g) not in Counter(map(exact, found))],
                   "extra_directives": [p for p in found if exact(p) not in Counter(map(exact, expected))],
                   "missing_spans": sorted(required - spans),
                   "errors": result["errors"], "calls": len(result["calls"])}
            rows.append(row)
    summary = {}
    for arm in protocol["arms"]:
        a = [r for r in rows if r["arm"] == arm]
        summary[arm] = {key: sum(int(r[key]) for r in a) for key in
                        ("gold_directives", "found_directives", "directive_match", "scope_match",
                         "logic_match", "temporal_match", "temporal_total", "span_hit", "span_total", "exact_ir", "calls")}
    data = {"protocol_sha256": digest(protocol), "gold_sha256": digest(gold),
            "summary": summary, "rows": rows}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "score.json").write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


def temporal_atoms(value: dict | None) -> list[tuple]:
    if not value:
        return []
    if value.get("op") == "ATOM":
        return [(value.get("quote"), value.get("temporal"))] if value.get("temporal") not in (None, "NONE") else []
    return sum((temporal_atoms(x) for x in value.get("children", [])), [])


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("freeze", "run", "score"))
    args = parser.parse_args()
    if args.phase == "freeze":
        freeze()
    elif args.phase == "run":
        run()
    else:
        print(json.dumps(score(), ensure_ascii=False, indent=2))
