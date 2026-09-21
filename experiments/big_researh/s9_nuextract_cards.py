#!/usr/bin/env python3
"""BIG_RESEARH S9 (I.C): NuExtract3-W4A16 structural extraction over public46.

WORKING load path (verified 2026-09-22 smoke, matches b43f615
src/guardian_truth/semantic_pipeline_v1/models/nuextract.py):
  AutoModelForImageTextToText + AutoProcessor BY NAME with
  HF_HOME=/mnt/data/guardian/hf_cache (offline). Loading the snapshot path
  with AutoModelForCausalLM produces garbage weight_shape buffers and a
  compressed-tensors decompression crash — do not do that.

Two verbatim extraction passes per case (NuExtract is a PURE verbatim
extractor; no reasoning delegated to the model):
  pass A (policy, <=48000 chars): NUEXTRACT_RULE_TEMPLATE (copied verbatim
       from b43f615 models/nuextract.py) -> rules + actions +
       temporal_relations, each with modality enums and source_quote.
  pass B (response, <=12000 chars): response_tools template ->
       tool_name_text / arguments_text.

Every string leaf is mechanically verified as a verbatim substring of its
source (span_ok + kind). Gold is never read here.

Outputs (append-only, resumable):
  outputs/big_researh/s9_nuextract/cards.jsonl
  outputs/big_researh/s9_nuextract/summary.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, "/mnt/data/guardian/venv/lib/python3.11/site-packages")

import os  # noqa: E402

os.environ["HF_HOME"] = "/mnt/data/guardian/hf_cache"
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "experiments" / "full21"))
sys.path.insert(0, str(REPO / "src"))

from run_granite_modes import read_cases  # noqa: E402

MODEL_NAME = "numind/NuExtract3-W4A16"

# --- template copied verbatim from b43f615 models/nuextract.py ---
NUEXTRACT_RULE_TEMPLATE = {
    "rules": [{
        "modality": ["REQUIRE", "FORBID", "ALLOW", "UNKNOWN"],
        "subject": "verbatim-string",
        "target_kind": ["ACTION", "STATE", "CLAIM", "INFORMATION", "EFFECT"],
        "target_name": "verbatim-string",
        "relation": ["IF", "ONLY_IF", "UNLESS", "NONE"],
        "temporal": ["BEFORE", "AFTER", "UNTIL", "WHILE", "NONE"],
        "condition_text": "verbatim-string",
        "exception_text": "verbatim-string",
        "values": ["verbatim-string"],
        "entity_references": ["verbatim-string"],
        "source_quote": "verbatim-string",
    }],
    "actions": [{
        "action": "verbatim-string",
        "object": "verbatim-string",
        "subject": "verbatim-string",
        "modality": ["REQUIRE", "FORBID", "ALLOW", "UNKNOWN"],
        "condition": "verbatim-string",
        "exception": "verbatim-string",
        "source_quote": "verbatim-string",
    }],
    "temporal_relations": [{
        "first": "verbatim-string",
        "relation": ["before", "after", "until", "while"],
        "second": "verbatim-string",
        "source_quote": "verbatim-string",
    }],
}

RESPONSE_TEMPLATE = {
    "response_tools": [{
        "tool_name_text": "verbatim-string",
        "arguments_text": "verbatim-string",
        "result_text": "verbatim-string",
    }] * 4,
}


def policy_text(case: dict) -> str:
    m = re.search(r"<policy>(.*?)</policy>", case["prompt"], re.DOTALL)
    return (m.group(1) if m else case["prompt"])[:48000]


def norm(t: str) -> str:
    return re.sub(r"\s+", " ", (t or "")).strip()


def verify_spans(obj, source: str, prefix: str = ""):
    """Recursively verify string leaves as verbatim substrings of source."""
    out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.extend(verify_spans(v, source, f"{prefix}.{k}" if prefix else k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out.extend(verify_spans(v, source, f"{prefix}[{i}]"))
    elif isinstance(obj, str) and obj.strip():
        s = obj.strip()
        pos = source.find(s)
        ok = pos >= 0
        kind = "verbatim"
        if not ok:
            n = norm(s)
            if n and n in norm(source):
                ok, kind = True, "verbatim_ws_tolerant"
            else:
                kind = "not_found"
        out.append({"field": prefix, "text": s[:400], "span_ok": ok,
                    "kind": kind, "start": pos if pos >= 0 else None})
    return out


def extract_once(processor, model, torch, source: str, template: dict,
                 max_new: int) -> tuple[str, float]:
    messages = [{"role": "user", "content": [{"type": "text", "text": source}]}]
    inputs = processor.apply_chat_template(
        messages, add_generation_prompt=True, tokenize=True, return_dict=True,
        return_tensors="pt", template=json.dumps(template, indent=4),
        enable_thinking=False,
    ).to(model.device)
    t0 = time.perf_counter()
    with torch.inference_mode():
        output = model.generate(**inputs, do_sample=False, max_new_tokens=max_new)
    dt = time.perf_counter() - t0
    generated = output[:, inputs["input_ids"].shape[1]:]
    text = processor.batch_decode(
        generated, skip_special_tokens=True, clean_up_tokenization_spaces=False)[0].strip()
    return text, dt


def parse_json_obj(text: str):
    text = text.strip()
    try:
        return json.loads(text), "direct"
    except Exception:
        pass
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0)), "regex_span"
        except Exception:
            pass
    return None, "unparseable"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--max-new", type=int, default=2500)
    args = ap.parse_args()

    out_dir = REPO / "outputs" / "big_researh" / "s9_nuextract"
    out_dir.mkdir(parents=True, exist_ok=True)
    rec_path = out_dir / "cards.jsonl"

    import torch
    from transformers import AutoModelForImageTextToText, AutoProcessor

    processor = AutoProcessor.from_pretrained(MODEL_NAME, trust_remote_code=True)
    model = AutoModelForImageTextToText.from_pretrained(
        MODEL_NAME, trust_remote_code=True, device_map="cuda",
        dtype=torch.bfloat16).eval()
    print(f"[s9n] model loaded: {MODEL_NAME}", flush=True)

    cases = read_cases(Path(args.input))
    if args.limit:
        cases = cases[:args.limit]

    done = set()
    if rec_path.exists():
        for line in open(rec_path, encoding="utf-8"):
            try:
                done.add(json.loads(line)["id"])
            except Exception:
                pass
    print(f"[s9n] resume: {len(done)} done, {len(cases) - len(done)} to go", flush=True)

    stats = {"cases": 0, "rules": 0, "rules_ok": 0, "actions": 0, "actions_ok": 0,
             "tools": 0, "tools_ok": 0, "errors": 0}
    with open(rec_path, "a", encoding="utf-8") as fout:
        for case in cases:
            cid = case["id"]
            if cid in done:
                continue
            rec = {"id": cid, "model": MODEL_NAME}
            try:
                pol = policy_text(case)
                resp = case["response"][:12000]
                raw_a, lat_a = extract_once(processor, model, torch, pol,
                                             NUEXTRACT_RULE_TEMPLATE, args.max_new)
                obj_a, how_a = parse_json_obj(raw_a)
                rules = actions = temporal = []
                if isinstance(obj_a, dict):
                    rules = [r for r in obj_a.get("rules") or [] if isinstance(r, dict)]
                    actions = [r for r in obj_a.get("actions") or [] if isinstance(r, dict)]
                    temporal = [r for r in obj_a.get("temporal_relations") or []
                                if isinstance(r, dict)]
                rules_v = verify_spans(rules, pol, "rules")
                actions_v = verify_spans(actions, pol, "actions")
                temporal_v = verify_spans(temporal, pol, "temporal_relations")

                raw_b, lat_b = extract_once(processor, model, torch, resp,
                                             RESPONSE_TEMPLATE, args.max_new)
                obj_b, how_b = parse_json_obj(raw_b)
                tools = []
                if isinstance(obj_b, dict):
                    tools = [r for r in obj_b.get("response_tools") or []
                             if isinstance(r, dict)]
                tools_v = verify_spans(tools, resp, "response_tools")

                rec.update({
                    "policy_rules": rules,
                    "policy_rules_spans": [r for r in rules_v if r["text"]],
                    "policy_actions": actions,
                    "policy_actions_spans": [r for r in actions_v if r["text"]],
                    "temporal_relations": temporal,
                    "temporal_relations_spans": [r for r in temporal_v if r["text"]],
                    "response_tools": tools,
                    "response_tools_spans": [r for r in tools_v if r["text"]],
                    "n_rules": len(rules), "n_rules_ok": sum(1 for r in rules_v if r["span_ok"]),
                    "n_actions": len(actions),
                    "n_actions_ok": sum(1 for r in actions_v if r["span_ok"]),
                    "n_temporal": len(temporal),
                    "n_tools": len(tools), "n_tools_ok": sum(1 for r in tools_v if r["span_ok"]),
                    "parse": {"policy": how_a, "response": how_b},
                    "latency_s": {"policy": round(lat_a, 2), "response": round(lat_b, 2)},
                })
                stats["rules"] += len(rules)
                stats["rules_ok"] += sum(1 for r in rules_v if r["span_ok"])
                stats["actions"] += len(actions)
                stats["actions_ok"] += sum(1 for r in actions_v if r["span_ok"])
                stats["tools"] += len(tools)
                stats["tools_ok"] += sum(1 for r in tools_v if r["span_ok"])
            except Exception as e:
                stats["errors"] += 1
                rec["error"] = f"{type(e).__name__}: {e}"
            stats["cases"] += 1
            fout.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fout.flush()
            print(f"[s9n] {cid}: rules={rec.get('n_rules', 'ERR')}ok"
                  f"{rec.get('n_rules_ok', 0)}/act{rec.get('n_actions', 0)}ok"
                  f"{rec.get('n_actions_ok', 0)}/tools{rec.get('n_tools', 0)}ok"
                  f"{rec.get('n_tools_ok', 0)} "
                  f"({rec.get('latency_s', {}).get('policy', '?')}s+", flush=True)

    (out_dir / "summary.json").write_text(json.dumps({
        **stats, "model": MODEL_NAME, "input": args.input,
        "done_total_after": len(done) + stats["cases"],
    }, indent=1))
    print(json.dumps(stats, indent=1), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
