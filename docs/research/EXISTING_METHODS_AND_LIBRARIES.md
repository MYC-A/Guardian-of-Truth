# Existing methods and libraries — survey and measured reuse decisions (2026-09-26)

Format required by the directive: `library/project | relevant idea | what can
be reused | what cannot | experiment performed | measured result | decision`.
Clones live in `/home/z/my-project/repos_analysis/` (local) and were analyzed
across the 2026-09-24..26 sessions; this cycle added tau-bench and the
practical probe measurements marked [B1]/[B2]/[B2g]/[B3]/[B6].

## A. Agent/runtime policy verification

| library/project | relevant idea | reusable | not reusable | experiment performed | measured result | decision |
|---|---|---|---|---|---|---|
| **Invariant** (invariantlabs-ai/invariant) | typed event model (Message/ToolCall/ToolOutput + tool_call_id pairing); declarative IPL with `->` (happens-before) / `~>`; quantifiers forall/count; 3-valued Unknown; error dedup; ranges-as-evidence | event schema + call/result pairing; dataflow order; 3-valued semantics; structural evidence ranges; COUNT quantifier for "no more than N" | tool matching is NAME-based (`tool:transfer(...)`); deontic REQUIRE/future absent; violations-only (no completeness) | its grammar/interpreter read; GRL→IPL compilation sketched; name-join fragility mirrored by our B3 measurement of the same pattern in TQ v2 | (B3) lexical name joins are the exact mechanism that lost 3 TPs under rename | **KEEP as reference event model + cross-check target; do NOT adopt its name joins** |
| **formal runtime verification for tool-using agents** (nikos-kekatos) | MFOTL/MonPoly monitors; obligations need approvals/timestamps; call-answer binding kills poisoning 94-99%→0; READONLY_PREFIX guard; 12-field enforcement-ready trace schema; earliest-warning metric; 780 metamorphic tests | rich trace schema fields (approval_id/state_before/state_after/trust_domain); call-answer binding ≈ our value-anchored obs joins; metamorphic testing of the verifier itself; earliest-warning timing metric | formulas are hand-written (no NL→formal); FOL predicates typed by substring matching; BFR 29.3% (triage filter, not gate) | prior-session deep read of paper + specs + monitors; the substring-typing limitation is the same class our effect typing replaces | [B2] generic morphology typing: 31/31 tools correct across 3 domains where their substring typing fails under rename | **KEEP schema fields + metamorphic discipline; SKIP MonPoly as runtime (Clingo already integrated)** |
| **NVIDIA NeMo Guardrails** | RailOutcome (allow/block/transform, fail-closed); 5 interception surfaces (input/tool-call/tool-result/output); Colang flow DSL | verdict contract + fail-closed + surface taxonomy | no formal semantics; order only via imperative flows; global $vars; no deontics | prior-session source read | — | **KEEP the RailOutcome contract pattern; SKIP the runtime** |
| **Guardrails AI** | field validators + on_fail policies (reask/fix/filter/refrain); FieldReAsk precision repairs | on_fail as a separate layer above verdicts; FailResult(error_spans+fix_value) structure | trajectories/events/order absent; LLM validators without UNKNOWN-typing | prior-session source read | — | **SHADOW (pattern only)** |
| **Snyk Agent Scan** (ex-Invariant) | closed versioned hazard vocabulary; evidence-first risk reports; rug-pull → re-inspection; consent/redaction | hazard-dict versioning; evidence-first reporting | server-side verdicts; MCP-surface focus (offline) | prior-session source read | — | **SHADOW (reporting pattern)** |

## B. Tool-use environments / state verification

| library/project | relevant idea | reusable | not reusable | experiment performed | measured result | decision |
|---|---|---|---|---|---|---|
| **tau-bench** (sierra-research/tau-bench) | deterministic JSON-backed env; whole-DB hash reward vs GT replay; output substrings; offline trajectory corpora with rewards; LLM fault taxonomy | replayable env + data (entity ownership graphs offline-checkable); historical trajectories as a 4th untouched corpus; pass^k metric math | no postconditions, no write tracking, no claim verification, no policy checker (wiki.md is prose; RULES is dead code); user simulator needs live LLM | THIS cycle: cloned + deep read of envs/base.py `calculate_reward`, tools, wiki; tool set embedded in B2 hard-negative benchmark | [B2] their tools classified correctly by generic typing (7/7); their reward design would PASS wrong-path-same-state and MISS informational violations — the classes Guardian checks | **KEEP as external corpus + gold-standard tool-schema source; SKIP reward as a model** |
| **AgentDojo** (ethz-spylab) | dual contract: verify by trace first, fall back to pre/post env diff; canary-proven injectability; benchmark versioning; injection-task × attack matrix | traces-first/state-diff-second contract; guardrails-by-default from pre/post diff; corpus generation via systematic mutations | bool-only verdicts; no temporal logic; imperative Python callbacks | prior-session deep read | — | **KEEP the dual contract + mutation-based corpus generation** |
| **ToolSandbox** (apple) | milestone DAG (partial order) + soft similarity matching; minefields zero the trajectory; guardrails = closed-world on unmentioned DBs; state-dependency in tools (ConnectionError when cellular off) | state-diff verification channel; add/remove/update delta typing ↔ effect classes; tool_trace extractors as supports() oracles | rouge_l fuzziness violates UNKNOWN discipline; DFS without guarantees | prior-session deep read | — | **KEEP state-diff channel + delta typing; SKIP similarity matching** |
| **ToolEmu** (ryoungj) | likelihood×severity rubric; underspecifications as a first-class case field; adversarial emulator for stress trajectories | negative-case generation format (Potential Risky Outcomes/Actions); severity layer on top of violated verdicts | LLM-judge as ground truth | prior-session read; case format informed our stress sets | — | **SHADOW (stress-set generator)** |

