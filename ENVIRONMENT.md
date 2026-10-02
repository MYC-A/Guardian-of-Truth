# ENVIRONMENT — research/three-architectures-24gb-20260930

Snapshot taken 2026-09-30 (new instance after migration). No secrets inside.

## Hardware (measured)

- GPU: NVIDIA GeForce RTX 3090 — 24576 MiB (24 GB class; prompt constraint assumed 24 GB VRAM)
- GPU driver: 580.159.03; CUDA Version: 13.0
- CUDA toolkit in image: 12.8 (nvcc V12.8.93); torch runs cu128 wheels
- CPU cores: 24
- Host RAM visible: 61 GiB; cgroup memory.max: 42.0 GiB
- Disk (overlay): 32G total, 11G free
- Container: Docker (vast.ai image, kernel 6.8.0-124-generic), hostname 24a8e939b2cc

**Design constraint per directive:** 24 GB GPU VRAM / 31 GB system RAM.
Measured limits are LOOSER (42 GiB cgroup RAM, 61 GiB host). All experiment
sizing in this branch is done against the stricter directive numbers
(24 GB / 31 GB); measured headroom is documented but not relied upon.

## Workspace layout

```
/workspace/guardian/
  venv/                    research venv (Python 3.12.3, uv)
  repos/Guardian-of-Truth/  repo, research branch checked out
  models/granite-guardian-4.1-8b/   (16G, Apache 2.0, rev recorded in .download_meta.json)
  hf_cache/                HF_HOME
  secrets/                 mistral.env, github_pat, api_keys.env (chmod 600/700, never printed)
  results/  logs/
```

## Python stack (venv, proven stack from previous stand)

torch 2.10.0+cu128+cu128 (CUDA on RTX 3090 verified: matmul+autograd OK),
transformers 5.16.1, sentence-transformers 6.0.1, peft 0.21.0, accelerate,
langextract 1.7.0, compressed-tensors 0.15.0, pandas, pyarrow, numpy,
requests, openai, pytest/pytest-asyncio, clingo, fastapi, uvicorn,
jsonschema, pydantic, hypothesis; guardian-truth editable install.

## API channels (smoke-tested 2026-09-30, statuses only)

| channel | endpoint | status | notes |
|---|---|---|---|
| Mistral | api.mistral.ai | 200 OK (chat completion) | key in secrets/mistral.env, model ministral-14b-latest |
| ollama.com free | ollama.com/v1 | 200 OK | gemma4:31b responded "OK"; also gpt-oss:20b/120b, nemotron-3-nano:30b/-super/-ultra worked in prior session; glm-5.3-flash is 402 paywalled |
| ukisai swift | ukisai.com/api/swift/v1 | 200 OK | reasoning model: allow higher max_tokens, content may trail reasoning_content |
| vireonix auto | vireonix.ai/v1 | 200 OK | model "auto" answered "OK"; actual backing family unverifiable — do not claim family independence |

Local GPU model: granite-guardian-4.1-8b (bf16 ≈ 15.6 GiB VRAM when loaded;
measured on the previous stand; sequential load/unload discipline).

## Provenance of environment facts

- Migration from previous vast stand (171.5.185.194:44479, RTX 3090 24G,
  125G RAM) — that stand is no longer reachable; all facts above were
  re-measured on THIS instance, not copied.
- Free-API provider credentials originate from the user's previous-session
  handoff (chat history), stored in secrets/api_keys.env; never printed.

## Re-provisioning addendum (2026-10-01, second stand migration)

The instance hosting this branch's runs became unreachable; the stand was
rebuilt on a new Vast machine (RTX 3090 24 GB, driver 595.84, CUDA 12.8
toolkit, 64 cores, 251 GiB RAM, hostname e0d16af6cec4). Everything below was
re-measured on THIS instance; the worktree lives at
`/workspace/guardian/repos/hybrid-assistants-worktree` (the path the launch
scripts expect) at branch HEAD 871293c9.

Re-verified on the new stand:

- venv: torch 2.10.0+cu128 (CUDA matmul+autograd OK), transformers 5.16.1,
  huggingface-hub 1.33.0 (pinned <2.0 for transformers 5.16.1), nltk + punkt
  (required by factcg_native.py), guardian-truth editable.
- granite-guardian-4.1-8b re-downloaded at pinned revision
  ab01ccca5dcfb80246369a086a4a87a29198f5af (16 G); bf16 local channel via
  llm.py: cold load ~10 s, greedy generation ~2 s, VRAM freed on exit.
