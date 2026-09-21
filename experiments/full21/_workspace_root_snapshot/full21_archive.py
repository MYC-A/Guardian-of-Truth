#!/usr/bin/env python3
"""FULL_21 Section 1: create archive branch full_21/archive-previous from superz worktree state.

Steps: fetch origin, branch, copy chain logs into repo, write archive doc,
commit, attempt push (expected blocked), git bundle + SHA256 to stable server dir.
"""
import json
import os
import subprocess
import time

WT = "/mnt/data/guardian/agent-workspace/Guardian-superz-fullcycle"
A = "/mnt/data/guardian/agent-workspace"
os.chdir(WT)


def run(cmd, **kw):
    p = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=kw.get("timeout", 120))
    return p.returncode, p.stdout.strip(), p.stderr.strip()


log = []

# 0. pre-checks
_, cur, _ = run("git rev-parse --abbrev-ref HEAD")
_, head, _ = run("git rev-parse HEAD")
log.append(f"before: branch={cur} head={head}")

# 1. fetch origin (public read)
rc, so, se = run("git fetch origin --prune 2>&1 | tail -3", timeout=180)
log.append(f"fetch rc={rc} {so[:200]} {se[:200]}")

# 2. create archive branch from current HEAD
rc, so, se = run("git checkout -b full_21/archive-previous")
log.append(f"branch rc={rc}: {so} {se}")

# 3. copy chain logs into repo for preservation
os.makedirs("outputs/superz_fullcycle/chainlogs", exist_ok=True)
import glob
copied = []
for f in glob.glob(f"{A}/*.log"):
    base = os.path.basename(f)
    if any(k in base for k in ("chain", "q_extract", "p_extract", "e3b_", "a4_")):
        dst = f"outputs/superz_fullcycle/chainlogs/{base}"
        if not os.path.exists(dst):
            import shutil
            shutil.copy2(f, dst)
            copied.append(base)
log.append(f"copied chain logs: {len(copied)}")