## C. Operational truth / parity

| library/project | relevant idea | reusable | not reusable | experiment performed | measured result | decision |
|---|---|---|---|---|---|---|
| **Hefesto** (artvepa80/Agents-Hefesto) | "declared vs observed" operational truth (imports vs deps, docs vs CI); capabilities manifest | the parity pattern generalized to policy↔action, claim↔effect, declared-success↔state-transition; CI integration (diff-only, dedup) | the static-analysis product itself | prior-session read | [B2] claim↔effect IS the parity check, solved by class typing | **KEEP the parity framing; SKIP the analyzer** |

## D. Structured extraction / semantic parsing (proposer-grade only)

| library/model | relevant idea | reusable | not reusable | experiment performed | measured result | decision |
|---|---|---|---|---|---|---|
| **GLiNER / GLiNER2.5** | zero-shot typed spans as bridge evidence | process-isolated sidecar; unresolved-tag discipline | complete rules (target 0.0, temporal 0.0 on synthetic) | semantic_pipeline_v1 integration + benchmarks (prior cycles) | modality 0.647 / target 0.0 — diagnostic only | **SHADOW (proposer only)** |
| **NuExtract (1.5-tiny / 3-W4A16)** | verbatim-quote structured extraction with deterministic normalization | span evidence channel (comparison spans 1.0); unbound slots preserved not guessed | full rules (modality 0.412 / target 0.0); NuExtract3 infeasible on A10 for full pipeline | semantic_pipeline_v1 + s9 cards (46/46 extractions, 376 rules; as judge context F1 .23–.38 — honest negative) | good SOURCE extractor, bad JUDGE | **KEEP as span-evidence extractor; REJECT as judge** |
| **LangExtract** | provider-gated extraction | honest UNAVAILABLE gating (never pretend local) | needs remote provider | investigator_tools targeted probe | n/a (no provider) | **SHADOW** |
| **NLI (cross-encoder/nli-deberta-v3-base)** | entailment as VETO on candidate inversions | contradiction ≥0.5 removes candidates (8/8 adversarial) | entailment ≠ establishment: [B2g] 21 entailments of which 5 are hard NEITHERs; only 11/16 ESTABLISHES entailed | semantic_pipeline_v1 + THIS cycle B2g | entailment tracks relatedness, not effect classes | **KEEP as veto-only firewall; REJECT as effect judge** |
| **Embeddings (BGE-M3 + reranker)** | retrieval/ranking only | candidate evidence, never proof | [B2g] cosine ESTABLISHES 0.695 ≈ PRECONDITION 0.709 > NEITHER 0.622 — cannot separate establishment from relatedness at any threshold | semantic_pipeline_v1 + THIS cycle B2g | similarity is NOT semantics (directive §26 confirmed) | **KEEP as retrieval only** |
| **SRL / OpenIE / dependency parsing** | actor/action/modality from syntax | — (candidate proposers) | coverage on RU/EN mixed transcripts; no effect semantics | literature check: no off-the-shelf SRL covers RU+EN tool-transcript hybrid reliably; our transport markers already give actor deterministically | B1 code baseline 23/23 without SRL | **REJECT for now (transport markers + typing suffice at 100% on B1)** |
| **PDDL / HTN planners** | feasibility as planning (H3) | the PROBLEM FORMULATION (typed facts + action classes + reachability) is PDDL-expressible; BFS suffices at this scale | full planner engines (state space tiny; engines add ops cost) | THIS cycle B6: typed fact space + catalog-derived action classes + two refusal semantics | mandate semantics reproduces feasibility_v2 exactly (0/16 stress); reachability adds 8/16 premature-abandonment detections | **KEEP the planning formulation; SHADOW external planner engines** |

## E. Prioritized conclusions

1. **Nothing turnkey exists for the NL-rule → verified-trajectory entry point**
   (the unique Guardian asset remains the lifter/Φ/grammar line); every
   surveyed system either hand-writes formulas (formal-rv), name-matches
   tools (Invariant), judges end-state only (tau-bench), or has no formal
   semantics (NeMo).
2. The highest-value reuse is REPRESENTATIONAL, not runtime: Invariant's
   event model, formal-rv's trace schema, AgentDojo/ToolSandbox's dual
   trace/state-diff contract, tau-bench's corpora as untouched domains.
3. The highest-value NEW (but minimal) component this cycle is the generic
   effect typing + value-anchored binding layer — measured at 100% on every
   isolated probe where LLM judges scored 56–83%, and validated by the B3
   replay restoring all frozen-suite TPs.
4. LLM/embedding components are proposers and vetoers only; the survey +
   measurements agree on this without exception.
