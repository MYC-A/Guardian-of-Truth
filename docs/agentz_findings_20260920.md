# Findings: C0 vs C3, notes investigation, hetero matrix (2026-09-20)

Agent line: research/agentz-c3-holdout-20260920. Pre-registration: docs/agentz_prereg_c0c3.md
(commit 6ff2404, BEFORE any full-set C3 run). All LLM = ministral-14b-latest (Mistral API),
evidence = ASP v2 + LangExtract text-acts; metrics reported STRICTLY SEPARATE per dataset.

## 1. Controlled C0 vs C3 comparison (frozen critic rules)

C3 = one anchored-critique pass over EVERY case (not only known false proofs), repaired
theory re-solved with identical evidence pipeline. Only the theory differs between arms.

| dataset        |  n | C0 F1  | C3 F1  | dF1     | FP_elim | TP_lost | FP_gain | UNRES C0→C3     |
|----------------|----|--------|--------|---------|---------|---------|---------|-----------------|
| synth-dev      | 120| 0.4421 | 0.1714 | −0.2707 | 11      | 15      | 1       | 0.708 → 0.917   |
| synth-holdout  |  40| 0.5714 | 0.1739 | −0.3975 | 4       | 8       | 0       | 0.625 → 0.925   |
| public46       |  46| 0.3226 | 0.2143 | −0.1083 | 1       | 2       | 0       | 0.826 → 0.891   |

**The 11/14 false-proof fix was selection-biased.** On the full sets the same critic
eliminates 16 false proofs but destroys 25 true proofs; UNRESOLVED share grows
everywhere. F1 degrades on all three datasets, including the independent holdout
(never used in any tuning), so this is not overfitting - it is a systematic property.

Mechanisms of TP loss (synth-dev, 15 cases):
- **M1 (4/15)**: repair adds semantically-correct but ontology-unencodable conditions
  ("successful get_balance", strict "before execution" order, actor roles) → conditions
  become unknown → proof of error is blocked. Criticism is RIGHT, ontology is too poor.
- **M2 (11/15)**: repair re-scopes/re-binds rules so they no longer match the encoded
  evidence facts (e.g., binds approval to a differently-named tool) → the proof is lost
  SILENTLY (unknown count unchanged). Criticisms are anchored in the POLICY, but the
  repair is anchored in NOTHING - no check that a repaired rule still points at the
  same evidence elements.
- 1 case of FP_gain: critic manufactured a new proof of error from an interpretation
  ("prohibition must be standalone") - proof gained from nowhere.

Conclusion: anchored critique is a precision-preserving but recall-destroying
component in its current form. It must not be applied symmetrically to all theories.

## 2. Notes investigation (LangExtract E1 + relevance probes; E2/GLM pending)

Method: per unresolved case, every unrepresentable_note is (a) labeled with claimed
capability (regex), (b) checked against RuleIR v2/v3 representability map, (c) verified
against the policy by LangExtract extraction (Mistral) with verbatim quotes, (d) probed
for decision relevance on the trajectory (deterministic: does the evidence touch the
element). Independent GLM extractor (E2) for dual confirmation is pending GLM API
recovery; current classes are E1-only.

| dataset   | notes | A ambiguity | B representable | C unrepresentable | D meta | decision-relevant | scoped-safe cases |
|-----------|-------|-------------|-----------------|-------------------|--------|-------------------|-------------------|
| synth-dev | 198   | 127 (64%)   | 40 (20%)        | 23 (12%)          | 8 (4%) | 67 (34%)          | 67%               |
| public46  | 215   | 153 (71%)   | 15 (7%)         | 41 (19%)          | 6 (3%) | 35 (16%)          | 50%               |

Reading:
- Notes are NOT noise and NOT hidden violations. Two-thirds are interpretive
  assumptions ("policy does not specify X; assumed Y") - they document the theory's
  reading, they do not carry checkable policy constraints.
- 7-20% claim unrepresentability that is FALSE for the v3 ontology (freshness,
  entity scope): pure LLM over-conservatism; these are free wins for a repair prompt.
- 12-19% are confirmed ontology gaps, dominated by strict temporal ordering
  (temporal_seq) and tool-result success status - exactly the capabilities needed to
  make freshness/actor rules fully checkable.
- **Certificate scoping**: PROVED_NO_ERROR may only ever mean "no violations of the
  REPRESENTED rules on THIS trajectory". 33-50% of note-blocked cases have NO
  decision-relevant unchecked semantics -> honest scoped certificates are possible
  there. The remaining cases must stay UNRESOLVED (or output a scoped certificate
  with an explicit unchecked-elements list). Absence of violations of represented
  rules is never claimed as absence of all violations.

## 3. Mistral↔GLM heterogeneity matrix (B architecture, public46)

