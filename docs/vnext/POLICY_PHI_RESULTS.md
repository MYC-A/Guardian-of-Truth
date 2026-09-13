# Policy / Φ program v1 — completed observed-development regression

Authoritative machine results: `outputs/vnext/policy_programs_v1_results.json`,
`policy_programs_v1_failure_audit.json`, `policy_programs_v1_artifact_audit.json`
and `policy_phi_results.json`. All 104 previously observed Policy Semantics V2
cases were predicted and sealed before their closed-world behavioral programs
were scored. The post-run audit validates all frozen source/input hashes, the
prediction seal, all 104 case rows and 312 physical request/result links; its
status is `INTEGRITY_VALID`. One admitted request has an explicitly unknown
remote outcome and was not automatically retried. This is artifact integrity,
not semantic correctness or whole-Core proof.

| Measure | Native multi-hypothesis Φ | Fixed P1 |
| --- | ---: | ---: |
| Accepted candidate behaviorally correct | 61 / 265 (23.0%) | not applicable |
| Fully eligible cases | 60 / 104 | 54 / 104 |
| At least one correct candidate on eligible cases | 28 / 60 (46.7%) | not applicable |
| Every candidate correct on eligible cases | 2 / 60 (3.3%) | not applicable |
| Strict all-candidate operational yield | 2 / 104 (1.9%) | not applicable |
| Correct behavior on schema-valid cases | not applicable | 29 / 54 (53.7%) |
| Physical requests / transport successes / schema-valid | 208 / 202 / 155 | 104 / 104 / 54 |
| Reported model tokens | 512,936 | 78,790 |

On the 29 cases where both native and P1 meet the paired eligibility rule, the
native *all-candidates-correct* rate is 48.3 percentage points lower than P1's
single-program correctness. That paired subset is small and selected by schema
success; it is not a generalization estimate. The P1 prompt, schema and semantic
arm are the frozen Cycle 2 baseline, but the shared run used a declared transport
envelope of 2,048 output tokens and 10-second request spacing rather than its
original 1,024/5 configuration. No original-transport-equivalence claim is made.

All 104 cases remain `OPEN_SEMANTICS`: no authoritative whole-policy meaning
universe was supplied. Challenger passes added 127 distinct candidates in 65
cases, but this only shows discovery, not coverage or correctness. Nine cases
have no accepted native hypothesis, 44 have a native frontend failure and 95
retain unresolved terms. Full interpretation recall and unsupported-reading
rate are **NOT_ESTABLISHED**; the benchmark scores world behavior, not whether
every alternative is a reasonable reading of unrestricted language.

The per-case taxonomy records 104 POLICY_COVERAGE, 98 POLICY_GENERATION,
72 SCHEMA and 5 TRANSPORT components (overlapping). Combined transport is
306/312; combined schema validity is 209/312, leaving 97 invalid schemas.
Native request latency p50/p95 is 32.71/114.99 seconds; P1 is 7.83/13.88
seconds. Combined reported tokens are 591,726. Cost is `NOT_AUDITED` because
no billed-price basis was verified. These figures are per physical request,
not per case.

The tested Φ program candidate is **not admitted** as an improvement over P1.
It overgenerates behaviorally wrong alternatives and is substantially less
schema-reliable under this provider; a correct candidate among wrong ones
cannot be selected by confidence without abandoning all-world semantics.
Do not patch this frozen version from its 104 seen labels. A later version
would need a distinct hypothesis, better constrained grounded generation and
new frozen evaluation; Policy v1 and Goal v2 results stay immutable.

This stage did not evaluate Goal/Plan v3, Claim Graph conjunction, Tool effects,
certified Core verdicts, the new blind holdout or end-to-end gain. In particular,
`OPEN_SEMANTICS` and a good P1 behavior score do not prove NO_ERROR.
