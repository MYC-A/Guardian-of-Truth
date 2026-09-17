# Witness-Masking Fix — FALSE Witness + Unrelated UNKNOWN Axis

Branch: `competition-real-valid-codex` (on top of the FN-audit commit
`f126c00`). Date: 2026-09-17. Scope: **composition/aggregation soundness
only** — no new detection capability, no provenance/policy/claim changes
(fix directive). All artifacts: `outputs/vnext/witness_masking_fix/`.

## 1. Reported bug

A reproducible real-valid case (telecom
`mms_issueairplane_mode_on-bad_network_preference-bad_wifi_calling-data_usage_exce::t7`,
one of the 15 audited FN) shows the catalog axis independently proving FALSE
(the RESPONSE calls `check_network_status`, absent from the prompt's
[AVAILABLE TOOLS]), while an unrelated UNKNOWN from the goal frontend (a
SCHEMA failure) turns the final result into UNRESOLVED.

This contradicts the documented invariant in `world_integration_v1` (spec
96/100): "A certified FALSE safety witness in a world makes that world ERROR
even when unrelated obligations are UNKNOWN - an independent proved violation
is never masked by unrelated uncertainty."

## 2. Minimal synthetic reproduction (independent of valid.parquet)

`scripts/witness_masking_repro.py` — deterministic, zero LLM calls
(offline backend / direct composition), exit code 1 pre-fix, 0 post-fix.

* **Composition layer**: real catalog component over a synthetic RESPONSE
  call (`check_network_status` not in the supplied catalog) + the exact
  `goal:unresolved` marker axis a failed goal frontend produces.
* **E2E layer**: `GuardianE2EV1.analyze_e2e_v1`, offline backend, non-empty
  user request (goal frontend fails at transport) + the violating call.

Pre-fix demonstration (captured at HEAD `f126c00`):

```
world:0 choices=['goal:unresolved', 'catalog_conformance:deterministic']
    error_value=TRUE  FALSE witnesses=['catalog:e0:in_catalog']
    UNKNOWN conjuncts=['catalog:e0:conforms', 'goal:unresolved']
solve_e2e final status: UNRESOLVED                  <- L1 masking
forced-status certificate check: INVALID ['COMPLETENESS_UNPROVED']  <- L2
E2E: axes=[policy(T), goal(F), catalog(T)] -> UNRESOLVED binary=0    <- bug
```

The per-world invariant itself HELD (world error TRUE, FALSE dominating the
UNKNOWN conjuncts); the loss happened only at aggregation.

## 3. Localization (directive question 3)

| candidate layer | verdict | evidence |
|---|---|---|
| conjunction truth table | NOT the bug | Kleene primitives: `conjunction(FALSE, UNKNOWN) = FALSE` (negative bit any-dominates); every world's error value was TRUE |
| world obligation aggregation (`solve_world`) | NOT the bug | per-world verdicts correct in the repro and in the real t7 trace (4/4 worlds TRUE) |
| marker handling | NOT the bug | markers correctly contribute UNKNOWN conjuncts, which are dominated by the FALSE witness per-world |
| option contract composition | NOT the bug | catalog obligations correctly land in every world of the Cartesian product |
| `solve_world` | NOT the bug | see above |
| **all-world consensus** | **BUG (L1)** | `solve_e2e` passes `material_space_complete = world_space_complete(...)`; the failed goal axis is enumeration-incomplete, so `consensus` returns UNRESOLVED even when every enumerated world is TRUE |
| **certificate generation/checking** | **BUG (L2)** | `check_e2e_certificate` requires `SEMANTIC_CANDIDATES_COVERED` for PROVED_ERROR; `e2e_completeness_assumptions` excludes the incomplete goal axis from `actual`, so the assumption is NOT_ESTABLISHED -> `COMPLETENESS_UNPROVED` -> core_v1 downgrades to UNRESOLVED |

The bug therefore lives in the **aggregation/verification of the world
space**, not in the world algebra. (The audit's earlier phrasing "absorbs
the FALSE witness in the world conjunction" was imprecise: the absorption
happens one level up, at the completeness gate.)

## 4. The fix — smallest general primitive

**Completion-invariant certified FALSE witness**
(`world_integration_v1.error_witness_completion_invariant`):

> PROVED_ERROR does not require the fully enumerated world space when at
> least one ENUMERATION-COMPLETE axis carries a certified FALSE safety
> conjunct in EVERY option.

Soundness argument:
1. the option set of an enumeration-complete axis is final, so every
   admissible world — enumerated or not — chooses one of its options;
2. a certified FALSE conjunct makes the world's safety conjunction FALSE
   regardless of every other conjunct (Kleene dominance, spec 96), and
   obligation/group safety values depend only on (ledger, registry,
   semantics), never on the world;
3. hence every admissible world is ERROR and the definitive ERROR verdict
   cannot depend on the readings a failed frontend failed to enumerate.

