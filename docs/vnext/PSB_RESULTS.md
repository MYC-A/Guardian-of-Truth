# PSB — Policy Structural Binding: causal experiment results (Stage A)

Experiment: `PSB_CAUSAL_V1` · Preregistration: `docs/vnext/PSB_PREREG_GATES_V1.json`
(frozen before the first inference request) · Runner commit at freeze:
`7d055caa` · Status: **SCORED + AUDITED, terminal**

This is the last standalone Policy architecture experiment per protocol.
PHV1 (59/80 = 73.75%) served as development evidence for hypothesis and
design only; it was never used as confirmatory data.

## 1. Design (frozen)

- **Arms** (same model `bai/qwen3.8-flash`, same atom-catalog contract, one
  parse per case per arm schema, one repair re-ask max, sealed before gold
  join):
  - **H0** — the frozen flat single-structure frontend, byte-identical to the
    PHV1 H0 (continuity machine-verified against the sealed PHV1 freeze).
  - **H1** — typed attachment graph (nodes: REGULATED / MODALITY / CONDITION /
    EXCEPTION / ACTOR / QUALIFIER; edges: REGULATES / ACTIVATES / EXEMPTS /
    ACTOR_OF / QUALIFIES / SOURCE_OF / PRECEDES / FOLLOWS) + deterministic
    per-clause compilation into the same v3 program space. No permission gate.
  - **H2** — the same sealed parse as H1, compiled with the frozen
    positive-evidence permission gate (text-level marker classes; rejected
    clauses are dropped to UNKNOWN, never remapped).
- **Benchmark**: 44 fresh gold-by-construction cases (zero shared word
  8-grams with V4/V5/PHV1), 12 relation/attachment, 8 exception-vs-condition,
  8 multi-clause modality/actor, 8 permission-evidence controls (incl. one
  empty-gold case), 8 multi-axis. 32/44 H0-representable (merge-equivalence),
  12 capacity cases (per-clause modality/actor/gates that a flat structure
  cannot express). Machine-checked binding discriminability per cohort.
- **Gates** (frozen): H1 = binding micro-F1 ≥ 0.85 AND behavioral ≥ H0+10pp
  AND H0-correct regression ≤ 5%; H2 = invented permission ≤ 2% AND
  permission clause precision ≥ 95% AND behavioral H2 ≥ H1; primary = H2 ≥
  H0+15pp; validity floor 0.90 per arm.

## 2. Primary measurements (MEASURED)

| metric | H0 (flat) | H1 (graph) | H2 (graph + gate) |
|---|---|---|---|
| behavioral case accuracy | **24/44 = 54.55%** [40.1, 68.3] | **32/44 = 72.73%** [58.2, 83.7] | **32/44 = 72.73%** |
| schema/compile validity | 42/44 = 95.45% | 37/44 = **84.09%** | 84.09% |
| binding micro-F1 (triples) | 0.820 | **0.856** | 0.856 (same parse) |
| invented permission (cases) | **10 (22.73%)** | **0 (0%)** | 0% |
| permission clause precision | 0.9545 | 0.950 | **1.000** |
| permission clause recall | 0.840 | 0.760 | 0.760 |
| H0-representable subset | 24/32 = 75.0% | 23/32 = 71.9% | 71.9% |
| capacity subset | **0/12 = 0%** | **9/12 = 75.0%** | 75.0% |

Paired H1 vs H0: **15 corrections : 7 regressions**, exact McNemar
p = 0.1338, Newcombe 95% CI for the +18.2pp delta [+0.01pp, +35.0pp];
correction precision 0.682. H2 vs H1: 0 : 0 (identical; the gate rejected
exactly one behaviorally-inert hallucinated permission clause on
`permission_evidence::p01`, lifting clause precision 0.95 → 1.00).

Cohorts (H0 → H1): exception-vs-condition 62.5% → **100%**; multi-clause
modality/actor 0% → **87.5%**; relation/attachment 66.7% → 75.0%;
multi-axis 75% → **50%**; permission controls 62.5% → 50%.