# 4. archive doc
ARCHIVE_DOC = """# FULL_21 archive of previous work (2026-09-21)

Branch `full_21/archive-previous` (created by Super Z agent, directive FULL_21).
Base: `research/independent-fullcycle-20260920-superz` @ `d0d3935` + all
uncommitted session-3/4 state (Q experiment scripts, keyless cache outputs).

## Completed experiments (superz fullcycle line, public46 unless noted)

All keyless-API experiments below ran on BlockRun/Pollinations/LLM7 pools as
declared; FULL_21 directive bans these pools for NEW mandatory runs. Results
are frozen as-is, without reprocessing.

| ID | Description | n | TP | FP | FN | TN | F1 | Notes |
|----|-------------|---|----|----|----|----|----|-------|
| E1 | offline baseline `--backend none` | 46 | 12 | 0 | 11 | 23 | .6857 | exact reproduction of offline line |
| E3a | A1R post-hoc re-anchor of A1 suspicions | 46 | 20 | 19 | 3 | 4 | .6452 | anchoring repaired (95/120); quote existence does not filter FP |
| E4/A4 | full-context cross-model verification | 52 susp | - | - | - | - | .6222 | per-suspicion analysis; 10 mixed-verdict cases |
| E5 | AND-ensemble of independent judges | 39 | - | - | - | - | .7442 | Mistral x gpt-oss-20b; P .80 |
| E7 | Granite Guardian 3.3-8B OR-baseline (function_call mode, 23 rows) | 46 | 13 | 0 | 10 | 23 | .7222 | offline candidate; standalone granite F1 .5161 |
| G | judge + graph digest (blockrun) | 29 scored | 4 | 1 | 11 | 13 | .4000 | coverage incomplete (FAILED rows); judge-base = blockrun, NOT self-consistent with E2-pollinations baseline |
| P | obligation-centered policy cards judge (blockrun extract) | 39 | 8 | 10 | 11 | 10 | .4324 | |
| G+P | pgjudge (blockrun judge + blockrun cards) | 39 | 13 | 6 | 7 | 13 | .6667 | |
| A4+P | a4p (blockrun verifier) | 46 | 15 | 14 | 8 | 9 | .5769 | verdict dist: 52 CONFIRMED / 8 REFUTED / 6 UNCERTAIN |
| A4+G+P | a4gp (blockrun verifier) | 46 | 16 | 13 | 7 | 10 | .6154 | verdict dist: 70/10/4 |
| E3b-verify | A4 verification of E3b suspicions | - | 11 | 7 | 12 | 16 | .5366 | after-verification metrics |
| E6 | AgentHallu DEV claim-level (blockrun) | 426 claims | 160 | 65 | 125 | 76 | .6260 | P .7098 R .5599; wall 3910 s; records sha256 68754e2c... |
| E9 | robustness (paraphrase/perturbation) | - | - | - | - | - | - | flips 0 |

Reference judges (previous sessions): E2 pollinations/gpt-oss-20b F1 .7556
(n=39); E2 blockrun F1 .6333 (n=43); E2 llm7/codestral F1 .5217 (n=30 quota).

## Q experiment state (INCOMPLETE, blockrun/pollinations/local)

- `experiments/superz_fullcycle/q_discriminate.py` + `q_local_checker.py` +
  `local_llm.py` (granite-guardian as plain generator via manual role tokens).
- theory extraction: blockrun 20 OK / 26 FAILED (34 cases attempted);
  pollinations mostly FAILED (provider ENOSPC); local (granite) FAILED —
  tokenizer error (missing sentencepiece for slow-tokenizer conversion).
- 3 stuck pollinations extract jobs were cancelled at FULL_21 start
  (banned provider, no progress). Cancelled job ids: 494d84d1, 54834595
  (dc7471c9 self-completed with failures).
- Q diff/answer/repair/verdict stages were never started.
- FULL_21 section 9 REDEFINES Q on Mistral API + NuExtract/LangExtract + Clingo.

## Control result to reproduce (from flash agent line, NOT this archive)

`research/flash-20260921` @ `8904a35`: granite groundedness full46 F1 .7805
(TP16 FP2 FN7 TN21); ensemble baseline OR granite F1 .8889 (TP20 FP2 FN3 TN21).
Artifacts: flash-repo `outputs/ifc/{ensemble_report_v1,percase_v1}.json/csv`.
AgentHallu DEV validation of granite groundedness: F1 .4043 (P .644 R .295).

## Known blockers at archive time

1. GitHub push: PAT is REDACTED in all Super Z directives; no credentials on
   server (~/.git-credentials absent; /etc/gitconfig has ModelScope headers
   only). Flash agent pushed from its own local environment (not shared).
   Mitigation: server-side commits + `git bundle` with SHA-256 manifest.
2. Mistral API: key lives in root-only `/mnt/data/guardian/secrets/mistral.env`;
   Gateway exec jobs run as uid 1000 (guardianagent) without env injection
   (`op_start` supports argv/cwd/timeout only). FULL_21 directive 23.3 model/API
   block was left as an unfilled placeholder. Local plan: local
   mistral-7b-instruct-v0.3 + NuExtract + LangExtract(local backend) + Clingo.
3. LangExtract grounder in repo expects Mistral API (`ministral-14b-latest`);
   must be re-pointed to a local OpenAI-compatible backend for FULL_21.

## Uncommitted files included in this archive commit

- experiments/superz_fullcycle/{local_llm.py, q_discriminate.py,
  q_local_checker.py, sweep_failed.py} (new)
- experiments/superz_fullcycle/{a4_pg.py, keyless_client.py, p_precond.py} (M)
- outputs/superz_fullcycle/e2_a0_cross/blockrun/cache/ + pollinations cache
  (raw API responses, evidence for metrics above)
- outputs/superz_fullcycle/chainlogs/ (copied from agent-workspace logs)
"""
os.makedirs("docs/superz_fullcycle", exist_ok=True)
with open("docs/superz_fullcycle/ARCHIVE_FULL_21.md", "w") as f:
    f.write(ARCHIVE_DOC)

# 5. commit everything
run("git add -A")
rc, so, se = run("git commit -m 'full_21: archive previous superz work — E1..E9 + G/P/G+P (blockrun line), Q partial state, chain logs, archive doc' 2>&1 | tail -3")
log.append(f"commit rc={rc}: {so} {se}")
_, new_head, _ = run("git rev-parse HEAD")
log.append(f"archive head: {new_head}")

# 6. attempt push (expected to fail without credentials)
rc, so, se = run("git push origin full_21/archive-previous 2>&1 | tail -3", timeout=120)
log.append(f"push rc={rc}: {so[:200]} {se[:300]}")

# 7. git bundle to stable server dir + sha256
bundle = "/mnt/data/guardian/results/full21_archive_previous_20260921.bundle"
rc, so, se = run(f"git bundle create {bundle} full_21/archive-previous 2>&1 | tail -2")
_, sha, _ = run(f"sha256sum {bundle} | cut -d' ' -f1")
_, size, _ = run(f"stat -c%s {bundle}")
log.append(f"bundle rc={rc} sha256={sha} size={size}")

print(json.dumps({
    "log": log,
    "archive_head": new_head,
    "bundle": bundle,
    "bundle_sha256": sha,
    "bundle_size": size,
}, ensure_ascii=False, indent=1))
