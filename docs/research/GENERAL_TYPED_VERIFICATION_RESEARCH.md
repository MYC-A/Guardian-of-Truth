# General typed verification research — 2026-09-26

Branch: `codex/generality-research-20260926` (from `codex/tq-generality-20260925`).
Scope: the 2026-09-26 directive — investigate whether a more general trajectory-
verification layer can be built by REUSING existing methods, rather than by
adding another set of domain lexicons. This document is the research record;
companion documents: `EXISTING_METHODS_AND_LIBRARIES.md` (the survey),
`ISOLATED_PROBES_RESULTS.md` (Stage B measurements), `GENERALITY_RESULTS.md`
(frozen-suite outcomes), `FINAL_ARCHITECTURE_DECISION.md` (KEEP/REJECT/SHADOW).

## 1. The research question, restated operationally

The directive asks whether trajectory checking can move from

```text
whole response / whole trajectory  ->  "violation yes/no"
```

to

```text
trajectory -> small checkable propositions -> evidence/state/effects -> composition -> verdict
```

without pre-committing to a representation. The prior cycle produced a useful
negative: Typed Questions v2 removed FPs in-sample but, on the lexically
perturbed service-desk suite, removed 7 FPs and LOST 3 TPs, failing the
safety gate. The directive's counter-hypothesis: the DECOMPOSITION may be
sound while the UNSOUNDNESS lives in the grounding/verification layer
(entity joins, latest-state joins, amount binding, action semantics,
claim↔effect equivalence). This cycle tested that hypothesis directly and
confirmed it (§4.3): replaying the SAME frozen model answers with a
value-anchored verification layer restores all 3 lost TPs while keeping all
7 FP removals (F1 0.6957 → 0.8205 on the frozen perturbed suite).

## 2. Audit of existing Guardian components (Stage A)

Full component-level audit was performed on `codex/tq-generality-20260925`
and related branches. The complete table lives in
`FINAL_ARCHITECTURE_DECISION.md` §2; the essentials:

| problem | existing implementation | guarantees | does NOT guarantee | known failure | reusable |
|---|---|---|---|---|---|
| policy → cards | `p_precond_api.py` pgjudge (Mistral, quote-grounded cards) | every card quote byte-anchored in policy; obligation_kind typed | card semantics coverage | label-lazy judge demands; card set varies across runs | YES (as proposer) |
| typed questions | `tq_questions_v2.py` (frozen v2 layer) | verbatim fragments w/ ids; model verdicts re-verified by code; INCONSISTENT never refutes; UNKNOWN keeps | join soundness | 3 TP lost on renamed suite (§3) | YES (decomposition layer) |
| fragment supply | `fragment_supplier.py` | all declarative sentences = claims; data-driven entity vocabulary; ordered timeline | semantic typing of fragments | ID_SHAPE / tool-name regexes are lexical | YES (with v3 joins) |
| entity binding | `typed_witnesses.same_entity`, `next/binder.py` | anchor-key joins; alternatives preserved | — | `not target_anchors or same_entity(...)` = permissive pass-any default; empty claim scope matches ALL evidence | PARTIALLY (fix defaults) |
| evidence ledger | `next/normalize.py`, `trace_records.py` | append-only; ATTEMPTED ≠ OBSERVED; failure never implies no-effect | business success of a call | `_succeeded` heuristic; FIFO pairing fallback | YES |
| tool effects | `next/effects.py` T0/T1, `cycle2/effect_ceiling.py` | T0 never invents effects; T1 human-signed contracts | coverage (11.67% internal / 0% external) | registry insufficient | YES (T0 idea → generalized by effect typing) |
| formal solver | `full_architecture_v1` Clingo evidence.lp/policy.lp | 43/43 vs incumbent 27/43 on NeutralCoreInput; certificates | policy semantics quality | semantics upstream bottleneck | YES |
| feasibility | `feasibility_witness.py` v2 | exact quotes; tool membership; premise binding | completeness of model-listed prerequisites; terminal-tool-call triggers | 0/3 public46 C1 misses recovered; text-trigger only | PARTIALLY (replaced by planner semantics) |

