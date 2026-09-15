# E2E COMPOSITION V1 — engineering worklog

## Phase 0 — Audit (2026-09-16)

### Topology establishment

- The integration baseline `8b0d13c` is the remote tip of
  `origin/experiment/guardian-vnext-from-0199bf9`; the local policy research
  line (tip `892093f`) had diverged from merge-base `6ab4af0` and was never
  pushed. The two lines partition the late components: the baseline line
  carries the Goal v3 archive + external source views v6 (with
  `declared_plan_actor`) + all vnext proof/factual infrastructure; the policy
  line carries the measured Policy research (C-ALR reimpl, PHV1, PSB, GRS,
  Policy final cycle) + the completed sealed policy_programs_v1 run.
- Assembled `experiment/guardian-e2e-v1` = merge(baseline `8b0d13c`,
  policy line `892093f`) as commit `a199252`. 372 add/add conflicts, all in
  `policy_programs_v1_*` outputs (baseline held an earlier partial sync of the
  run; the policy line holds the completed sealed run) — resolved to the
  policy line's sealed versions; `PROGRESS.md` auto-merged as a union;
  everything else auto-resolved.

### Verification

- Baseline suite (`PYTHONPATH=src`, worktree at `8b0d13c`): 1484 passed /
  6 failed / 482 subtests. Merged E2E tree: 1549 passed / 6 failed.
- Failure classification: `scripts/audit_baseline_freeze_drift.py` proves all
  freeze-manifest non-exact entries are EOL-only (content-identical under LF
  or CRLF normalization); 28 manifests scanned in the merged tree. One
  failing test is a provider-env binding test requiring absent API keys.
  4 pre-existing CONTENT_DRIFT entries are the disclosed post-seal runner
  fixes (PSB paired-statistics counter; policy-final scoring fixes;
  grs_dev rerun tooling) — documented in their results files, seals
  untouched.
- Working-tree byte state note: this repository's freeze manifests were
  authored under mixed line-ending states (Windows autocrlf author + LF-pinned
  `vnext/**`); no single working-tree byte state satisfies all manifests
  simultaneously. The E2E worktree is kept at `core.autocrlf=true` (author
  state for the majority, matching the main checkout where all policy seals
  were produced and verified).

### Component provenance

- H0: byte-identity chain C-ALR → PHV1 → PSB → GRS → final machine-verified
  inside the merged tree (all continuity tests green in the 1549).
- GRS-refined: grounder + frozen B1 + canonicalizer verified via the policy
  final freeze `identity_continuity` block and green tests.
- T1 (16/16), T2 (18/18, nontrusted), Binding v2 (34/34), Claim Graph v1
  (sealed, 41 cases), SourceEnvelope v4 audit, Temporal v4 — sealed artifacts
  present and test-covered.
- Goal sweep (Conservative incumbent, FR1, E5, trusted frame assembler):
  NOT PRESENT. Exhaustive negative verification: worktree, all branches,
  full object inventory, reflog, fsck dangling, upload/, download/, remote
  refs, GitHub API search. The repository's goal line ends at the baseline
  commit itself (extraction v3 rejection; S1-scale results, behavioral 0.0)
  which does not match the spec's sweep numbers (80.8%/63.5%/78.6%).
  → REQUIRED INPUTS BLOCKER recorded in the manifest (§G) and the Phase 0
  audit; delivery contract specified (git ref or hashed bundle).

### External benchmarks

- Located and probed reachable: `ethz-spylab/agentdojo`,
  `sierra-research/tau2-bench`, `apple/ToolSandbox`, `LiYu0524/ATbench`.
  No imports yet; adoption audits are Phase 2 work (spec §69).

### Deliverables

- `docs/vnext/E2E_COMPONENT_MANIFEST_V1.md`
- `docs/vnext/E2E_COMPOSITION_V1_PHASE0_AUDIT.md` (spec §103 audit block)
- this worklog

### State

Phase 0 COMPLETE. Phase 1 (integration design) BLOCKED on Goal-axis required
inputs per spec §6; no E2E arm can run without them (E0/E1 need the
Conservative incumbent; E2/E3 need FR1/E5; E4 needs both). No fabrication
was performed; no LLM inference was requested in this phase.
