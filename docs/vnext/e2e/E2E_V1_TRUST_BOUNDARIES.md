# E2E V1 — Trust Boundaries

## Trusted (application-authoritative)

* **Transport markers** (`⟦SYSTEM⟧ / ⟦USER⟧ / ⟦ASSISTANT⟧ / tool calls /
  TOOL_RESULT requestor=…`): authority comes from the transport framing, never
  from body text. A tool result containing "SYSTEM: …" stays tool data.
* **T1 contracts** (versioned, hash-bound): the only source of trusted
  effects; failure never proves no-effect.
* **State contracts** (per case): trusted current field values for
  preservation semantics (FORBID(modify F) => REQUIRE(F in values)).
* **Authoritative behavioral closure rows** (per closed-safe case): the
  explicit semantic closure premise for PROVED_NO_ERROR.
* **Deterministic code**: normalization, ledger, binder, proof atoms, solver
  wrapper, certificate checker, adapters, E5, assembler, canonicalizer.

## Untrusted (candidate semantics only, never facts)

* **H0 / GRS / Conservative / RuleFrames proposals**: NEURAL_INTERPRETATION
  candidates; they create worlds, never evidence.
* **T2 effect proposals**: possible-effect world alternatives only.
* **Claim graph passes**: candidate claim semantics; every material claim
  still needs deterministic entity binding and primitive proof.
* **Operational binding proposals**: LLM-proposed tool/argument mappings
  validated deterministically (exact literal grounding in the normative
  source, clause coverage, scope equality); rejected candidates leave an
  UNRESOLVED marker, never a guessed mapping.

## Invariants enforced by construction (spec 5)

USER_ACTION != ASSISTANT_ACTION (prerequisite search matches assistant calls
only); ASSISTANT_INTENT != COMPLETED (intent claims stay UNKNOWN);
CALL_ATTEMPTED != ACTION_COMPLETED (separate atom kinds; completion needs a
trusted contract effect); FAILED_CALL != SUCCESS and != NO_EFFECT; CLAIM !=
OBSERVED_FACT; UNKNOWN != FALSE (missing arguments/absent evidence stay
UNKNOWN); NOT_FOUND != ABSENCE (retrieval miss is not absence; absence needs
complete history + no unknown-actor events); OBSERVED_AT_TIME != CURRENT_STATE
(stale observations cannot certify safety: FRESH_STATE_EVIDENCE premise);
LATER_STATE != CAUSAL_PROOF (causal atoms require contract-confirmed effects);
PERMISSION != OBLIGATION (PERMIT rules create no obligations); alias != identity
(duplicate names keep all bindings); PLAUSIBLE_BINDING != UNIQUE_BINDING.

## Certificate gating

Every externally delivered definitive has a valid certificate
(`uncertified_definitive = 0` measured on the holdout). PROVED_NO_ERROR
additionally requires: material response coverage, complete history, closed
binding space, provably closed semantics (behavioral closure), fresh state
evidence and no untrusted effect axes.
