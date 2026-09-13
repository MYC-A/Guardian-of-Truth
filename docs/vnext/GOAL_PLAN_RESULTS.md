# Goal/Plan — frozen development v1

Source of truth: outputs/vnext/goal_plan_v1_results.json.
Implementation: a8d7678, with its full hash in the pre-request freeze.
All 22 frozen cases were predicted and separately hash-sealed before scoring.
There are only 11 independent semantic inputs: context_variant alone duplicates
context. No blind cases or labels were opened.

## Reliability and semantics

Transport: 22/22. Schema-valid: 15/22 (68.18%); seven failures are schema errors,
not semantic false negatives or transport failures.
The invalid completion text was not retained by the v1 backend, so the exact
JSON/schema violation cannot be reconstructed. No claim of a truncation or quota
cause is established; failed completions used fewer than the 2048-token ceiling.

Conditional field scores use 15 schema-valid cases and 28 accepted readings.
Grounding rejected all readings in four additional schema-valid cases; those
cases remain in the eligible-case denominator, not silently dropped.

| Field | Candidate precision | All-candidate case accuracy |
| --- | --- | --- |
| Source goal fidelity | 28/28 = 1.000 | 11/15 = 0.733 |
| Expected step | 25/28 = 0.893 | 9/15 = 0.600 |
| Expected action | 13/28 = 0.464 | 4/15 = 0.267 |
| Allowed scope | 24/28 = 0.857 | 9/15 = 0.600 |
| Drift label | 6/28 = 0.214 | 2/15 = 0.133 |

These are predeclared exact normalized field matches, not independent semantic
equivalence adjudication. A plausible paraphrase may fail exact action matching.
Drift labels proposed by an LLM are not evidence of behavioral violations.

## Checked behavior

PROVED_ERROR = 0; PROVED_NO_ERROR = 0; UNRESOLVED = 22; INCONSISTENT = 0.
Core resolution = 0%; unresolved = 100%. No definitive certificates were produced;
their validation rate is null, NOT 100%.
Primary reasons: GOAL_PLAN_AMBIGUOUS = 15, SCHEMA_ERROR = 7.

On the 20 binary-annotated cases, vNext and fixed X0 both have
TP=0, FP=0, FN=18, TN=2, precision=null, recall=0, F1=0, balanced error=0.5.
Two gold-UNRESOLVED cases are excluded from binary scoring.
Every vNext binary zero is a declared competition fallback, not proof of safety.
There is no measured downstream gain in this stage.

## Failure audit and next-version candidates

Immutable per-case taxonomy: outputs/vnext/goal_plan_v1_failure_audit.json.
The schema boundary and loss/rejection of candidate grounding precede solver
evaluation. Accepted readings also encounter unsupported operational obligations:
v1 treats goal constraints as textual conditions and cannot compile them.
The current proof engine cannot establish behavior when these material mappings
remain unbound; this is not evidence that the solver chose a wrong proof.

Before another version: add value-free schema-violation diagnostics; decompose
Goal/Plan semantic generation into smaller source-ID-grounded passes; represent
plan constraints separately from policy conditional antecedents; compile all
clauses with preserved ambiguity instead of dropping unsupported conditions.
The v1 report, prompts, code snapshot and annotations must remain unchanged.
Exact source bytes were archived and checked against every pre-request source
hash in goal_plan_v1_source_archive.json, so a legitimate new-version repair
does not silently replace the implementation behind these v1 results.

Latency p50=14383.362 ms, p95=18214.728 ms; reported tokens=37173.
Cost NOT_AUDITED. The earlier simple provider gate did not establish reliability
for this larger multi-hypothesis schema. Blind admission is NOT_ESTABLISHED.

## Native v2 — separately completed experiment

Source: `outputs/vnext/goal_plan_v2_results.json`; implementation
`a9150076a445d7cf86eac70500aa259f058a9209`. All 22 predictions were sealed before
scoring; 113 frozen sources have an exact byte archive. v1 results above are unchanged.

| Field | Exact candidate accuracy | All-candidate case accuracy |
| --- | --- | --- |
| Declared goal source | 58/77 = 0.7532 | 12/20 = 0.6000 |
| Expected step | 48/81 = 0.5926 | 8/21 = 0.3810 |
| Expected action source | 29/81 = 0.3580 | 2/21 = 0.0952 |
| Allowed scope sources | 74/81 = 0.9136 | 18/21 = 0.8571 |
| Drift type | 24/77 = 0.3117 | 0/20 = 0 |

Conditional denominators exclude failures of the relevant narrow field task,
not all cases with any failed request. Expected-step matches are annotation
proxies, not evidence of active plan progress. v1 field metrics have different
definitions and must not be treated as directly interchangeable.

Goal-layer: 22/22 UNRESOLVED; zero definitive verdicts/certificates; validation
rates null. Transport=190/190; schema=176/190; tokens=361883; cost NOT_AUDITED;
latency p50=14123.487 ms, p95=39617.261 ms. Diagnostic binary TP=0, FP=0, FN=18,
TN=2, F1=0, identical to X0 on 20 annotated cases; unresolved=100%.

Full audit precedes next-version fixes: GOAL_PLAN_SEMANTICS affects 22 cases,
EVIDENCE_COMPLETENESS 21, SCHEMA 12 (overlapping). Extra-constraint requests cause
11 of 14 schema failures. Supplementary receipt audit: 19 raw declared-goal nulls,
zero parser-changed values. No parser-loss/truncation cause is asserted. No fresh
activation fabricated, no blind gold read, no downstream gain established.
Goal v3 is a separate hypothesis in GOAL_PLAN_V3_DESIGN.md; v2 remains frozen.
