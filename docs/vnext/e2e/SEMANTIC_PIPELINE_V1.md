# SEMANTIC PIPELINE V1 — EXPERIMENT REPORT

Branch: `codex-update-run` @ `4639b46f2e6995ea7036aef73a01ebbc723c0e14` (start = end: production tree untouched; all experiment code is new under `experiments/semantic_pipeline_v1/`)
Experiment code: `experiments/semantic_pipeline_v1/` (16 modules) · Artifacts: `outputs/vnext/semantic_pipeline_v1/`
Dev data: `valid.parquet` (46 rows, VIEWED DEVELOPMENT DATA — never used for tuning literal rules) · Held-out: 17 synthetic cases with unseen tools/domains.
Remote usage: Mistral API only (`ministral-14b-latest`; key never printed). All other models LOCAL on CPU (2 cores, 3.9 GiB RAM, no GPU).

---

## 0. What was built (architecture under test)

```
PROMPT + RESPONSE
  -> Phase 2  SourceTimeline: lossless segments + fragments (byte-exact spans,
              event/turn order, FIFO call/result pairing, ERROR-response split)
  -> Phase 3  Retrieval: A deterministic + B lexical (+locality) + C embeddings
              (multilingual MiniLM) + D KB-document candidates. ADD-ONLY.
  -> Phase 6  Extractors (independent, no voting):
              Mistral RuleIR (cached, verbatim-grounded, unless-mirror)
              NuExtract-1.5-tiny (local; verbatim span evidence)
              GLiNER2.5-small (local; typed spans)
  -> Phase 8  Deterministic renderer (no LLM)
  -> Phase 9  NLI firewall (cross-encoder/nli-deberta-v3-small, local)
  -> Phase 11 Binding (exact lexical -> embeddings -> cross-encoder rerank)
  -> Phase 5/12 RuleIR (pydantic-validated compositional typed IR)
  -> Phase 13 Phi = set of admissible interpretations (dedupe by semantic_key)
  -> Phase 14 Thin adapter -> incumbent compile_h0 -> incumbent core
              (ledger / world algebra / solver / certificate UNCHANGED;
              feature-flagged, default off)
```

## 1. What information does the current Guardian actually lose?

Four concrete losses, each with a code citation (details in `SEMANTIC_PIPELINE_CURRENT_FLOW.md`):

1. **ERROR tool responses are invisible to the semantic layer.** `← TOOL_RESPONSE tool [ERROR]: …` does not match the transport grammar's colon requirement (`parsing.py:10-14`), so the error line is swallowed into the preceding CALL event's text and **no result event exists** (verified by direct parser test). T2 therefore never fires for failed calls, and the "Tool not found" evidence class (retail__48, telecom t6/t10) is semantically discarded. Our Phase-2 builder splits these out as first-class `TOOL_RESULT` segments (kind `error_result`).
2. **Normative text inside KB/tool results can never become policy input.** The policy source is exclusively the SYSTEM `<policy>` span; KB documents reach only the T2 effect-proposal module.
3. **Non-final USER/ASSISTANT turns are never semantically interpreted** (goal firewall = last user turn only; claims = response only; history text only feeds deterministic claim binding).
4. **Tool descriptions and schema field descriptions** are extracted into premise inventories but never sent to any policy/binding LLM module.

Two additional routing facts documented along the way: the policy frontend actually receives the **instructions tail** (the extraction regex starts at the first `<policy>` occurrence inside the instructions sentence) plus nested policy documents — a superset leak, not a loss; and `case.history=()` for competition inputs.

## 2. What information is preserved but routed to the wrong module?

- **History tool results**: reach T2 (as raw payloads for *effect hypotheses*) — usable as evidence, never as rules.
- **Catalog schemas**: reach T2 only as schema dicts (field names/kinds) when the tool has an observed paired call; field-description text and the whole catalog block reach no semantic module.
- **Tool descriptions**: inventory rows only.
- **Earlier user turns**: deterministic claim binding only.

## 3. What is current required-fragment recall?

**64.8%** (68/105 human-annotated required fragments role-usable in the incumbent routing; `retrieval_coverage.csv`, `retrieval_coverage_summary.json`). The losses concentrate in: KB rules reaching only T2 (not usable as rules), non-last user turns, tool/schema text, and ERROR responses (delivered nowhere).

