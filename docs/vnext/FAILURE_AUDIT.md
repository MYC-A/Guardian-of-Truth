# vNext failure audit — current frozen evaluations

The cycle is incomplete. This is not the final blind audit or promotion decision.

Offline T1 v1: 16 applicable fixture cases exact, two missing-contract cases
NOT_APPLICABLE_T1; real-tool generalization/downstream gain NOT_ESTABLISHED.
See TOOL_SEMANTICS_RESULTS.md and its frozen per-case report.

Development provider gate v1: four repeated controlled task families, 12/12
transport/schema/semantic checks; zero classified failures.
See outputs/vnext/provider_gate_failure_audit_v1.json.
This did not prove reliability for the full Goal/Plan schema.

Goal/Plan v1: all 22 controlled cases completed; 7 schema errors, 15 schema-valid
cases, no definitive Core decision. The immutable case taxonomy links original
expected and actual Core statuses, blocked hypotheses, reasons and rejected
operational mappings. Source: outputs/vnext/goal_plan_v1_failure_audit.json.
Expected-action/drift mismatches, unsupported constraint lowering and candidate
source-grounding rejection are distinct from transport. See GOAL_PLAN_RESULTS.md.

Suggested repairs are next-version candidates only. No frozen v1 result,
prompt, benchmark or decision mapping was modified after the result.
Claim, policy, T2/binding semantic stages, dev ablations and blind failure audit
are still pending. Definitive-error/no-error correctness is not inferred from
binary fallbacks, and missing results are not replaced with theoretical gains.