Cross-branch conclusions (from the audit of `big_researh`, `semantic-pipeline-v1`,
`full-architecture-v1`, `E2E-agent-1/2`, `full_21/*`, `research/*`):
the frozen control to beat is OR-ensemble F1 .8889 on public46; the strongest
foundation for a generality layer is `full_architecture_v1` (NeutralCoreInput +
Clingo + certificate checker); the soundness invariants from
`PRE_BENCHMARK_SOUNDNESS_AUDIT.md` (SND-01..11) are the spec any new layer must
inherit; and the recurring bottleneck across ALL cycles is upstream semantics
(binding, claim typing, policy meaning), never the solver.

## 3. Why TQ v2 lost TPs on the renamed domain — the exact mechanisms

The frozen traces (`outputs/searh_23/tq_generality/sd_renamed_frozen_v2/`)
contain the per-question, per-card evidence chains. Reading the three lost
TPs directly:

1. `renamed__desk_v1__call_bad_no_identity` and
   `renamed__desk_v1__call_bad_wrong_amount_auth`: the card was REFUTED by
   `Q_CONDITION_APPLICABLE` with the note *"response executes
   ['perform_swap'], not the governed action; this clause does not rule the
   executed call"*. The "not-governed → REFUTED" escape hatch compares the
   POLICY's words ("device replacement") against the RENAMED TOOL NAME
   (`perform_swap`) LEXICALLY. In the original vocabulary the tool was
   `execute_replacement`, which lexically matches "replacement", so the same
   check correctly proceeded to condition verification. Under renaming the
   lexical join returns "no overlap" and the verifier concludes — falsely —
   that the precondition clause does not govern the call, clearing a real
   violation (missing identity verification / wrong-amount authorization).
2. `renamed__desk_v1__text_bad_stock_claim`: the card (obligation_kind
   `refusal`) was REFUTED by the PERMISSION-direction rule *"permission
   conditions code-verified TRUE: action permitted"*. Stock IS available, so
   the permission condition holds — but for a REFUSAL-kind card, a satisfied
   permission condition means the complementary MANDATE applies (the agent
   must act rather than falsely claim impossibility). The direction semantics
   ignored the card's obligation kind.
3. Additionally discovered while replaying: the condition facts themselves
   were joined by tool-name regexes (`verif|identity|…|match` on tool names)
   and ID-shape regexes, plus a latent negation bug in the confirmation
   regex ("Пока НЕ подтверждаю" matches the confirm pattern — the
   precondition-ablation stress set exposed it).

**Answer to directive question 1 (why TPs were lost):** lexical
governed-action↔tool-name joins + obligation-kind-blind direction semantics +
lexicon-shaped condition facts. **Answer to question 2 (decomposition or
verification?):** verification. The typed-question decomposition, the model
mappings, and the arbitration were frozen and unchanged; only the join layer
varied — and that alone moved F1 0.7222 → 0.8205 (§4.3).

## 4. What was tested this cycle (Stage B) — headline results

All probes are in `experiments/generality26/`; full numbers in
`ISOLATED_PROBES_RESULTS.md`.

### 4.1 B1 — action/actor/modality minimal pairs (23 items)

