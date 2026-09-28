"""LLM-based frontend arms (Mistral API backend).

  DEEPKE  - DeepKE-LLM InstructKGC instruction paradigm: the EXACT English
            event-extraction template (eet_template.json, template "0")
            from the DeepKE repository with the Level F schema, asked to
            answer in a JSON format. This gives the DeepKE-LLM paradigm a
            real run; the supervised deepke pip modules require training
            data and stay out of the zero-shot comparison (documented).
  LLM_SG  - schema-guided extraction control with our own prompt: one call
            proposing the full typed candidate graph (mentions + types +
            arguments + semantic links). Same paradigm, our infra - the
            control that separates "ready system value" from "LLM value".

Both arms are name-blind (no tool names anywhere).

Run (server, main venv):
  python3 lf_llm_frontends.py DEEPKE|LLM_SG [original|renamed]
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).parent
PL = HERE.parent / "policy_licensing_v1"
sys.path[:0] = [str(PL)]
from pl_common import Mistral  # noqa: E402

OUT = HERE / "outputs"

PHRASE = {
    "EVENT": "action or task to be performed",
    "EVENT_REFERENCE": "reference to an action or task",
    "STATE_OR_FACET": "state or condition of an action",
    "ARTIFACT": "document, report, log or record",
    "CHECK": "verification or checking action",
    "ENTITY": "physical object or participant",
}
PHRASE_TO_TYPE = {v: k for k, v in PHRASE.items()}

# DeepKE InstructKGC English event-extraction template (verbatim,
# eet_template.json -> en -> template -> "0").
DEEPKE_TEMPLATE = (
    "As an event analysis specialist, you need to review the input and "
    "determine possible events based on the event type directory: "
    "{s_schema}. All answers should be based on the {s_format} format. If "
    "the event type does not match, please mark with NAN.")

LLM_SG_SYSTEM = """You are a precise information extraction engine for workplace policies. You propose a TYPED SEMANTIC MENTION GRAPH. Every proposed span must be an EXACT substring of the policy text, copied character by character. Never paraphrase.
Mention types:
- EVENT: a verbal clause naming an action, operation or check to be performed (imperative, passive or participial)
- EVENT_REFERENCE: a noun phrase or pronoun that refers to an action mentioned elsewhere
- STATE_OR_FACET: a clause asserting a state or facet of an action (complete, passed, valid, found, recorded)
- ARTIFACT: a document, report, log or record
- CHECK: a verification action over a state or event
- ENTITY: a physical object, participant, time or value
Semantic links (between proposed mentions):
- SAME_EVENT: two EVENT mentions of the same occurrence
- REFERENCE_OF: an EVENT_REFERENCE points to the EVENT it refers to
- STATE_OF: a STATE_OR_FACET asserts a state of an event
- ARTIFACT_ABOUT: an ARTIFACT documents an event
- CHECKS: a CHECK verifies an event or state
Answer strictly as JSON:
{"mentions": [{"span": "...", "type": "...", "predicate": "lemma of the action verb or null",
               "arguments": [{"role": "object|actor|location|time|value", "span": "..."}]}],
 "links": [{"type": "...", "from_span": "...", "to_span": "..."}]}"""


def load_suite(which: str) -> list[dict]:
    fname = ("level_f_cases.json" if which == "original"
             else "level_f_cases_renamed.json")
    return json.loads((HERE / "frozen" / fname).read_text(encoding="utf-8"))


def find_offset(policy: str, span: str) -> tuple[int, int] | None:
    if not span:
        return None
    idx = policy.find(span)
    if idx >= 0:
        return idx, idx + len(span)
    s = span.strip()
    if s and s != span:
        idx = policy.find(s)
        if idx >= 0:
            return idx, idx + len(s)
    return None


def run_deepke(which: str) -> None:
    client = Mistral(model="ministral-14b-latest", cache_dir=OUT / "_cache")
    outdir = OUT / "DEEPKE"
    outdir.mkdir(parents=True, exist_ok=True)
    schema_str = ", ".join(f"{k} ({v})" for k, v in PHRASE.items())
    fmt = ('{"<mention type>": ["<exact substring>", ...], ...} ; use '
           'NAN when a type has no mentions')
    instruction = DEEPKE_TEMPLATE.format(s_schema=schema_str, s_format=fmt)
    for case in load_suite(which):
        path = outdir / f"{case['case_id']}.json"
        if path.exists():
            continue
        policy = case["policy"]
        user = (f"Input: {policy}\n\n{instruction}")
        t0 = time.time()
        parsed = _ask(client, "You are a helpful assistant.", user, 900)
        candidates = []
        i = 0
        for key, spans in (parsed or {}).items():
            if not isinstance(spans, list):
                continue
            mtype = key if key in PHRASE else PHRASE_TO_TYPE.get(key,
                                                                  "UNKNOWN")
            for s in spans:
                if not isinstance(s, str) or s == "NAN":
                    continue
                i += 1
                off = find_offset(policy, s)
                candidates.append({
                    "cid_local": f"c{i:02d}", "span": s,
                    "start": off[0] if off else None,
                    "end": off[1] if off else None,
                    "type": mtype, "predicate": None,
                    "arguments": [], "relations": [],
                    "grounded_tools": [],
                    "provenance": "offsets" if off else "none",
                    "raw_label": key})
        path.write_text(json.dumps(
            {"case_id": case["case_id"], "arm": "DEEPKE",
             "instruction": instruction,
             "candidates": candidates, "raw": parsed,
             "latency_s": round(time.time() - t0, 2)}, indent=1) + "\n",
            encoding="utf-8")
        print(case["case_id"], len(candidates), flush=True)


def run_llm_sg(which: str) -> None:
    client = Mistral(model="ministral-14b-latest", cache_dir=OUT / "_cache")
    outdir = OUT / "LLM_SG"
    outdir.mkdir(parents=True, exist_ok=True)
    for case in load_suite(which):
        path = outdir / f"{case['case_id']}.json"
        if path.exists():
            continue
        policy = case["policy"]
        user = (f"POLICY TEXT:\n\"{policy}\"\n\n"
                "Propose the typed semantic mention graph. Every span must "
                "be an exact substring of the policy text. Include all "
                "mentions of every type. Answer strictly as JSON.")
        t0 = time.time()
        parsed = _ask(client, LLM_SG_SYSTEM, user, 2500)
        candidates, links = [], []
        by_span = {}
        for i, m in enumerate((parsed or {}).get("mentions", []), start=1):
            if not isinstance(m, dict):
                continue
            span = m.get("span", "")
            off = find_offset(policy, span)
            args = []
            for a in m.get("arguments", []) or []:
                aoff = find_offset(policy, a.get("span", ""))
                if aoff:
                    args.append({"role": a.get("role", "argument"),
                                 "span": a["span"],
                                 "start": aoff[0], "end": aoff[1]})
            rec = {"cid_local": f"c{i:02d}", "span": span,
                   "start": off[0] if off else None,
                   "end": off[1] if off else None,
                   "type": m.get("type", "UNKNOWN"),
                   "predicate": m.get("predicate"),
                   "arguments": args, "relations": [],
                   "grounded_tools": [],
                   "provenance": "offsets" if off else "none"}
            candidates.append(rec)
            by_span[span] = rec
        for lk in (parsed or {}).get("links", []):
            if not isinstance(lk, dict):
                continue
            a = by_span.get(lk.get("from_span"))
            b = by_span.get(lk.get("to_span"))
            if a and b:
                a["relations"].append({"to": b["cid_local"],
                                       "type": lk.get("type", "UNKNOWN")})
            else:
                links.append({"unresolved": lk})
        path.write_text(json.dumps(
            {"case_id": case["case_id"], "arm": "LLM_SG",
             "candidates": candidates, "unresolved_links": links,
             "raw": parsed, "latency_s": round(time.time() - t0, 2)},
            indent=1) + "\n", encoding="utf-8")
        print(case["case_id"], len(candidates), flush=True)


def _ask(client, system: str, user: str, max_tokens: int) -> dict:
    for _ in range(4):
        try:
            r = client.ask(system, user, max_tokens=max_tokens)
            parsed, _err = Mistral.parse_json(r["raw"])
            if parsed:
                return parsed
        except Exception:
            time.sleep(3)
    return {}


if __name__ == "__main__":
    arm = sys.argv[1] if len(sys.argv) > 1 else "DEEPKE"
    which = sys.argv[2] if len(sys.argv) > 2 else "original"
    t0 = time.time()
    if arm == "DEEPKE":
        run_deepke(which)
    elif arm == "LLM_SG":
        run_llm_sg(which)
    else:
        raise SystemExit(f"unknown arm {arm}")
    print(arm, "done", round(time.time() - t0, 1), "s")
