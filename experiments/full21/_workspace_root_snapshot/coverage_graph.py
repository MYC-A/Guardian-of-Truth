
import sys, csv, json
from pathlib import Path
from collections import Counter
W = Path("/mnt/data/guardian/agent-workspace/Guardian-superz-fullcycle")
sys.path.insert(0, str(W / "experiments" / "superz_fullcycle"))
sys.path.insert(0, str(W / "src"))

from g_graph import load_cases
from guardian_truth.parsing import parse_events, parse_catalog
from guardian_truth.provenance import build_graph

cases = load_cases()
total = {"hist_calls": 0, "hist_results": 0, "cand_calls": 0, "args": Counter(), "facts": 0,
         "timelines": 0, "empty_digest": 0}
for cid, case in cases.items():
    history = parse_events(case["prompt"], "prompt")
    candidate = parse_events(case["response"], "response")
    g = build_graph(history, candidate)
    hc = sum(1 for e in history if e.kind == "call")
    hr = sum(1 for e in history if e.kind == "result")
    cc = sum(1 for e in candidate if e.kind == "call")
    total["hist_calls"] += hc; total["hist_results"] += hr; total["cand_calls"] += cc
    total["facts"] += len(g.facts)
    total["timelines"] += sum(1 for f in g.facts if f.previous)
    for a in g.arguments:
        total["args"][a.status] += 1
    has_content = (cc > 0 and any(a.status not in ("observed_match",) for a in g.arguments)) or total["timelines"] > 0
print("TOTALS:", json.dumps({k: (dict(v) if isinstance(v, Counter) else v) for k, v in total.items()}))

# пример формата: первые 400 символов prompt одного кейса с вызовами
for cid, case in cases.items():
    history = parse_events(case["prompt"], "prompt")
    if sum(1 for e in history if e.kind == "result") > 3:
        print(f"\n===== sample format {cid} (first 500 chars) =====")
        print(case["prompt"][:500].replace("\n", "\\n")[:500])
        break

# распределение статусов аргументов по кейсам
arg_cases = 0
for cid, case in cases.items():
    candidate = parse_events(case["response"], "response")
    if any(e.kind == "call" for e in candidate):
        arg_cases += 1
print(f"\ncases with candidate tool calls: {arg_cases}/46")