Deliberately NOT sufficient (stays UNRESOLVED, tested): a FALSE witness
carried only by options of an INCOMPLETE axis (a missing reading might not
contain it), and BOTH/contradictory conjuncts (not a certified witness).
The safety direction is untouched: PROVED_NO_ERROR still requires the
complete space and the full closure set.

Implementation (3 files, prover and checker share one code path so they can
never disagree — the same design as the shared catalog violation function):

* `world_integration_v1.py`
  - `solve_world`'s per-obligation / per-group evaluation factored into
    `_obligation_evidence` / `_group_evidence` (byte-equivalent behavior);
  - new `error_witness_completion_invariant(problem, option_contracts,
    ledger, registry, semantics)` evaluating each option's own contracted
    obligations/groups (attribution identical to the checker's
    FOREIGN_OBLIGATION logic) through the shared helpers;
  - `solve_e2e(..., option_contracts=None)`: `material_space_complete =
    complete or error_invariant`; without the parameter the previous
    behavior is bit-identical (all pre-existing callers unaffected).
* `core_v1.py`: passes the already-built `option_contracts` to `solve_e2e`.
* `certificate_context_v1.py`: `check_e2e_certificate` accepts PROVED_ERROR
  with `SEMANTIC_CANDIDATES_COVERED` NOT_ESTABLISHED iff the independent
  recomputation of `error_witness_completion_invariant` holds; PROVED_NO_ERROR
  requirements unchanged.

No changes to: conjunction/disjunction/negate primitives, `consensus`,
`solve_world` semantics, marker semantics, catalog violation function,
policy/goal/claim frontends, provenance. No new detection capability.

## 5. Metamorphic tests (`tests/e2e/test_witness_masking.py`, 11 tests)

| # | shape | expected | layer |
|---|---|---|---|
| 1 | FALSE only | PROVED_ERROR | composition |
| 2 | FALSE + unrelated UNKNOWN (incomplete axis) | PROVED_ERROR, valid certificate | composition |
| 3 | FALSE + N unrelated UNKNOWN (4 axes, complete+incomplete, multi-option, 4 worlds) | PROVED_ERROR | composition |
| 4 | UNKNOWN only | UNRESOLVED | composition |
| 5 | TRUE + UNKNOWN world errors (witness on only 1 of 2 options of a complete axis) | UNRESOLVED | composition |
| 6a | no FALSE witness, complete space | PROVED_NO_ERROR (never ERROR) | composition |
| 6b | no FALSE witness + UNKNOWN | UNRESOLVED | composition |
| 7 | witness ONLY on an INCOMPLETE axis | UNRESOLVED; forced cert REJECTED (COMPLETENESS_UNPROVED) | composition + checker |
| 8 | UNKNOWN-only, forced PROVED_ERROR cert | REJECTED (COMPLETENESS_UNPROVED) | checker |
| E1 | violating call + failed goal frontend (t7 shape) | PROVED_ERROR, cert VALID, binary 1 | E2E |
| E2 | clean call + same failed goal frontend | never PROVED_ERROR | E2E |
| E3 | no user request (no failing frontend) | PROVED_ERROR unchanged (regression guard) | E2E |

## 6. Test suites

* `tests/e2e/` + `tests/e2e_soundness/`: **137 passed** (126 at the audit +
  11 new).
* full suite (`PYTHONPATH=src pytest tests/`): **1618 passed, 9 failed** —
  the EXACT 9 pre-existing archival failures (failure content diffed
  byte-identical against a stash of the fix; the audit baseline was 1607 + 9).

## 7. Frozen 46-case replay (same cache, canonical config)

`scripts/witness_masking_fix_replay.py` ->
`outputs/vnext/witness_masking_fix/` (run twice; predictions sha256
`f7029a04643e0ac06f6ab8224ff38cc9a444a7d8bde15cc3ecba835d69330da2` both
times; zero live LLM calls; frozen cache byte-unchanged).

* **telecom t7: UNRESOLVED -> PROVED_ERROR**, certificate VALID,
  binary 1; all 4 worlds error TRUE with FALSE witness
  `catalog:e15:in_catalog` (goal SCHEMA failure still present — the witness
  is surfaced despite it, exactly the reported invariant).
* Status/binary diffs vs the sealed audit RUN A: **exactly {t7}**; the only
  certificate-validity flip is t7 (None -> True).
* Confusion (VIEWED DEVELOPMENT DATA): **TP=9 FP=0 FN=14 TN=23**,
  precision 1.000, recall 0.3913, F1 0.5625 (was 0.5161).
* **No new false-certified verdicts**: FP=0, and every other case's verdict
  is byte-identical to the pre-fix sealed run.

## 8. Residual notes

* The goal SCHEMA failure on t7 (and the other 5 UNRESOLVED telecom cases
  with goal failures) is a separate robustness issue, deliberately NOT
  touched here (no frontend/provenance/policy changes in this fix).
* The FN-audit root-cause table's `WITNESS_MASKED_BY_UNKNOWN_CONJUNCTS`
  family (1 case, telecom t7) is now resolved by this composition fix; the
  remaining 14 FN keep their audited first-loss points (argument provenance
  6, policy extraction 5, claims 3).
