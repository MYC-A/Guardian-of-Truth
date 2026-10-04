# Verified research transfer — 2026-10-04

This audit checks primary articles and publicly visible source, rather than
assuming that names in the task document imply ready-to-use libraries. No upstream
library code or model weights were copied. The proposed operations below are
research hypotheses; upstream task scores are not Guardian scores.

| Work and checked primary source | Specific operation worth testing | Boundary for Guardian |
|---|---|---|
| [Microsoft Fara verifier](https://github.com/microsoft/fara/blob/main/webeval/src/webeval/rubric_agent/mm_rubric_agent.py) | Dependency-aware criteria; distinguish process and outcome evidence | Criterion generation still needs semantic validation; a rubric is not a complete policy extractor |
| [MSS-Complement / SERBench](https://arxiv.org/abs/2609.20050), [resources](https://github.com/LordTARN1SHED/SERBench) | Select a set covering every known evidence group, instead of ranking individually similar passages | Unknown or omitted requirements cannot be recovered by set coverage alone |
| [S2G-RAG implementation](https://raw.githubusercontent.com/nianaaa/S2G-RAG/main/inference/inference_bm25.py) | `call_suff_gate_batch`, `extract_gap_items`, `build_query_from_missing`: typed missing slots direct retrieval | Gap generation is model-dependent; Guardian already has read requests; measure additional set-level utility |
| [GinSign](https://arxiv.org/html/2512.16770v1) | Input-defined predicate candidates followed by type-compatible argument selection | Assumes an accurate, fixed signature; the pilot uses source IDs, not an invented ideal ontology |
| [QA-SRL parser](https://github.com/nafitzgerald/nrl-qasrl) | Role questions can expose who/what arguments before binding | Ordinary sentence roles do not establish normative scope or tool effects |
| [ARTEMIS distinguishing traces](https://github.com/dmmendo/ARTEMIS/blob/main/dist_trace.py) | Find traces separating Boolean/temporal alternatives | A generated discriminator identifies disagreement; independent source-grounded gold is still needed |
| [ToolGuard review stage](https://raw.githubusercontent.com/AgentToolkit/toolguard/main/src/toolguard/buildtime/gen_spec_v2/stages/review.py) | Check omitted per-tool constraints and negative examples | Review is LLM reasoning; voting does not prove completeness |
| [AgentRx](https://github.com/microsoft/AgentRx), [AgentPex](https://github.com/microsoft/agentpex) | Step-level constraints and complete-trace diagnostics | Useful infrastructure, not independent guarantees of policy-to-API alignment |

The MSS paper reports set recovery on coding-agent states. S2G-RAG's code runs a
sufficiency gate over accumulated evidence, parses structured gaps, and appends
gap fields to retrieval queries. Its query builder limits missing groups to a
small prefix; Guardian must retain unresolved groups when budgets end. The pilot
therefore does not import a general RAG stack for this already available operation.

GinSign's article explicitly conditions grounding on a supplied system signature
and notes constant binding and signature size/update limitations. The article and
its reference links checked here did not identify a verified public official
checkpoint/implementation for its learned grounder. This is **not** a claim that
none exists; no such artifact is used in the experiment. Signature classification
cannot replace the unmeasured acquisition of the signature itself.

The Fara module includes separate dependency review and evidence interpretation.
Our inference is to preserve dependencies in local requirements and to avoid
equating criterion visitation with norm completeness. Source-ID addressing,
native argument joins and chronological checks are repository mechanisms, not
claims of reproducing any of these articles.

## Already-tested mechanisms retained as negative evidence

The original methods review and `limits_probe.json` already demonstrate that
roundtrip consistency can preserve an incorrect action/scope. No fresh model
roundtrip is needed to establish that logical limitation. System V2's action
inventory and compositional arms previously lost shared predicate context.
Neither a new name for decomposition nor additional LLM calls establishes an
improvement. The frozen A2/A3 pilot is designed to measure this question directly.

## What is actually implemented

A2/A3 preserve the full catalogue and policy at lowering, source candidates remain
pending before target-specific trees, and A3 returns to original source without
seeing the forward interpretation. Native comparisons and tree evaluation reuse
the existing runtime. A5 grouped evidence planning and A6 falsification should
remain separate diagnostics unless pilot failures justify activating them.
