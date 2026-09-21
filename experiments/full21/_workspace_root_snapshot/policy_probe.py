
import sys, csv, re, json
W = "/mnt/data/guardian/agent-workspace/Guardian-superz-fullcycle"
sys.path.insert(0, f"{W}/experiments/superz_fullcycle")
from g_graph import load_cases

cases = load_cases()
n_policy = 0
sizes = []
for cid, case in list(cases.items()):
    m = re.search(r"<policy>(.*?)</policy>", case["prompt"], re.DOTALL)
    if m:
        n_policy += 1
        sizes.append(len(m.group(1)))
    else:
        sizes.append(-1)
print(f"cases with <policy>...</policy>: {n_policy}/46")
import statistics
pos = [s for s in sizes if s > 0]
if pos:
    print(f"policy size: min={min(pos)}, median={statistics.median(pos):.0f}, max={max(pos)}")
neg = [i for i, s in enumerate(sizes) if s < 0]
if neg:
    print("no-policy cases:", [list(cases.keys())[i] for i in neg][:10])
# пример policy
cid = list(cases.keys())[0]
m = re.search(r"<policy>(.*?)</policy>", cases[cid]["prompt"], re.DOTALL)
if m:
    print(f"\n===== policy sample {cid} (first 700 chars) =====")
    print(m.group(1)[:700])
