# LLM-FIRST EXTRACTION F6 — RESEARCH LOG

Branch: `codex/llm-first-extraction-f6-20260929`
(base `codex/event-normalization-f5-20260929` @ 27a21bc5, worktree
`/home/z/my-project/got-f6`). All timestamps 2026-09-29.

## D1. State recovery (pre-work)

- F5 report + research log read: v10 F5 P .406 / R .361 (overfit
  confirmed); oracleA .800/.667 (stack transfers); oracleB .483/.389
  (sanitation is the bottleneck); identity transfers (F1 .61–.67);
  external entity-coref fails at the mention layer.
- Pipeline code read end-to-end: lf_llm_frontends (LLM_SG frontend),
  w1_hygiene (connective strip), w1_bnorm (boundary normalizer),
  w1_pipe3 (build_nodes_v3 consolidation + frozen relation stack loop:
  CE-gated pair proposal → E3v3 certificate → judge v3 → gates →
  DIR/CLS fallbacks), en_f5_run's byte-verbatim replay mechanism.
- Granite config located (full21/run_granite_modes.py, local
  transformers, granite-guardian-3.3-8b; gateway README lists 4.1-8b);
  gateway executor 503 all session → Granite arm blocked, documented.
- Environment: no local GPU; installed torch-cpu 2.14, stanza 1.14,
  sentence-transformers 6.1, langextract 1.7 (+openai) locally; models
  bge-reranker-base + bge-base + stanza-en downloaded to local HF cache.
  Mistral API (ministral-14b-latest, codestral-latest) reachable with
  throttling; keys never printed.

## D2. F6 suite frozen (BEFORE inference; commit 375c5e41)

24 policies (8 M / 8 L / 8 S), 221 mentions, 97 events, 43 edges, 293
pairs (SAME 37 / RELATED 142 / DIFF 114), 6 CF twins, 6 renamed.
Manifest sha 3a5a019c…; conventions include the three deliberate gold
changes vs F5 (nested mentions kept, RECORD first-class, outcome states
own cid). Full-format conversion sha 737a9602/eb23e68b committed.

## D3. Arms/prompts frozen (commit ec928cb8) then single inference round

- Raw arms A/B × mistral/codestral × {f6, cf, f6r}: ALL quotes
  verbatim-verified programmatically; **0 hallucinations everywhere**.
- Mention metrics: mistral A coverage **1.0**, strict .721, exact F1
  .465, junk 2. ARM B (strict grounding prompt) WORSE (more mentions,
  lower precision — negative result #3).
- NLP audit (stanza anchors): 131 anchors; mistral A 0 misses to catch
  (watchdog vacuous on short policies); codestral 1 miss, detected.
- Relation-stack replay (byte-verbatim frozen loop, CPU CrossEncoder,
  env-var credentials — no frozen file modified):
  oracle1 .892/.767 (stack transfers to F6), oracle3 .162/.140 (naive
  raw→stack fails), oracle2 .35/.163 (raw spans beat even gold identity),
  v10-on-F6 .697/.535 (the old chain is stronger on F6 than on F5 —
  F6's licensing constructions are more canonical; comparison is
  within-suite so still valid).
- **rawsan** (raw candidates into the FULL frozen sanitation chain):
  **P .800 / R .558 / F1 .658** — beats v10 (.697/.535/.605);
  rawsan2 (codestral) identical scores (.800/.558) → extractor-agnostic.
- Identity: F4way gold pairs F1 .607, 0 dangerous (transfers);
  raw-mention pairs F1 .798, 4 dangerous; CF twins 2/6 both-sides
  (cf_logged and cf_grind now correct; check-embedding and
  prescribed-vs-performed still fail).
- ARM E: agreement .847, weak uncertainty separation (.966 vs .814).
- ARM D: 61 spots, resolver veto precision 1.0 / recall .33, selective
  ≈ mistral alone; always-two union precision inflated by duplicates.
- ARM F: judge correct on .312 of decisive type disputes (rubber-stamps
  extractor 1) — negative.
- ARM G: risk-coverage nearly flat (base .925 → .956 at 57% coverage);
  signals informative individually but no usable gate at this accuracy
  level; no logprobs on this API; no "Jeff" anywhere in the repo
  (searched; arm honestly named).
- ARM H/I: 10/24 divergent interpretations; **18/24 verdict-equivalent,
  6 verdict-critical**; single-parse recall .581, union .651 (+.07
  upside concentrated on the 6 critical policies). Verdict proxied by
  licensed gold-cid edge sets (no traces in F6; documented).
- Rename: codestral 6/6 structural identity, mistral 1/6 (.676).
- LangExtract (same model as ARM A, 8 cases): coverage .976, junk 5,
  alignment built-in — **no gain over the raw prompt**.

## D4. Incidents (documented; none retro-tuned on F6 results)

- Two simultaneous pip installs corrupted torch mid-install → clean
  CPU reinstall; no effect on results.
- RAWA candidates initially carried the F6 sem taxonomy instead of the
  pipeline type vocabulary → v10 junk filters collapsed them to 1 node;
  fixed (type mapping), chain re-run from scratch. Root cause was an
  adapter schema bug, not an F6-informed change; the fix is
  schema-level, deterministic, and pre-dated any F6 score inspection.
- en_f6_graph._ceaf_entity / labelers use overlap-aware gold labeling
  (raw spans differ from gold spans) — documented measurement choice.
- The hyb arm (connective-strip + compatible_nodes) is labeled POST-HOC
  in the report: composed of frozen mechanisms but motivated by
  diagnosing oracle2/oracle3 on F6; superseded by rawsan, which needs no
  new composition at all.

## D5. Pre-registered prediction verdicts

Written into the phase plan before inference:
1. "Raw LLM extraction will materially improve mention recall" —
   CONFIRMED (coverage 1.0 vs frontend .992 with 33 junk; F5 A-layer
   was .768).
2. "Raw LLM mentions fed directly to the frozen stack will beat the
   NLP-first chain" — FALSIFIED (P .162 vs .697) — the strongest
   negative result of the round.
3. "The NLP watchdog will catch a meaningful share of misses" —
   FALSIFIED on F6 (0 misses to catch; base rate ~0).
4. "A second extractor/judge adds measurable quality" — FALSIFIED at
   mention level; PARTIALLY CONFIRMED only in the verdict-aware form
   (6/24 policies, +.07 recall upside).

## D6. Conclusion (report §19–21)

The simplest evidence-supported architecture is the current pipeline
with the candidate generator swapped for the raw LLM extractor
(rawsan): P .800 / R .558 — the best real sealed-suite result this
project has produced. The naive LLM-first form is refuted; the
sanitation chain is NOT obsolete (its boundary normalization and
consolidation are exactly what raw mentions lack); the candidate-
generation half of the frontend is. Open: Granite (gateway), long
policies, trace-level verdicts, bnorm over-dropping, check-embedding
and prescribed-vs-performed identity classes, extractor rename
stability.
