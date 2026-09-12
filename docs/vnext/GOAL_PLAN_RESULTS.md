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
