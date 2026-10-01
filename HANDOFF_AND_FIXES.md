# Hybrid service handoff and Stage-A corrections (2026-10-01)

## Latest continuation

Writable branch: `codex/hybrid-vast-followup-20261001`; isolated local
worktree `.worktrees/hybrid-assistants-20261001`. Server SSH alias now
`guardian-vast`. Remote jobs use separate pinned worktrees for graph/Phi
matrix, independent review, and model translation comparisons. Do not
change a checkout while its recorded PID/job is active.

All six frozen sealed arms are complete (800+160 predictions) and the Phi
frontend is complete (160 translations). Joint completion-gated scoring
selected R0: sealed TP68/FP4/FN0 vs baseline TP68/FP28/FN0. Private supervised
service now uses `r0-service-v1`, the R0 method with a12000-character
deployment cap and no archived dev replay; actual HTTP/CLI/outage/recovery passed.
See `DECISION.md` and `docs/searh_23/HYBRID_SEALED_RESULTS_2026-10-01.md`.
No quality algorithm, prompt or vote combination was changed after gold.
Subsequent operational changes disable hidden SDK retries, retain safe
transport metadata and make the operations probe wait for listener startup.

The original `Guardian-of-Truth` server checkout and the main Windows
checkout are untouched. `/etc/vast-agents-guide.md` was read on the new
server. No driver/CUDA install, tunnel or public service was created.

Full completed dev evidence is summarized in
`docs/searh_23/HYBRID_DEV_RECOVERY_2026-10-01.md`. Current corrected runs:

- baseline graph arms `20912812e42d502de1f3`;
- independent B `436ba4b3c7bb178336ca`;
- M01/M11 and H3 `f949f802a239f2c3cdce`;
- Phi translations `feb312d214f1d141f051`;
- Codestral comparison `08502602a420a6a3f45a` (exact cache recovered
  after fixing successful-completion loss for explicit provider/model IDs).

Mistral credentials/model still come from server secret env files; keys
are never included in prompts, reports or Git. Kimi Code returned HTTP
402 and Mistral Small HTTP429; no quality conclusion is drawn from these
missing answers. Automatic JSON validity must not be equated to faithful
NL→predicates: both available translators can prove the wrong proposition.

MiniCheck loads the original PyTorch bin, not the migration's misleading
`model.safetensors` hardlink. Native cache location is explicitly pinned
to `/workspace/guardian/hf_cache/hub` to avoid repeat downloads.

## Original Stage-A handoff

Worktree: `codex/hybrid-assistants-step1-4-20261001`, based on
`research/hybrid-service-20261001@3b0186f8`. GPU host: `vast_me` via SSH.
The remote experiment checkout is a separate detached worktree at
`/workspace/guardian/repos/hybrid-assistants-worktree`; the existing
`/workspace/guardian/repos/Guardian-of-Truth` checkout was left on its branch.
The Vast guide `/etc/vast-agents-guide.md` was read before server work.

## Reproduced faults and fixes

1. **Judge adapter**: `judge.py` emits a flat vote with `label`, `type`,
   `response_quote`, `policy_quote`, `history_quote`, `catalog_quote`,
   `source_refs`, and `explanation`. The service previously iterated the
   nonexistent `evidence` array and could return `ERROR` with no findings.
   `_judge_findings` now consumes the actual schema and retains every nonempty
   source quote, target statement, refs, model, and explanation. Source offsets
   are included when source text is available. An `UNSUPPORTED` vote contains
   the target quote without a fabricated quote of absent evidence.
2. **FactCG**: Stage A used `tokenizer(doc, claim, max_length=512)`. The
   [authors' code](https://github.com/derenlei/FactCG) uses an instruction
   string, NLTK sentence and word tokenization into at most 550-word chunks,
   max length 2048, class-1 softmax, and maximum chunk score. The new native
   adapter ports this behavior from `derenlei/FactCG@41f1854` (MIT) and pins
   Hugging Face snapshot `0430e3509dbd28d2dff7a117c0eae25359ff3e80`.
   The former pair adapter remains in the *same run* as a control.
3. **Smoke accuracy**: filtering `None` predictions before zipping with gold
   shifted every subsequent pair. `_acc` now filters paired values, reports
   valid coverage, conditional accuracy, and accuracy with invalid as wrong.
4. **V2 trust boundary**: `acquire_documented_v2` labeled all contracts as
   model-proposed if any tool had `auto_contracts`. It now matches each binding
   to the corresponding `producer_scope`. A mixed-source regression shows the
   other tool's explicit contract retains `DOC_EXPLICIT`.
5. **Readiness and source quotes**: `/ready` now makes a cached, non-inference
   `GET /models` check and distinguishes configured credentials from backend
   reachability. `/health` remains a process liveness check. Structural
   findings quote actual target call lines; their mechanical reasoning remains
   in `arguments_for`, not misrepresented as a verbatim policy quote.

## Measured on `vast_me`

The paired 15-case checker smoke is recorded in
`experiments/searh_23/hybrid_service_v1/outputs/native_smoke_corrected/`;
the original Stage-A output remains in `outputs/native_smoke/`.

| Candidate | Valid | Correct on valid | Scope |
|---|---:|---:|---|
| FactCG, former pair input | 15/15 | 10/15 | Same checkpoint and cases |
| FactCG, author input | 15/15 | 15/15 | Same checkpoint and cases |
| MiniCheck native | 15/15 | 13/15 | Same smoke bank |
| Granite 4.1 BYOC | 15/15 | 15/15 | Same smoke bank, peak allocated VRAM 15.7 GiB |

These are format and integration smoke results. The 15 examples were already
visible; no model or architecture is selected from them.

The actual FastAPI TestClient path on the server is recorded in
`outputs/http_live_smoke/report.json`. A structural error returned `ERROR`
with one finding; a live model error returned `ERROR` with two populated
`CONTRADICTION` findings (Gemma and Mistral); the supported answer returned
`NO_ERROR`; an oversized input and an injected backend outage returned
`UNKNOWN`; after restoring the channel, the same request returned `NO_ERROR`.
Model calls were 2 per case, using 2,498 and 2,340 total tokens respectively.
The ready probe reported both Mistral and Ollama configured and reachable.

`python -m pytest -q tests/test_hybrid_service_fixes.py
experiments/searh_23/hybrid_service_v1/test_structural_v02.py
experiments/searh_23/hybrid_service_v1/test_archive_dsp.py
experiments/searh_23/hybrid_service_v1/test_v2_boundaries.py` passed locally.
`python service/test_service_smoke.py` passed 7/7. The latter is a standalone
script: running it directly avoids its non-pytest `tmp_dir` argument.

## Wiring boundary

The evaluated service currently calls `parse_case_v02` and `judge.ask_vote`.
`v2_boundaries.py` is still a standalone correction and test module; the
service has no Step-2 fact-contract path that could call it. This fix cannot
be credited as an end-to-end quality improvement until a modular runtime
explicitly consumes it. The historical syntax repair in `backend_v1.py` is
also distinct from a live evaluated service repair loop. These distinctions
are recorded before further comparisons to prevent a standalone unit test
from being counted as a service result.

Disk after the separate checkout and native smoke: about 0.9 GiB free on the
32 GiB overlay. No other agent's files, model cache, or active results were
deleted. Bespoke-7B and PRT-Qwen remain blocked by this measured disk limit.
