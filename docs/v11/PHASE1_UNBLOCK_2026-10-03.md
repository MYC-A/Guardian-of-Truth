# Phase 1: core unblock (bounded admissibility)

Branch `prod/phase1-admissibility-20261003`, based on `research/v11-universal-rescue-20261003@355948b5`.

## Changes
1. **Bounded Admissibility** (`policy_table_v11/admissibility.py`): verdict ADMISSIBLE / VIOLATION / UNKNOWN.
   Unresolved atoms are residual risk, not a blocker. UNKNOWN only when the step cannot be inspected.
   Enforcement modes STRICT / BALANCED / PERMISSIVE map verdict to ALLOW / REJECT / REVIEW
   (write verbs default to HIGH risk; override via `tool_risk`). Machine-readable audit trace
   (`trace_id`, policy hash, violated rule/clause quotes, argument, history snapshot hashes, latency).
2. **Fault-tolerant citations** (`citations.py`): `\s+` regex, typographic quotes, dashes, NBSP,
   zero-width chars, escaped line breaks. Casing/spelling never repaired; ambiguity still rejected.
   `admit_ledger` / `admit_lowerings` quarantine a single clause/obligation/lowering instead of the group.
3. **Typed atoms** (`compile.py`, `evidence_scope.py`): argument presence (`args.X exists`) is schema,
   never policy evidence. Obligations about user consent/supplied data require DIALOGUE_STATE scope
   (user turns only); scope inferred bilingually from obligation text when the ledger omits it.
4. **Bounded consent witness** (`consent.py`): beyond the exact certificate protocol, TRUE only if the
   latest assistant message asks for consent and names every non-enum argument value, and the very next
   user turn opens with an affirmation without negation/question. Explicit mismatched certificates are not rescued.
5. **Step router** (`router.py`): TOOL_CALL / PROSE / MIXED / EMPTY; prose never goes to the prover.

## valid.parquet (no LLM, no policy table, schema+provenance invariants only)
- Tool-call steps: 23/23 receive a verdict (0 UNKNOWN). 8 VIOLATION, all label 1 (precision 1.0).
- 12 erroneous calls are ADMISSIBLE at this layer: they need compiled policy atoms (Phase 2).
- Prose steps: 23 UNKNOWN by design (prose channel is Phase 3).
- Latency median 0.18 ms, max 3.3 ms per step.

**Dataset caveat:** in valid.parquet step type almost determines the label (prose 21/23 clean,
calls 20/22 with errors). Thresholds were not tuned to this; F1 on these 46 rows is not evidence of generality.
