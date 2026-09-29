"""CUR arm: the current frozen H2/Stanza frontend ported to Level F.

This is the CURRENT baseline. It reuses the frozen policy_licensing_v1
machinery verbatim (stanza clause+NP candidates, name-blind bge-reranker
grounding) and the Level E opaque-tool resolver fix (le_frontend_fixed):
the resolver sees tool descriptions and stable slot ids, never names.
The generic POS rescue (sentence-initial nominal/adjectival root followed
by a determiner phrase) is ON by default, matching the Level E exploratory
follow-up configuration that recovered missed imperatives.

Output: outputs/CUR/<case_id>.json with the unified candidate schema:

  {"case_id", "arm", "candidates": [
      {"cid_local", "span", "start", "end", "type", "predicate",
       "arguments": [], "relations": [], "grounded_tools", "provenance"}]}

The H2 resolver only labels roles; it has no Level F ontology typing, so
type is UNKNOWN for every candidate (honest default - the old frontend
does not know the new ontology) except role-derived hints that were part
of its frozen output (none here).

Run (on server, main venv):
  python3 lf_cur_frontend.py [original|renamed]
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).parent
PL = HERE.parent / "policy_licensing_v1"
sys.path[:0] = [str(PL)]
from pl_frontend import analyse_case, SUBORDINATORS  # noqa: E402
from pl_common import Mistral, render_tool  # noqa: E402

OUT = HERE / "outputs"

# Resolver prompt: Level E opaque-tool variant (le_frontend_fixed.py).
RESOLVER_SYSTEM = """You see one candidate span from a policy and the three most similar tools from the catalog. Decide what kind of mention the span is by judging the tools from their description and schema (never by name):
- REALIZES_OPERATION: executing the tool performs the action in the span
- CHECKS_PRECONDITION: executing the tool verifies whether the state in the span holds
- OBSERVES_STATE: executing the tool reads or observes the state in the span
- COMMUNICATES: executing the tool sends a communication about the span
- UNRELATED: no tool matches the span
- UNKNOWN: cannot decide
Answer with JSON only: {"label": "..."}."""

LABEL_TO_ROLE = {
    "REALIZES_OPERATION": "OPERATION_EFFECT",
    "CHECKS_PRECONDITION": "PRECONDITION_CHECK",
    "OBSERVES_STATE": "STATE_OBSERVATION",
    "COMMUNICATES": "COMMUNICATION",
}


def secondary_candidates(policy: str, doc) -> list[dict]:
    """Generic POS rescue from le_frontend_fixed.py (structural only)."""
    out = []
    for s in doc.sentences:
        words = s.words
        if len(words) < 3:
            continue
        first, second = words[0], words[1]
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


def opaque_tool(tool: dict, rank: int) -> str:
    return json.dumps({"id": f"slot_{rank}",
                       "description": tool["description"],
                       "input": tool.get("input", {}),
                       "output": tool.get("output", {})})


def load_suite(which: str) -> list[dict]:
    fname = ("level_f_cases.json" if which == "original"
             else "level_f_cases_renamed.json")
    return json.loads((HERE / "frozen" / fname).read_text(encoding="utf-8"))


def main() -> None:
    import numpy as np
    import stanza
    from sentence_transformers import CrossEncoder

    which = sys.argv[1] if len(sys.argv) > 1 else "original"
    nlp = stanza.Pipeline("en", processors="tokenize,pos,lemma,depparse",
                          verbose=False, use_gpu=True)
    rer = CrossEncoder("BAAI/bge-reranker-base", device="cuda",
                       max_length=512,
                       cache_folder="/workspace/guardian/hf_cache")
    client = Mistral(model="ministral-14b-latest", cache_dir=OUT / "_cache")
    outdir = OUT / "CUR"
    outdir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    for case in load_suite(which):
        path = outdir / f"{case['case_id']}.json"
        if path.exists():
            continue
        policy = case["policy"]
        doc = nlp(policy)
        cands = analyse_case(nlp, {"policy": policy})
        seen = {(c["start"], c["end"]) for c in cands}
        for c in secondary_candidates(policy, doc):
            if (c["start"], c["end"]) not in seen:
                cands.append(c)
        # grounding: name-blind rerank over the catalog
        pairs, owners = [], []
        for i, c in enumerate(cands):
            for t in case["tools"]:
                pairs.append((c["span"], render_tool(t)))
                owners.append(i)
        scores = (rer.predict(pairs, batch_size=32,
                              convert_to_numpy=True).tolist()
                  if pairs else [])
        top3: dict[int, list] = {}
        for i, s in zip(owners, scores):
            top3.setdefault(i, []).append((float(s)))
        top_tools = {}
        for i in range(len(cands)):
            tools = list(zip(case["tools"], top3.get(i, [])))
            tools.sort(key=lambda x: -x[1])
            top_tools[i] = [t["name"] for t, _ in tools[:3]]
        # resolver: one narrow question per candidate (opaque slots)
        records = []
        for i, c in enumerate(cands):
            tools3 = []
            for rank, (t, _) in enumerate(
                    sorted(zip(case["tools"], top3.get(i, [])),
                           key=lambda x: -x[1])[:3], start=1):
                tools3.append(opaque_tool(t, rank))
            user = (f"CANDIDATE SPAN: \"{c['span']}\"\n\n"
                    f"SIMILAR TOOLS:\n" + "\n".join(tools3)
                    + "\n\nAnswer with JSON only: {\"label\": \"...\"}")
            ok, label = False, "UNKNOWN"
            for _ in range(4):
                try:
                    rec = client.ask(RESOLVER_SYSTEM, user, max_tokens=120)
                    parsed, err = Mistral.parse_json(rec["raw"])
                    lab = parsed.get("label", "UNKNOWN") if parsed else "UNKNOWN"
                    if isinstance(lab, list) and lab:
                        lab = str(lab[0])
                    if isinstance(lab, str) and lab:
                        label = lab.strip()
                        ok = True
                        break
                except Exception:
                    time.sleep(2)
            role = LABEL_TO_ROLE.get(label, "UNKNOWN")
            records.append({
                "cid_local": f"c{i+1:02d}",
                "span": c["span"], "start": c["start"], "end": c["end"],
                "type": "UNKNOWN",
                "predicate": c.get("verb"),
                "arguments": [],
                "relations": [],
                "role": role,
                "resolver_label": label,
                "grounded_tools": top_tools.get(i, []),
                "is_np": c.get("is_np", False),
                "pos_rescue": c.get("pos_rescue", False),
                "mark": c.get("mark"),
                "provenance": "offsets",
            })
        path.write_text(json.dumps({"case_id": case["case_id"], "arm": "CUR",
                                    "candidates": records}, indent=1) + "\n",
                        encoding="utf-8")
        print(case["case_id"], len(records), flush=True)
    print("CUR done", round(time.time() - t0, 1), "s; calls:",
          client.calls, "usage:", client.usage_total, flush=True)


if __name__ == "__main__":
    main()
