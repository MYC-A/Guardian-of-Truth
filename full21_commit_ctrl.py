#!/usr/bin/env python3
"""FULL_21: commit control reproduction + docs."""
import json
import os
import subprocess

WT = "/mnt/data/guardian/agent-workspace/Guardian-full21-hybrid"
os.chdir(WT)

def run(cmd, t=120):
    p = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=t)
    return p.returncode, p.stdout.strip(), p.stderr.strip()

out = {}

DOC = """# FULL_21 control: Guardian baseline OR old Granite 8B (frozen)

## Reproduction result (2026-09-21)

Reference: flash agent line `research/flash-20260921` @ `8904a35`,
`outputs/ifc/ensemble_report_v1.json`. Reproduced by Super Z in this worktree
with the identical runner, input, model and parameters.

- Runner: `experiments/full21/run_granite_guardian_flash.py` (imported from
  flash branch; identical to `experiments/offline_guardian/run_granite_guardian.py`
  @ `origin/research/flash-20260921`)
- Model: `/mnt/data/guardian/models/granite-guardian-3.3-8b-b3421eda`
  (ibm-granite/granite-guardian-3.3-8b, revision b3421eda..., 16.3 GB safetensors)
- Criterion: `groundedness`; think=false; max_context_chars=12000
  (head_tail_per_field truncation — prompt typically 46646 -> 4800 chars);
  max_new_tokens=16; transformers backend; device_map=auto
- Input: `outputs/full21/input/public46_label_free.csv`,
  SHA-256 `9f6f5fc496d25e80a008adb589ddcb30fb681d0da131fb83c37fc220c5089e93`
  (exact public46 label-free CSV)
- Gold: flash `outputs/ifc/predictions.csv` (id,label; 46 rows)

## Metrics

| System | TP | FP | FN | TN | P | R | F1 |
|--------|----|----|----|----|---|---|----|
| baseline offline Guardian | 12 | 0 | 11 | 23 | 1.0 | .5217 | .6857 |
| granite groundedness @12k (repro) | 16 | 2 | 7 | 21 | .8889 | .6957 | .7805 |
| granite groundedness @12k (flash ref) | 16 | 2 | 7 | 21 | .8889 | .6957 | .7805 |
| **baseline OR granite (repro)** | **20** | **2** | **3** | **21** | .9091 | .8696 | **.8889** |

Per-case agreement with flash records: **46/46** (risk tokens identical,
zero mismatches). Artifacts:
- `outputs/research_granite_guardian/full21_control_repro/` (records.jsonl 46 ok,
  run_config.json, summary.json)
- `outputs/full21/control_repro_summary.json`, `outputs/full21/control_repro_percase.csv`

## Context-length ablation (from flash records, preserved unmodified)

- granite groundedness @60k: TP10 FP0 FN13 TN23, P 1.0, R .4348, F1 .6061
  (truncation applied on 29/46 vs 46/46 at 12k; 8 prediction flips vs 12k)
- baseline OR granite@60k: TP18 FP0 FN5 TN23, F1 .878
- More context HURTS recall on this checkpoint/task: the 12k head-tail window
  is part of the frozen control, not a free lunch to re-tune.

## Known limits

public46 is PUBLIC_SEEN (repeatedly inspected); .8889 is a reproduction of a
specific historical configuration, not a generalization claim or competition
readiness. Mistral API channel is blocked in this environment (secrets are
root-only); FULL_21 Mistral experiments will use local mistral-7b-instruct
v0.3 as the declared substitute channel unless access appears.
"""
os.makedirs("docs/full21", exist_ok=True)
open("docs/full21/CONTROL.md", "w").write(DOC)

run("git add outputs/full21 outputs/research_granite_guardian/full21_control_repro docs/full21/CONTROL.md")
rc, so, se = run("git -c user.name='Super Z Agent' -c user.email='agent@guardian.local' commit -m 'full_21 sec.2: control Guardian OR old Granite 8B reproduced EXACTLY — granite groundedness@12k F1 .7805, baseline OR granite TP20 FP2 FN3 TN21 F1 .8889; 46/46 per-case agreement with flash reference; frozen config + artifacts + context ablation (60k F1 .6061 documented)' 2>&1 | tail -3")
out["commit"] = (rc, so, se)
out["head"] = run("git rev-parse HEAD")
print(json.dumps(out, ensure_ascii=False, indent=1))