- MiniCheck-Flan-T5-Large re-fetched from lytang/MiniCheck-Flan-T5-Large.
  Disk-dedup note: the hub cache held BOTH the original pytorch_model.bin
  and the HF auto-conversion model.safetensors (3.13 G each). The two were
  proven functionally IDENTICAL on the branch's 15-case native bank
  (same per-example probabilities to 3 decimals, acc .867, misses exactly
  on the two policy-interpretation cases — bit-consistent with the smoke
  recorded on the previous stand). To keep both load paths
  (main-ref bin / device_map conversion ref) resolving to the same bytes
  without re-downloading, the conversion blob was replaced by a hardlink to
  the original (freed 3.13 G; disk now ~3.7 G free).
- FactCG-DeBERTa-v3-Large re-fetched at pinned revision
  0430e3509dbd28d2dff7a117c0eae25359ff3e80; the redundant
  pytorch_lightning_ckpt (~1.7 G) is deliberately NOT downloaded
  (model.safetensors is the only weights path factcg_native.py loads);
  native-format load + score verified on GPU (435M params, 1.64 GiB VRAM).
- Bespoke-MiniCheck-7B and PRT-Qwen-7B remain BLOCKED:disk (unchanged
  protocol decision — ~15 GB weights each do not fit alongside granite).
- All five API channels re-smoked through llm.py: mistral 0.7 s, ollama
  gemma4:31b 0.7 s, ollama gpt-oss:20b 0.9 s, ukisai swift 1.0 s, vireonix
  auto 2.6 s — all answered the standard prompt.
- Branch test suite: 42 passed (hybrid_service_v1: archive_dsp,
  formal_advisory, specialist_bank, structural_v02, v2_boundaries;
  tests/: fresh_suite_v1, hybrid_campaign, hybrid_service_fixes).
- service/test_service_smoke.py in its script mode (as on the previous
  stand): 7/7 passed, including the batch CLI + JSONL audit path. In the
  isolated smoke environment the v6-judges config reached the live judge
  channels (provisioned here) and returned a valid verdict.
- Native checker bank reproduction (the numbers the protocol's Stage A
  recorded): MiniCheck-Flan-T5-Large 15/15 format, acc .867, misses
  idx {3, 13} = the two policy-applicability cases — identical to the
  previous stand's smoke. FactCG and Granite BYOC load and answer in their
  native formats on this stand.

No committed outputs were modified by the re-provisioning; the smoke
reproductions above were run as ad-hoc probes (not written into
outputs/native_smoke*), preserving the recorded results.

## New free channels addendum (2026-10-02, third-stand session)

User-supplied additional free API models were probed (one short real chat
probe per channel; probes are counted attempts):

- ollama.com/v1 now also answers: glm-5.3-flash -> HTTP 402 "not included
  in your free usage" (channel OFF, quota-blocked; do not re-probe until
  quota/config changes), gpt-oss:120b (reasoning model — empty content at
  tiny max_tokens; needs larger output budgets), nemotron-3-nano:30b,
  nemotron-3-super, nemotron-3-ultra (all OK, 0.6-1.5 s).
  gpt-oss:20b/gemma4:31b and ukisai/swift + vireonix/auto re-confirmed.
- NEW provider aihorde (oai.aihorde.net/v1, anonymous public key
  "0000000000", crowdsourced: latency/availability vary): google/
  gemma-4-31b OK (7.1 s via llm.py), koboldcpp/Llama-3.2-3B-Instruct OK
  (2.9 s). koboldcpp/Qwen/Qwen3.5-0.8B timed out at 150 s (worker offline;
  not retried — low value). response_format/json_object is NOT sent to
  aihorde (compat not guaranteed), same guard as ukisai/swift.
- Family accounting: google/gemma-4-31b is the SAME gemma family as
  gemma4:31b (transport redundancy only, never an independent family
  vote); koboldcpp/Llama-3.2-3B-Instruct is the small llama family;
  nemotron-3-* sizes are one nemotron family; gpt-oss:20b/120b one family.
- llm.py registry extended accordingly (aihorde provider + two models);
  verified through the real llm.py transport path with cache disabled.

## Economy fixes + §7 A/C runs addendum (2026-10-02, continuation session)

Three user-reported economy bugs fixed and verified offline (commit 4f978cdf;
12/12 test_budget_breaker tests, 16/16 boundaries, 9/9 binding tests; the
frozen negative-pilot code identity d41f244f... deliberately UNCHANGED —
fixes live in modular_common.py / channel_breaker.py / run_control.py only):

