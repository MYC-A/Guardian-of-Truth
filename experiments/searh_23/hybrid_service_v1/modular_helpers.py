"""Source-preserving Step-2 evidence and Step-1 policy advisory views.

These helpers never decide an error. GE consists of mechanically parsed
observations and target argument links. GP here is a *surface clause graph*:
exact clauses and their lexical/tool links, not a verified interpretation of
conditions or exceptions. Both retain explicit omissions and source offsets.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
import sys
sys.path.insert(0, str(ROOT / "src"))

from guardian_truth.parsing import parse_events  # noqa: E402
from guardian_truth.provenance import build_graph  # noqa: E402


def evidence_subgraph(prompt: str, response: str, *, max_facts: int = 36,
                      max_arguments: int = 24) -> dict:
    history = parse_events(prompt, "prompt")
    target = parse_events(response, "response")
    graph = build_graph(history, target, max_links=32)
    response_lower = response.casefold()
    target_values = {json.dumps(a.value, ensure_ascii=False, sort_keys=True)
                     for a in graph.arguments}

    def relevance(fact):
        scoped = any(str(e.value).casefold() in response_lower
                     for e in fact.entities if str(e.value))
        same_value = (json.dumps(fact.value, ensure_ascii=False,
                                 sort_keys=True) in target_values)
        return (int(scoped or same_value), fact.event)

    # Retain the most relevant and recent observations, including positive
    # matches; never turn an omitted observation into evidence of absence.
    facts = sorted(graph.facts, key=relevance, reverse=True)[:max_facts]
    arguments = graph.arguments[:max_arguments]
    return {
        "module": "GE/provenance-subgraph-v1",
        "status": "MECHANICAL_OBSERVATIONS_ONLY",
        "facts": [asdict(f) for f in facts],
        "target_arguments": [asdict(a) for a in arguments],
        "issues": list(graph.issues),
        "coverage": {"history_events": len(history),
                     "target_events": len(target),
                     "facts_shown": len(facts), "facts_total": len(graph.facts),
                     "arguments_shown": len(arguments),
                     "arguments_total": len(graph.arguments),
                     "truncated": len(facts) < len(graph.facts) or
                                  len(arguments) < len(graph.arguments)},
        "warning": ("Observed values are not tool-effect guarantees. "
                    "A target argument absent from these facts can still be "
                    "licensed by policy, user input, or computation."),
    }


_BOUNDARY = re.compile(r"(?<=[.!?;])\s+(?=[A-ZА-ЯЁ])")
_MARKERS = re.compile(r"\b(?:if|only if|unless|except|before|after|until|"
                      r"while|never|must|may|should|если|только если|"
                      r"кроме|до|после|нельзя|должен|может)\b", re.I)


def policy_surface_graph(policy: str, tool_names=()) -> dict:
    """Exact source clauses; markers are lexical hints, not parsed logic."""
    boundaries = [0, *(m.end() for m in _BOUNDARY.finditer(policy)), len(policy)]
    nodes = []
    for left, right in zip(boundaries, boundaries[1:]):
        raw = policy[left:right]
        quote = raw.strip()
        if not quote:
            continue
        start = left + raw.index(quote)
        tools = [name for name in tool_names if name in quote]
        nodes.append({"id": f"p{len(nodes)}", "quote": quote,
                      "start": start, "end": start + len(quote),
                      "tool_mentions": sorted(tools),
                      "surface_markers": [m.group(0) for m in
                                          _MARKERS.finditer(quote)],
                      "status": "UNINTERPRETED_SOURCE"})
    edges = []
    for i, node in enumerate(nodes):
        if i:
            edges.append({"from": nodes[i-1]["id"], "to": node["id"],
                          "kind": "NEXT_CLAUSE"})
        for prior in nodes[:i]:
            shared = set(prior["tool_mentions"]) & set(node["tool_mentions"])
            if shared:
                edges.append({"from": prior["id"], "to": node["id"],
                              "kind": "SHARED_TOOL_MENTION",
                              "tools": sorted(shared)})
    return {"module": "GP/surface-clauses-v1", "status": "SURFACE_ONLY",
            "nodes": nodes, "edges": edges,
            "coverage": {"source_chars": len(policy),
                         "quoted_chars": sum(len(n["quote"]) for n in nodes),
                         "clauses": len(nodes),
                         "semantic_complete": False},
            "warning": ("The graph preserves quotes and links but does not "
                        "establish governed action, Boolean scope, or exceptions.")}


def plain_evidence_summary(graph: dict) -> str:
    """Length-comparable prose over the same selected GE facts."""
    lines = []
    for fact in graph["facts"]:
        entity = ", ".join(f"{e['field']}={e['value']}"
                           for e in fact["entities"]) or "unscoped"
        lines.append(f"At event {fact['event']}, {fact['tool']} reported "
                     f"{fact['field']}={fact['value']} for {entity}.")
    for argument in graph["target_arguments"]:
        lines.append(f"Target argument {argument['path']}={argument['value']} "
                     f"has observation status {argument['status']}.")
    if graph["coverage"]["truncated"]:
        lines.append("Some observations were omitted due to the shared size limit.")
    return "\n".join(lines)


def advisory_for(ctx, kind: str) -> tuple[str, dict]:
    if kind == "none":
        return "", {"advisory": "none"}
    ge = evidence_subgraph(ctx.prompt_raw, ctx.response_raw) if kind in {
        "ge", "ge_gp", "plain"} else None
    gp = policy_surface_graph(ctx.policy_text, ctx.catalog.tools) if kind in {
        "gp", "ge_gp"} else None
    blocks = []
    if ge is not None:
        blocks.append(plain_evidence_summary(ge) if kind == "plain" else
                      json.dumps(ge, ensure_ascii=False, separators=(",", ":")))
    if gp is not None:
        blocks.append(json.dumps(gp, ensure_ascii=False,
                                 separators=(",", ":")))
    text = ("ADVISORY VIEWS FROM THE SAME SOURCE (untrusted; verify against "
            "the complete original context above):\n" + "\n".join(blocks))
    return text, {"advisory": kind,
                  "ge": ge["coverage"] if ge else None,
                  "gp": gp["coverage"] if gp else None,
                  "advisory_chars": len(text)}


def formal_advisory(record: dict | None) -> tuple[str, dict]:
    """Render the same frozen model-proposed Φ for graph/no-graph judge arms.

    A solver result is only relative to the translation; the judge receives
    source text elsewhere and must independently check semantic faithfulness.
    """
    if record is None:
        return "", {"formal": "NOT_AVAILABLE"}
    translation = record.get("translation")
    if record.get("status") != "VALID" or not isinstance(translation, dict):
        return "", {"formal": "INVALID_TRANSLATION",
                    "reason": record.get("reason")}
    payload = {"module": "Phi/bounded-signed-Horn-shadow-v1",
               "status": "MODEL_TRANSLATION_UNVERIFIED",
               "relation_relative_to_translation": record["relation"],
               "reason": record["reason"],
               "program": translation,
               "proof": record.get("proof", []),
               "warning": ("Exact source quotes establish provenance only. "
                           "The translation may omit rules, invert necessity, "
                           "or misbind entities. Check against original text.")}
    query = translation.get("query")
    if query is not None and any(fact.get("literal") == query and
            any(source.get("source_id") == "target" for source in fact.get("sources", []))
            for fact in translation.get("facts", [])):
        payload["warning_flags"] = ["QUERY_SOURCED_FROM_TARGET_NOT_INDEPENDENT_EVIDENCE"]
    rendered = json.dumps(payload, ensure_ascii=False,
                          separators=(",", ":"))
    if len(rendered) > 9000:
        return "", {"formal": "TOO_LARGE", "chars": len(rendered)}
    return rendered, {"formal": "ADVISORY", "relation": record["relation"],
                      "chars": len(rendered)}
