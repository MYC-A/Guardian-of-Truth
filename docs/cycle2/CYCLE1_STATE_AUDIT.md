# Guardian Cycle 2 — audit of the Cycle 1 research state

Audit date: 2026-09-12  
Research base: `bbd58efc4c346ad1dfa3acd7184c8ea2bbf45fd2`  
Production reference: `afb7906c3a3244fbc4196fe5cb2ea18ee86e0d96`  
Baseline verification: `python -m pytest -q` → `511 passed` on the exact
research base.

This document is an index over executable code, tests, machine-readable
outputs, and raw predictions. It does not reinterpret or rewrite the historical
Cycle 1 reports. When a historical Markdown statement conflicts with an output
or executable implementation, the latter is authoritative.

## Status vocabulary

- `IMPLEMENTED`: executable implementation exists on the audited commit.
- `NOT_IMPLEMENTED`: the named arm or required behavior does not exist.
- `RAN_VALIDLY`: the relevant runner completed with compatible observations.
- `RAN_PARTIALLY`: only a subset completed or the sample is insufficient.
- `TRANSPORT_BLOCKED`: API transport/rate limits prevented semantic inference.
- `INVALID_EVALUATION`: the score cannot answer the claimed research question.
- `DEV_ONLY`: evaluated only on `valid.parquet` or controlled regression cases.
- `EXTERNAL_PROXY_ONLY`: external labels are not Guardian target-turn labels.

Status is deliberately multi-valued. For example, an arm can be both
`IMPLEMENTED` and `TRANSPORT_BLOCKED`.

## Component audit

