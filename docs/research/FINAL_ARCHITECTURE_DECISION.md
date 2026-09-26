# Final architecture decision — 2026-09-26 cycle

Verdicts for every major component, per the directive's required
KEEP / REJECT / SHADOW format, followed by the architecture that the
evidence supports and the promotion gates.

## 1. Component verdicts

### Guardian components (existing)

| component | verdict | reason |
|---|---|---|
| Typed-question DECOMPOSITION (tq_questions_v2 question set: Q_ACTION_STATE, Q_CONDITION_APPLICABLE, Q_CLAIM_SOURCE, Q_DEMAND_PRESENT, Q_OBLIGATION_HISTORY, Q_HANDOFF_TRIGGER + arbitration order) | **KEEP** | B3 controlled replay: same decomposition + model answers, different join layer ⇒ F1 0.7222→0.8205 on the frozen perturbed suite with 0 TP lost. The decomposition is sound; it was never the failure. |
| fragment_supplier (all-sentences claims, data-driven entities, ordered timeline) | **KEEP (with v3 fixes)** | declarative coverage 1.0 everywhere; timeline gives order/latest as code facts. Fix: negation-aware confirmation (latent bug found), stop using ID_SHAPE/tool-name regexes for facts. |
| TQ v2 VERIFICATION layer (lexical governed-action join, tool-name-regex condition facts, kind-blind direction semantics) | **REJECT** | the measured failure mechanism: lexical name joins false-clear real violations under rename; PERMISSION semantics inverted for refusal-kind cards. Superseded by the v3 join layer. |
| v3 join layer (value-anchored (key,value) joins; effect-class governed-action binding; request-context targets; kind-aware directions) | **KEEP (candidate)** | restored 3/3 TPs, kept 7/7 FP removals on the frozen perturbed suite; every mechanism rename-robust by construction. Promotion gated on a fresh sealed run (§3). |
| Generic effect typing (READ/JOURNAL/DEFER/AUTH_MUT/MUTATION/COMMUNICATE/NOOP from morphology + arg-schema shape + result shape) | **KEEP (proposer-grade; trust-grade per tool only with T1 sign-off)** | 31/31 tools across 3 domains; 39/39 claim↔effect hard negatives; rename-robust. Feeds binding, B2, B6, and future T2 contract derivation. |
| feasibility_witness v2 (LLM proposes alternative; code validates) | **REPLACE (keep as reference)** | B6: the mandate-only planner semantics reproduces its frozen behavior deterministically (0/16 stress, 4/4 authored TPs); the planner also fixes its trigger gap (terminal tool calls) and its prerequisite-completeness gap (union-of-clauses conditions). The LLM arm remains as a fallback where the policy is not parseable. |
| Reachability overlay (planner semantics: PREMATURE_ABANDON) | **SHADOW** | 8/16 stress-set detections of "refused although achievable"; semantics defensible (observed-negative or user-decline justify; missing lookups do not) but UNLABELLED — needs a labelled set before any verdict role. |
| pgjudge cards + Mistral condition mappings | **KEEP (proposer only)** | mappings are the input the v3 layer verifies; the B3 replay used the frozen mappings successfully. Multi-parse disagreement gate (§3 G4) before promotion. |
| investigator_v2 arms A/B/C/M | **KEEP (architecture) / REJECT (current effectiveness)** | unchanged from prior cycle: zero flips; fixed routing = agent routing. |
| fp_refute_layer v3.1/v4/modal-safe base | **KEEP (baseline)** | the control every new layer must beat; frozen behavior reproduced everywhere. |
| X5/X0 V5.3 production line, cycle2 X5_CORE, vnext boundaries (SND-01..11) | **KEEP (as specified)** | production stays X0 V5.3; X5_CORE stays auditable scaffold; SND invariants are inherited by the v3 layer verbatim (no join without a value; no absence-as-fact; UNKNOWN≠FALSE). |
| full_architecture_v1 (NeutralCoreInput + Clingo evidence.lp/policy.lp + certificates) | **KEEP (solver backend)** | 43/43 vs incumbent 27/43; the v3 layer's condition verdicts are exactly the kind of premises it consumes. |
| semantic_pipeline_v1 (SourceTimeline, NLI firewall, Φ, RuleIR) | **KEEP (representation); SHADOW (pipeline)** | RuleIR schema (modality/typed terms/conditions/temporal) is the right NL-side IR; the A8 end-to-end arm stays un-integrated per its own §15. |
| GLiNER2.5 / NuExtract / LangExtract / BGE / NLI | **SHADOW (proposer/veto only)** | re-confirmed this cycle: BGE cannot separate establishment from relatedness; NLI entailment follows overlap; best model (Granite) still 83% vs typing 100%. |
| LettuceDetect locator | **REJECT** | unchanged negative (0/12 operation-grade, +1 FP/suite). |
| Gravit epistemic verifier | **REJECT (method) / SHADOW (TruthVector interface)** | token-overlap + uncalibrated thresholds + self-confirming tests. |

