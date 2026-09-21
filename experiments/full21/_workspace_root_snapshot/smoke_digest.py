
import sys, csv, json
from pathlib import Path
W = Path("/mnt/data/guardian/agent-workspace/Guardian-superz-fullcycle")
sys.path.insert(0, str(W / "experiments" / "superz_fullcycle"))
sys.path.insert(0, str(W / "src"))

from g_graph import load_cases, graph_digest

cases = load_cases()
ids = list(cases.keys())[:2]
for cid in ids:
    d = graph_digest(cases[cid]["prompt"], cases[cid]["response"])
    print(f"===== {cid} digest ({len(d)} chars) =====")
    print(d[:1500])
    print("...")
