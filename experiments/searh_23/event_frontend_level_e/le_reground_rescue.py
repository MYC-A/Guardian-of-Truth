"""Ground completed rescued spans using unchanged name-blind tool semantics.

The first rescue used the LLM's abbreviated span for tool ranking. This
follow-up fixes that causal defect by re-ranking only after code has restored
the exact full source sentence. E3 results for this arm are exploratory.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).parent
EC = HERE.parent / "event_canon_v1"
PL = HERE.parent / "policy_licensing_v1"
sys.path[:0] = [str(EC), str(PL)]
from pl_common import Mistral, render_tool
from pl_frontend import RESOLVER_SYSTEM, LABEL_TO_ROLE
from le_frontend_fixed import opaque_tool
from le_imperative_completion import rewrite_e3

OUT = HERE / "outputs"


def main():
    from sentence_transformers import CrossEncoder
    rewrite_e3()
    cases = {c["case_id"]: c for c in json.loads((HERE / "frozen" / "frozen_cases.json").read_text(encoding="utf-8"))}
    rer = CrossEncoder("BAAI/bge-reranker-base", device="cuda", max_length=512,
                       cache_folder="/workspace/guardian/hf_cache")
    client = Mistral(cache_dir=OUT / "_cache")
    target = OUT / "FRONTEND_imperative_regrounded"
    target.mkdir(parents=True, exist_ok=True)
    records = OUT / "E3_IMPERATIVE_GROUNDING"
    records.mkdir(parents=True, exist_ok=True)
    for p in sorted((OUT / "FRONTEND_imperative_completed").glob("e_*.json")):
        dest = target / p.name
        if dest.exists():
            continue
        data = json.loads(p.read_text(encoding="utf-8"))
        case = cases[data["case_id"]]
        for event in data["events"]:
            if event.get("dep") != "rescue_imperative":
                continue
            span = event["span"]
            tools = case["tools"]
            scores = rer.predict([(span, render_tool(t)) for t in tools], convert_to_numpy=True)
            ranked = sorted(zip(scores, tools), key=lambda z: -float(z[0]))[:3]
            query = json.dumps({"policy_span": span,
                                "tools": [opaque_tool(t, j+1) for j, (_, t) in enumerate(ranked)]}, ensure_ascii=False)
            rec = client.ask(RESOLVER_SYSTEM, query, max_tokens=200)
            ans, err = Mistral.parse_json(rec["raw"])
            ans = ans if isinstance(ans, dict) else {}
            label = ans.get("label")
            event["previous_role"] = event["role"]
            event["previous_tools"] = event["governed_tools"]
            event["role"] = LABEL_TO_ROLE.get(label, "UNKNOWN") if isinstance(label, str) else "UNKNOWN"
            event["governed_tools"] = [ranked[0][1]["name"]] if ranked else []
            event["resolver_label"] = label
            (records / f"{data['case_id']}__{event['span_start']}.json").write_text(
                json.dumps({"span": span, "scores": [{"name": t["name"], "score": float(s)} for s, t in ranked],
                            "response": rec["raw"], "error": err}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(data["case_id"], span, event["role"], event["governed_tools"], flush=True)
        dest.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"calls": client.calls, "usage": client.usage_total}), flush=True)


if __name__ == "__main__":
    main()
