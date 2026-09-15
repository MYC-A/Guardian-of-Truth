# E2E V1 — Trust Boundaries (Phase 1)

## Epistemic classes in the pipeline (spec §4)

| Class | Producers | Enters proof as |
|---|---|---|
| OBSERVED | result payloads via ledger observations; T1 trusted effects | OBSERVED_STATE/RESULT_FIELD evidence, disarming/gate condition atoms |
| CONTRACT_DERIVED | versioned T1 contracts (hash-bound identity) | ACTION_COMPLETED occurrences; no-effect refutations |
| NEURAL_INTERPRETATION | H0, GRS grounder/B1, goal frames, semantic binding, claim passes | interpretation axes and candidate obligations ONLY — never evidence |
| CLAIMED | assistant response text | factual-consistency obligations (must be proven against evidence) |
| UNKNOWN | anything unproven | four-valued Truth.UNKNOWN; decisive UNKNOWN blocks definitives |

## Non-negotiable invariants (spec §5) and their enforcement points

| Invariant | Enforcement |
|---|---|
| USER_ACTION ≠ ASSISTANT_ACTION | actor equality in prove_atom; target calls are response-document assistant calls only; the at-least-once scan filters actor=assistant (user text never satisfies; §128 test) |
| CALL_ATTEMPTED ≠ ACTION_COMPLETED | distinct AtomKinds; completion requires trusted causal effect or is refuted only by no-effect contracts |
| FAILED_CALL ≠ SUCCESS / ≠ NO_EFFECT | no-effect refutation requires an explicit `no_effect_conditions` contract; without it the completion stays UNKNOWN |
| CLAIM ≠ OBSERVED_FACT | claim parser never sets truth; claims become must-be-proven obligations |
| UNKNOWN ≠ FALSE / NOT_FOUND ≠ ABSENCE | four-valued lattice + AbsenceScope machinery (unchanged) |
| OBSERVED_AT_TIME ≠ CURRENT_STATE | LATEST_OBSERVATION/AT time modes; stale observations never prove current state |
| LATER_STATE ≠ CAUSAL_PROOF | CAUSAL_ATTRIBUTION requires single paired call + effect match (unchanged) |
| PERMISSION ≠ OBLIGATION / NO_VIOLATION ≠ PERMITTED | v3 program semantics; permission rules emit no obligations; explicit permission needs positive support |
| PLAUSIBLE_BINDING ≠ UNIQUE_BINDING | binding candidates with >1 entries branch into worlds; duplicate names stay AMBIGUOUS (binder, unchanged) |
| GOAL ≠ POLICY | independent axes; the goal frontends never see the policy text and vice versa |

## LLM proposal boundaries (reject-only validation)

1. **H0**: frozen STRUCTURE_SCHEMA + `compile_v3_structure` (raises on
   violation).  One repair re-ask on transport/schema/compile failure only.
2. **GRS**: catalog-only atoms with exact spans (`validate_inventory`);
   closed-vocabulary DSL (`validate_ruleset_ast` rejects unknown IDs and
   free-text leaves); ONE_OF ≤ 2; the canonicalizer may only insert
   RULE-wrappers (token-multiset proof).  Hallucination counters run on raw
   proposals.
3. **Goal frames**: every semantic field needs an E5-resolved extractive ref
   (exact offsets or unique quote); ambiguous/unresolvable mandatory refs
   REJECT the frame; enum fields validated; no semantic repair anywhere.
4. **Semantic binding**: tools ∈ catalog; argument paths exist in the schema
   or actual calls; observation paths exist in actual result payloads;
   literals canonical and quote-grounded; multiple candidates = separate
   worlds (never collapsed).
5. **Claim passes**: baseline 10-pass machinery (span inventory IDs only,
   never offsets; entity refs must appear verbatim in the response).

## Sealing discipline

- Per-request artifacts persisted by `PersistedSemanticBackend` (write-once,
  hash-bound, resumable; abandoned requests never re-sent).
- Per-frontend outputs and per-arm predictions sealed (hash + gold_joined
  flag) BEFORE any gold join; the scorer refuses unsealed runs.
