"""Research-only frontend with opaque resolver tool IDs and generic POS rescue.

Grounding still uses the existing name-blind bge reranker. The resolver sees
description/schema and stable slot IDs, never tool names. An uncertain
sentence-initial imperative-looking root may become a SECONDARY candidate;
it is not accepted as an event without a later eventness decision.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).parent
EC = HERE.parent / "event_canon_v1"
PL = HERE.parent / "policy_licensing_v1"
sys.path[:0] = [str(EC), str(PL)]
from pl_frontend import analyse_case, LABEL_TO_ROLE, COND_MARKS, RESOLVER_SYSTEM
from pl_common import Mistral, render_tool
from ec_common import load_suite

OUT = HERE / "outputs"


def secondary_candidates(policy: str, doc) -> list[dict]:
    out = []
    for s in doc.sentences:
        words = s.words
        if len(words) < 3:
            continue
        first, second = words[0], words[1]
        # Structural uncertainty only: any sentence-initial nominal/adjectival
        # token followed by a determiner phrase can be a mistagged imperative.
        # No domain verb list and no automatic event acceptance.
        if first.upos not in {"NOUN", "PROPN", "ADJ"} or second.upos != "DET":
            continue
        if any(w.upos == "VERB" and w.id != first.id for w in words[:4]):
            continue
        toks = [w for w in words if w.upos != "PUNCT"]
        if not toks:
            continue
        st, en = toks[0].start_char, toks[-1].end_char
        out.append({"span": policy[st:en], "start": st, "end": en,
                    "dep": first.deprel.split(":")[0], "mark": None,
                    "verb": first.lemma, "is_np": False, "pos_rescue": True})
    return out


def opaque_tool(tool: dict, rank: int) -> dict:
    return {"id": f"slot_{rank}", "description": tool["description"],
            "input": tool.get("input", {}), "output": tool.get("output", {})}


def main():
    import stanza
    from sentence_transformers import CrossEncoder

    nlp = stanza.Pipeline("en", processors="tokenize,pos,lemma,depparse", verbose=False, use_gpu=True)
    rer = CrossEncoder("BAAI/bge-reranker-base", device="cuda", max_length=512,
                       cache_folder="/workspace/guardian/hf_cache")
    client = Mistral(cache_dir=OUT / "_cache")
    which = os.environ.get("EC_SUITE", "original")
    rescue = os.environ.get("LE_RESCUE", "0") == "1"
    tag = "fixed_rescue" if rescue else "fixed"
    outdir = OUT / ("FRONTEND_" + tag + ("_renamed" if which == "renamed" else ""))
    outdir.mkdir(parents=True, exist_ok=True)
    for case in load_suite(which):
        path = outdir / f"{case['case_id']}.json"
        if path.exists():
            continue
        policy = case["policy"]
        cands = analyse_case(nlp, {"policy": policy})
        if rescue:
            seen = {(c["start"], c["end"]) for c in cands}
            for c in secondary_candidates(policy, nlp(policy)):
                if (c["start"], c["end"]) not in seen:
                    cands.append(c)
        tool_names = [t["name"] for t in case["tools"]]
        pair_inputs = [(c["span"], render_tool(t)) for c in cands for t in case["tools"]]
        scores = rer.predict(pair_inputs, batch_size=32, convert_to_numpy=True) if pair_inputs else []
        events = []
        for i, c in enumerate(cands):
            ss = scores[i*len(tool_names):(i+1)*len(tool_names)]
            ranked = sorted(zip(ss, case["tools"]), key=lambda z: -float(z[0]))[:3]
            user = json.dumps({"policy_span": c["span"],
                               "tools": [opaque_tool(t, j+1) for j, (_, t) in enumerate(ranked)]},
                              ensure_ascii=False)
            rec = client.ask(RESOLVER_SYSTEM, user, max_tokens=200)
            ans, _ = Mistral.parse_json(rec["raw"])
            label = (ans or {}).get("label")
            if isinstance(label, dict):
                label = label.get("label") or label.get("role") or label.get("choice")
            role = LABEL_TO_ROLE.get(label, "UNKNOWN") if isinstance(label, str) else "UNKNOWN"
            if c.get("mark") in COND_MARKS and role == "OPERATION_EFFECT":
                role = "PRECONDITION_CHECK"
            events.append({"span": c["span"], "span_start": c["start"], "span_end": c["end"],
                           "role": role, "governed_tools": [ranked[0][1]["name"]] if ranked else [],
                           "resolver_label": label, "is_np": bool(c.get("is_np")),
                           "dep": c.get("dep"), "mark": c.get("mark"),
                           "pos_rescue": bool(c.get("pos_rescue"))})
        path.write_text(json.dumps({"case_id": case["case_id"], "events": events},
                                   ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(case["case_id"], len(cands), len(events), flush=True)
    print(json.dumps({"model": client.model, "new_calls": client.calls,
                      "usage": client.usage_total}), flush=True)


if __name__ == "__main__":
    main()
