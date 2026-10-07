# Guardian local A100 experiments — plan and protocol

Branch `research/guardian-local-a100-20261007-1` (from `403d811e`, tip of
`fix/guardian-contract-safety-20261007` at start; all six PROMPT control pins
verified as branch tips on GitHub, no newer fixes — the two 2026-10-07 audit
branches are ancestors of `403d811e`, not newer corrections).

**Goal.** Reduce semantic misses while preserving accusation precision and
universality; separately measure the effect of the model, the architecture, and
each additional component. Focus families: wrong sum, same-name foreign entity,
temporal conditions, exceptions, ambiguous choice, latest data state.

**Constraints.** One A100 80GB PCIe (cc 8.0, driver 595.71.05, CUDA 12.8).
No paid external LLM APIs — every new inference is a local model. Production
default and main are untouched. Rules by benchmark ID / tool name / business
value / gold are forbidden. Gold, split/family names, diagnostic IDs and ready
causes never enter any prompt or router. `workspace_is_volume=false`: push to
GitHub after every experiment cell (PAT in secrets, never printed).

## Environment

| item | value |
|---|---|
| experiment venv | `/workspace/guardian/venv` (guardian-truth editable, py3.12) |
| serve venv | `/workspace/guardian/serve_venv` (vllm 0.31.0, torch 2.13.0+cu130) |
| GGUF backend | llama.cpp built at pinned commit `f498f864fbc0472004ee1c3616c1188c68eb157f` (tag b11459) |
| endpoints | vLLM `127.0.0.1:8000/v1`, llama-server `127.0.0.1:8080/v1` (loopback only) |
| cache identity | provider + endpoint + model id + exact request bytes (after hooks) + attempt; model id carries checkpoint@revision:quant:backend — a local model is never named Ministral |

Control worktrees (read-only, never rewritten): wt-contract-safety-403d811e,
wt-v6fix-5330dcc4, wt-addons-1b543b9b, wt-semantic-28dec932,
wt-modular-6135ae69, wt-v4-32ede180.

## Variants (architecture, one change at a time)

| variant | definition | scored decision |
|---|---|---|
| A | R_fix only; no blind pass, no new components | `binary_rfix` from AM runs |
| M | A + strict v6fix@403d811e layers | `binary` from AM runs |
| B | M + leak-free neutral blind pre-pass (`blind2`) | `binary` |
| Bopen | equal-call control: same pre-pass but it SEES the current move (`open`) | `binary` |
| T | B + typed condition_checks (sources, bindings, claimed result) | `binary` |
| E | T + deterministic evaluator of the analysis' own checks | `binary` |
| L | OLD v6fix@5330dcc4 on the same rows/model (old-code worktree import) | `binary` |

A and M are read from ONE execution (`AM`, no pre-pass): both decision rules are
mechanical postprocessing of the same saved primary replies — zero extra calls.
Old leaking CB (`1b543b9b` C) is a negative control only, never a candidate.

## Models (one main checkpoint at a time)

| step | checkpoint | revision | file | backend |
|---|---|---|---|---|
| 1 | mistralai/Ministral-3-14B-Instruct-2512 | 29439f81c2be | bf16 (4 shards, 28G) | vLLM |
| 2 | ggml-org/Qwen3.8-27B-GGUF | 71bc7b627595 | Q8_0 (~28.6G) | llama.cpp |
| 3 | openai/gpt-oss-20b | 6cee5e81ee83 | native (MXFP4-capable backend) | vLLM (Harmony) |
| 4 | mradermacher/CompassJudger-2-32B-Instruct-GGUF | 7f6877f97adf | Q8_0 (~34.8G) | llama.cpp |
| 5 | barozp/Qwen3.8-27B-Opus-Distill-v2-GGUF | 64d56b13ea8d | Q8_0 (~29.0G) | llama.cpp |
| 6 | bartowski/Llama-3-Patronus-Lynx-70B-Instruct-GGUF | 581017200918 | IQ4_XS (~37.9G) | llama.cpp |

Discipline between checkpoints: stop server → save results → offline recompute
→ commit/push → verify remote SHA → delete only own downloaded weights → free
VRAM. Winner may be re-downloaded at the end for the final check. Qwen thinking
on/off is a separate ablation with time and output-truncation accounting.