1. Runner phase wiring: Budget() and split-aware runners resolve the phase
   explicitly through budget_phase() (dev continuation -> authorized dev2,
   sealed -> frozen heldout); GUARDIAN_MODULAR_BUDGET_PHASE pins a launch.
   The exhausted legacy pilot ledger (699667/700000) is never an implicit
   default again.
2. Atomic single post-cooldown admission: an expired 429 cooldown is claimed
   by exactly ONE caller (breaker state PROBING, BEGIN IMMEDIATE re-check);
   concurrent callers are vetoed with PROBE_IN_FLIGHT until the admitted
   request finishes (success clears / 429 re-arms with inherited cycles /
   5xx releases). Claim window 300 s > client timeout 240 s.
3. Unknown-spend ceiling now counts in-flight RESERVED api rows (the
   150k+150k under a 200k cap repro now vetoes the second reservation).

§7.A closed (0 new API attempts): FactCG fixed 6-claim bank complete
(12/12 rows; the two remaining claims scored 0.5169 / 0.9272), and the saved
V2 proposals replayed offline (v2_replay.py): 15 archived answers re-served
by exact cache key, 13 journaled live-call failures reproduced as failures,
proposals bit-identical on 4/4 cases; native Steps 2-4 recomputed with the
current layer (fact counts 0->3 on two cases — documented evolution, the
pilot_v2 journal is untouched history).

§7.C closed (dev2 phase): frozen negative-routing B-run executed from pin
87182e5c (= 97ad5a8b + the two infrastructure commits above; freeze gate
re-verified pre-launch: code_sha256 == selection.json). 48 unique shared-B
mistral queries, 192/192 arm decisions, 53 dev2 attempts / 92381 logical /
91339 known tokens / 169 s / 0 pending. Verdict scoring
(score_negative_arms.py): strict_positive reproduces the archived C0 exactly
(TP25/FP3/FN1/TN19, F1 .9259); strict_always TP26/FP21/FN0 (F1 .7123);
strict_source_adaptive and strict_matched_random BOTH TP26/FP8/FN0 (F1
.8667) from DIFFERENT selected sets (overlap = the known FN only): the
shared B reviewer flags an additional error on every reviewed NO_ERROR
primary (6/6 per arm), repairing the known FN (dev_inclusive_timezone::02,
valid review, not CONFIRMED-by-routing) at the cost of 5 new FPs each.
Honest negative: at equal query fraction the adaptive source triggers show
no dev advantage over matched random; B's additional-error precision on
clean NO_ERROR primaries is the governing factor (1/6 per selection).

# ENVIRONMENT.md addendum — §7 B–F continuation (2026-10-02, pin 8b2bdf11)

Inference pin: every §7.B–F API run below executed at git HEAD 8b2bdf11
with GUARDIAN_MODULAR_BUDGET_PHASE=dev2; no commit happened mid-run. All
selection files were frozen before their first paid call; gold was opened
only by post-run scorers after the journals were complete.

§7.B closed (graph arms resume + atomic completion, dev2):
- pilot_graph 24/24 rows (6 legacy pilot-phase rows preserved + 18 new
  dev2 rows): G1/G2/G2-linear/G3 all TP2/FP0/FN0/TN4 on the paired
  6-case bank, pairwise decision agreement 6/6; two legacy rows keep
  INVALID B (dev_latest::00 G2-linear/G3) preserved as-is; G3 bounded to
  <=4 read-only queries (one legacy row requested 0). Provenance note:
  dev_latest::01 G2-vs-G2-linear information_sha256 differs ONLY because
  the G2 row is legacy code and G2-linear is dev2 (typed-binding graph
  fields; 96/96 selection-identical regression) — within one provenance
  every pair shares the hash. All arms forward the full prompt plus an
  advisory: added organization/prompting is measured, not context economy.
- pilot_atomic 6/6 rows: honest negative — atomizer INVALID 4/6
  (invalid_atom_inventory / per-atom shape on tool-call targets), verifier
  MODEL_JUDGED 1/6; gold atomic_claims remain a diagnostic layer only.
  Analysis: results/modular_steps_20261002/mechanism_paired_analysis.json.

§7.C tail closed (temporal-calculation assistant module):
- New author bank dataset/temporal_boundary (10 cases: +05:45/-12:00/-06:00
  minute offsets, +14:00 extreme, fractional seconds, cross-day equality,
  unzoned literal determinable only by reasoning, latest-of-two clocks).
