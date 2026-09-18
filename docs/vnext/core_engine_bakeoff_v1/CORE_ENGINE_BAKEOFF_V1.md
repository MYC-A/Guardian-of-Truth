# CORE ENGINE BAKE-OFF V1 — final report

Branch: `core-engine-bakeoff-v1` (experiment; not merged anywhere)
Base: `4e6d200` (semantic_pipeline_v1 final commit, branch codex-update-run tree)
Completed: 2026-09-19 (interrupted 2026-09-18 session finished: environment rebuilt
in a fresh container, all suites re-run from scratch, artifacts consolidated, committed).

## 1. Question

How much of the custom Guardian Core (procedural Python evaluation of worlds,
conditions, obligations, consensus) can be replaced by mature rule/logic engines
WITHOUT renegotiating Guardian evidence semantics — where "semantics" is fixed by
the NeutralCoreInput reference contract (four-valued evidence, attempt/completed
split, staleness, absence-proof premises, claim≠evidence, per-interpretation
worlds + cautious consensus)?

Candidates: current Core (baseline) · Clingo/ASP · s(CASP)/SWI-Prolog ·
Drools/KIE · Soufflé (provenance probe only, per directive).

## 2. Method (soundness fences)

* **NeutralCoreInput** — the ONE neutral input: facts (ACTION_ATTEMPTED /
  ACTION_COMPLETED / ACTION_FAILED / STATE_OBSERVATION / FIELD_VALUE / EFFECT /
  CLAIM / ENTITY / RELATION), interpretations (already-formalized FORBID /
  REQUIRE / BEFORE / AFTER / ONLY_IF / UNLESS / comparisons / counts / AND-OR-NOT
  condition trees), evidence status, uncertainty, source refs, content hash.
  Engines start AFTER semantic interpretation; no engine parses English.
* **Gold firewall** — labels never enter NeutralCoreInput; all 43 scenarios are
  synthetic with machine-checkable oracles (expected final, expected worlds,
  expected primitives).
* **Evidence semantics safety fence** (each backend must prove it natively or
  abstain): ATTEMPTED≠COMPLETED, FAILED≠SUCCESS, UNKNOWN≠FALSE, NOT_FOUND≠ABSENT,
  HISTORICAL≠CURRENT, CLAIM≠observation, absence refutes only under explicit
  history_complete/known-actors premises.
* **Prover=checker discipline**: backends re-derive world verdicts from the same
  serialized facts; classification of mismatches (ENGINE_SEMANTIC_MISMATCH /
  ADAPTER_BUG / UNSOUND_NEW_ENGINE / CURRENT_CORE_LIMITATION) is automated in
  runner.py.

## 3. Results (re-run 2026-09-19, fresh container; identical to 2026-09-18)

| backend | final | worlds | primitives | unsound verdicts |
|---|---|---|---|---|
| current Guardian Core (B3/FULL_SEMANTICS) | 27/43 | 30/46 | 47/58 | 0 (16 honest CURRENT_CORE_LIMITATION abstentions) |
| Clingo 5.8.2 | **43/43** | **46/46** | **58/58** | 0 |
| s(CASP) 1.1.4 (SWI 9.2.9) | **43/43** | **46/46** | **58/58** | 0 |
| Drools 10.2.0 (KIE, JRE 21) | **43/43** | **46/46** | **58/58** | 0 |

Brave/cautious-vs-consensus equivalence (Clingo): EQUIVALENT on all 43 scenarios
(required consensus = cautious consequence of violation; tested, not assumed).

The 16 incumbent abstentions concentrate in exactly the families the engines
evaluate natively: numeric comparisons, cardinality (#count), disjunction/nested
trees, value-typed state exceptions (latest/superseded/conflict/staleness).

Scaling (2-core sandbox, subprocess startup included):
events 100→10k: current 0.01→5.1s; clingo 0.01→0.9s; rules 1→100: clingo
0.01→0.07s; s(CASP) ~2.2→35.8s (one process per query — F2 below); Drools
~3.6→4.5s (one JVM per case, flat). Full numbers: outputs/core_engine_bakeoff_v1/performance.json.

## 4. Engine capability findings (details: engine_capabilities.json)

* **Clingo** — full candidate. Choice rules give one stable model per
  interpretation (replaces manual Cartesian world enumeration); recursion folds
  condition trees natively; #max/#count handle staleness and cardinality;
  brave/cautious from the model set. Danger fenced: default negation is
  closed-world, so all refutation is EXPLICIT (sup/ref facts) and absence-derived
  refutation exists only under recorded premises.
* **s(CASP)** — full candidate with a unique differentiator: justification trees
  per query (scasp/2 with tree/1). Costs: six documented engine findings —
  dual-generation over fact joins diverges (F1), not re-entrant (F2), no `;` in
  bodies (F3), negated predicates must be defined single-clause (F4), contiguous
  clauses (F5), facts-before-rules (F6) — so evidence joins are enumerated by the
  adapter as ground markers while s(CASP) keeps the semantic layer.
* **Drools** — full candidate via declared fact types + programmatic
  KieFileSystem on a bare JRE (single-file source launcher; no javac/maven).
  No answer sets: worlds/consensus fold in the harness. `not exists` is hard
  closed-world — absence rules are only generated under complete-history
  premises (structural gate).
* **Soufflé** — probe only: recursive Datalog + `--provenance` explain() works
  (0.02s); no disjunction/choice semantics and no four-valued truth — future
  provenance/certificate accelerator, not a core replacement.

## 5. Real-46 replay — deferred (deliberate)

The planned real-case replay (outputs/.../real/frozen_core_inputs + raw_predictions)
is superseded by the follow-up experiment **full-architecture-v1** (new directive),
which replays all 46 real cases across the full arm matrix N0..N5 including
Clingo-backed cores, with the same gold firewall and frozen-cache discipline.
Duplicating it here would run the same pipeline twice with no additional evidence.

## 6. Conclusion

The incumbent Core's *semantics* survived every engine port intact (zero unsound
verdicts anywhere), while its *mechanisms* (world enumeration, condition
evaluation, comparison/cardinality plumbing, consensus folds) are fully
replaceable: Clingo, s(CASP) and Drools each answered 43/43 with native engine
features. Recommended engine for the full architecture: **Clingo** (answer sets =
worlds; cautious consequences = consensus; smallest adapter; best scaling).
s(CASP) justification trees are the best human-audit story and the natural
certificate witness generator. Drools is viable where a JVM stack already exists.

Artifacts: outputs/core_engine_bakeoff_v1/{synthetic_results.json,
performance.json, engine_capabilities.json, environment.json, souffle_probe.json}.