## 4. Does embedding retrieval improve recall?

| Method | Recall |
|---|---|
| current Guardian routing (role-usable) | 0.648 |
| deterministic-only (A) | 0.705 |
| embeddings-only (C) | 0.581 |
| **combined A+B+C+D** | **1.000** |

Yes — but only as a *union channel*: the embeddings add rank-diverse candidates (with per-type quotas and a 0.15 floor), the lexical+locality channel catches failed-lookups and value-linked evidence, and the KB channel guarantees document-like results. Embeddings alone are far below the deterministic baseline. Three initially-missed fragment classes (JSON profile blobs, colloquial Russian user turns, error strings) were closed by (a) response-text value anchoring, (b) one-event locality, (c) per-source-type quotas — all recall-motivated, generic decisions.

## 5. Does LangExtract add anything beyond our own chunking/retrieval?

**No — investigated, not usable here.** langextract 1.7.0 offers exactly three model backends (provider registry): Gemini API (remote — forbidden: only Mistral is allowed), local Gemma-family inference via MediaPipe (model sizes 2–3+ GiB exceed the 3.5 GiB RAM sandbox — the same infeasibility class as NuExtract3), and OpenAI GPT endpoints (no `api.mistral.ai`-compatible backend in the installed version). Its retrieval-relevant machinery (sentence/token chunking, span alignment) is already covered by our Phase-2 segments, which are span-exact **by construction** (byte offsets into the original prompt/response). Writing a custom model adapter to force Mistral through LangExtract would re-measure what A2 (Mistral RuleIR) already measures, with an additional framework in the loop.

## 6. Mistral vs NuExtract3: which preserves semantics better?

**NuExtract3 (the current 4B model) cannot run on this hardware** — fp16 weights ~8 GB, official W4A16 quantizations are compressed-tensors (vLLM/GPU-oriented, no supported CPU path), no GGUF conversion exists on the Hub (details in `hardware.json`). The smallest technically sound local variant of the same family, **NuExtract-1.5-tiny (494M)**, was used.

On the held-out synthetic set (rate = hits / *applicable* cases, from `stage_metrics.json`):

| dimension | Mistral | NuExtract-1.5-tiny | GLiNER2.5 | union (Phi) |
|---|---|---|---|---|
| modality | 0.733 | 0.412 | 0.647 | **0.882** |
| target | 0.6 | 0.0 | 0.0 | 0.529 |
| condition | 0.286 | **0.571** | 0.143 | 0.571 |
| exception | 1.0 | 0.0 | 0.0 | 1.0 |
| temporal | 0.5 | 0.0 | 0.0 | 0.5 |
| comparison (op+value) | — | **1.0** | 0.0 | 1.0 |
| cardinality | **1.0** | 0.0 | 0.0 | 1.0 |
| preservation field | 1.0 | 1.0 | 0.0 | 1.0 |

**Mistral is the only extractor that produces complete rules** (modality+target+conditions together); NuExtract-tiny is a *span-evidence* channel (its 0.5B slot-filling copies whole sentences into action slots — 55 MODALITY_UNSUPPORTED / 14 COARSE_SPAN failures in the required-fragment run — but its condition/threshold spans are the most reliable: comparison spans 2/2); the documented few-shot continuation confused the 0.5B model into re-emitting the input block, so the single-input protocol + deterministic modality/grounding gates were used instead.

## 7. What does GLiNER2.5 contribute?

Typed zero-shot spans with model-provided offsets: a *third, fully local* extraction channel whose modality signal (0.647) corroborates or disagrees with Mistral; it labels the same span with several modalities (noise that the NLI firewall then flags). It contributes no relations/temporal structure in our schema (0/2 temporal) — consistent with its design as a span extractor. Cost: 1.4 s model load, 0.08 s per unit — the cheapest channel.

## 8. Does the NLI detect semantic inversions?