| Component | Current implementation | Tested? | Usable now? | Known limitation | Cycle 2 change? |
|---|---|---:|---:|---|---|
| `PolicyMeaning` | Typed, trace-independent record with modality, subject, regulated matter, qualifiers, temporal/identity/quantification, uncertainty and source provenance in `records.py`; proposal validation in `model_tasks.py` | Yes | As a proposal IR | v1 cannot represent every required relation/scope/reference distinction; Cycle 1 exact-schema results are not behavioral evidence | Yes, only if the frozen benchmark proves a structural representational gap |
| Obligation DSL | Deterministic `compile_meaning` boundary plus four-valued obligation solver | Yes | For registered predicates and supported constructs | Open vocabulary fails closed; permissions/context do not create strict violation obligations | No redesign; extend only from a general semantic requirement with positive, negative and metamorphic tests |
| Policy coverage ledger | Every segmented policy span receives a coverage status in `PolicyBundle.coverage` | Yes | Yes | P0 compiled only 5 of 523 unique segments and marked 518 `UNKNOWN` on dev | Preserve and expose in all Cycle 2 telemetry |
| Evidence Ledger | Normalized events and typed evidence records preserve status, provenance, freshness and completeness certificates | Yes | Yes | Evidence volume does not imply semantic relevance or completeness | Preserve |
| Tool Effect Registry | Schema-derived T0 plus human-reviewed contracts loaded from `contracts/tool_effects_v1.json` | Yes | Only where provenance is trusted | T1 has seven reviewed contracts and only five confirmed-effect records; most of 55 dev tools remain without trusted effects | Expand to a measured gold ceiling for tools occurring in positives/FNs/external cases |
| Claim extraction | Response-only deterministic extractor with explicit coverage ledger; LLM proposal parser exists | Yes | C0 only as a low-coverage baseline | C0 found 9 claims and covered 5.33% of audited spans; live C1/C2 probes were tiny and not scored against span gold | Build and freeze a response-only 150–300-span benchmark before comparing C0/C1/C2 |
| Binder | Exact scope/predicate matching and candidate sets over claims/evidence | Yes | Narrowly | No independently scored entity/time/source binding benchmark; unknown matches remain unresolved | Keep; measure failures before extending |
| Four-valued solver | `TRUE/FALSE/BOTH/UNKNOWN` logic and explicit `PROVED_ERROR/PROVED_NO_ERROR/UNRESOLVED/INCONSISTENT` result | Yes | Yes | Most X5 dev cases never reach a proof because upstream coverage is sparse | Preserve; report solver reach separately from binary score |
| Binary adapter | Frozen strict-v1 mapping; fallback labels and `used_fallback` are explicit | Yes | Operationally | Mapping `UNRESOLVED→0` can hide missing coverage in binary metrics | Preserve mapping for comparability, always co-report unresolved/inconsistent rates |
| X0 | Exact V5.3 incumbent | Yes | Yes | Dev/regression evidence only; not an architectural upper bound | Freeze as production/control arm |
| X1 | Strictly parsed holistic model arm with cited responsible sources | Yes | Interface usable | Full-input Cycle 1 request exceeded provider limits; compact probe was not the required full-input baseline | Re-run only with a model that passes the new reliability gate |
| X4 | Deterministic VIGIL-like trace-conditioned arm | Yes | Yes as an experimental arm | Cycle 1 evaluation was dev-only and does not establish transfer | Freeze before external labels and include unchanged in G1 |
| X5 | Policy→effects/evidence→claims→binding→solver path in `monitor.py` | Yes | Research only | Cycle 1 `X5_PROPOSED_MIN` included incumbent findings and therefore did not isolate the new architecture; 34/46 dev cases were unresolved | Split into `X5_CORE` and `X5_PROTECTED`; add required per-case execution telemetry |
| Long-context L2 | Exhaustive compile-once assembly with controlled dependency tests | Yes | Default policy path | Only controlled dependency retention was tested, not semantic correctness on a new failure family | Keep as default; do not add retrieval variants without a measured failure |
| External adapters | Pinned ATFD, tau-bench, AgentDojo, ToolSandbox and BFCL adapters/readiness checks | Yes | For schema/proxy diagnostics | ATFD/tau Cycle 1 score used trajectory outcome; ToolSandbox/BFCL have no compatible target-turn gold; AgentDojo had no frozen recorded artifact | Audit genuinely step-localized sources and freeze only cases with proven target-step labels |
| Benchmark harness | Reproducible stage runners, hashes, blinded proposal freeze, paired statistics helpers and provider profiles | Yes | Yes as infrastructure | Cycle 1 policy runner did not have a reliability admission gate and mixed operational failure with aggregate semantic zeros in presentation | Add predeclared reliability gate and explicit transport/schema/semantic outcome types |

## Arm-by-arm Cycle 1 disposition

