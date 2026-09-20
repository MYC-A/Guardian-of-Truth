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
