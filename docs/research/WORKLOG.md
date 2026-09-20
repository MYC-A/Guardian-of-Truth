# Research worklog — 2026-09-19

## 07:43–07:50 UTC: preserve and inventory

- Original worktree: `semantic-pipeline-v1` `0d8d804`, no tracked edits; pre-existing untracked manual and agent config preserved. `git ls-remote --heads origin` confirmed nine branches. `core-engine-bakeoff-v1` is a commit lineage under FullArch, not an advertised remote branch.
- Fetched FullArch without checking out the original worktree. Created isolated local `A:\GIS_Загрузки\Guardian Offline Research 20260919` branch `research/offline-20260919` at `923bb445`. Verified 191 GB free on A: before creation. No reset/clean/pull.
- Researcher fully read the three original `manual/` files and the external v2 handoff, created `MANUAL_INDEX.md`. The documents were copied into the isolated worktree after a presence-only secret scan (no private key/token value matches).
- Tester established SSH access and found prepared model environments/caches but no existing Guardian repository or experiment outputs at the documented paths. Created isolated remote clone `/mnt/data/guardian/Guardian-of-Truth-Offline-20260919` at `923bb445`; no existing env/cache/process was altered.
- Official 2026 PDF fetched and parsed; SHA-256 `9462490004b977e6d99a157c02effdb577b767dcf90a69e7765b78b8e8b5e3df`; task-one CLI, H100, 30 min, <40 GB confirmed. Task page returned HTTP 403. Internet blocked statement is task-two-specific.

## 07:50 UTC: executable offline baseline

Hypothesis: current `scripts/predict.py` already accepts unseen CSV offline and offers a measurable exact-check baseline. Stop rule: stop after one full viewed-dev pass and one fresh three-row smoke; do not tune on those labels.

- Command: `PYTHONPATH=src python scripts/predict.py --input valid.parquet --output outputs/research_offline_20260919/baseline_dev46.csv --audit outputs/research_offline_20260919/baseline_dev46_audit.jsonl --run-report outputs/research_offline_20260919/baseline_dev46_runtime.json --backend none`.
- Commit `923bb445`; data SHA-256 `8e730cc999a6cf07c3f17f273300a17ce16539c5b6166885e74b41e93cfc47ba`; model none; result TP12 FP0 FN11 TN23, F1=.685714, 34 fallbacks, 0.395 s for 46 on local Ryzen 7 5825U. Viewed-dev diagnostic only.
- Fresh unseen, unlabeled three-row CSV passed the official entrypoint and produced columns `id,label`, 0/0/0. No gold was present in this inference input. `tests/test_cli.py tests/test_runtime.py`: 17 passed in 1.08 s.
- Server fresh three-row `--backend none` smoke passed with `PYTHONPATH=src` in 0.00976 s and no GPU allocation. Bare source checkout without install initially raised `ModuleNotFoundError`; packaging in Docker uses `pip install .[data]`, which still requires a separate cold verification.

## Next bounded actions

1. Reproduce the same 46-row offline baseline on the isolated server, compare hashes and counts; do not infer hidden F1.
2. Build a standalone local Granite Guardian probe for `function_call` and `groundedness` with explicit context budget and raw score trace. No production routing until 3 fresh smoke and independent balanced data demonstrate TP gain without unacceptable FP.
3. Recover FullArch N5's two false-positive source-to-verdict traces from tracked frozen Phi if Clingo is already available; stop if dependencies would require broad environment changes.
4. Perform isolated `pip install .` and Docker cold-start when tooling permits. Do not touch frozen branches or existing outputs.


## 07:52 UTC: remote baseline replication

Tester reran the same `--backend none` viewed-dev baseline in the isolated remote clone at `923bb445`, `PYTHONPATH=src`, no API/GPU/install. Input SHA-256 matched local: `8e730cc999a6cf07c3f17f273300a17ce16539c5b6166885e74b41e93cfc47ba`. Predictions SHA-256: `07dff1f61d1cde4ae2aa93d7bf51f42b92e792fedcaf62b12bef9f1e5cb8d790`. Exact ID join produced TP12 FP0 FN11 TN23, F1=.685714; pipeline 0.650 s, shell wall 1.153 s, GPU 0 MiB. Artifacts: `/mnt/data/guardian/Guardian-of-Truth-Offline-20260919/outputs/research_offline_20260919/`. Docker CLI is absent on the server. The initial bare checkout command failed on missing import; setting PYTHONPATH succeeded. A project install remains untested.