| generator \ reviewer | GLM | Mistral |
|----------------------|-----|---------|
| GLM                  | 0.6909 | **0.6939** (B3) |
| Mistral              | pending (GLM API down) | 0.6471 |

GLM→Mistral (independent reviewer) beats both homogeneous cells. The missing
Mistral→GLM cell waits for GLM API recovery; per-case suspicion-level analysis
(independent vs self refutation of lost conditions / modality inversions) follows.

## 4. Infra findings (important for all agents)

- **max_tokens=2048 truncated theory JSON on real policies** (public46 prompts are
  40KB+): ALL 46 theories silently failed to parse ("theory_parse_failed"), producing
  a fake "C-line is inert on real data" result. Fixed to 6144. Any consumer of earlier
  public46 C-line artifacts from this branch must re-run.
- Background processes do not survive tool-call teardown in this sandbox; all runs are
  foreground-chunked workers with bridge-level cache resume (scripts/worker.py).
- GLM (z-ai-web-dev-sdk) hung repeatedly during this session; Mistral stayed healthy.
  GLM-dependent cells (E2 dual extraction, hetero cell Mistral→GLM) are queued.

## 5. Next steps

1. C3v2 pre-registration: critique + deterministic REPAIR VALIDATION - reject any
   repaired rule that (a) adds conditions the ontology cannot encode, or (b) no longer
   binds to the trajectory's evidence vocabulary (tools/fields present in the trace).
   Hypothesis: keeps most FP elimination, removes M1+M2 TP loss. Dev-tune on
   synth-dev, single confirm run on synth-holdout/public46.
2. Scoped certificates (notes A/B/C classes) -> no-error path for the E-cascade;
   never full "no violations" claims.
3. GLM recovery: E2 dual confirmation, hetero cell Mistral→GLM.
4. Full joint architecture E v2 with the above components.

## 6. C3v2 (pre-registered repair validation) - results

Validation rules V1/V2/V3 (deterministic, per-rule fallback to the original rule).

| dataset       | C0 F1  | C3 F1  | C3v2 F1 | TP_lost C3→C3v2 | FP_elim C3→C3v2 | rejections (V1/V2/V3) |
|---------------|--------|--------|---------|-----------------|-----------------|-----------------------|
| synth-dev     | 0.4421 | 0.1714 | 0.4130  | 15 → 2          | 11 → 2          | 111 / 78 / 6          |
| synth-holdout | 0.5714 | 0.1739 | 0.5556  | 8 → 0           | 4 → 0           | 41 / 29 / 2           |
| public46      | 0.3226 | 0.2143 | 0.3226  | 2 → 0           | 1 → 0           | 333 / 71 / 83         |

Validation removes the catastrophic harm AND the benefit. The 9 surviving false proofs
on synth-dev are undecidable at proof level: their sound repairs require
actor/permission/indirect-observation/temporal-precedence semantics the ontology does
not encode (V2 rejections). Critique-as-theory-rewriter is a wash; the critic's value
must come from ontology extension or from non-rewriting integration.

## 7. E v2 (joint architecture with scoped certificates) - results

Cascade: symbolic proof => 1; scoped no-error certificate (notes filtered by taxonomy:
A/D always, B trusted to encoded rules, C only if not decision-relevant) => 0; else
cached A0 judge. Composition variants (dev): judge 0.8163 | proof∪judge 0.7895 |
judge+coverage-cert-flip 0.8082 | hybrid 0.7815 - NO variant beats the judge.

| dataset       | judge F1 | E v2 F1 | sources (proof/cert/judge) |
|---------------|----------|---------|----------------------------|
| synth-dev     | 0.8163   | 0.7015  | 35 / 34 / 51               |
| synth-holdout | 0.8333   | 0.7391  | 15 / 10 / 15               |
| public46      | 0.7302   | 0.7000  | 8 / 3 / 35                 |

Certificate precision: ungated 0.62 (synth-dev), coverage-gated 0.89 (8/9 gold=0) -
but coverage-gated certificates almost always agree with the judge, so the net effect
is ~zero. Symbolic proofs (P≈0.6) unioned with a recall-1.0 judge only add FP.

**Unified conclusion**: the binding constraint of the whole symbolic line is THEORY
COVERAGE, not proof mechanics. The same missing capabilities (temporal_seq,
success_status, actor_role/permission, indirect observation) appear as (a) C3's M1
unencodable repairs, (b) C-class notes, (c) uncovered theories behind invalid
certificates, (d) the FP floor of proofs. Extending the ontology + theory prompt for
exactly these capabilities is the single highest-leverage next step; everything else
(repair, certificates, cascades) re-shuffles the same covered/vacuous boundary.

## 8. Notes taxonomy on synth-holdout (E1, independent set)

60 notes / unresolved cases: A 68%, B 18%, C 10%, D 3%; scoped-safe 68% -
consistent with synth-dev (the taxonomy generalizes beyond the dev split).
