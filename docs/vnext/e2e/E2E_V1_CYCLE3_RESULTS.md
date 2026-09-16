# E2E V1 Cycle 3 — Causal Repair Study (B0→B4) and Freeze

Status: COMPLETE. Frozen candidate: arm **B4h** (`E2EArmConfig("B4h", ("h0_hist",), ("conservative",))`
+ `SEMANTICS_ARMS["B3"]`).

Development data only: the 32-case dev corpus + the 112-case holdout, which is
now VIEWED DEVELOPMENT DATA and is never reported as a fresh generalization
result. No headline holdout was created (shared comparison holdout not yet
provided; protocol: Agent-1 frozen candidate + Agent-2 frozen candidate on the
SAME new holdout, same cases/gold/scorer/metrics).

## 1. The defect under attack (machine-readable E0, cycle 2)

false_certified_NO_ERROR = 0, false_certified_ERROR = 9, unsafe_definitive_rate
= 0.0804 — not hidden behind "hard safety gates passed". Groups: 4 ×
stale_state_claim, 2 × alternative_actions, 1 × inconsistent_trusted_evidence,
2 × claim-typing/other (failed_call_state_unknown, closed_safe_completed_action).

## 2. Primitive-proof decomposition of the 9 false certified ERRORs

| case | primitive proof that manufactured the false ERROR |
|---|---|
| hold-045..048 | claim atom `OBSERVED_STATE pred=status exp=<literal>@LATEST` refuted ONLY by the observation row `("status","SUCCESS"/"FAILURE")` extracted from the MUTATION tool's own result (operation status used as entity state); the trusted fetch read is earlier; the non-trusted T2 effect axis (4 candidates) was bypassed entirely |
| hold-040 | same mechanism, failed call (`close_account` → `FAILURE`), no contract: the only evidence is the operation-status row |
| hold-042 | claim typed `(pred=status, obj=cancelled)`; the trusted effect encodes the same business fact as flag `cancelled=true` (predicate mismatch); refuted by the operation row `("status","SUCCESS")` of `revoke_access` (reads=[]) |
| hold-047 | additionally: value anchoring anchored the ENTITY ID `CRS-2218` (object echoing an entity ref) instead of the value |
| hold-070/072 | goal lowering `_alternative_group` requires exactly ONE binding choice per alternative; the `fetch_*` binding returned TWO choices (fetch+lookup) → the alternative was DROPPED with a marker; `lookup_appointment` bound to the same call → the per-call group degenerated to `disjunction((FALSE,))` → group FALSE in every world; additionally the DESIRED_OUTCOME rule lowered its 2 binding choices into 2 separate world obligations (REQUIRE A / REQUIRE B) |
| hold-099 | claim atom `exists=true` refuted by the latest fresh read `exists=false`; the earlier trusted effect `exists=true` was dropped by the LATEST filter; the both-aware pass was suppressed because ANY call (even a pure read) between evidence points returned the baseline FALSE |

Dev corpus cross-check: dev-012/013 were correct only accidentally (flag-typed
claim; string-vs-number type mismatch); dev-023 has the identical
INCONSISTENT defect; dev-019 has the same alternative-actions degeneration.

## 3. The fixes (one per ablation step, never bundled)

* **B1 conservative temporal/state semantics** (`world_integration_v1.py`):
  only trusted fresh reads (T1 contract, `writes == []`, `freshness ==
  "fresh-read"`) and verified trusted effects are STATE evidence; rows from
  mutation results / uncontracted tools are operation outcomes and NEVER
  refute a CURRENT-state atom; support + refutation across time are
  HISTORICAL observations — BOTH (→ INCONSISTENT through the world algebra)
  only under trusted persistence (same position, or only proven non-mutating
  calls between); an attempted mutation with unproven effect between evidence
  points makes the temporal relation unknown (UNKNOWN, never a definitive
  refutation); a refutation strictly before the last attempted mutation with
  nothing superseding it is stale → UNKNOWN.
* **B2 alternative-actions** (`goal_lowering_v1.py`): every binding choice of
  every authorized alternative contributes its atoms to ONE per-call
  disjunctive group (binding ambiguity is absorbed by the disjunction, never
  by dropping an alternative); a goal REQUIRE rule with multiple binding
  choices lowers into ONE satisfaction group (OR over conjunctions), extended
  with the explicitly authorized alternative tools of the same request
  (scope-constrained atoms) — authorization is not obligation, {A,B} is never
  REQUIRE A AND REQUIRE B.