## 07:55 UTC: bounded historical FullArch N5 replay started

Hypothesis: the tracked frozen Phi plus Clingo 5.8.2 can recover the two N5 false-positive case traces missing from ignored outputs, exposing the first source-to-verdict loss. This is a historical replication only, not a new offline model. Stop rule: one smoke case then one 46-row pass; stop on solver failure or >10 minutes. Clingo was installed only into a temporary local target, not the project or server venv. One-case smoke succeeded; full output namespace is `outputs/research_fullarch_replay_20260919/full/`, with stdout/stderr redirected. Command: `PYTHONPATH=<temp-clingo>;src python experiments/full_architecture_v1/benchmarks/real46.py --arms N5 --output-dir outputs/research_fullarch_replay_20260919/full`. Dataset SHA is the public46 SHA above; Phi is the tracked frozen Mistral artifact.

## 07:59 UTC: FullArch N5 historical replay and root cause

The bounded 46-row replay completed once on local CPU with Clingo 5.8.2. TP4 FP2 FN19 TN21, F1=.2759, matching `0c2bda7`. Predictions SHA-256 `3f63cc791c4bbc236e2aab2b0df2e05a43935cba382b3cb9b5a2c20286769fea`; sum per-case runtime 102.77 s, mean 2.23 s. The two FP are `banking_knowledge__task_063::t8` and `banking_knowledge__task_081::t35`. Reconstructed certificates show `unit:0002:mistral:2` is the sole false obligation in all 64 interpretations for each case. RuleIR had a request-count condition and KB-guidance exception, but compiler emitted unconditional `FORBID transfer_to_human_agents` after both failed lowering. Source-to-verdict details in `FAILURE_ANALYSIS.md`. This is a formal-lowering soundness bug; code correction is underway, and this replay remains a historical frozen-Phi result.

## 08:00 UTC: preregistered local model probes

Granite Guardian 3.3 8B official card confirms Apache-2.0 and separate `function_call` and `groundedness` criteria. Hugging Face revision `b3421eda4ba6fc9f9a71121d7e62de08827469a4` has 16,341,771,384 bytes of safetensors, so one model fits the server's free disk; 15.22 GiB weights leave limited A10 VRAM for context. Existing venv already has torch 2.9.1+cu128, transformers 5.16.1, vLLM 0.15.1. A single durable CPU/network download is running in its own namespace, PID 26862; no GPU work during transfer. Stop on auth/network/disk failure or OOM at first one-case model load; no repeated large download. The experimental runner is isolated from `scripts/predict.py` and stores only probabilistic scores.

Before model inference, 32 newly authored synthetic pairs were frozen under `benchmarks/offline_guardian_v1/`: 16 function-call and 16 groundedness rows, 16 positive/16 negative total. Inference inputs contain no labels; `gold.csv` is separate. SHA-256: tool input `cb567c6a14d2265d7f93155cb1c60beed332679ffa43f73d8e47ae5815e91305`, claim input `835d5ac9fe3beabb86991af250ddda26a8afb880c0cc688a7886a9d56b26efa5`, gold `0ec45efee2b9764f7d21eab3029eb76c2f36f9959040ae90c3c4d6babfe2383b`. This is an independent-of-public46 *synthetic* diagnostic set, not hidden contest validation. Stop model integration if the relevant criterion cannot distinguish valid/invalid pairs or adds substantial FP; public46 is for later viewed-dev error audit only.

While Granite transfers, a separate cached NLI DeBERTa-base claim probe will run only on the 16 claim rows, after 1–3 smoke. It is a low-cost entailment/contradiction channel, not a policy/tool detector or proof. No calibration threshold will be fit on public46.

## 08:05 UTC: sound lowering fix and repeat replay

