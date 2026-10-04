# Completion and validation audit

This completes the bounded mechanism research, not the proposed full Guardian
architecture. The inference protocol was committed at `2a2fe963` before the first
new call. Final diagnostics use separate modules/contracts; frozen requests,
raw replies, predictions, official gold and historical experiments are retained.

## Requirements and evidence

| Requested work | Completed evidence | Practical limit |
|---|---|---|
| Independent worktree and research branch | Base `6035918c`; branch `research/hybrid-mechanisms-v1-20261004` | Production/source graph remains unchanged. |
| Historical raw/code/metric audit | REPOSITORY_AUDIT.md; DECISION_CONSISTENCY.md; original Telecom raw replay | A/C inversion is in model JSON; internal generation cause is unobserved. |
| V4 alternative mandatory-process contract | Retained research_v5/binary_audit sidecar and binary-method audit | Six changed labels are an alternative full-journal contract, never a changed original gold or model improvement. |
| Known valid46 diagnosis and R0 feasibility | valid46_baseline_replay.json; retained network-disabled R0 valid46 run | OR F1=0.8889; sealed160 F1=0.9714 is a different dataset. One-shot raw per-row snapshot was not recovered. |
| Seven competing hypotheses | HYPOTHESES.md | Includes alternatives and refutation criteria; selection of I4 was fixed beforehand. |
| Decision-order/label factorial | 16 calls, two providers, two original cases, I1-I4 | One reply per cell; repeated cases are not independent holdout examples. |
| Source-equivalent second model | Actual IDs and provider preflight; preserved request/source seals | Mistral JSON schema vs Gemma JSON-object transport; provider modes differ. |
| Separate reasoning and decision | Two Stage A and two Stage B calls; code_adapters | Stage A omits the decisive prohibition; model B independently reinterprets original sources. |
| Paired code facts K0/K1/K2 | CODE_FACTS.md; exact I4 reuse; four added calls | K1 repairs one admission, no raw binary error; K2 adds uncertainty. |
| Paired contradiction C0/C1/C2 | CONTRADICTION_REVIEW.md; four added calls | Citation metadata is potential mismatch, not certified semantic contradiction. |
| Bounded one-shot/iterative retrieval | RECURSIVE_RETRIEVAL.md; retained gap plan/controller/trace | R1 plan rejected before reads; working recursion NOT_TESTED, not disproved. |
| Simpler coverage comparator | Eight original reads; coverage_final raw/controller | Finds early h10 and correct cause; no binary-label gain over R0. |
| Conditional consistency and proof | CONSISTENCY_GATE.md; gate; oracle_supported_proof.json | V1 zero flags, V2 zero calls; V3 requires independent source qualification. |
| Additional whole-move and negative controls | Original multicall/Silver fixtures; two extra calls | Missed payment fields and invented consent expose limits; no generalization claim. |
| Genuine exception and early/late audit | explicit_exception_offline_audit.json | Four-request local permission, 209843-character evidence distance; another reason-code issue prevents whole-move compliance certification. Zero inference. |
| Long original context access | long_context_access_audit.json | Full/index/graph availability compared offline; model-quality comparison NOT_TESTED. |
| Literature and implementation research | EXTERNAL_RESEARCH.md | Nine requested primary works plus related work; foreign task scores are not Guardian F1. |
| Separate binary/causal/admission metrics | controlled_scores.json; causal_annotations.json; per_call_matrix.json; target_norm_coverage_audit.json | Technical labels are null; semantic UNKNOWN=0 explicitly; targeted critical-norm audit is not exhaustive policy recall. |
| Exact budget, transport and provenance | ledger.json, requests, raw, protocol.json | 34 attempts/217722 tokens; no retries, unknown usage, hidden clipping or extra weights. |
| Required ten reports and fifteen answers | Ten named reports; FINAL_ARCHITECTURE_EVIDENCE.md | One recommended minimal flow with component statuses; full implementation outside task. |
| Reproducibility and independent review | offline_replay.json; server_offline_replay.json; final_code_review.json; completion_code_audit.json | Replay and tests establish the measured mechanics, not absence of every bug or semantic reliability. |

## Verification

The complete relevant regression selection passed: **205 tests**. It combines
the 86 focused research tests with existing graph, ranked search, quote adapter,
provenance, process/role-grounding and Telecom recovery checks. No HTTP inference
is performed by these tests. The code reviewer independently passed the focused
86-test selection. No code was changed after this selection; subsequent edits
add analysis artifacts and documentation only.

```powershell
$env:PYTHONPATH="$PWD;$PWD\src"
$env:PYTHONIOENCODING='utf-8'
python -m pytest -q tests/test_hybrid_transport.py tests/test_hybrid_logic.py tests/test_hybrid_packets.py tests/test_hybrid_fenced.py tests/test_hybrid_guarded_plan.py tests/test_hybrid_metrics.py tests/test_evidence_graph.py tests/test_evidence_graph_ranked_search.py tests/test_evidence_graph_quote_adapter.py tests/test_provenance.py tests/research_v5/test_process_grounding.py tests/research_v5/test_native_role_grounding.py tests/telecom_causal_recovery/test_recovery.py
python -m experiments.hybrid_mechanisms.runner replay
python -m experiments.hybrid_diagnostics.fenced_replay
python -m experiments.hybrid_diagnostics.metrics
```

Use the prepared Python environment described in RUNBOOK.md. The first replay
verifies frozen hashes, exact retained request/raw bytes and prediction derivation;
the later diagnostics preserve the original predictions. Mistral and Gemma
metadata are cached; offline operations require no credential or provider call.

The original frozen scorer also pools extra I4 cases with the two-case factorial.
Its retained output is historical. `controlled_scores.json` explicitly separates
EXTRA_I4 and gives null full-subset F1 when a technical admission fails. Conditional
F1 always carries its admitted denominator. There is no new all-valid46 inference
score, independent holdout result or population improvement estimate.

## Stop decision

The two unused request slots are not permission to retry the rejected planner
or fabricate a V2 candidate. Those branches are retained as failed/skipped under
the frozen protocol. A repaired recursive experiment or broader test needs a
new protocol and separate results. The next proposed prototype uses originals,
generic coverage, small code facts and one semantic reviewer; compulsory norm
compilation and extra reviewers are not supported by this measured cost/benefit.