Binding per-class F1 (H0-flat-projection → PSB graph): CONDITION 0.706 →
**0.863**, ACTOR 0.714 → **0.833**, CLAUSE (scope) 0.865 → **0.891**,
EXCEPTION 0.923 → 0.929, MODALITY 0.865 → 0.849; QUALIFIER_PROVENANCE
1.00 → 0.00 (the only provenance case, x03, became a graph-format failure).

Efficiency: H0 47 requests / 71.8K tokens / median 8.9s; PSB 51 requests /
117.7K tokens / median 11.2s (graph output ≈ 1.6x tokens).

## 3. Gate evaluation (MEASURED)

- **H1 gates**: binding F1 0.856 ≥ 0.85 **PASS**; behavioral +18.2pp ≥ 10pp
  **PASS**; H0-correct regression 7/24 = 29.2% ≤ 5% **FAIL**.
- **H2 gates**: invented permission 0% ≤ 2% **PASS**; clause precision 1.00
  ≥ 0.95 **PASS**; behavioral H2 ≥ H1 **PASS** — H2 hypothesis SUPPORTED
  (trivially: see §4).
- **Primary candidate gate**: +18.2pp ≥ 15pp numerically PASS, but promotion
  requires H1 AND H2 AND primary → **NOT PROMOTED**.
- **Validity floor**: PSB arm 84.09% < 90% → frozen verdict field
  **INFRASTRUCTURE_FAILURE** (see §5 for what the seven failures actually
  are).

## 4. Post-seal failure audit (deterministic, no LLM judge)

H0's 20 errors: 7 atom recognition (incl. clause-shape/scope misbinds),
6 other (multi-field), 3 relation strength, 2 representation gap, 2
multi-axis. Its 10 invented-permission cases reproduce the PHV1
condition-dropping-under-exceptive signature at a higher rate on this
binding-heavy corpus.

H1's 12 errors decompose into exactly two causes:
1. **Graph-format assimilation failures (7)** — schema-valid JSON that
   violates frozen graph rules after both attempts: atoms used as node ids
   (m07), edge direction flipped (x07), fields folded into REGULATED nodes
   (x04, r12), two ACTIVATES on one clause (x05), QUALIFIES pointed at a
   qualifier (x03, p08). Four of the seven were H0-correct cases.
2. **Semantic errors (5)** — invented actor gates for non-person subjects
   ("freight", "passengers": p01, r02), modality flip on a "reserved to"
   construction (p07: PROHIBITION-reading of an exclusive permission),
   strength flip (p04: NECESSARY for a plain before-deadline obligation),
   scope merge (r08: "both closed" read as one together-clause).

The permission-evidence result deserves emphasis: **H1 reached 0% invented
permission without the gate** — the structured extraction prompt alone
eliminated the PHV1 failure mode (10/44 → 0/44 verdict-level; the single
hallucinated permission clause on p01 was behaviorally inert on the frozen
worlds and is visible only in clause precision, where H2's gate rejected
it). H2 is therefore supported-but-redundant on this benchmark: its gates
pass, and its unique measurable effect is precision 0.95 → 1.00 at zero
behavioral cost (H2 = H1 on every case).

## 5. Verdict (frozen decision table)

**Frozen verdict field: INFRASTRUCTURE_FAILURE** — the preregistered
validity floor (0.90) is breached on the PSB arm (37/44 = 0.841). The seven
breaching cases are model-side graph-format assimilation failures, not
plumbing faults; under the frozen wording they nonetheless cap the run as
"not a clean scientific result". The hypothesis gates are reported
separately and are unaffected by this label:

- **H_struct (structural binding)**: **REJECTED as a promotable candidate** —
  the regression gate fails (29.2% > 5%; even excluding the four format
  failures, 3/24 = 12.5% > 5%). As a *diagnosis* it is strongly supported:
  the entire H1 gain concentrates exactly where the hypothesis predicts
  (capacity 0% → 75%, exception-vs-condition → 100%, multi-clause → 87.5%),
  condition/actor/scope attachment F1 all rise, and on the 32
  H0-representable cases H1 ≈ H0 (71.9% vs 75.0%) — i.e. explicit binding
  fixes what the flat representation *cannot express*, while the graph
  format costs ~16% first-contact validity and 3 semantic regressions on
  what H0 already handled, on this frozen small model.