Commit `36d4b58` changes only the RuleIR→Neutral compiler and adds six focused regressions. An obligation is no longer emitted if any condition or exception leaf cannot be represented; explicit unresolved content and unsupported temporal rules also abstain; supported BEFORE/UNTIL/AFTER fields are preserved; capped world enumeration cannot certify an incomplete product. Targeted compiler tests: 6 passed. CLI/runtime tests: 17 passed.

The same N5 replay over the same tracked Phi completed once: TP3 FP0 FN20 TN23, F1=.2308, unresolved rate .6522. Prediction SHA-256 `5f3e6f9c940b6614211efe7475b920017e81f90a4712ae2c839c3996ff4b958b`; sum per-case time 13.18 s, mean .287 s. Both former FP and one former TP (`airline__23::t10`) became `UNRESOLVED`; no new positive prediction appeared. This preserves proof soundness at a measured recall cost and does not make frozen Phi an offline final frontend.

Full repository tests after the fix: 1626 passed, 9 failed in 12.86 s. The nine failures are the same historical artifact/seal hash failures documented before this work; the new compiler regressions and CLI tests pass. No failure references the changed compiler.

## 08:06 UTC: cached NLI inference

The prepared server's cached `cross-encoder/nli-deberta-v3-base` snapshot `6c749ce3425cd33b46d187e45b92bbf96ee12ec7` passed import smoke, a two-pair smoke, then all 16 frozen claim rows offline. Model safetensors SHA-256 `d8148c6d49e0a7925134294c56326c71fe0ab1dc390e37355e00c7efbb488afa`; label map is 0 contradiction, 1 entailment, 2 neutral. It produced 8 entailment and 8 contradiction labels; summed model latency 945.739 ms, mean 59.109 ms, max 303.404 ms. Gold was not present on the server. Exact post-inference scoring is pending retrieval of `records.jsonl`; the SSH endpoint began refusing connections immediately after the run, so no accuracy claim is made yet.

## 08:09 UTC: package install smoke

Created an isolated local venv under an ignored research output, installed `guardian-truth` 0.2.0 with `pip install ".[data]"`, imported pandas 3.0.2 and pyarrow 25.0.1, and ran the official `scripts/predict.py` entrypoint over the fresh three-row CSV. Output was valid `id,label` and the run completed with three explicit fallback decisions. This verifies package metadata and the Python entrypoint. It does not verify the Dockerfile, base-image availability, container size, GPU model packaging or cold-start budget because neither local nor server environment exposes a Docker CLI.

## 11:05-11:12 UTC: exact binding boundary and clean N5 replay

The three N5 positives remaining after the lowering fix were audited to their first premise. All depended on cross-encoder target mappings; the retail witness mapped unrelated policy phrases to `return_delivered_order_items`. Commit `1f5a093` now admits only a single exact-method, identity-consistent binding to the proof pipeline. Focused binding/compiler tests passed.

The first repeat exposed `num(7.8)` parser failures in 13 rows. A second repeat exposed Clingo treating hyphens in unquoted fact IDs as subtraction. The backend now sends non-integral floats through a distinct nonnumeric value (so ordered comparison abstains), retains integral floats as integers, and quotes opaque fact IDs. Thirteen focused soundness/serialization tests pass.

The final one-time replay at `outputs/research_fullarch_replay_20260919/exact_binding_serialization_fix/` completed all 46 rows: 46 `UNRESOLVED`, checker 46/46, TP0 FP0 FN23 TN23, F1=0, no syntax errors and no undefined arithmetic operations. Predictions SHA-256 `c389c822c64a1ec12fe59d8d3d454641e59f6a3f452354a207def8ce841459d0`; summed per-case time 31.21 s. Frozen-Phi N5 is therefore rejected as a contest arm; its former apparent recall was not proof-safe.

Full repository tests after the changes: 1639 passed, 9 failed. The same nine historical artifact seal/hash and protected-incumbent path failures remain; no new soundness, adapter, CLI or runtime failure appeared.

## 11:12 UTC: Granite adapter interface smoke

Commit `08e5394` adds a gold-free `id,prompt,response` to Granite function-call adapter with source trace and explicit `unavailable` states. Six adapter tests pass. An end-to-end preprocessing plus model-runner dry-run over three unlabeled viewed rows produced one ready row, two `missing_target_assistant_tool_call` rows, and three dry-run records. No model decision or metric was generated. The SSH tunnel still returns `Connection refused`; the prior Granite download was not restarted and NLI records were not regenerated.

