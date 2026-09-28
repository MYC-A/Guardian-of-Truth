"""Ready IE frontend adapters for Level F (main venv).

Arms:
  uie_direct  - PaddleNLP UIE (uie-base-en), one pass, typed schema
  uie_staged  - UIE in three passes: typed mentions -> arguments -> links
  gliner      - GLiNER zero-shot typed mention detection
  oneke       - OneKE 13B (GGUF Q3_K_L, llama.cpp) schema-guided extraction
  oneke_ee    - OneKE with the event-extraction instruction (triggers+args)
  omnievent   - OmniEvent toolkit trigger+argument extraction

Schema phrasings are FROZEN from dev calibration (old Level E texts, see
lf_dev_calibration.py output committed before test). Adapters never read
gold.

Every adapter emits the unified candidate schema used by lf_score.py /
lf_downstream.py.

Run (server, main venv):
  python3 lf_ready_frontends.py <arm> [original|renamed]
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).parent
OUT = HERE / "outputs"

# Frozen schema phrasings (dev-calibrated on OLD Level E dev texts).
PHRASE = {
    "EVENT": "action or task to be performed",
    "EVENT_REFERENCE": "reference to an action or task",
    "STATE_OR_FACET": "state or condition of an action",
    "ARTIFACT": "document, report, log or record",
    "CHECK": "verification or checking action",
    "ENTITY": "physical object or participant",
}
PHRASE_TO_TYPE = {v: k for k, v in PHRASE.items()}
TYPES = list(PHRASE)

ONEKE_SYS = ("You are a helpful assistant. You are an expert in "
             "information extraction. Please respond in the format of a "
             "JSON string.")
ONEKE_NER_INSTR = (
    "You are an expert in entity and mention recognition. Please extract "
    "mentions that match the schema definition from the input. Return an "
    "empty list if the mention type does not exist. Please respond in the "
    "format of a JSON string. The schema types are: action or task to be "
    "performed (an instruction or verbal clause describing an operation); "
    "reference to an action or task (a noun phrase or pronoun pointing to "
    "an action); state or condition of an action (a clause asserting that "
    "something is complete, valid, passed, found or recorded); document, "
    "report, log or record (an artifact); verification or checking action "
    "(an action of verifying or testing something); physical object or "
    "participant (an entity).")
ONEKE_EE_INSTR = (
    "You are an expert in event extraction. Please extract event triggers "
    "(the verbal phrase expressing an action, verification or state) and "
    "their arguments (the objects they act on) from the input. Return an "
    "empty list if no events exist. Please respond in the format of a JSON "
    "string like [{\"trigger\": \"...\", \"trigger_type\": \"action|"
    "verification|state|reference|artifact\", \"arguments\": "
    "[{\"role\": \"object\", \"text\": \"...\"}]}].")


def load_suite(which: str) -> list[dict]:
    fname = ("level_f_cases.json" if which == "original"
             else "level_f_cases_renamed.json")
    return json.loads((HERE / "frozen" / fname).read_text(encoding="utf-8"))


def normalize_type(label: str) -> str:
    """Map any model label to the Level F ontology; unknown -> UNKNOWN."""
    if label in PHRASE:
        return label
    if label in PHRASE_TO_TYPE:
        return PHRASE_TO_TYPE[label]
    low = label.lower()
    for t, p in PHRASE.items():
        if low == p or low == t.lower():
            return t
    return "UNKNOWN"


def find_offset(policy: str, span: str) -> tuple[int, int] | None:
    """Locate an extracted span in the policy text; None if not verbatim."""
    if not span:
        return None
    idx = policy.find(span)
    if idx >= 0:
        return idx, idx + len(span)
    stripped = span.strip()
    if stripped and stripped != span:
        idx = policy.find(stripped)
        if idx >= 0:
            return idx, idx + len(stripped)
    return None


def cand(cid: str, span: str, mtype: str, policy: str, *,
         predicate=None, arguments=None, relations=None, score=None,
         extra: dict | None = None) -> dict:
    off = find_offset(policy, span)
    rec = {"cid_local": cid, "span": span,
           "start": off[0] if off else None,
           "end": off[1] if off else None,
           "type": mtype, "predicate": predicate,
           "arguments": arguments or [], "relations": relations or [],
           "grounded_tools": [], "provenance": "offsets" if off else "none",
           }
    if score is not None:
        rec["score"] = score
    if extra:
        rec.update(extra)
    return rec


# ----------------------------------------------------------------- UIE
def run_uie(which: str, mode: str) -> None:
    from paddlenlp import Taskflow

    outdir = OUT / ("UIE" if mode == "direct" else "UIE_STAGED")
    outdir.mkdir(parents=True, exist_ok=True)
    schema = list(PHRASE.values())
    ie = Taskflow("information_extraction", schema=schema,
                  model="uie-base-en", prob_thresh=0.3)

    for case in load_suite(which):
        path = outdir / f"{case['case_id']}.json"
        if path.exists():
            continue
        policy = case["policy"]
        results = ie(policy)[0] if mode == "direct" else {}
        candidates = []
        cid_n = 0
        if mode == "direct":
            for phrase, items in (results or {}).items():
                mtype = PHRASE_TO_TYPE.get(phrase, "UNKNOWN")
                for it in items:
                    cid_n += 1
                    candidates.append(cand(
                        f"c{cid_n:02d}", it["text"], mtype, policy,
                        score=round(float(it.get("probability", 0)), 4),
                        extra={"raw_label": phrase,
                               "uie_start": it.get("start"),
                               "uie_end": it.get("end")}))
        else:
            # staged: pass1 typed mentions; pass2 arguments for EVENT-like;
            # pass3 typed-pair relations for semantic links
            mentions = []
            for phrase, items in (ie(policy)[0] or {}).items():
                mtype = PHRASE_TO_TYPE.get(phrase, "UNKNOWN")
                for it in items:
                    mentions.append((mtype, it))
            arg_schema = {PHRASE["EVENT"]: ["object acted on", "actor",
                                            "location", "time or value"]}
            ie_args = Taskflow("information_extraction", schema=arg_schema,
                               model="uie-base-en", prob_thresh=0.3)
            for mtype, it in mentions:
                cid_n += 1
                args = []
                if mtype in ("EVENT", "CHECK"):
                    sent = _sentence_of(policy, it.get("start", 0))
                    if sent:
                        res = ie_args(sent)[0] or {}
                        for sub in res.get(PHRASE["EVENT"], []):
                            off = find_offset(policy, sub["text"])
                            if off:
                                args.append({"role": "argument",
                                             "span": sub["text"],
                                             "start": off[0], "end": off[1]})
                candidates.append(cand(
                    f"c{cid_n:02d}", it["text"], mtype, policy,
                    arguments=args,
                    score=round(float(it.get("probability", 0)), 4),
                    extra={"raw_label": PHRASE.get(mtype, mtype)}))
            # pass3: relation-style links between mention types
            rel_schema = {PHRASE["EVENT_REFERENCE"]: [PHRASE["EVENT"]]}
            ie_rel = Taskflow("information_extraction", schema=rel_schema,
                              model="uie-base-en", prob_thresh=0.3)
            res = ie_rel(policy)[0] or {}
            by_span = {c["span"]: c for c in candidates}
            for refs in res.get(PHRASE["EVENT_REFERENCE"], []):
                # UIE nested returns {"object acted on"->...} or text pairs;
                # handle the plain span pair form defensively
                if isinstance(refs, dict):
                    for target_list in refs.values():
                        for tgt in target_list:
                            a = by_span.get(refs.get("text", ""))
                            b = by_span.get(tgt.get("text", "")
                                            if isinstance(tgt, dict) else tgt)
                            if a and b:
                                a["relations"].append(
                                    {"to": b["cid_local"],
                                     "type": "REFERENCE_OF"})
        path.write_text(json.dumps({"case_id": case["case_id"],
                                    "arm": f"UIE_{mode}",
                                    "candidates": candidates}, indent=1)
                        + "\n", encoding="utf-8")
        print(case["case_id"], len(candidates), flush=True)


def _sentence_of(policy: str, pos: int) -> str | None:
    for m in re.finditer(r"[^.]*[.]", policy):
        if m.start() <= pos <= m.end():
            return m.group(0)
    return None


# ---------------------------------------------------------------- GLiNER
def run_gliner(which: str) -> None:
    from gliner import GLiNER

    outdir = OUT / "GLINER"
    outdir.mkdir(parents=True, exist_ok=True)
    model = GLiNER.from_pretrained("urchade/gliner_base",
                                   cache_dir="/workspace/guardian/hf_cache")
    labels = list(PHRASE.values())
    for case in load_suite(which):
        path = outdir / f"{case['case_id']}.json"
        if path.exists():
            continue
        policy = case["policy"]
        entities = model.predict_entities(policy, labels,
                                          threshold=0.3)
        candidates = []
        for i, e in enumerate(entities, start=1):
            mtype = normalize_type(e.get("label", ""))
            candidates.append(cand(
                f"c{i:02d}", e["text"], mtype, policy,
                score=round(float(e.get("score", 0)), 4),
                extra={"raw_label": e.get("label")}))
        path.write_text(json.dumps({"case_id": case["case_id"],
                                    "arm": "GLINER",
                                    "candidates": candidates}, indent=1)
                        + "\n", encoding="utf-8")
        print(case["case_id"], len(candidates), flush=True)


# ---------------------------------------------------------------- OneKE
def load_oneke():
    from llama_cpp import Llama

    return Llama(
        model_path="/workspace/guardian/models/oneke/oneke-q3_k_l.gguf",
        n_gpu_layers=-1, n_ctx=4096, n_threads=8, verbose=False)


def oneke_call(llm, policy: str, instruction: str, schema: list) -> str:
    sintruct = json.dumps({"instruction": instruction, "schema": schema,
                           "input": policy}, ensure_ascii=False)
    prompt = (f"[INST] <<SYS>>\n{ONEKE_SYS}\n<</SYS>>\n\n"
              f"{sintruct}[/INST]\n")
    out = llm(prompt, max_tokens=700, temperature=0.0, repeat_penalty=1.1,
              stop=["</s>", "[/INST]"])
    return out["choices"][0]["text"]


def run_oneke(which: str, ee: bool = False) -> None:
    llm = load_oneke()
    arm = "ONEKE_EE" if ee else "ONEKE"
    outdir = OUT / arm
    outdir.mkdir(parents=True, exist_ok=True)
    schema = list(PHRASE.values())
    for case in load_suite(which):
        path = outdir / f"{case['case_id']}.json"
        if path.exists():
            continue
        policy = case["policy"]
        t0 = time.time()
        raw = oneke_call(llm, policy,
                         ONEKE_EE_INSTR if ee else ONEKE_NER_INSTR,
                         schema)
        candidates = []
        try:
            data = json.loads(_extract_json(raw))
        except Exception:
            data = []
        if isinstance(data, dict):
            data = [data]
        for i, item in enumerate(data, start=1):
            if not isinstance(item, dict):
                continue
            if ee and "trigger" in item:
                mtype = normalize_type(str(item.get("trigger_type", "")))
                args = []
                for a in item.get("arguments", []) or []:
                    if isinstance(a, dict) and a.get("text"):
                        off = find_offset(policy, a["text"])
                        args.append({"role": a.get("role", "argument"),
                                     "span": a["text"],
                                     "start": off[0] if off else None,
                                     "end": off[1] if off else None})
                candidates.append(cand(
                    f"c{i:02d}", str(item["trigger"]), mtype, policy,
                    arguments=args,
                    extra={"oneke_raw": item}))
            else:
                for key, vals in item.items():
                    mtype = normalize_type(key)
                    if isinstance(vals, str):
                        vals = [{"text": vals}]
                    for v in vals or []:
                        text = v.get("text") if isinstance(v, dict) else str(v)
                        if text:
                            candidates.append(cand(
                                f"c{i:02d}", str(text), mtype, policy,
                                extra={"raw_label": key}))
        path.write_text(json.dumps({"case_id": case["case_id"], "arm": arm,
                                    "candidates": candidates,
                                    "raw_output": raw[:4000],
                                    "latency_s": round(time.time() - t0, 1)},
                                   indent=1) + "\n", encoding="utf-8")
        print(case["case_id"], len(candidates),
              round(time.time() - t0, 1), "s", flush=True)


def _extract_json(raw: str) -> str:
    raw = raw.strip()
    m = re.search(r"```(?:json)?\s*(.*?)\s*```", raw, re.DOTALL)
    if m:
        return m.group(1)
    start = raw.find("[")
    if start >= 0 and raw.find("[") < raw.find("{"):
        return raw[start:raw.rfind("]") + 1]
    start = raw.find("{")
    if start >= 0:
        return raw[start:raw.rfind("}") + 1]
    return raw


# ------------------------------------------------------------- OmniEvent
def run_omnievent(which: str) -> None:
    import sys
    sys.path.insert(0, "/workspace/guardian/repos/OmniEvent")
    from OmniEvent.infer import infer

    outdir = OUT / "OMNIEVENT"
    outdir.mkdir(parents=True, exist_ok=True)
    for case in load_suite(which):
        path = outdir / f"{case['case_id']}.json"
        if path.exists():
            continue
        policy = case["policy"]
        t0 = time.time()
        try:
            results = infer(text=policy, task="EE")
            events = results[0].get("events", []) if results else []
        except Exception as exc:  # documented failure path
            path.write_text(json.dumps({"case_id": case["case_id"],
                                        "arm": "OMNIEVENT",
                                        "error": str(exc)[:500],
                                        "candidates": []}, indent=1)
                            + "\n", encoding="utf-8")
            print(case["case_id"], "ERROR", str(exc)[:120], flush=True)
            continue
        candidates = []
        for i, ev in enumerate(events, start=1):
            trigger = ev.get("trigger") or ev.get("word") or ""
            etype = str(ev.get("event_type", ""))
            args = []
            for a in ev.get("arguments", []) or []:
                atext = a.get("argument") or a.get("text") or ""
                off = find_offset(policy, atext)
                args.append({"role": a.get("role", "argument"),
                             "span": atext,
                             "start": off[0] if off else None,
                             "end": off[1] if off else None})
            candidates.append(cand(
                f"c{i:02d}", str(trigger),
                "UNKNOWN", policy, arguments=args,
                extra={"omnievent_type": etype}))
        path.write_text(json.dumps({"case_id": case["case_id"],
                                    "arm": "OMNIEVENT",
                                    "candidates": candidates,
                                    "raw": events[:4000],
                                    "latency_s": round(time.time() - t0, 1)},
                                   indent=1) + "\n", encoding="utf-8")
        print(case["case_id"], len(candidates), flush=True)


if __name__ == "__main__":
    arm = sys.argv[1] if len(sys.argv) > 1 else "uie_direct"
    which = sys.argv[2] if len(sys.argv) > 2 else "original"
    t0 = time.time()
    if arm == "uie_direct":
        run_uie(which, "direct")
    elif arm == "uie_staged":
        run_uie(which, "staged")
    elif arm == "gliner":
        run_gliner(which)
    elif arm == "oneke":
        run_oneke(which, ee=False)
    elif arm == "oneke_ee":
        run_oneke(which, ee=True)
    elif arm == "omnievent":
        run_omnievent(which)
    else:
        raise SystemExit(f"unknown arm {arm}")
    print(arm, "done", round(time.time() - t0, 1), "s")