## Data (existing loaders and gold; nothing relabeled)

Available in-repo now: `dev`(10) `devT`(8) `frozen`(14) `contrast`(14) short
diagnostics (author-labeled); `frozen120` with existing regression/dev/holdout
family splits; `holdout2` (72 real tau2 rows, real gold). Real sets recovered
from pinned `403d811e` git objects into `/workspace/guardian/data_root_403d811e`
(immutable; sha256 + uniqueness receipts in the extraction script): valid46
(46 rows), lb_long(57), lb2_long(47), lb3_long(56), ext_tau2(70 inputs /
68 tau2v2 gold), hold_tau2h(51), hold_holdout2(72).

Dev usage: short diagnostics + frozen120 regression/dev + holdout2 diagnostics.
Post-fixation comparison: lb2_long, lb3_long, hold_tau2h, hold_holdout2 and
synthetic holdout (pending upload), plus fresh paired runs per §Final.

## Fixed run parameters

Evidence view 20 000 BYTES (the historical budget); serialized request cap
60 000 bytes (UTF-8 body, checked pre-send); temperature 0; attempts `(0,1)`
for v6fix F extraction; workers 4 (wire bytes are worker-count independent;
local server batching is recorded in receipts).

Output budgets (owner directive 2026-10-07 §3): reason-capable models get an
initial budget of 8192 completion tokens (review + pre-pass + F extraction;
`--review-max-tokens/--pre-max-tokens/--frules-max-tokens`, recorded in every
phase manifest) because a mid-reasoning truncation is a FORMAT failure, never
a comprehension verdict; one diagnostic config at 16384 is allowed on the same
short part if truncation persists. Non-reasoning wire: 1700 review / 1700 pre
/ 700 F (historical pin). Identical INPUTS matter more than identical
completion limits; modes, budgets, times and tokens are reported separately
per model. Thinking mode: OFF for the Qwen main circle (already-started launch
completes at its pinned budgets; recorded exception), ON ablation on
dev+contrast (24 rows) at 8192; native reasoning formats (gpt-oss Harmony) run
as-native. A created-but-not-transmitted blind analysis is NOT a delivered B2.

## First circle 2026-10-07 (owner directive; supersedes the older cell plan)

Mandatory identical set for every universal reviewer candidate: dev(10) +
contrast(14) + valid46(46) = 70 fixed rows. ONE AM run and ONE B2 run; A
(binary_rfix) and M (binary, strict v6fix) are offline postprocessing of the
same AM record — zero extra calls. Ministral baseline = saved results on the
same 70 rows, no new inference. The running Qwen circle additionally covers
devT+frozen (superset; those cells were already cached, zero extra calls).
NOT in the first circle: per-model lockbox/holdout, triple repeats,
architecture sweeps, long library tuning, per-model prompt perfecting.
Checkpoint change order: save → offline recompute → commit/push → verify
remote SHA → stop server → delete own weights → next model. BLOCKED ≠ EXECUTED.

### Preregistered two-candidate selection (fixed BEFORE any first-circle result of models 2–5 is viewed)

Ranked on the 70 fixed rows, A arm and B2 arm both reported:
1. Executability gate: valid solution (valid verdict or valid fallback) on
   ≥80% of the 70 rows in the AM arm; below that the model is reported but is
   not a candidate.
2. Diagnostics sanity gate: dev F1 ≥ 0.60 AND contrast F1 ≥ 0.60 (A arm) —
   a model failing clean synthetic rows is not a candidate regardless of
   valid46.
3. Primary: valid46 F1 (the only non-synthetic set in the circle).
4. Secondary: valid46 precision (accusation precision is delivery-critical).
5. RU/EN reported separately; a candidate with RU F1 more than 2× below its EN
   F1 is flagged as RU-limited in the report.
6. Tie-breaks (in order): valid46 F1 → valid46 precision → valid-solution
   coverage on the 70 → cause correctness on the valid46 self-check sample of
   changed decisions (self-check, NOT independent labeling) → wall time per
   row → peak VRAM.