Deterministic classification (fragment flags + generic effect typing of the
response's calls): **23/23 = 100%**. Mistral `ministral-14b-latest`
(JSON mode, the same question form as the frozen TQ layer): **14/23 = 60.9%**,
and only 25% on the critical tool-semantics pairs (executed vs journal vs
read vs schedule vs failed-attempt). The small LLM conflates semantic
relatedness with execution — exactly the §8/§9 failure class the directive
names. Actor attribution (AGENT vs USER vs TOOL) is likewise better in code
when the transport provides the call marker.

### 4.2 B2/B2g — claim↔effect equivalence on hard negatives (39 pairs)

Pairs with deliberately high lexical overlap (`execute_replacement` vs
`record_audit` vs `check_authorization`; renamed vocabulary
`perform_swap`/`log_completion`/`lookup_approval`; generic families
cancel/refund; tau-bench retail tools). Gold: only a successful
MUTATION-class result ESTABLISHES an action-completion claim; reads
establish PRECONDITION FACTS at best; journal/schedule establish neither.

| method | overall | hard-negative rejection | establishes recall |
|---|---:|---:|---:|
| BGE-M3 cosine (best threshold 0.674) | 0.871 | ~0.68* | — |
| NLI DeBERTa (entailment=establishes) | 0.538 | 0.737 | 0.688 |
| Mistral 14B judge | 0.564 | 0.421 | 0.750 |
| Granite Guardian 4.1 8B (BYOC) | 0.828 | 0.933 | 1.000 |
| **deterministic claim-class × tool-class typing** | **1.000** | **1.000** | **1.000** |

*BGE cosine means: ESTABLISHES 0.695 ≈ PRECONDITION_FACT 0.709 > NEITHER
0.622 — similarity cannot separate "establishes" from "related precondition
fact" at all; a threshold that keeps ESTABLISHES also keeps most hard
negatives. Embeddings measure RELATEDNESS, not ESTABLISHMENT (directive §10
confirmed quantitatively).

The deterministic typing is generic: English tool-naming morphology
(read/check/lookup/find = READ; write/log/record/audit = JOURNAL;
schedule/defer = DEFER; authorize/approve/grant = permission-creating
MUTATION; transfer_to/route_to + human-object = COMMUNICATE; causative verbs
= MUTATION) + arg-schema shape (id+non-id-string = verification-shape;
id+amount = authorization-shape; availability key = stock-shape) + claim
morphology (action-completion vs fact-assertion). It is rename-robust BY
CONSTRUCTION because it never joins on surface names of tools.

### 4.3 B3 — binding-layer A/B replay (the critical probe)

Replay of the FROZEN v2 traces (same model answers, same questions, same
arbitration) with ONLY the `Q_CONDITION_APPLICABLE` verification replaced by
a v3 implementation: value-anchored `(key, value)` joins on parsed JSON
(case_id↔case_id, amount↔amount), effect-class-based governed-action binding
(explicit policy tool mention > clause effect-class vs tool effect-class),
request-context targets for text-only responses, obligation-kind-aware
PERMISSION/REQUIREMENT semantics, negation-aware confirmation. On the frozen
renamed suite (the holdout where v2 failed):

| arm | TP | FP | FN | F1 |
|---|---:|---:|---:|---:|
| modal-safe base | 16 | 14 | 0 | 0.6957 |
| TQ v2 (frozen, lexical joins) | 13 | 7 | 3 | 0.7222 |
| **TQ v3 (value-anchored joins)** | **16** | **7** | **0** | **0.8205** |

All three lost TPs restored (`call_bad_no_identity`,
`call_bad_wrong_amount_auth`, `text_bad_stock_claim`); all seven FP removals
kept; zero TP lost. The same model proposals, a different verifier — the
decomposition hypothesis is confirmed and the failure is localized to the
join layer. (The sd_orig replay used a stale dev-loop trace whose stored
answers predate final v2 gates; it is reported as diagnostics only in
`ISOLATED_PROBES_RESULTS.md` §4.)

### 4.4 B6 — feasibility as planning (hypothesis H3)

The service-desk domain formalized as a typed fact space (facts from
value-anchored observations; action classes from catalog shapes) with two
refusal-semantics readings, evaluated on the frozen 16-case precondition
ablation stress set + the authored refusal/handoff cases:

- **mandate-only semantics** (a refusal violates only if every mandate
  condition is already satisfied): 0/16 candidates on the stress set —
  byte-consistent with feasibility_witness v2's frozen 0-CANDIDATE result —
  and CANDIDATE on the 4 authored false-refusal/handoff cases. The planner
  REPRODUCES the LLM-based witness deterministically.
- **reachability semantics** (a refusal also violates when missing
  conditions are achievable via declared tools): 8/16 stress variants become
  `CANDIDATE_PREMATURE_ABANDON` (identity never checked though
  `match_contact`/`verify_requester` is declared; authorization never
  looked up though an id+amount read tool exists), while stock-out and
  user-declined variants remain justified. This reading is STRICTER than
  the model-based witness and is exactly the "agent refused although it
  could have completed prerequisites" class the directive describes.

## 5. What the existing-methods survey changed in the design

- **Invariant (IPL)** confirmed the event-model and 3-valued discipline but
  also that its tool matching is name-based (`tool:transfer(...)`) — the
  same lexical-join fragility we just measured. We take its
  `tool_call_id` pairing, `->` dataflow order, and ranges-as-evidence, not
  its name joins.
- **formal-rv (MFOTL/MonPoly)**: obligations need approvals/timestamps in
  the trace schema to be checkable; Guardian's transport already carries
  ordered events; its call-answer binding (lookup-call ↔ result binding)
  maps onto our value-anchored observation joins.
- **tau-bench**: reward = whole-DB hash equality + output substrings; NO
  postconditions, NO write tracking, NO claim verification. Its reusable
  pieces are the deterministic replayable env and offline trajectory
  corpora — and the explicit demonstration that identity/freshness/binding
  checking is NET-NEW (what Guardian builds).
- **ToolSandbox**: milestone-DAG + state-diff verification, guardrails-by-
  default from pre/post state, and tool_trace extractors — the state-diff
  channel is the right COMPLEMENT to trace-based checks (traces-first,
  state-diff-second, as AgentDojo's dual contract shows).
- **AgentDojo**: utility/security per-task callbacks over pydantic env
  diffs + canary-proven injectability; the pattern "verify by trace, fall
  back to state diff" and benchmark versioning transfer directly.
- **NeMo Guardrails / Guardrails AI / Snyk Agent Scan**: RailOutcome
  (allow/block/transform, fail-closed) as the verdict contract;
  on_fail policies as a separate layer; closed, versioned hazard
  vocabulary with evidence-first reports.
- **Hefesto**: "declared vs observed" operational-truth parity — the same
  shape as claim↔effect and policy↔action checks.
- **Structured extraction (GLiNER / NuExtract / LangExtract / NLI)**: already
  measured in prior cycles (semantic_pipeline_v1): GLiNER target accuracy
  0.0 on synthetic rules; NuExtract-1.5-tiny target 0.0; NLI firewall is
  useful as a VETO (contradiction), never as a creator of facts; embeddings
  (BGE) measured again this cycle — cannot separate establishes from
  related. These remain proposer-grade only.

## 6. Answers to the directive's 28 questions (condensed)

1–2: §3 above — verification layer, not decomposition (proven by controlled
replay). 3: Invariant's typed event model is the best existing
action/event representation (with formal-rv's schema fields); PDDL-style
action typing comes for free from tool catalogs (B2: 100%). 4: no
turnkey runtime-verification framework fits the NL-rule entry point;
Clingo (full_architecture_v1) is the proven solver backend. 5–6: tool
effects SHOULD be represented as typed action classes + per-domain T1
contracts; a custom ontology is NOT needed beyond the six generic classes
(READ/JOURNAL/DEFER/AUTH/MUTATION/COMMUNICATE) — measured 31/31 tools across
three domains. 7: effect contracts can be DERIVED from schemas to
proposer-grade (B2/B6); promotion to trusted T1 needs per-domain sign-off
(the ceiling experiment's rule). 8–9: performed/claimed/proposed/asked —
code + transport markers (B1: 100% vs 61%). 10–11: claim↔effect by
class-matching, not similarity (B2). 12–13: wrong-entity/stale-state joins
die with value-anchored binding + latest-observation discipline (B3). 14–16:
feasibility IS a planning problem (B6); untried-action detection = reachability;
prerequisite completeness = multi-parse disagreement gate + code-detected
condition coverage (the COND_PATTERNS gap on the mandate clause is measured
in B6 and fixed by the union-of-clauses derivation). 17: multiple
interpretations preserved as alternatives (binder discipline). 18–20:
deterministic = transport parsing, joins, effect typing, latest-state,
reachability; LLM = proposer of mappings/condition lists/claims (never
verifier of its own proposal). 21–22: see FINAL_ARCHITECTURE_DECISION.md.
23–25: see GENERALITY_RESULTS.md — frozen replay positive for v3 joins;
the remaining bottleneck is policy-compiler coverage (open-vocabulary
condition nouns) and the public46 banking-domain transfer.

## 7. What was deliberately NOT done this cycle

No whole-Guardian F1 runs on public46/hotel with the v3 layer (development
is gated on isolated-probe success first, per directive §30); no promotion
of anything into frozen candidates; no lexicon additions (the only new
"vocabulary" is generic normative-policy concepts: identity/confirmation/
authorization/stock + English tool-naming morphology); the frozen suites
were not modified.