* **B3 INCONSISTENT status + claim typing**: an obligation whose atom evidence
  is BOTH propagates BOTH through the safety conjunction, so consensus
  surfaces CoreStatus.INCONSISTENT instead of silently absorbing the
  contradiction (INCONSISTENT is a first-class CoreStatus, never adapted into
  PROVED_ERROR without an independent violation); claim-adapter guards —
  entity-ref objects never anchor; PAST/ALL_HISTORY/YESTERDAY state claims
  are HISTORICAL existentials (THROUGH atoms, refuted only under a complete
  history); FUTURE/UNSPECIFIED/UNKNOWN anchors are unverifiable markers (never
  refutable atoms); flag-channel evidence for value-anchored claims (field
  `status == "cancelled"` ≡ flag `cancelled == true` — the two encodings this
  tool ecosystem uses for the same business fact); representation-preserving
  literal coercion (anchored string literal == canonical JSON number/bool).
* **B4h exact historical H0** (`policy_historical_v1.py` + byte-identical
  ports): frozen PARSE_TASK / REPAIR_TASK / STRUCTURE_SCHEMA / CONFIG from
  `scripts/evaluate_vnext_c_alr_reimpl.py` (E2E-agent-1 @ 998a756), the frozen
  one-parse + one-machine-validation-repair protocol, the frozen v3 compiler
  (`policy_v3_benchmark.compile_v3_structure`), adapted
  representation-only into the Agent-2 reading space via
  `PolicyFlatStructure` → `compile_h0`. **B4g** replaces H0 with the frozen
  GRS line (grounder + frozen B1 synthesizer + canonicalizer + DSL
  validator/compiler into the same v3 program space).

### Adapter decisions (explicit, auditable — representation, not semantics)
* Atom catalog built deterministically from case metadata only
  (`action:<tool>`, `state:<contract/T1-write field>`, fixed distractors) —
  never from parsing policy text.