7. FP/FN compromise: two candidates with complementary profiles are allowed
   (one precision-oriented, one recall-oriented) when their valid46 F1 differs
   by ≤0.05; both are carried into stage 2.
8. Differing coverage: additionally compare the common subgroup where BOTH
   models have a valid solution; the full-row numbers stay primary.
9. No convenient-set or best-seed selection; UNKNOWN/tech rows and delivery
   failures are reported as-is and never deleted; B2 counted only where the
   blind analysis was actually transmitted to the review request.
10. Lynx runs the native document/question/answer factual-grounding role and
    is rated SEPARATELY — never merged into the universal policy-reviewer
    ranking. CompassJudger is checked through the explicitly-labeled pointwise
    adapter first; its native pairwise judging is a separate experiment.

## Metrics and repeats

Per variant×set: TP/FP/FN/TN, precision/recall/F1/specificity, UNKNOWN/coverage,
tech rows (never scored as NO_ERROR), cause_auto (target + marker where gold has
markers), family breakdown, RU/EN split (Cyrillic-share heuristic), format vs
semantic miss classification (post-hoc audit of changed decisions), calls and
actual tokens per row, wall time, peak VRAM. Repeats: rep1 everywhere; reps 2–3
only on discordant rows (pre-declared, as in the addons study); final key
comparison gets three fresh paired runs — deterministic temperature-0 repeats
are reported as such, never summed as independent examples. Family-level
uncertainty for synthetic splits.

## Choice rules (fixed before runs)

1. A candidate must not lose precision on dev diagnostics while gaining recall;
   FP/FN conflicts are reported as trade-offs, not net wins.
2. Mechanical authority is never extended to make F1 look better; no new
   mechanical certificates without a cited contract text.
3. `tool_universe_closed` / `history_complete` only with a real caller
   guarantee of the input contract; a AVAILABLE TOOLS header alone never closes
   the universe.
4. Component admitted only with measured contribution on the SAME base-system
   inputs (TP/FP/FN/cause/coverage/cost), including a local test that the
   native adapter actually fires on an error/clean pair.
5. Model comparison uses the same base architecture (A/M/B) on the same rows;
   different architectures go to a separate table.
6. No benchmark-ID/tool-name/business-value rules; contrasts added on dev use
   the published mutation kinds (rename, reorder, same-name owner, boundary
   sum/date, permissive exception) and freeze before running.

## Experiment cells and commit protocol

A cell = model × variant × set × stage. Before inference: commit/push code,
protocol, config, input manifest, checkpoint revision. After inference: save raw
replies, actual requests (or reproducible packets), receipts, hashes, metrics,
diff list, timing, honest conclusion → offline recompute → commit/push → verify
remote SHA. Technical failure is a result with its own push. Old journals are
never rewritten; the best seed is never picked. Large logs are compressed and
sharded with a manifest; weights, venvs, keys and foreign data are never
committed. Secrets checked before every push.

## GPU-time forecast (smoke-measured, updated per cell)

Ministral-3-14B bf16 on A100: review call ≈ 1.5–3k in / ≤1.7k out tokens per
row; short diagnostics 46 rows × (1 review + 1 F-extraction per policy + 1
pre-pass where applicable). Full A/M/B/Bopen/T/E/L over 46 short rows ≈
46×(7…10) calls ≈ 350–450 calls ≈ 0.5–1.5 h at batched throughput (measured in
the smoke receipt). frozen120 splits ≈ 4–6× that per split. Holdout2 (72 real
rows, longer contexts) ≈ 2–4 h per full variant pass. Exact numbers recorded per
cell in EXPERIMENTS.csv.

## Deliverables

docs/guardian_local_a100/{PLAN.md, REPORT.md, MODEL_MANIFEST.json,
EXPERIMENTS.csv}, results catalog with hashes, local runner
(experiments/guardian_local_a100/) and recompute.py. The report states what was
executed, what was NOT_EXECUTED, what actually helped, what was redundant, and
which conclusions are limited by self-authored tests; ends with a concrete
recommended checkpoint + architecture + components, a lighter delivery variant
and the branch/SHA — or a plain statement that no semantic improvement was found.

