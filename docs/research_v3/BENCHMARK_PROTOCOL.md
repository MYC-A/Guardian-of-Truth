# Research V3: frozen benchmark protocol (fixed before any model output was seen)

Base: `research/evidence-graph-probe-20261004` @ 1980776e (latest research HEAD on 2026-10-04).
Regression on base (sandbox, PYTHONPATH=src): 2307 passed, 15 failed, 3 collection errors.
Failures are artifact-hash integrity checks (`parsing.py:HASH_MISMATCH` etc., consistent with
line-ending normalisation from `.gitattributes` on checkout) and missing optional deps
(`experiments/searh_23/three_architectures/llm.py`). `tests/test_evidence_graph*.py`: 67/67 pass.

## Data
`experiments/research_v3/fixtures/build_benchmark.py` (deterministic, no model).
8 domain families x 11 controlled variants = 88 rows in competition row format
(`{id, prompt, response}`), gold kept in separate `*_gold.jsonl`.
Split by DOMAIN before any run: dev = asset, reservation, bank (33); sealed = inventory,
shipment, calendar, publishing, access (55). Sealed is not used for any prompt or parameter choice.

Variants / controls (PROMT.md section 10):
compliant(0), missing_check(1, J), check_is_target(0, A check vs execute), renamed_violation(1, B),
other_subject(1, D), other_object(1, D), negative_result(1, I/E), distant_exception(0, G),
exception_scope(1, F AND-scope), false_success(1, I text claim), preview_effect(0, C declared read-only
tool with action-like name). Balance: 7 positive / 4 negative per domain.

Known bias: the same agent wrote generator and methods; templates are shared across domains
(only wording, roles, tools differ). Results measure transfer across wording/tool names, not
across structurally new norm types. This is NOT a replacement for an externally authored holdout.

## Arms (same model, same seed, same rendering with code-issued S#/E# ids, same checker)
- A0 direct contextual judge (1 call); verdict taken as is, sentence-id validity recorded.
- A1r early full formalization REPLICA (inventory from policy+catalog without the conversation,
  cached per policy; judge stage sees only the inventory). Not the frozen EvidenceGraph code:
  the rows are format compatible so the frozen A1 can be run where its provider is available.
- A2 lazy: target-first discovery over full policy + full catalog (joint grounding), then
  formalization of only the candidate norms into code-checkable evidence atoms.
- A3 = A2 + independent target->policy pass that sees only the target declaration.
Evidence atoms are decided by code only (RESULT_FIELD with entity binds, ABSENT over the complete
visible history, verbatim USER_STATEMENT). Three-valued combination uses frozen
`guardian_truth.evidence_graph.logic`.

## Metrics
3-way exact; binary with UNKNOWN->0 and UNKNOWN->1 reported separately; per-control accuracy;
UNKNOWN rate; calls and provider tokens.
Model: free public endpoint text.pollinations.ai, alias `openai` -> gpt-oss-20b (anonymous tier).