## 2026-09-19 11:30–12:20 UTC: remote recovery and completed BASE component probes

- SSH became usable only with forced PTY. The prepared A10 has 23,028 MiB and
  was idle before each run. Existing environments and caches were reused; no
  framework or model was reinstalled. The old server checkout remains at
  `923bb445` with its untracked experiment files preserved.
- Recovered the sealed NLI 16-pair records. Post-hoc scoring at commit `4af3816`
  produced TP8 FP0 FN0 TN8, F1 1.0 on the synthetic claim slice. Records SHA is
  `825112e214c5075527551a998a667469c02c44401dd83f8c0140c1a1a492ee1c`;
  model snapshot `6c749ce…`, weights SHA `d8148c6…8afa` (737,726,552 bytes).
- Granite Guardian 3.3 8B revision `b3421eda…` was already fully downloaded
  (16,341,771,384 weight bytes). Three function-call smoke cases parsed and
  were correct. On the frozen 16 tool pairs it scored TP8 FP0 FN0 TN8, mean
  772.986 ms, peak 16,029 MiB, records SHA `1c4cdbf…a43a2`. On the same 16
  claim pairs it scored TP8 FP0 FN0 TN8, mean 716.368 ms, peak 15,963 MiB,
  records SHA `aa38120…9ceb5`. These are synthetic diagnostics.
- The label-free public46 adapter yielded 23 eligible tool-call rows and 23
  explicit missing-target abstentions. Granite alone scored TP8 FP0 FN15 TN23,
  F1 .516129. The fixed diagnostic OR with legacy baseline scored TP13 FP0
  FN10 TN23, F1 .722222 versus baseline .685714. The only gained TP was
  `airline__7::t6`; no FP was introduced. Mean eligible latency was 1,113.546
  ms, peak 16,735 MiB; records SHA `d201442…49f35e`. This is PUBLIC_SEEN and
  cannot select the production rule.
- One malformed diagnostic command printed the remote process environment into
  the private tool transcript. No secret is recorded in repository artifacts,
  but the exposed ModelScope access tokens require rotation.

## 2026-09-20: reproducible branch and architecture-v2 boundary

- Fixed Python's default 131,072-character CSV field limit in both Granite and
  NLI readers. Commits: `52bf829` and `492775a`; focused tests pass.
- Published `research/offline-20260919` to GitHub for the first time at
  `492775a`. Remote model experiments now use a separate detached worktree from
  that exact published commit; the old server tree is not switched or cleaned.
- Fully read and preserved
  `manual/guardian_codex_architectures_v2_2026-09-20.md` (SHA-256
  `a12eb81f…d3bbb`). It reclassifies Granite/NLI as BASE components and requires
  controlled A0-A3 and B0-B5 comparisons before any C claim.
- Commit `620dfa0` implements only the shared Architecture A source-grounding
  contract: exact offsets or a unique quote are accepted; missing, mismatched,
  or ambiguous spans are `UNANCHORED`; a high score cannot emit a positive;
  formal state remains separate. Twenty-one related Granite/NLI/grounding tests
  pass. No model-backed Architecture A/B result is claimed.
- Server inventory confirms cached NLI, NuExtract3-W4A16, GLiNER2.5, BGE models,
  and Granite 3.3 8B. There is no confirmed local Mistral checkpoint. Historical
  API-derived Phi cannot satisfy the local B0 or BASE Mistral requirement.

## 2026-09-20 23:15 UTC: PUBLIC_SEEN NLI transfer test and CLI correction

Hypothesis: cheap DeBERTa NLI over the fixed 23 public46 text-only rows can add a
claim-error TP to the exact baseline without a tool-policy FP. Stop rule: one
label-free pass; reject the pairing if it adds no TP or introduces substantial
FP. The run used published commit `492775a` in detached server worktree
`/mnt/data/guardian/Guardian-research-offline-20260920`.

