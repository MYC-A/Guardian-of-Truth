# Modular hybrid call paths (2026-10-01)

This map distinguishes code that runs in the service from isolated helpers.
`ORIGINAL` means pre-existing on the source branch, `ADAPTED` means connected
or corrected here, and `NEW` means introduced here. A source quote validates
provenance; it does not validate a model's interpretation.

| Step | Module / status | Consumer in evaluated run | Output and limit |
|---|---|---|---|
| 1: policy | `three_architectures.common` catalog/policy split, ORIGINAL | `structural_v02.parse_case_v02` → `service.runtime.check` | Lossless raw policy and catalog for the base path; no complete semantic rule parse. |
| 1: policy | `modular_helpers.policy_surface_graph`, NEW | `advisory_for` → `judge.build_judge_user` when config advisory is `gp` or `ge_gp` | Exact clause quotes, offsets, lexical markers and tool mentions. Status `SURFACE_ONLY`; cannot establish action scope or exception logic. |
| 1: policy | `semantic_pipeline_v1`, GRS/typed formal frontends, ORIGINAL | **Standalone** in this branch | Candidate formal interpretations only; no production certification or judged arm yet. |
| 2: observations | `guardian_truth.parsing.parse_events` → `provenance.build_graph`, ORIGINAL | `modular_helpers.evidence_subgraph` → judge prompt when GE enabled | Mechanically extracted result values, entity keys, chronology, source offsets, positive and negative argument links; missing evidence never proves error. |
| 2: effects | `v2_boundaries.acquire_documented_v2`, ADAPTED | **Standalone** regression suite | Separates model proposed `AUTO_VERIFIED` from application structured `DOC_EXPLICIT` per producer. No service path currently consumes contracts. |
| 3: target | `structural_v02.parse_case_v02`, ORIGINAL | All service configs | Target calls, catalog/schema checks, neutral suspicions. Confirmed structural hits can decide ERROR; clean scan is UNKNOWN without model. |
| 3: target | `three_architectures.judge.ask_vote`, ADAPTED prompt | `runtime._judge_stage` | Target response quote must be verbatim; technical invalid answers get one re-ask. Advisory GE/GP never replaces original text. |
| 3: checker | MiniCheck, corrected FactCG, Granite BYOC native, ADAPTED | **Smoke only** | No specialist has yet been wired to an end-to-end candidate bank. The 15-case results are adapter checks. |
| 4: verdict | `service.runtime._judge_stage`, ADAPTED | `runtime.check` → HTTP/CLI | Single judge or V6 routing; model verdict has `JUDGED` findings, not formal proof. API supports ERROR/NO_ERROR/UNKNOWN and degradation. |
| 4: formal | `guardian_truth.formal_reasoning`, `semantic_pipeline_v1.phi`, ORIGINAL | **Standalone** | Solver can evaluate a supplied interpretation; completeness/correctness of NL→Φ remains unproved. |
| 4: refusal | `v2_boundaries.validate_goal_v2`, ADAPTED | **Standalone** | Empty candidate list is not exhaustive. There is no service level reachability certificate yet. |

The new G0/G1/G2/G3/G-plain configs compare only advisory *presentation to
the same Gemma judge*, with the same raw source and structural gate. GP in
those configs is surface structure, not full semantic GP; Φ and specialist
checker arms require separate integration and must not be inferred from G3.

Call path for the current graph arms:

`HTTP/CLI → GuardianServiceRuntime.check → parse_case_v02 → structural hit? → advisory_for(config) → judge.build_judge_user(raw + advisory) → ask_vote/validate_vote → _judge_findings → JSON/audit`.

The comparison runner (`campaign.py`) uses the same `GuardianServiceRuntime`
and frozen config files. It never reads gold. `score_campaign.py` refuses to
open gold until all planned predictions are complete and checks the frozen
hashes. Checkpoints and per-case records live outside the repository on the
Vast instance, under `/workspace/guardian/results/hybrid_campaigns/`.