**Yes, decisively.** Phase-10 adversarial pairs (`nli_adversarial_demo.json`): mean embedding cosine of *opposite-meaning* pairs **0.866** (max 0.976: "at least two" vs "at most two"), while the NLI cross-encoder labels **8/8 CONTRADICTION** — including reversed temporal ("verify before close" vs "close before verify"), must/may, not-allowed/allowed, threshold flips, only-when/even-when. In-pipeline, the firewall flagged **1,211 / 4,316 Φ candidates (28%)** as CONTRADICTION — largely the unless-routed-to-conditions inversions (both readings were kept in Φ via the deterministic *unless-mirror*; the firewall then selects which can survive A7 filtering).

## 9. Why are embeddings insufficient for semantic validation?

See 8: cosine similarity cannot separate an assertion from its inverse (0.87 mean on contradictions). Embeddings are therefore used **only** for candidate retrieval (ADD-ONLY) and CrossEncoder/NLI for pairwise semantic checking — the architecture's split is empirically justified, not stylistic.

## 10. Does the CrossEncoder improve tool/field binding?

Binding pipeline (exact lexical → embedding top-5 → cross-encoder rerank, keep alternatives): on the synthetic set, **18/36 matching rules BOUND-correct, 0 BOUND-wrong, 2 AMBIGUOUS, 16 UNKNOWN** — precision 1.0, recall 0.5. The conservative posture (UNKNOWN rather than a wrong binding) is intentional: embedding similarity is never a proof, ambiguity stays multiple. The dominant failure mode is the UNKNOWN floor (cross-encoder logit thresholds), not wrong bindings.

## 11. How many interpretations does Φ typically contain?

Dev: **mean 91** interpretations per case (median ~78; range 2–119) after semantic-key deduplication of 4,316 total candidates; synthetic: **mean 7.6** (small policies). Large dev Φ sizes reflect genuine policy size (telecom 23 k-char policies) plus instruction-noise candidates — which the admission gates then remove before lowering.

## 12. Which current FN classes become representable?

Representable **in RuleIR/Φ** (synthetic B-metrics + traces in `example_traces.json`): KB-derived rules (the rule inside a tool-result document — retrieved via channel D, extracted, NLI-checked), reversed temporal relations, numeric thresholds (comparison atoms), cardinality ("at least 2"), nested AND conditions, exceptions ("unless"), provenance-like source constraints, preservation rules — all with byte-exact source spans. On dev, all 105 human-required fragments are now retrieved (coverage 100%), including every KB rule fragment the incumbent routing lost.

## 13. Which remain impossible?

**Lowerable into the incumbent core — the central bottleneck found by this experiment:**
1. **Natural-language condition atoms are undecidable in the world algebra.** The incumbent's decidable conditions are atom-catalog predicates (tool-call facts like `action:get_flight_status`); Φ conditions are NL predicates ("request cannot be handled within the tools") → evaluate UNKNOWN → no FALSE witnesses → UNRESOLVED. This is why A0's h0_hist policy-path TP (premature escalation via a decidable condition atom) does not reproduce through Φ: a *condition→ledger binding* stage does not exist yet.
2. **Comparisons and cardinalities have no V1 lowering** (recorded as unresolved terms — never fabricated).
3. **Closure-gated classes** (catalog absence, extra fields) remain UNKNOWN by the soundness-corrected defaults — untouched by this experiment, as required.
4. **Goal-frontend SCHEMA fragility**: 25/46 dev cases had goal_conservative SCHEMA failures on the fresh cache (both arms equally affected; the frozen-cache lineage was luckier).

## 14. What changes are general vs benchmark-shaped?

Hardcoding scan (`hardcoding_scan.json`): **all 14 pipeline modules have ZERO benchmark-specific terms in executable code** (the only matches are `__main__` smoke-test selectors and a doc comment). Domain names/case ids appear ONLY in `coverage_annotations.py` — the Phase-4 evaluation harness (human-audited required-fragment ground truth, which the protocol explicitly asks to derive from audited development failures) — and in the report trace selector. The retrieval channels, cue lexicons (EN+RU generic), unless-mirror, NLI/binding/admission logic, RuleIR, and the synthetic set (unseen tools/domains) are domain-independent. No valid.parquet literal value, case ID or gold label conditions any pipeline decision.

## 15. Is the architecture worth integrating into Guardian?

### Final Guardian delta (dev 46, fresh shared cache, HEAD production defaults)