- **H_perm (permission gate)**: **SUPPORTED** — but redundant with the
  representation change itself on this benchmark.

**Terminal decision (protocol §62, hard stop): STOP standalone Policy
research.** No final holdout (not earned by the frozen promotion rule).
Outcome in the §52 sense: **POLICY_LIMITATION_CONFIRMED** — the Policy
semantic frontend remains imperfect; proceed to integration / composition
(Goal + Binder + Evidence + Temporal/Effects + Core) with the limitation
documented below, where the end-to-end effect of the parser error rate
(after abstention, UNKNOWN, certificates, independent witnesses) is to be
measured systematically per §53.

### Documented Policy limitation (for integration)

- Recommended frontend: **H0** (the frozen flat conservative parse). On this
  binding-heavy causal corpus it scores 75% on H0-representable cases and
  54.5% overall; on the PHV1 distribution it was 73.75% [63.2, 82.1]; on the
  controlled V5 dev distribution 95.77%. It cannot express per-clause
  modality/actor/gate divergence at all (0/12 capacity cases).
- Known failure modes to absorb downstream: invented PERMISSION under
  exceptive constructions (22.7% of cases here; 10% on PHV1), relation
  strength confusion (IF/ONLY_IF/UNLESS), cross-clause attachment, polarity.
- The PSB graph is a validated *diagnostic instrument* (binding metrics,
  0% invented permission) but not a deployable frontend at
  `qwen3.8-flash`-class capacity under the frozen one-parse protocol.

## 6. Research questions (§61)

- **Q1** relation binding as dominant PHV1-gap cause: **SUPPORTED** (gains
  concentrate in binding/capacity cohorts; attachment F1 rises).
- **Q2** explicit structure improves behavioral correctness: **MEASURED
  YES** (+18.2pp; CI [+0.0, +35.0]; p = 0.134 at n=44) — **GATED NO**
  (regression gate).
- **Q3** condition/exception attachment errors reduced: **YES** (cohort
  62.5% → 100%; EXCEPTION F1 0.923 → 0.929; CONDITION F1 0.706 → 0.863).
- **Q4** multi-axis improved: **NO** (75% → 50%; four graph-format failures).
- **Q5** gate removes invented PERMISSION: **YES** — and the representation
  alone already removed it (H1 = 0%).
- **Q6** correction precision of the structural layer: **0.682** (15:7).
- **Q7** regressions on H0-correct cases: **29.2%** (7/24) — gate failed.
- **Q8** generalization to a new prospective holdout: **NOT TESTED**
  (promotion not earned).
- **Q9** ready for integration: **YES, with documented limitation** (H0
  frontend; §5).

## 7. Discipline record

- Prereg gates, corpus, gold graphs, prompts, schema, compiler, gate marker
  classes, model/provider, retry policy, scorer: frozen before the first
  inference request; H0 byte-identity chain (C-ALR → PHV1 → PSB)
  machine-verified at freeze.
- Both arms sealed (`prediction_sha256`, `case_ids_sha256`,
  `gold_joined=false`) before any gold join; seals re-verified at scoring.
- One disclosed post-seal correction: the frozen runner's paired-statistics
  counter read the per-case row instead of its `correct` flag (0:0
  discordants in the first results file). Fixed and recomputed by
  `scripts/psb_causal_posthoc_rescore.py`, which re-verifies seals, gold and
  case hashes and records the superseded runner hash; predictions, gold and
  seals untouched. All numbers in this document are from the corrected
  rescoring.
- Terminology: prospective frozen holdout semantics respected; PHV1, V4, V5
  and this causal corpus are development data and were never used
  confirmatorily.
- No LLM judge anywhere; all classification is deterministic typed-field and
  triple diffing.

## 8. Historical separation (not a learning curve)

Arm C ≈78.1% (user-reported, absence-attested, different implementation) ·
H0-V5 95.77% (machine-verified, controlled dev distribution) · PHV1 73.75%
(machine-verified, prospective holdout, development evidence) · PSB causal
H0 54.55% / H1 72.73% (machine-verified, binding-heavy causal benchmark,
different distribution and purpose). These are separate
implementations/distributions and are never to be plotted as one curve.