- All 23 rows completed, but every relation was `neutral`. Post-hoc text-slice
  metrics are TP0 FP0 FN2 TN21, F1 0; missed IDs are `airline__8::t7` and
  `retail__29::t13`. Full-46 legacy OR is unchanged at TP12 FP0 FN11 TN23,
  F1 .685714. The whole-context NLI pairing is rejected.
- Records SHA `4acd21647aadcc1075ddf96aa9bc1d571825fcba37c0d79516fde8520cf57afb`;
  config SHA `4d0ef70e90b7e9320b40540969513e4fbecfb800d01f96d56a6d80da16af3916`;
  post-hoc report SHA `3f44181d…cf22d5`. Inference sum 1,166.565 ms, mean
  50.720 ms, process wall 42 s, sampled peak VRAM 1,119 MiB.
- The first attempted main-entrypoint replay exposed Python's 131,072-character
  CSV field limit in `src/guardian_truth/cli.py`. Commit `1aa88a9` raises the
  explicit limit to 16 MiB and adds a 140,000-character regression. With the
  worktree `src` forced first on `PYTHONPATH`, 31 CLI/runtime/A-contract tests
  pass. The initial test invocation imported a different globally installed
  editable checkout; this explains its unrelated failures and is an environment
  warning for local/server commands.
- After the developer agent configuration was corrected, it completed commit
  `01e7ebf`: a gold-free Architecture A grounding CLI that consumes raw atomic
  suspicion JSONL, writes ordered per-case records plus a hashed run manifest,
  rejects duplicate/unknown IDs and output overwrite, and keeps formal
  `UNRESOLVED` separate. Thirteen focused tests pass. This is infrastructure,
  not a model-backed A result.

## 2026-09-20: Architecture A full inference and Architecture B model preflight

- A0 and A1 inference both reached 46/46 terminal `OK` in the isolated server
  worktree. A0 used 49 journal requests after three successful retries; records
  SHA is `c3b624688a2208c58b986f280cb0985a50a505cb853237240f4cdbcfd5b67cf6`.
  A1 used 48 journal requests after two successful retries and 630,613 tokens;
  records SHA is `50af6bf5daa075884205121b697c94e8f2d85bb0a7fe6bbbc0934ca3c667e41a`.
  Post-hoc gold join: A0 TP22 FP16 FN1 TN7, precision .5789, recall .9565,
  F1 .7213. Exact OR A0 reaches TP23 FP16 FN0 TN7, F1 .7419. A1 emits no
  positives: all 120 proposed suspicions are `UNANCHORED`. Ignoring only the
  grounding gate, the same A1 generation is TP21 FP20 FN2 TN3, F1 .6563, so
  the gate suppressed 21 TP and 20 FP. Report SHA is
  `a1d2b35c89c61acc07a4f1acb43187e5ed1ea2becb2e5b423b4d4e514feae89d`.
- Cached `numind/NuExtract3-W4A16` loaded offline on the prepared A10 in
  103.859 s. Peak allocated/reserved VRAM was 5,280,815,104 / 5,335,154,688
  bytes. This is a load smoke only, not an extraction-quality result.
- Cached `fastino/gliner2.5-multi-v1` loaded in its isolated environment in
  25.706 s and completed the fixed smoke in 0.696 s. It returned source-offset
  entities and relation hypotheses. VRAM was not observable across the isolated
  subprocess, so it remains unmeasured. This confirms adapter availability but
  does not make GLiNER output a premise or proof.
- Commit `b43f615` connects real Mistral, NuExtract and GLiNER provider paths,
  an injected LangExtract grounder, and a conservative handoff to the existing
  FullArch N5 arm. Each whole-theory alternative remains separate; GLiNER is
  evidence only; unanchored or non-exact bindings abstain. Fifty-six relevant
  tests pass locally. Three additional solver tests cannot run because the local
  `clingo` module lacks its native `Control`; they must run in the server venv.

## 2026-09-20: first real Architecture B model run and formal handoff

- One `syn_dispatch__exception_unless` case ran with real `ministral-14b-latest`,
  cached `numind/NuExtract3-W4A16`, and `fastino/gliner2.5-multi-v1` in a clean
  detached server worktree at `453b595`. The 68 s provider run was performed
  once; peak observed GPU occupancy was 9,955 MiB. Input SHA is
  `1304c58598ccdeabc77768eb22d36e7d95de60bd3207f23d2bc663f12d020de3`;
  provider-output SHA is
  `cab60ee20664e391f6aa1f574eaf2ea82ae4a6b16a13e7bf827202a93f191f87`.
