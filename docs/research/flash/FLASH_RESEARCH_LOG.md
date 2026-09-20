# FLASH research line — independent continuation (2026-09-21)

Branch: `research/flash-20260921` (base = `research/independent-fullcycle-20260920` @ `a16d9b1`).
Agent prefix: **flash** (isolated per multi-agent directive; several agents work concurrently).
Server workspace: `/mnt/data/guardian/agent-workspace/flash-repo` (own clone; foreign worktrees untouched).

## Directive being executed

"GUARDIAN OF TRUTH — ПРОДОЛЖЕНИЕ ИССЛЕДОВАНИЯ A4/E4 И НОВЫХ АРХИТЕКТУР" (upload, 2026-09-21):
(1) restore actual state, (2) finish A4 and E4, (3) fix control configurations,
(4) study Astra material, (5-8) experiments G (existing fact graph), P (local precondition
checks), G×P, (9) combinations with A4/E4, (10) Q discriminating questions, (11) contrast
pairs, (12) self-directed methods, (13) independent evaluation, (14) unified protocol,
(15) git discipline with intermediate pushes.

## State restoration findings (2026-09-21)

- My previous line (`research/independent-fullcycle-20260920` @ `a16d9b1`) is fully pushed;
  best confirmed result there: ensemble `baseline OR granite_grounded` F1 0.8889 (TP20 FP2 FN3),
  granite groundedness alone F1 0.7805; 3 residual FN = premature-escalation class;
  AgentHallu DEV 488 independent check of granite: F1 0.4043 (honest negative).
- The interrupted session referenced by the directive was located:
  workspace `Guardian-superz-fullcycle`, branch `research/independent-fullcycle-20260920-superz`
  @ `1c47059`, **5 commits NOT pushed to GitHub**, untracked `experiments/superz_fullcycle/a4_analysis.py`.
  Its E-series: E1 baseline reproduction .6857 (exact), E2 cross-model judges
  (pollinations .7556 n=39 / blockrun .6333 n=43 / llm7 .5217 n=30 partial),
  E3a A1R re-anchor (95/120 anchored, F1 .6452), E3b live A1R (queued), E4a fragment-scoped
  A3 verification (6 CONFIRMED / 18 REFUTED / 69 UNCERTAIN → F1 .1538, REJECTED — committed),
  **E4b full-context A4 verification ("running" at interruption)**, E5 AND-ensemble .7442,
  E6 AgentHallu (in flight), E7 Granite OR .7222 (exact), E8 mutual critique (queued),
  E9 robustness (queued).
- The directive's "A4: 7 CONFIRMED / 9 REFUTED" corresponds to an intermediate snapshot of
  the E4b journal (`a4_pollinations/verifications.jsonl`); at interruption it held
  82 records: 24 CONFIRMED / 39 REFUTED / 15 FAILED (8 unique FAILED keys, "empty model
  reply" on long telecom contexts).
- E2E-agent-1's historical "E4" (retention arm, coverage .174) is a DIFFERENT E4
  (manual/guardian_master_handoff_2026-09-19.md); the directive's E4 pairs with A4 inside
  the interrupted session's e4_a34_verify package. Both readings documented; this line
  completes the a34_verify package (directive sec. 2) and does not resurrect the retention arm.

## What is running / completed in this line (updated as work proceeds)

### Step 1 — E4b/A4 completion (in flight)
- Read-only copies of the interrupted session's artifacts → `outputs/flash/sources_superz_e4/`
  (provenance recorded; their workspace NOT modified, their branch NOT pushed by me).
- `experiments/flash/flash_e4b_complete.py`: re-verifies ALL 94 positive suspicions with an
  independent channel (blockrun pool, gpt-oss-120b-class) under the IDENTICAL A4 prompt —
  dual-purpose: (a) completes the 8 FAILED keys so technical failure is never silently
  treated as refutation (directive sec. 18), (b) full per-key verifier-model dependence data
  (directive sec. 2.1). Journal: `outputs/flash/e4b_a4_verify/verifications_flash.jsonl`.
- `experiments/flash/flash_a4_analysis.py`: per-suspicion analysis (producer, reason_type,
  anchors, verdicts, correctness classes, eliminated FP / lost TP / new FP / gained TP,
  final confusion vs E3a control + line controls, multi-suspicion handling).

### Step 2 — experiment G (prepared)
- Own worktree `.worktrees/fullarch` = `origin/full-architecture-v1` @ `923bb44` (read-only usage).
- `experiments/flash/flash_g1_graph_verify.py`: paired G3 probe — same blockrun verifier,
  same prompt skeleton, but `<history_digest>` replaces raw prompt: graph-derived compact
  digest (FactNode facts linked to response tokens by exact value match; entity-scope
  expansion; explicit omission notes; raw-text fallback for non-JSON KB results).
  Control = E4b blockrun full-context verdicts. Digests measured 1.2-6.1k chars vs 21-47k raw.
- Graph build smoke-tested on server: airline__10::t19 → 69 events, 781 facts, 13 linked events.

### Control configurations (directive sec. 3) — see CONTROLS_FLASH.md

## Infrastructure notes
- .gitignore: flash whitelist added (`outputs/flash/**` selective).
- Keyless client `experiments/flash/flash_keyless.py`: blockrun min_interval 13s,
  pollinations 16s, llm7 8s; disk cache under `outputs/flash/_llm_cache_flash/` (not committed).
- Big files NOT committed: `sources_superz_e4/input.csv` (2.6MB, derivable from valid.parquet
  by dropping labels), LLM cache. Committed: a1r_cases.jsonl, source verifications.jsonl,
  flash journals, analysis outputs, scripts, docs.
