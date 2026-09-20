"""Standalone E2 extractor runner (GLM via z-ai-web-dev-sdk): fills notes_e2_{ds}.json
cache so notes_probe.py can skip the GLM phase. Runs on a DIFFERENT provider than the
Mistral critique batch - safe to run in parallel.

Usage: python3 notes_e2_runner.py synth-dev [limit]
"""
import json, os, sys
from pathlib import Path
sys.path.insert(0, "/home/z/my-project/got-agentz/experiments/agentz_arch_v1")
# ensure NO mistral key -> provider zai
os.environ.pop("MISTRAL_API_KEY", None)
from common.io_utils import load_dataset, run_llm, extract_json, SYSTEM_PROMPT
from arch_c_theory import policy_text
from notes_probe import e2_prompt

OUT = Path("/home/z/my-project/got-agentz/outputs/agentz")

def run(ds, limit=None):
    rows = {r["id"]: r for r in load_dataset(ds)}
    c0v3 = json.loads((OUT / f"arch_c0v3_{ds}.json").read_text())
    targets = [cid for cid, det in c0v3["details"].items() if det.get("pred") is None]
    if limit:
        targets = targets[:limit]
    cache = OUT / f"notes_e2_{ds}.json"
    e2 = json.loads(cache.read_text()) if cache.exists() else {}
    todo = [cid for cid in targets if cid not in e2]
    print(f"E2/GLM: {len(todo)} calls (of {len(targets)} targets)", flush=True)
    tasks = [{"id": f"{cid}-e2", "system": SYSTEM_PROMPT,
              "prompt": e2_prompt(policy_text(rows[cid]["prompt"]))} for cid in todo]
    for i in range(0, len(tasks), 20):
        batch = tasks[i:i + 20]
        outs = run_llm(batch, concurrency=4)
        for cid, text in outs.items():
            j = extract_json(text)
            e2[cid.replace("-e2", "")] = j.get("elements", []) if isinstance(j, dict) else {"error": "parse"}
        cache.write_text(json.dumps(e2, ensure_ascii=False))
        print(f"  batch {i//20+1}/{-(-len(tasks)//20)} done ({len(e2)} cached)", flush=True)
    print("E2 cache complete:", cache)

if __name__ == "__main__":
    ds = sys.argv[1] if len(sys.argv) > 1 else "synth-dev"
    lim = int(sys.argv[2]) if len(sys.argv) > 2 else None
    run(ds, lim)