- Mistral returned zero normalized rules. NuExtract returned two; one preserved
  `FORBID/UNLESS` and its exact source quote but the boundary rejected its
  condition as `unless-without-exception`. The second was rejected as
  `INVALID_SOURCE_SPAN`. GLiNER's six hints remained evidence only. These
  are actual model outputs, not a preformalized scenario.
- Commit `d4212ae` fixed the combined-provider JSONL handoff without rerunning
  models. All three B0 alternatives reached existing N5 as `UNRESOLVED` with
  zero representable and exact-bound rules, so no Clingo/checker execution was
  possible; `phi-empty:no-eligible-rules` is the recorded marker. B0 records
  SHA `5ba734d74a5faf47b8a17eaa62ad0d6a2b634bb7fe76b5cf165fd194ba80d856`;
  N5 alternatives SHA `bc7b6ec7ca596a08f3df124f6a2970624dbe6312941c1e40581e705aad4e9ac0`.
  Server namespace: `/mnt/data/guardian/results/b0_smoke_20260920T175500_syn_dispatch_exception_unless/`.
- Commit `0694c2d` allows a correct theory to receive zero issues/no repair,
  permits a source-grounded addition without altering an existing element, and
  recovers offsets from one unique verbatim original quote. The validator still
  rejects missing and ambiguous quotes. Seventy relevant local tests pass.

## 2026-09-20: pinpoint old B0 formal losses before five-case run

The old one-case N5 invocation used a 64-byte placeholder `competition_input.csv`;
the actual NuExtract RuleIR provenance refers to `prompt[248:367]` in the full
case. Its `INVALID_SOURCE_SPAN` therefore reflects mismatched input artifacts,
not a failed quote in that model output. In the prepared five-case competition
CSV (5,642 bytes), all five source texts match their prompt offsets exactly.
The `FORBID/UNLESS` donor instead placed its sole exemption in `condition` and
left `exception` empty. The conservative boundary now maps that unambiguous
operand to `exceptions`, without adding a conjunctive prerequisite; 31 B theory
tests pass. The server's five-case raw run remains pinned to `0694c2d` so this
fix can be measured by replaying its sealed outputs without new model calls.

## 2026-09-20: one-case B0 replay after UNLESS and full-input fixes

The first real provider artifact was reused without model calls (SHA
`cab60ee20664e391f6aa1f574eaf2ea82ae4a6b16a13e7bf827202a93f191f87`).
At `3a073a5`, input SHA stayed `1304c58598ccdeabc77768eb22d36e7d95de60bd3207f23d2bc663f12d020de3`;
the correct full prompt/response CSV SHA is
`3259a1dc47d0d299c863b193058c047f91d81c6c7e2a1c4044b5cf1eb1753656`.
B0 records SHA `6d820cc893a607a3056b1d21320a392c92bc8c96d8cc259146f50277198a976d`;
N5 alternatives SHA `fd8376bd39a82fd7e304a6c4c81593d7e30733f913498107b570f102c84c5d19`.
Server namespace: `/mnt/data/guardian/results/b0_replay_3a073a5_20260920/`.
Both NuExtract elements are now `BINDING_REQUIRED` with valid full-input spans;
the `UNLESS` exemption is preserved. Both still fail exact catalog identity:
model target `dispatch` versus tool `dispatch_field_technician`. N5 reports
`representable_rules=2`, `exact_bound_rules=0`, `rules_lowered=0`,
`UNRESOLVED`, markers `target-unbound:dispatch` and
`unbound-action-object:a field technician`. Checker `ok=True` refers to the
empty lowered rule set, not a Clingo proof of this policy. The next loss is
target/entity binding; no second B0 extraction run is justified.

## 2026-09-20: real five-case B0–B3 pilot