- Offline ground-truth gate (module_verification.json): PASS 18/18 — ISO
  arithmetic exact, spans verbatim, ADVISORY_ONLY decision, unzoned literal
  declined (no default timezone guessed).
- Paired run (temporal_assistant_pilot): identical sources, strict
  source-bound-v2 B without vs with the module advisory; primary J reused
  from the frozen control archive (4 cases) or run once per new case and
  shared by both arms. Result: 18/18 decisions UNCHANGED (both arms
  TP6/FP12/FN0 — B flags additional errors everywhere; precision on clean
  governs), known FN dev_inclusive_timezone::02 repaired by a valid B
  verdict in both arms. Honest negative: the code-computed arithmetic
  advisory changes no B verdict on this bank. Cost: B_with adds ~1.1k
  logical tokens per case for the advisory payload (measured, journaled).
- Attempt-1 ran fresh primaries for all 18 cases (contradicting the frozen
  reuse plan); archived in full as temporal_assistant_pilot_attempt1 with
  RECOVERY_NOTE.json; versioned recovery re-ran with archive reuse at
  ~1 fresh API call (cache-identical messages re-served); attempt-1 costs
  remain counted in the dev2 ledger.

§7.D closed:
- M1 automatic SystemV2 Steps2-4 E2E (system_v2_pilot.py, 4 cases,
  ordinary upstream — no gold substitutions; §7.A replay had already
  proved the archived proposals bit-identical): equals archived C0 exactly
  (TP3/FP0/FN0/TN1; all four C0->v2 transitions unchanged; not degraded).
- M2 bounded CCG (ccg_bounds.py, offline, zero API): bounded repair
  cascade recovered 11/11 previously failed sentences (7 pure LEXICAL:
  sentence re-split / semicolon split / composed boundary split /
  equals-normalize / drop-back; 4 LEXICALIZED_SEMANTIC rewrites
  'regardless of' -> 'without regard to'); every attempt journaled
  before/after. Minimal meaning-flipping counterexamples (only-if,
  unless, negation, modality, connective scope, inclusive/exclusive
  boundary, implication direction): 19/20 DISTINGUISHED (HOL root formula
  changed), 1 COVERAGE_GAP (transformed refusal sentence unparseable),
  0 INSENSITIVE. coqtop is not installed and was not installed (no
  gigabyte Coq on this disk); no lossy HOL->proposition bridge attempted;
  predicates remain uninterpreted — no normative-semantics claim.

§7.E closed:
- SelfCheck bank (selfcheck_bank.py, 3 preselected uncertainty cases,
  k=3 seeds 19/37/53, temperature .7, max_tokens 800): judge mode
  (gemma4:31b on JUDGE_SYSTEM) and reconstructed-target mode (mistral,
  explicit reconstruction prompt) measured separately, never mixed.
  agreement 1.0 / frequency entropy 0 on all three; native SelfCheck-NLI
  (author SelfCheckNLI class, DeBERTa checkpoint) judge-mode contradiction
  0.005/0.003/0.164; reconstructed-target-mode 0.845/0.605/0.584 — the
  target-mode number measures divergence from the surrogate generator,
  not truth. SEP not claimed (no hidden states/probe on API models).
  Environment: transformers 5.16.1 (main venv) cannot load the DeBERTa
  spm tokenizer even with tiktoken 0.14.0 installed (attempted); the NLI
  execution runs under modular_venv (transformers 4.57.6), matching the
  earlier selfcheck_recovery provenance.
- RAG-Triad bank (triad_bank.py completes pilot_triad to a 3-case bank;
  raw / G2 / G2-linear paired inputs x target/explanation): TruLens author
  templates through the pinned transparent adapter with the budgeted
  Mistral backend — an adapted feedback executor, NOT a native TruLens
  provider run. Target moves grounded 2-3/3 across modes; Guardian
  explanations score 0-2/3 (diagnostic only, no correctness proof).

§7.F closed (long-bank LLM quality, pre-registered subset):
- 12 cases chosen before viewing results (5 family/size/position combos
  with clean+error twins + one 12k probe pair; begin/middle/end;
  exception/version families; 1k/4k/8k/12k) through the unchanged C0
  service (r0-service-v1): TP5/FP0/FN1/TN6, F1 .909, no UNKNOWN/degraded.
  Exception family 4/4 errors caught at every position; the single FN is
  the version-update family at begin. 12000-exact is in-limit by
  construction; 12001+ remains the operational UNKNOWN smoke (existing
  service_long_v2 receipts, not re-run). The bank's artificial
  two-SYSTEM-message stress layout is flagged in every prediction row.