### External components (reuse)

| component | verdict | role |
|---|---|---|
| Invariant event model (Message/ToolCall/ToolOutput + tool_call_id pairing + `->` order) | **KEEP** | canonical trajectory serialization; cross-check evaluator target |
| formal-rv trace schema (approval_id, state_before/after, trust_domain) + metamorphic testing | **KEEP** | trace enrichment checklist; verifier self-test methodology |
| AgentDojo dual contract (traces-first, state-diff-second) + canaries | **KEEP** | verification contract for env-backed domains |
| ToolSandbox state-diff channel + delta typing | **KEEP** | the second verification channel where post-state is observable |
| tau-bench corpora + replay env | **KEEP** | fourth untouched domain + deterministic replay oracle |
| Clingo (via full_architecture_v1) | **KEEP** | solver backend for composed verdicts |
| External PDDL/HTN engines | **SHADOW** | formulation proven (B6); engines unnecessary at current state-space size |

## 2. The architecture the evidence supports

```text
trajectory (transport markers authoritative)
   ↓  [code]  parse timeline + call/result pairing (Invariant-style events)
   ↓  [code]  catalog → generic effect typing (per tool)          ← B2: 100%
   ↓  [code]  value-anchored facts: verifications / authorizations /
              stock / effects / user-confirm(+decline)            ← B3: joins
policy text
   ↓  [LLM=proposer + code gates]  quote-grounded cards; condition
              mappings; multiple independent parses → disagreement ⇒ UNKNOWN
   ↓  [code]  condition coverage check (code-detected ∪ model-listed);
              mandate = union over clauses                        ← B6
alarm/card + facts
   ↓  [code]  governed-action binding (explicit tool mention >
              effect-class match > UNKNOWN)
   ↓  [code]  typed condition verification (TRUE/FALSE/UNKNOWN by
              value joins; no join ⇒ UNKNOWN)                     ← B3
   ↓  [code]  kind-aware direction composition (PRECONDITION /
              POSTCONDITION / PERMISSION / REQUIREMENT × obligation_kind)
   ↓  [code]  refusal arm: mandate semantics (default) + reachability
              overlay (SHADOW, auditable)                         ← B6
   ↓  [solver] Clingo composition over verified premises (certificates)
   ↓  verdict: PROVED-VIOLATION / REFUTED / UNKNOWN + evidence spans
```

LLM usage is confined to three proposer roles (span/claim proposal,
policy-quote → condition mapping, alternative-action proposal), each behind
code gates (byte-anchored quotes, copied-text checks, coverage checks,
multi-parse disagreement). Nothing model-produced is ever a premise.

## 3. Promotion gates for the next cycle (Stage D→E)

1. **G1 fresh seal**: integrate the v3 join layer into the TQ runner; one
   sealed run on public46 + service_desk original (development/in-sample),
   one on hotel + service_desk renamed + tau-bench-derived fourth domain
   (frozen, no code changes after the first frozen result).
2. **G2 zero-TP-loss gate**: any frozen run with lost TPs fails the layer
   (the v2 standard).
3. **G3 multi-parse gate**: condition mappings from ≥2 independent parses
   (Mistral + Granite); disagreement ⇒ UNKNOWN (measured disagreement rate
   is a reported metric, not a tunable).
4. **G4 planner overlay gate**: labelled premature-abandonment set before
   the reachability overlay gets any verdict role.
5. **G5 T1 sign-off rule**: effect-class typings used as CONFIRMED-effect
   evidence only after per-domain T1 sign-off (ceiling-experiment rule
   unchanged).

## 4. What is explicitly NOT decided

- Whether TQ questions remain NL-question-shaped or become typed predicates
  (`Q(effect_established)` etc.) — both are the same decomposition; the
  directive's §19 says the FORM is free, and the evidence does not
  distinguish forms.
- Whether the policy compiler should adopt RuleIR as its output IR (likely,
  but the v3 layer currently consumes cards + condition lists; unification
  is next-cycle mechanical work).
- Public46/banking transfer of the planner semantics (unmeasured).