All five fixed seen synthetic cases were processed by real
`ministral-14b-latest`, cached `numind/NuExtract3-W4A16`, and cached
`fastino/gliner2.5-multi-v1` at server detached HEAD `0694c2d`; provider raw
responses are saved in `b3_smoke_0694c2d_20260920T1815Z/providers.jsonl`.
Mistral extracted 0/2/1/1/0 rules, NuExtract 2/3/3/1/1, GLiNER supplied
6/6/7/1/7 evidence hints. At `3a073a5`, real LangExtract direct-original
returned 7 exact quoted fragments across five cases, with interpretation
explicitly unverified. B0 and B1 each yielded six RuleIR-representable
alternatives across 15 whole theories, zero exact-bound and zero lowered rules;
B2 yielded zero representable because no model supplied complete clause accounts.
Existing N5 was called per theory with the correct full CSV, but no policy
proof reached Clingo. Five case verdicts remain `UNRESOLVED`.

The initial B3 call at `3a073a5` exposed a genuine schema mismatch: Mistral
returned lists of typed issues, whereas the adapter expected one scalar type.
All five original raw responses were retained. Commit `509c1c9` conservatively
splits each grounded list into separate typed issues. The real repeat produced
22 typed Mistral issues on NuExtract theories and zero NuExtract issues on
Mistral theories, including two empty Mistral theories. NuExtract's five
addressed repair calls returned empty `changes` and `additions`; there are zero
repaired theories, and B3's ten originals remain `UNRESOLVED` with zero
representable/linked/lowered rules through its strict gate. Commit `ca3a81f`
corrects the misleading `BIDIRECTIONAL_COMPLETE` classification for this
no-op-with-issues pattern without repeating model calls. The raw `509c1c9`
record retains its historical status for audit; no semantic repair is claimed.
Server archive hashes: first five-case stage
`79e5c27aa1fe7d6fec109eed4f417f8c93ad78adc9c752f5c52bca7f18c14593`;
repeat stage `93d74bedd4fdd96eea862d1b233a0faf5ecaee663a4d18a00d14b7f519375e33`.
Local 33 focused B theory tests pass. Next matched comparison uses all 17
frozen seen synthetic cases (14 errors, 3 controls); the five provider outputs
are reused exactly, with only 12 new cases sent to models.

## 2026-09-20: independent fullcycle line — access setup checkpoint

New branch `research/independent-fullcycle-20260920` (base = `1755838`, offline-20260919 tip).
Access layer verified end-to-end before any experiment work:

- Guardian Gateway 2.0 on ModelScope A10: /health 200 v2.0; /gpu success=true exit_code=0
  NVIDIA A10 23 GiB; /environment torch 2.9.1+cu128 CUDA True; file roundtrip byte-identical
  (relative paths only); real GPU job SUCCEEDED exit 0 with GUARDIAN_GATEWAY_TEST_OK,
  hostname dsw-537551-56fdf888f9-dpqk5. TLS pinned by SHA256 fingerprint; no verify=False anywhere.
  Gateway logs endpoint returns one {"stream","content"} per call; client merges streams.
- Persistent access config outside the repo: token/cert/github_token (600) + guardian_client.py
  (files/jobs/wait_job/run_python, status+exit_code checking, no secret in logs or URLs).
- Server inventory read-only: models granite-guardian-3.3-8b + mistral-7b-instruct-v0.3;
  hf_cache 14G (bge-m3, bge-reranker-v2-m3, nli-deberta-v3-base, NuExtract3-W4A16,
  gliner2.5-multi-v1); venv clingo 5.8.2 + langextract + gliner; results/ holds sealed
  b0/b3/b17 artifacts of the Codex line. Five foreign worktrees identified and untouched;
  no global git config changes on the server.
- My isolated server clone: /mnt/data/guardian/agent-workspace/guardian-repo on this branch.
- Keyless LLM APIs smoke-tested OK: BlockRun.ai, LLM7.io, Pollinations (independent
  critic/repair channels for direction B, per directive §7.5).
- Full state table and verified historical numbers: docs/research/INDEPENDENT_FULLCYCLE_20260920.md.

No model calls on competition data were made in this phase (server instruction §8:
setup + small checks only). Next: baseline reproduction on the server clone, then
A1 grounding-producer repair and two-generative-critic B experiments.
