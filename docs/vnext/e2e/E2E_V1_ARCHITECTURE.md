# E2E V1 — Architecture (frozen at 4d7fdfb)

## 1. Overview

Guardian E2E V1 judges a full AI-agent trajectory (policy, user request,
history with tool calls/results, target assistant text + attempted actions)
and returns one of `PROVED_ERROR / PROVED_NO_ERROR / UNRESOLVED /
INCONSISTENT` with a certificate for every definitive verdict. The binary
0/1 label appears only in the adapter after the proof Core.

```
E2ECaseInput
  -> source adapter v1          [TEXT_VIEW / ACTION_VIEW / firewall goal source]
  -> normalize (baseline)       [transport-marker authority; ambiguity-preserving]
  -> EvidenceLedger             [append-only; observations only from results]
  -> T1 (trusted contracts) / T2 (untrusted candidates)
  -> claim graph (baseline 10 passes + E2E claim overlay)
  -> PASS 1 frontends (trajectory-free):
        policy: H0 (flat) and/or GRS (grounder -> B1 synth -> DSL -> canonicalizer)
        goal:   Conservative and/or RuleFrames (+E5 resolver + assembler)
     -> compiled program space (FORBID_CALL / REQUIRE_PRESERVE / REQUIRE_CALL /
        GOAL_CALL / GOAL_ALTERNATIVES / PERMIT)
     -> deterministic equivalence dedupe (no winner selection)
  -> PASS 2 lowering (trajectory binding):
        baseline operational binding (LLM proposal + deterministic literal/clause
        validation), prerequisite atoms (assistant-call search), preservation
        obligations (tool-match implication), disjunctive authorization groups
  -> axes: policy, goal, per-claim, T2-effects
  -> exact Cartesian worlds (budget 4096; exceeded => UNRESOLVED)
  -> per-world verdicts (FALSE dominates UNKNOWN; markers are UNKNOWN conjuncts)
  -> all-world aggregation (consensus)
  -> certificate -> independent deterministic checker -> downgrade on invalid
  -> product adapter (binary label; UNRESOLVED never a fake NO_ERROR)
```

## 2. Arms (spec 137-142)

| Arm | Policy | Goal |
|-----|--------|------|
| E0  | H0     | Conservative |
| E1  | GRS    | Conservative |
| E2  | H0     | RuleFrames+E5 |
| E3  | GRS    | RuleFrames+E5 |
| E4  | {H0, GRS} | {Conservative, RuleFrames+E5} (deduped retention) |

Lower layers identical across arms; frontends are memoized (one semantic
attempt per distinct input), so arms share all frontend computation.

## 3. Key mechanisms

* **Goal firewall (PASS 1)**: goal frontends receive ONLY the user request
  (`{"user_request", "instructions"}`); byte-invariance across futures is
  regression-tested (10 divergent futures).
* **H0**: one flat structure per policy, one registered format re-ask; schema-
  valid output is never semantically retried; UNAVAILABLE is never safe.
* **GRS**: grounder (source-grounded atoms) -> B1 composes ONLY inventory IDs
  -> closed DSL (validated) -> canonicalizer (structure-preserving repairs
  only: wrapper, ordering, duplicate removal).
* **E5**: strictly deterministic reference resolution (EXACT / UNIQUE_QUOTE /
  AMBIGUOUS / UNRESOLVED); no fuzzy matching, no LLM fixes.
* **Assembler**: canonical IDs/order/arity; no semantic repair.
* **Program space**: shared by policy and goal; polarity fixed by the compiled
  rule KIND; BEFORE-requirements compile to conditional prohibitions
  (REQUIRE(A) BEFORE(B) => FORBID(B) WHEN NOT(A-preceded-B)).
* **Worlds**: one admissible choice from every material axis; a certified
  FALSE witness in a world makes it ERROR even with unrelated UNKNOWNs
  (spec 96); UNKNOWN conjuncts (unresolved markers) block NO_ERROR only.
* **Closure**: behavioral signature equality (bound tool + constraints +
  polarity + conditions + group alternatives) against authoritative
  behavioral rows supplied by the application; never inferred from frontend
  agreement (spec 102).
* **Certificates**: `guardian-e2e-v1-proof-v1`; the independent checker
  recomputes every primitive proof and world verdict, validates obligation
  grounding, coverage and closure premises; invalid => UNRESOLVED.
* **Registered deterministic repairs** (transport-level only, receipted):
  action-clause check drop, arguments-path prefix strip, allowed_json
  canonicalization, punctuation-stripped quote variants, JSON object
  extraction. No semantic retries anywhere.

## 4. Entry point and dependency injection (spec 109-110)

`GuardianE2EV1(backend, registry=..., arm=..., max_worlds=4096,
adapter_mode=AUDIT, enable_t2=True, oracle_policy=False, oracle_goal=False)`
-> `analyze_e2e_v1(case) -> E2EAnalysis`. No hidden API clients, no hidden
global semantic state. The baseline `vnext.core.analyze` (B0) is untouched
and remains runnable.