New artifacts (all under experiments/searh_23/modular_steps_20261002/ and
results/modular_steps_20261002/ unless noted): build_temporal_bank.py,
temporal_assistant_pilot.py, score_temporal_arms.py,
score_mechanism_arms.py, system_v2_pilot.py, score_system_v2.py,
ccg_bounds.py, selfcheck_bank.py, triad_bank.py, long_bank_pilot.py,
score_long_bank.py; dataset/temporal_boundary/{input,author_gold,manifest};
results temporal_assistant_pilot(_attempt1), system_v2_pilot, ccg_bounds,
selfcheck_bank, pilot_triad_v2, long_bank_pilot,
mechanism_paired_analysis.json.

dev2 ledger after §7.A–F: 263/300 attempts, 805401/1.2M logical,
659829/1M known tokens, 807/14400 model-seconds, 0 pending reservations.
Sealed untouched; default service config R0 unchanged.

## Addendum: repair/model-roles assignment (2026-10-02, reviewer_repair)

Economy layer: Budget.install() is IDEMPOTENT per ledger — a second install
with the same phase reuses the live owner published as llm._budget_layer_owner;
a different phase raises BudgetPhaseConflict (never a silently double-wrapped
transport). modular_runtime.guarded_llm() drives the live owner. The historical
dev2 ledger was NOT rewritten: budget_reconciliation.py (read-only) isolated 39
phantom double-count pairs to the system_v2 E2E window (rows 219-296);
reconciled dev2 real spend 239/300 attempts / 688205 logical / 551276 known.

New phase reviewer_repair (budget_phases.json): 300 attempts / 1M known /
200k unknown upper bound / 1.2M logical; fully spent: 300/300, 465984 known,
597414 logical, 0 pending; modules census(7)/atomic-v2(25)/role(189)/deferred(79).

New channels measured (model_census.json): gemma4:31b, gpt-oss:20b/120b,
nemotron-3-nano:30b/-super/-ultra on ollama.com (usage + latency receipts);
google/gemma-4-31b via aihorde works WITHOUT usage reporting (upper-bound
accounting only; transport redundancy of the gemma family, never an
independent vote); glm-5.3-flash remains 402 OPEN_PERMANENT.

New artifacts (experiments/searh_23/modular_steps_20261002/): test_single_layer_
budget.py, budget_reconciliation.py, build_fp_corpus.py, fp_cause_atlas.py,
b_payload_audit.py, REPAIR_CAUSE_AUDIT.md, atomic_check_v2.py,
test_atomic_v2.py, atomic_repair_pilot.py, score_atomic_repair.py,
probe_census.py, role_prompts.py, role_pilot.py, score_roles.py,
build_deferred_bank.py, deferred_pilot.py, score_deferred.py,
MODEL_ROLE_PROTOCOL.md; dataset/deferred_bank/{input,author_gold,manifest};
repair_receipts/ (reconciliation, atlas, raw corpora, payload audit, census,
role/deferred selections and scores). Raw journals in results/modular_steps_
20261002/{role_pilot,deferred_pilot,atomic_repair_pilot}/.


### Addendum 2026-10-02 (all-methods-noft cycle)

- New budget phase modular_all_noft_20261002 (1600 attempts / 4M known /
  6M logical / 200k unknown-upper / 76,800 model-seconds); dev2 and
  reviewer_repair CLOSED (ledgers never edited). Fresh ledger
  modular_all_noft_20261002_budget.sqlite.
- Disk quota 32G, ~650M free at cycle start: model strategy is
  download→pilot→delete with pinned revisions; Granite Guardian BF16 (16G)
  runs FIRST while its weights are still on disk, then weights are deleted
  after receipts; larger candidates (safeguard MXFP4 12.1G, PRT/CANOE/Bespoke
  ~15G BF16 or 4-bit) load sequentially in freed space. No FP32 copies; no
  weights of active jobs deleted; ≥2G GPU / ≥3G RAM system reserve kept.
- Sealed vault: /workspace/guardian/results/modular_steps_20261002/sealed_vault
  (chmod 700/600, keeper protocol_auditor, access log; builder inside the
  vault only — repo carries metadata manifest only).