| Arm | Status | Authoritative evidence | Cycle 2 interpretation |
|---|---|---|---|
| P0 | `IMPLEMENTED`, `RAN_VALIDLY`, `DEV_ONLY` | `outputs/next/policy_arms.json`; 16-case frozen regression inside `policy_model_run_groq_full.json` | Keep as deterministic control; the 16 cases are regression, not the new benchmark |
| P1 | `IMPLEMENTED`, `RAN_PARTIALLY`, `TRANSPORT_BLOCKED` | 5/16 transport+schema-valid outputs, 1/16 exact semantic-correct in the frozen raw run | No P1-vs-P2 conclusion is valid until a paired, admitted model run exists |
| P2 | `IMPLEMENTED`, `RAN_PARTIALLY`, `TRANSPORT_BLOCKED` | 3/16 transport successes, 2/16 schema-valid outputs, 0/16 exact semantic-correct | Not rejected; exact representation was the wrong primary metric and paired sample was insufficient |
| P3 | `IMPLEMENTED`, `RAN_PARTIALLY`, `TRANSPORT_BLOCKED` | 1/16 transport success, 0 schema-valid | Not established |
| P4/P5/P6 | `IMPLEMENTED` as offline scaffolds or selection utilities, `NOT_IMPLEMENTED` as valid benchmark arms | Executable candidate-pool, pairwise and mutant/world utilities; no admitted full run | Do not run P4 until P2 is valid; P5/P6 remain diagnostics |
| C0 | `IMPLEMENTED`, `RAN_VALIDLY`, `DEV_ONLY` | 9 claims; 5.33% span coverage; 136 `UNKNOWN` coverage items | Valid low-coverage baseline, not evidence that X5 claims are adequate |
| C1/C2 | `IMPLEMENTED` proposal/parser path, `RAN_PARTIALLY` probe only | Groq 3/6 successful calls; OpenRouter 2/6 successful calls; no independent claim gold | Not established |
| T0 | `IMPLEMENTED`, `RAN_VALIDLY`, `DEV_ONLY` | 55 unique tools; no trusted effects | Schema/name inventory only, never proof of an effect |
| T1 | `IMPLEMENTED`, `RAN_PARTIALLY`, `DEV_ONLY` | Seven reviewed contracts; five confirmed-effect records | Coverage ceiling not yet measured |
| T2/T3 | `NOT_IMPLEMENTED` as evaluated arms | Listed unavailable in `tool_effect_arms.json` | Forbidden until T1 shows conditional gain |
| X0 | `IMPLEMENTED`, `RAN_VALIDLY`, `DEV_ONLY`, `EXTERNAL_PROXY_ONLY` | Dev: TP=12, FP=0, FN=11, TN=23; external score used trajectory outcome | Production incumbent, not proven best architecture |
| X1 | `IMPLEMENTED`, `RAN_PARTIALLY`, `TRANSPORT_BLOCKED` | Strict model-arm code and compact/full probes | Mandatory new external baseline after provider admission |
| X4 | `IMPLEMENTED`, `RAN_VALIDLY`, `DEV_ONLY` | `end_to_end_arms.json` | Freeze unchanged before new labels; required constituent of G1 |
| X5 (Cycle 1 combined path) | `IMPLEMENTED`, `RAN_VALIDLY`, `DEV_ONLY`, `EXTERNAL_PROXY_ONLY`, `INVALID_EVALUATION` for isolated gain | Same dev binary predictions as X0; 73.91% unresolved; external proxy all-zero | Equality with X0 does not establish architectural equivalence |
| G1 | `NOT_IMPLEMENTED`, not run | No Cycle 1 artifact for `X0 OR (X4 AND X1)` | Must be frozen exactly as supplied before any new holdout labels are viewed |
| L0/L1/L2 | `IMPLEMENTED`, `RAN_VALIDLY`, `DEV_ONLY` | Controlled long-context report: L1 silently omitted required dependencies; L0/L2 did not | Keep L2; reject L1 top-k as default |

## Provider evidence is not a Cycle 2 gate

The Cycle 1 four-case role probes are useful connectivity diagnostics, not an
admission test. Groq and one OpenRouter model each returned 4/4 correct probe
answers, while the subsequent policy run was heavily rate-limited. Gemini was
2/4 transport-successful. Other recorded profiles were blocked or unreliable.
None of these results satisfies the Cycle 2 requirement of 12–20 paced,
schema-constrained calls with a threshold frozen in advance.

Previously exposed TokenHarbor and NVIDIA credentials are treated as
compromised and must not be used. Cycle 2 code and reports may record an
environment-variable name, but never a secret value, length, fingerprint,
header, or exception containing a header.

## Cycle 2 entry decision

The research infrastructure is usable without redesign. The first unresolved
scientific gates are, in order:

1. provider/model reliability admission;
2. behavioral policy semantics on a new frozen 80–150-case benchmark;
3. response-only claim extraction on a new frozen 150–300-span benchmark;
4. a trusted T1 ceiling and isolated `X5_CORE` execution coverage;
5. genuinely target-turn-localized external data and a blind paired comparison
   of X0, X1, X4, X5_CORE, X5_PROTECTED, and the predeclared G1 formula.

No architecture is promoted, rejected, or revised by this audit.