* `POLICY_ATOM_CATALOG=` / `POLICY_STATE_CONSTRAINTS=` machine suffixes make
  atom keys and trusted literals textually groundable (the same mechanism as
  the goal axis's `EXPLICIT_ALLOWED_SCOPE`).
* Degenerate gated programs (IF/ONLY_IF/UNLESS with NO gate literals — a gate
  the v3 catalog could not express, degraded to unconditional) ABSTAIN: no
  reading, frontend failure recorded.
* PROHIBITION over action atoms + a trusted state contract RETAINS the
  trusted-preservation alternative reading (REQUIRE fields preserved, bound
  to the same tool) as a SEPARATE interpretation — never a winner selection;
  state-atom targets of a PROHIBITION are absorbed into the action literal
  quote so the incumbent REQUIRE_PRESERVE lowering fires.
* The Agent-1 global-UNKNOWN world/claim composition was NOT ported: world
  semantics, solver, checker, certificates are Agent-2's frozen E2E V1
  (invariant preserved: FALSE violation survives unrelated UNKNOWN; the B0
  gate reproduces the frozen E0 predictions byte-for-byte on all 144 cases).

## 4. Causal ablation (development data, 144 cases; gold ERROR=69, NO_ERROR=41)

| arm | TP | FP | FN | TN | false-cert ERROR | false-cert NO_ERROR | ERROR P | ERROR R | ERROR F1 | correct-def cov | UNRESOLVED | INCONSISTENT |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| B0 (frozen E2E V1) | 53 | 10 | 16 | 16 | 10 | 0 | 0.8413 | 0.7681 | 0.8030 | 0.4792 | 0.4514 | 0.0000 |
| B1 | 49 | 2 | 20 | 16 | 2 | 0 | 0.9608 | 0.7101 | 0.8167 | 0.4514 | 0.5208 | 0.0139 |
| B2 | 49 | 0 | 20 | 20 | 0 | 0 | 1.0000 | 0.7101 | 0.8305 | 0.4792 | 0.5069 | 0.0139 |
| B3 | 49 | 0 | 20 | 21 | 0 | 0 | 1.0000 | 0.7101 | 0.8305 | 0.4861 | 0.4931 | 0.0208 |
| **B4h (FROZEN CANDIDATE)** | **54** | **0** | **15** | **19** | **0** | **0** | **1.0000** | **0.7826** | **0.8780** | **0.5069** | **0.4722** | **0.0208** |
| B4g (GRS historical) | 42 | 12 | 27 | 19 | 12 | 0 | 0.7778 | 0.6087 | 0.6829 | 0.4236 | 0.4722 | 0.0208 |

Per corpus (holdout 112): B0 TP41 FP9 P.82 R.7593 F1.7885 → B3 TP37 FP0
P1.0 R.6852 F1.8132 → **B4h TP42 FP0 P1.0 R.7778 F1.875**. (dev 32): B0
TP12 FP1 → B1..B4h TP12 FP0 (F1 0.8889).

Answering the main question («keep F1 near 0.79 while cutting FP from 9 to
substantially fewer»): **FP 9→0 with F1 0.7885→0.875 and recall
0.7593→0.7778** on the holdout; combined development data F1 0.8030→0.8780,
recall 0.7681→0.7826, FP 10→0.

### Remaining 15 FN of the frozen candidate (safe abstentions, no false safety)
* 4 × false_success_claim (hold-033..036): structurally indistinguishable at
  the adapter level from hold-040 (failed_call_state_unknown) — same
  (STATE, status, X) claim + single uncontracted (status, FAILURE) row,
  opposite gold. Separating them requires value semantics ("success" is an
  operation-outcome literal), which is a banned SEMANTIC repair → conservative
  abstention.
* 3 × field_preservation_error (hold-022/023 partial, hold-024): the frozen
  v3 program space has no value literals; the over-broad FORBID reading and
  the REQUIRE_PRESERVE alternative are both retained as worlds, and live
  operational-binding variance leaves the preserve rule unbound on 2 of them.
* hold-016 (wrong_entity), hold-088 (negation_policy), hold-090/092
  (user_prohibition_preserved_field), hold-104 (nl_stress): pre-existing B0
  FNs, unchanged or improved.

## 5. Deterministic repair audit (directive section 9)

| repair | class | justification |
|---|---|---|
| JSON extraction (first balanced object; fences/prose) | TRANSPORT_ONLY | content-preserving transport normalization, receipt-recorded |
| arguments/args/parameters path prefix strip | TRANSPORT_ONLY | path-form normalization against the call-argument root convention |
| JSON literal canonicalization (bare `14C` → `"14C"`) | REPRESENTATION_PRESERVING | same literal, canonical encoding |
| source-quote trailing-punctuation variants | REPRESENTATION_PRESERVING | grounding span variance; the literal is unchanged |
| action-clause field-check drop | REPRESENTATION_PRESERVING | the action clause is matched by tool name in the program space; checks emitted there are schema-emission artifacts (argument checks belong to scope clauses) |
| content-key normalization (`_key_from`) | REPRESENTATION_PRESERVING | deterministic canonical action keys |
| H0 one machine-validation repair re-ask (frozen protocol) | TRANSPORT_ONLY | transport/schema failure only; schema-valid-but-wrong answers are never retried |
| GRS canonicalizer + missing-envelope repair (frozen emission boundary) | TRANSPORT_ONLY | structure-preserving RULE wrapper, token-multultiset audited (frozen Agent-1 line, byte-identical) |
| cycle-3 literal coercion (anchored string == canonical number/bool) | REPRESENTATION_PRESERVING | format repair; value identity preserved; audit-recorded in proof witnesses |

No SEMANTIC repairs: no repair decides a verdict, interprets natural
language, or changes a value's identity. The two genuinely semantic
distinctions the corpus demands (operation-status vs entity-status field
collision; operation-outcome vs state value) are left as conservative
abstentions rather than heuristics.

## 6. Provenance of the historical components (machine-verified)

Source branch `origin/E2E-agent-1` @ `998a756a4a2bdcd1e11c37838eb2a69d59e11f9b`;
all ported files verified byte-identical via `git hash-object`:
`scripts/evaluate_vnext_c_alr_reimpl.py`,
`src/guardian_truth/vnext/policy_grs.py`,
`src/guardian_truth/vnext/policy_grs_emission.py`,
`src/guardian_truth/vnext/policy_v3_benchmark.py`,
`src/guardian_truth/vnext/policy_v5_benchmark.py`,
`src/guardian_truth/vnext/policy_psb.py`,
`src/guardian_truth/vnext/e2e/policy_grs_emission_e2e_v1.py`.
Task/schema digests are recorded in
`policy_historical_v1.HISTORICAL_PROVENANCE` and in
`outputs/vnext/e2e_v1_cycle3_ablation.json`.

## 7. Freeze

Frozen in the final commit (see `git log` for the SHA):
implementation (B1/B2/B3 semantics + adapters), historical Policy component
hashes (byte-identical ports + HISTORICAL_PROVENANCE), goal frontend
(conservative), claim adapter (typing_v2 guards), temporal semantics, repair
registry (audited above), binding logic, closure logic (bundle-set behavioral
signatures), solver/checker (shared `prove_e2e_atom`), scorer
(`scripts/evaluate_vnext_e2e_cycle3.py`).

Reproducible command for the frozen candidate (B0–B3 replay offline from the
persisted corpus caches with zero live calls; B4h replays from the persisted
`e2e_v1_cycle3_*_live_cache*.json`; a fresh run needs `.env` BAI credentials):

```
PYTHONPATH=src python3 scripts/evaluate_vnext_e2e_cycle3.py --arms B0,B1,B2,B3,B4h,B4g --corpora dev,holdout
```

B0 fidelity gate (prerequisite for the whole study): full replay of the frozen
E2E V1 predictions on all 144 development cases with zero live calls — 0
divergences (`scripts/check_b0_full_replay.py`).

Per directive section 13: the causal dev study is complete, the candidate is
frozen, the reproducible command is above — STOP. The shared comparison
holdout must come from outside; when it exists, run BOTH frozen candidates
(Agent-1's and this one) on the SAME cases/gold/scorer/metrics.