| Arm | TP | FP | FN | TN | Precision | F1 | false-certified |
|---|---|---|---|---|---|---|---|
| A0 incumbent (fresh cache) | 2 | 0 | 21 | 23 | 1.0 | 0.160 | 0 |
| A1 retrieval-augmented incumbent | 2 | 0 | 21 | 23 | 1.0 | 0.160 | 0 |
| A8 full pipeline | 1 | 0 | 22 | 23 | 1.0 | 0.083 | 0 |
| A8 synthetic held-out (17) | 0 | 0 | 14 | 3 | — | 0 | 0 |

(For reference, the frozen-lineage baseline at HEAD defaults was TP=3 — the audit's C3; A0-fresh differs because the fresh single-shot cache lacks the fix2 iteration lineage. A0 and A8 share goal/claims/T2 cache entries; the delta is attributable to the policy frontend substitution.)

### Decision (Phase 20 rule)

| criterion | verdict |
|---|---|
| 1. higher required-fragment recall | **YES** 0.648 → 1.000 |
| 2. better semantic preservation on held-out | **PARTIAL** — union modality 0.882, comparison/cardinality/exception 1.0, but conditions 0.571 and target 0.529 |
| 3. no benchmark-specific rules | **YES** (scan clean) |
| 4. disagreements stay multiple interpretations / UNKNOWN | **YES** (Φ sets, unless-mirror, AMBIGUOUS bindings, UNKNOWN floor) |
| 5. no new false-certified ERROR | **YES** (0 in every arm) |
| 6. reproducible local models/config | **YES** (all local models pinned + caches committed) |

**RECOMMENDATION — SPLIT KEEP:**
- **KEEP** the Phase-2/3 source-timeline + retrieval layer (in particular the ERROR-response split and the KB/lexical channels): it is pure coverage, zero-risk, and the prerequisite for every later stage. The ERROR-response split also fixes a real parser-level information loss that the incumbent has today.
- **KEEP** the NLI firewall + Phase-10 evidence as a standard candidate-validation gate (it caught 28% of candidates including all semantic inversions).
- **KEEP** RuleIR as the representation standard for future frontends (compositional, pydantic-validated, span-grounded, benchmark-independent).
- **DO NOT integrate the full Φ→core frontend yet.** The final-Guardian delta on dev is negative (TP 2→1 fresh-cache) for a structural reason, not a tuning reason: the incumbent V1 lowering cannot consume Φ's NL conditions (undecidable), comparisons or cardinalities. Integration requires core-side work that this experiment is forbidden to do: (a) a condition→ledger-atom binding stage, (b) comparator/cardinality atoms in the world algebra. Until then, Φ-based frontends will systematically under-certify relative to a compact H0 reading that happens to use decidable condition atoms.

NuExtract-1.5-tiny and GLiNER2.5: keep as *optional* evidence channels (they strengthen the union on conditions/thresholds and add a local third opinion), but they are not individually sufficient — the pipeline's full-rule quality currently rides on Mistral.

## Artifacts

```
outputs/vnext/semantic_pipeline_v1/
  hardware.json                     models, limits, NuExtract3 infeasibility reasons
  retrieval_coverage.csv            105 required fragments x methods (+ summary json)
  semantic_extraction_results.jsonl 4,578+ rule rows / failures / no-result markers
  nli_results.jsonl                 4,578 NLI checks
  binding_results.jsonl             4,578 binding results (composite keys)
  phi.jsonl                         Phi per case (63 cases)
  nli_adversarial_demo.json         Phase 10 embeddings-vs-NLI demonstration
  stage_metrics.json                Phase 15 A/B/C stage measurements
  ablations.json                    A0..A8
  example_traces.json               9 family traces (raw -> Phi -> verdict)
  hardcoding_scan.json              benchmark-term scan of all experiment modules
  final_summary.json                machine-readable summary
  mistral_cache.json                extractor cache (payload-keyed)
  e2e_semantic_cache.json           incumbent-frontends cache for A0/A1/A8
  final_guardian_A{0,1,8}*_progress.json  per-case verdicts
  _v1_run/                          first-pass artifacts (pre relaxed-cue filter)
```

Tests: `tests/e2e` + `tests/e2e_soundness` **138 passed**; full suite **1,620 passed + the 9 pre-existing failures** (identical set to pre-experiment; tracked files unmodified — `git status` shows only new untracked files).
