#!/usr/bin/env python3
"""Local generative model runner (single load, sequential inference).

Model: granite-guardian-3.3-8b (full local files; based on granite-3.3-8b-instruct).
Prompt: MANUAL granite role-token format (avoids the guardian judge-preamble
injection of the default chat template — we need plain instruction following,
not risk assessment).

CLI:
  python local_llm.py --in requests.jsonl --out responses.jsonl [--max-new 1200]

requests.jsonl rows: {"id": str, "system": str, "user": str}
responses.jsonl rows: {"id": str, "content": str, "prompt_tokens": int, "gen_tokens": int}
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

MODEL_PATH = "/mnt/data/guardian/models/granite-guardian-3.3-8b-b3421eda"

ROLE_OPEN = "<|start_of_role|>"
ROLE_CLOSE = "<|end_of_role|>"
TEXT_END = "<|end_of_text|>"


def build_prompt(system: str, user: str) -> str:
    parts = []
    if system:
        parts.append(f"{ROLE_OPEN}system{ROLE_CLOSE}{system}{TEXT_END}\n")
    parts.append(f"{ROLE_OPEN}user{ROLE_CLOSE}{user}{TEXT_END}\n")
    parts.append(f"{ROLE_OPEN}assistant{ROLE_CLOSE}")
    return "".join(parts)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--out", dest="out", required=True)
    ap.add_argument("--max-new", type=int, default=1200)
    ap.add_argument("--model", default=MODEL_PATH)
    args = ap.parse_args()

    done = set()
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.is_file():
        with open(out_path, encoding="utf-8") as f:
            for line in f:
                try:
                    done.add(json.loads(line)["id"])
                except Exception:
                    pass

    reqs = []
    with open(args.inp, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            r = json.loads(line)
            if r["id"] not in done:
                reqs.append(r)
    print(f"[local_llm] {len(reqs)} to do, {len(done)} done", flush=True)
    if not reqs:
        return 0

    import os
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    t0 = time.time()
    tok = AutoTokenizer.from_pretrained(args.model, local_files_only=True,
                                        trust_remote_code=False)
    model = AutoModelForCausalLM.from_pretrained(
        args.model, local_files_only=True, trust_remote_code=False,
        torch_dtype=torch.float16, device_map="cuda")
    model.eval()
    print(f"[local_llm] model loaded in {time.time()-t0:.0f}s", flush=True)

    with open(out_path, "a", encoding="utf-8") as out:
        for i, r in enumerate(reqs):
            prompt = build_prompt(r.get("system", ""), r["user"])
            inputs = tok(prompt, return_tensors="pt", add_special_tokens=False,
                         truncation=True, max_length=28000).to("cuda")
            t1 = time.time()
            with torch.no_grad():
                gen = model.generate(
                    **inputs, max_new_tokens=args.max_new, do_sample=False,
                    pad_token_id=tok.eos_token_id)
            new_tokens = gen[0][inputs["input_ids"].shape[1]:]
            content = tok.decode(new_tokens, skip_special_tokens=True)
            # stop at end_of_text marker if the model continues beyond one turn
            if TEXT_END in content:
                content = content.split(TEXT_END)[0]
            rec = {"id": r["id"], "content": content.strip(),
                   "prompt_tokens": int(inputs["input_ids"].shape[1]),
                   "gen_tokens": int(new_tokens.shape[0]),
                   "latency": round(time.time() - t1, 1)}
            out.write(json.dumps(rec, ensure_ascii=False) + "\n")
            out.flush()
            if (i + 1) % 10 == 0:
                print(f"[local_llm] {i+1}/{len(reqs)} done", flush=True)
    print("[local_llm] ALL DONE", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
