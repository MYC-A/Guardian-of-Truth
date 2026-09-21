#!/usr/bin/env python3
"""FULL_21: read run_config + summary of flash granite runs (pure python)."""
import json

G = "/mnt/data/guardian/agent-workspace/guardian-repo/outputs/ifc/research_granite_guardian"
out = {}

for d in ("full46_ifc", "full46_ctx60k_ifc", "agenthallu_dev_ifc"):
    try:
        out[d + "_config"] = json.load(open(f"{G}/{d}/run_config.json"))
    except Exception as e:
        out[d + "_config"] = f"ERR {e}"
    try:
        out[d + "_summary"] = json.load(open(f"{G}/{d}/summary.json"))
    except Exception as e:
        out[d + "_summary"] = f"ERR {e}"

recs = [json.loads(l) for l in open(f"{G}/full46_ifc/records.jsonl", encoding="utf-8")]
out["n_records"] = len(recs)
ex = dict(recs[0])
ex.pop("raw_model_output", None)
out["rec_example"] = ex
out["pred_dist"] = {}
for r in recs:
    p = r.get("prediction")
    out["pred_dist"][str(p)] = out["pred_dist"].get(str(p), 0) + 1
out["statuses"] = {}
for r in recs:
    s = r.get("status")
    out["statuses"][str(s)] = out["statuses"].get(str(s), 0) + 1

print(json.dumps(out, ensure_ascii=False, indent=1))
