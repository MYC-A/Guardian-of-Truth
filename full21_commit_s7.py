#!/usr/bin/env python3
"""FULL_21: commit think_v2 + S7."""
import json
import os
import subprocess

WT = "/mnt/data/guardian/agent-workspace/Guardian-full21-hybrid"
os.chdir(WT)

def run(cmd, t=120):
    p = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=t)
    return p.returncode, p.stdout.strip(), p.stderr.strip()

out = {}

DOC = """# FULL_21: think mode + claim-level Granite verifier (S7)

## Think mode (Section 3)

- v1 (max_new_tokens=400): 17/46 cases produced no `<score>` token — coverage
  gap preserved as missing, never coerced to 0.
- v2 (max_new_tokens=1200): 46/46 scored. Standalone TP13 FP5 FN10 TN18
  **F1 .6341**; OR-baseline F1 .7826.
- **Honest negative: the checkpoint's think mode degrades this task** versus
  the no-think control (F1 .7805 standalone / .8889 OR). The reasoning trace
  moves the guardian away from its trained risk-token behavior. No-think is
  part of the frozen control and remains correct.

## Claim-level verification (Sections 3.6 + 5 verifier side)

Suspicions: archived E3b producer records (103 statements with
`proposed_violation` text across 23 cases; producer was blockrun — frozen
previous work, zero new external calls). Granite groundedness judges each
STATEMENT against the bounded case context; risk=yes -> suspicion CONFIRMED;
case label = 1 iff >=1 CONFIRMED.

| Verifier | TP | FP | FN | TN | P | R | F1 |
|----------|----|----|----|----|---|---|----|
| s7 plain (context only) | 13 | 10 | 0 | 0 | .5652 | 1.0 | .7222 |
| s7 graph (context + digest) | 13 | 10 | 0 | 0 | .5652 | 1.0 | .7222 |

- Producer-label agreement: plain 62/103, graph 63/103 (one flip).
- **Granite's yes/no risk token is a weak discriminator for verifying foreign
  suspicions**: every suspicion-covered case is flagged (all 23 -> label 1),
  so recall saturates at 1.0 while precision collapses. The A4 blockrun
  structured verifier (CONFIRMED/REFUTED/UNCERTAIN + reasons) was more
  discriminating on the same suspicions (archived F1 .6222 full-46).
- **The graph digest does not change verifier outcomes** (+1/103 flips, same
  case metrics) — the digest neither helps nor hurts in the verifier role.
  Combined with S5 (judge side), the current digest format shows no benefit
  in EITHER role for Granite; the graph's remaining value must come from a
  different integration (e.g., NuExtract/LLM-facing evidence, not guardian
  risk scoring).
- probabilistic_score was unavailable in these records (no yes/no logprob
  pair returned), so no score-distribution analysis is possible; argmax token
  is the only signal. Limitation recorded.

## Artifacts

- outputs/research_granite_guardian/full21_s3_g12k_think_v2/
- outputs/research_granite_guardian/full21_s7_{plain,graph}/
- outputs/full21/s7_metrics.json
- experiments/full21/s7_claim_verifier.py
"""
open("docs/full21/THINK_AND_CLAIM_VERIFIER.md", "w").write(DOC)

run("git add -f outputs/research_granite_guardian/full21_s3_g12k_think_v2 outputs/research_granite_guardian/full21_s7_plain outputs/research_granite_guardian/full21_s7_graph outputs/full21/s7_metrics.json experiments/full21/s7_claim_verifier.py docs/full21/THINK_AND_CLAIM_VERIFIER.md 2>&1 | head -2")
rc, so, se = run("git -c user.name='Super Z Agent' -c user.email='agent@guardian.local' commit -m 'full_21: think mode degrades control (v2 46/46 scored, F1 .6341 vs .7805; OR .7826 vs .8889) — honest negative; S7 claim-level granite verifier overtriggers (R 1.0 P .5652 on 23 suspicion-cases), graph digest no verifier effect (+1/103); weak discriminator vs structured A4 verifier' 2>&1 | tail -2")
out["commit"] = (rc, so[:300])
out["head"] = run("git rev-parse HEAD")
print(json.dumps(out, ensure_ascii=False, indent=1))
