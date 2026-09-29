# Integration v1: inspect interfaces before trusting composed verdicts

Branch: `codex/integration-research-20260929`. Research only; `scripts/predict.py`
and existing frozen inference records remain unchanged.

Imported research:

- Step 1 / IE: `df4f9508` (includes `092896d7`).
- Step 2: `921f4437`.
- Generality join design: inspected at `529b338d`; its lexical effect classes
  and permission-to-mandate inference are not imported as authoritative facts.

## Phase 1: deterministic interface audit

`frozen/audit_controls.json` is committed before running its audit. These are
author-written development controls, not an independent generalization test.
Evaluate two boundaries, without network, GPU or model calls:

1. Step 1 event compatibility must preserve distinct explicit objects/occurrences.
2. Step 2 copying a real result value/path must not establish an arbitrary
   business predicate, execution strength, trusted authority, or entity binding.

Report each case and retain the old metrics. In particular, the existing Step 2
scorer accepts predicate **OR** provenance-path agreement and counts strength
errors separately. Its WorldFact precision is not semantic-predicate precision
and cannot serve as a gate for the composed detector.

## Phase 2: integration boundary

Reuse transport events, exact source paths, the append-only Step 2 ledger and
as-of queries. Keep observations separate from semantic world facts. A raw field
report must have producer scope and cannot mean a named action completed merely
because its value is `completed`. Semantic mapping needs a separately supplied,
version-bound contract; model-proposed bindings remain hypotheses.

Add strict scoring: predicate, entity, value, strength, time and provenance must
all agree; one prediction cannot earn duplicate gold credit. Preserve legacy
scores as source-observation diagnostics.

For Step 1, retain successful endpoint certificates as proposals and add an
explicit-identifier veto before action compatibility. No new domain/action
dictionaries. UNKNOWN never authorizes a merge or a negative fact.

## Next validation gate

After interface controls, freeze new integrated trajectories with wrong-object,
wrong-amount, check-versus-action, async, status collision across producers,
stale/revoked state, result-before-action cutoff and permission-versus-obligation
contrasts. Compare legacy and guarded arms. Separately report oracle-contract
coverage and automatic-mapping coverage; do not call contract-assisted success
an automatic policy compiler. No tuning after opening the next sealed results.
