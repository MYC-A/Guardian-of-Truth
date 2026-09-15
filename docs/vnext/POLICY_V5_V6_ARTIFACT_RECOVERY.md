# Recovery report: Policy V5/V6 sealed artifacts (2026-09-14)

Purpose: document, with machine-checkable evidence, what happened to the sealed
Policy V5/V6 artifacts and what this handoff contains. No numbers were re-derived,
re-judged or written by hand from conversation memory into any bundle.

## 1. Timeline (file mtimes in the surviving session workspace `/tmp/my-project`)

| when (2026-09-13) | what |
|---|---|
| 08:41–10:41 | policy_programs_v1 resume session (Task 1); commits 5618c64, 0e59804 pushed to local branch only |
| 11:53–13:04 | probe_p1_transport.py, smoke_policy_v3_runner.py, diagnostics/p1_transport_probe.json; docs POLICY_V3_RESEARCH_REPORT.md (12:01) |
| 13:49–13:58 | `policy_v4_cases.json` (390,865 B) + policy_v4 per-case arm files (arm_a, arm_b1, arm_b23 + mut_00/01) — captured inventory: `tool-results/bash_1789314758852_*.txt` |
| 15:43–15:56 | POLICY_V4_RESULTS.md (8,602 B); benchmark source reads captured: `tool-results/read_1789314839583_*.txt` (policy_v4_benchmark.py, 512 lines) |
| 16:17–17:56 | **policy_v5 run**: 142 cases; `policy_v5_cases.json` 466,249 B; per-case `arm_a` / `arm_b24` (+ `adm_00/01` admission verdict files); `policy_v5_predictions.json` 750,862 B; `policy_v5_prediction_seal.json` 443 B; `policy_v5_results.json` 599,774 B; `policy_v5_failure_audit.json` 514,109 B; `policy_v5_freeze.json` 9,066 B; `policy_v5_gates.json` 1,883 B; POLICY_V5_RESULTS.md 11,848 B — captured inventory: `tool-results/bash_1789322908821_*.txt`; benchmark source read captured: `tool-results/read_1789322967720_*.txt` (policy_v5_benchmark.py, 605 lines) |
| 18:08–18:17 | V6-cycle verification/audit scripts written: verify_v5_artifacts_v6cycle.py, audit_v5_coordination_stage_a.py, classify_v5_coordination_audit.py |
| 20:19 | decompose_v6_failures.py — references `policy_v6_predictions.json`, `policy_v6_results.json` (mutation_ledger), `policy_v6_benchmark.py`, `policy_v6_arms.py`, `policy_v4_scoring.py`, arm key `arm_b245` |
| 2026-09-14 ~03:00 | sandbox rebuilt; repo restored from the ~11:53 state; all V3–V6 outputs (untracked, never committed, never pushed) lost; `/tmp/my-project` partially survived (scripts + tool-results), its `guardian-of-truth/` clone removed |

## 2. Verification performed in the current environment (all negative)

- repo tree: no `policy_v4/v5/v6` prediction/result/cases files in `outputs/` or `benchmarks/`.
- git: single local branch; reflog = clone → 5618c64 → 0e59804 → f86b9a5 (my C-ALR prereg commit);
  `git fsck --full --unreachable --dangling` → nothing.
- remote: `git fetch origin` advanced `experiment/guardian-vnext-from-0199bf9` 6ab4af0..8b0d13c —
  new commits are Goal-v3 work only; `git ls-tree` on all remote branches → 0 `policy_v[3456]` files.
- filesystem: `find / -xdev` for `policy_v6_*.json`, `policy_v5_predictions.json`,
  `policy_v5_results.json`, `policy_v4_predictions.json` → nothing outside the lost sandbox.
- `upload/` empty; `/tmp/my-project` contains no `guardian-of-truth/`.

## 3. What survived and is included (verbatim)

1. `policy_v4_benchmark.py` (512 lines) and `policy_v5_benchmark.py` (605 lines) —
   recovered from tool-result captures by deterministic line-number-prefix stripping
   (`scripts/recover_policy_benchmarks.py`); syntax-valid; provenance hashes in
   `recovered/_recovery_provenance.json`. These define the V4/V5 benchmarks and their
   gold (admissible structures literal in templates; "frozen_before_predictions": true).
2. Six V6-cycle session scripts (see README) — they document the exact sealed-file
   shapes: predictions `{case_id, arm_a|arm_c: {...}, arm_b24|arm_b245: {value:
   {structure, program, mutations: [{mutation_type, admission: {code,
   grounded_spans}}]}}}`, results `{arm_c, arm_b4, mutation_ledger rows
   {case_id, mutation_type, licensed, admitted_b4, judged_status}, paired, by_family}`,
   seal `{prediction_sha256 (canonical digest), case_ids_sha256, gold_joined=false}`.

## 4. What is lost and must be re-supplied to emit the bundle

- V5: `policy_v5_predictions.json`, `policy_v5_prediction_seal.json`,
  `policy_v5_results.json`, `policy_v5_failure_audit.json`, `policy_v5_freeze.json`,
  `policy_v5_gates.json`, `policy_v5_cases.json`, per-case request/result files.
- V6: predictions, results, seal, cases, failure audit, plus the source modules
  `policy_v6_benchmark.py`, `policy_v6_arms.py`, `policy_v4_scoring.py` (not even
  inventoried before loss — only referenced by `decompose_v6_failures.py`).
- Also lost: `POLICY_V3_RESEARCH_REPORT.md`, `POLICY_V3_RESULTS.md`,
  `POLICY_V4_RESULTS.md`, `POLICY_V5_RESULTS.md`, V4 predictions/results.

Re-supply options, in preference order:
1. The user restores verbatim copies from wherever the previous sandbox's files were
   mirrored (local disk, another machine, backup). Everything else in this handoff
   then produces the bundle deterministically.
2. If no copy exists anywhere: the V5/V6 runs are not reproducible without new LLM
   calls, which this task explicitly forbids — the honest conclusion is that the
   sealed V5/V6 evidence is gone and the C-ALR cycle needs a re-run protocol
   (outside this handoff's scope).

## 5. What was NOT done (by rule)

- No LLM calls; no re-scoring; no gold edits; no reconstruction of predictions;
- no conversation-quoted number was written into any machine artifact as a fact;
- no KEEP/REJECT conclusion — Stage A remains the decision point.
