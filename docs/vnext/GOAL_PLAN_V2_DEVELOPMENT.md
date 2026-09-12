# Goal/Plan v2 development boundary

This is a new development version after the immutable Goal/Plan v1 failure audit.
It is not an evaluated candidate and is not wired into the frozen Claim Graph v1
job or the current Core certificate format. Production and Cycle 2 are unchanged.

## What changed

`goal_native.py` uses deterministic IDs for the declared goal, every ordered plan
step and every literal scope group. Source offsets are calculated by code; the
model selects IDs rather than generating offsets or paraphrased expected actions.
Every scope group retains all permitted values. History and target content remain
untrusted data, not replacement instructions or evidence of completed steps.

One bounded reading-inventory task is followed by seven narrow field tasks and
one extra-constraint task. Failed fields do not remove readings. Duplicate IDs,
missing goal grounding, terminal/action conflicts, omitted scopes and invalid
clause arities keep their diagnostic and OPEN_SEMANTICS status. Even a successful
parse is only EMPIRICALLY_COVERED, never closed because its output schema is finite.

Plan steps, order, scope and conditional constraints have separate typed records.
They are not stored as policy antecedents. IF means condition implies required
action; ONLY_IF means action implies necessary condition; UNLESS means absence
of the exception implies prohibition, not that the exception mandates the action.

`goal_formula.py` lowers these records into a small four-valued formula language.
Each leaf requires a separately grounded ProofAtom and the evidence prover.
An LLM expected-step index does not establish the active step. Scope applicability
is separate from argument compliance. Order requires prior completed-action
evidence and an exact later invocation; a user completion cannot silently be
credited to the assistant. Missing material bindings remain UNKNOWN even when
a partial implication could look vacuously satisfied. Multiple bindings must be
enumerated by the caller, never selected by confidence.

NO_EXTRA_CONSTRAINT is an empty additional obligation, not a proof that all
possible obligations were discovered. The compiler never raises semantic
coverage above EMPIRICALLY_COVERED. A future NO_ERROR path still needs independent
authoritative closure and evidence-completeness checks.

`semantic_v2.py` distinguishes invalid JSON from structural schema failures,
including required fields, types, enums, cardinality, bounds and duplicate items.
Diagnostics contain fixed codes and schema-owned paths, not model values or
unknown property names. Transport and schema failures stay separate. Sequential
requests and the ten-second start interval remain; no hidden retry is introduced.

## Still required before a v2 evaluation

- Ground plan progress, action meaning and scope applicability from actual source
  and evidence; unsupported business/action mappings must not be guessed.
- Enumerate admitted goal/policy/binding worlds and integrate the new formula
  language with an independent certificate checker, not merely the old solver.
- Preserve all policy exceptions and open-vocabulary ambiguity.
- Freeze the new frontend, prompts, schemas, proof format and scorer before any
  v2 model-stage evaluation. Keep v1 results and exact source provenance intact.
- Evaluate provider reliability on the full new task schemas, not only toy tasks.

Unit tests check contracts, failure preservation and all four-valued conditional
pairs. They do not establish semantic accuracy, runtime improvement, a resolved
end-to-end fraction or any gain on the untouched blind holdout.
