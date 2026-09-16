# Pre-Benchmark Soundness Audit — Guardian B4h (B4h-sound-v1)

Audit mandated by the pre-benchmark directive (universality of proof semantics,
not benchmark performance). Frozen starting point: branch `E2E-agent-2`,
commit `e7eb79c7897789ec14c696b6b9626a6b73e97306` (historical frozen H0 +
Conservative Goal + cycle-3 B3 evidence/claim/world semantics = candidate B4h).

Audited modules: `world_integration_v1.py`, `tools.py` (vnext), `ledger.py`
(vnext), `proof_evidence.py` (vnext), `claim_adapter_v1.py`,
`certificate_context_v1.py`, `policy_historical_v1.py`, `goal_lowering_v1.py`,
plus the full supporting chain (`core_v1`, `goal_composition_v1`,
`policy_composition_v1`, `policy_lowering_v1`, `binder`, `grounding`, `claims`,
`normalize`, `backend_v1`, frozen C-ALR/GRS line).

Main invariant under test (directive §49):

> PROVED means PROVED FROM EXPLICIT TRUSTED PREMISES — never "reasonable under
> common API conventions".

The old dev32 + holdout112 corpora were used ONLY as regression diagnostics
(§41); every fix below is motivated by a formal invariant plus a minimal
synthetic counterexample, never by a benchmark case.

---

## 1. Findings table

| Finding | Counterexample (minimal) | Current behavior (pre-audit) | Correct behavior | Class | Fix? |
|---|---|---|---|---|---|
| SND-01 implicit persistence: cross-time support+refutation with no intervening assistant mutation inferred "one material snapshot" | read status=active@t1; external actor blocks account (not in ledger); read status=blocked@t3; claim "status is active" | BOTH → INCONSISTENT certified | historical pair; freshest trusted read decides the CURRENT claim → FALSE; INCONSISTENT requires an explicit persistence/exclusive-writer premise | FORMAL_SOUNDNESS_BUG | FIXED |
| SND-02 asymmetric staleness: support (and refutation-with-earlier-support) preceding the LAST attempted mutation stayed definitive | read active@t1; attempted set_status@t2 (unproven effect); claim "status is active" | TRUE (and the variant refute@suspended@t2 + mutation@t3 → FALSE) | UNKNOWN — the last attempted mutation's effect is unproven; staleness must be symmetric | FORMAL_SOUNDNESS_BUG | FIXED |
| SND-02+08 false certified NO_ERROR: stale support + freshness established by the mutation's own envelope row | same as above; response claims "status is active"; goal closure supplied | PROVED_NO_ERROR certified | UNRESOLVED | FORMAL_SOUNDNESS_BUG | FIXED (atom-level SND-02 + closure-level SND-08) |
| SND-03 predicate-name row binding without output-path/entity alignment | pure reader returns `{"status": "SUCCESS", "account": {"id": "A-1", "status": "pending"}}`; claim "account A-1 status is active" | top-level envelope row (status, SUCCESS) refutes the claim → FALSE | UNKNOWN: the envelope field is not the nested entity's state; rows bind entities only within their own JSON object scope | FORMAL_SOUNDNESS_BUG | FIXED (subtree scope + same-scope ambiguity skip; flat single-entity envelope residue documented as REP-01) |
| SND-03b flat multi-entity row unattributable | reader returns `{"from_account": "A-1", "to_account": "A-2", "from_balance": 100}`; claim "A-2's from_balance is 100" | row supports the claim anchored to the WRONG entity → TRUE | UNKNOWN: same predicate name ≠ same entity state | FORMAL_SOUNDNESS_BUG | FIXED (same-scope ambiguity skip) |
| SND-04 lexical enum↔flag equivalence: claim value token opened an evidence channel on a same-named boolean predicate | reader returns `{"item_id": "ITEM-1", "red": true}`; claim "color is red" | flag channel supports → TRUE (and `red: false` refutes → FALSE) | UNKNOWN: `P==V ↔ V==true` requires a trusted equivalence declaration (REP-02) | FORMAL_SOUNDNESS_BUG | FIXED (flag channel removed) |
| SND-05 failed pure reads counted as trusted fresh state observations | T1 reader contract (writes=(), fresh-read); read FAILS with `{"status": "FAILURE", "error": "timeout"}`; claim "status is active" | envelope row refutes → FALSE (certified ERROR) | UNKNOWN: the read did not observe anything; contract preconditions must gate read rows exactly as evaluate_t1 gates effects | FORMAL_SOUNDNESS_BUG | FIXED (precondition-gated `_pure_reader_event`) |
| SND-06 trace completeness used as state-timeline completeness for PAST existentials | complete trace; reads show active@t1, active@t3; external actor set cancelled@t2; claim "status WAS cancelled" | FALSE | UNKNOWN: refuting "was never X" needs the complete state timeline (external mutations never appear as events); `history_complete` certifies only the supplied trace | FORMAL_SOUNDNESS_BUG | FIXED (FALSE unreachable) |
| SND-07 cross-frame authorized-alternative satisfaction (global union, no linkage) | "Book flight FL-1. Also, cancel hotel H-1 or modify hotel H-1." + assistant only calls cancel_hotel | REQUIRE(book_flight) satisfied by the unrelated authorization alternative → NO_ERROR path | PROVED_ERROR: alternatives extend a requirement only under frame-level or operational linkage to that same requirement | FORMAL_SOUNDNESS_BUG | FIXED (linked alternatives + already-bound filtering) |
| SND-08 FRESH_STATE_EVIDENCE closure established by operation-status rows | the SND-02+08 counterexample | freshness "established" by the mutation result's own (status, SUCCESS) row | only pure-reader observations and verified trusted effects establish freshness (same discipline as the solver) | FORMAL_SOUNDNESS_BUG | FIXED |
| SND-09 action-gate observation fallback resolved prerequisites from untrusted operation rows | gate "check_booking" (CALL_ATTEMPTED, expected true); uncontracted mutation result `{"booking": false}` | token-overlap row refutes the gate → FALSE | UNKNOWN: gates resolve only from trusted state evidence | FORMAL_SOUNDNESS_BUG | FIXED (fallback restricted to pure-reader rows / verified effects under conservative semantics) |
| SND-10 goal frames with conditions/exceptions crashed compile_goal_contract | any AUTHORIZATION/DESIRED_OUTCOME frame carrying `conditions` | TypeError (runner degrades the case to UNRESOLVED; library call raises) | conditions compile to prerequisite atoms (bound="HISTORY") | FORMAL_SOUNDNESS_BUG (crash; no false definitive) | FIXED |
| COV-01 reads from tools with unrelated writes discarded | tool reads `account.balance`, writes `audit.last_access` | rows discarded → UNKNOWN | correct abstention (tool not globally read-only); field-level read contracts would recover it (REP-01) | CONSERVATIVE_COVERAGE_LIMITATION | documented, not fixed |
| COV-02 nested business fields unreachable by bare claim predicates | claim predicate "status" vs row predicate "account.status" | UNKNOWN | correct abstention; path-qualified predicates need claim-side path anchoring (V2) | CONSERVATIVE_COVERAGE_LIMITATION | documented |
| COV-03 flag-channel coverage removed with SND-04 | hold-042 shape: claim (status, "cancelled") + trusted effect (cancelled, true) | was TRUE | now UNKNOWN; returns with explicit semantic_equivalences (REP-02) | CONSERVATIVE_COVERAGE_LIMITATION (cost of a soundness fix) | documented |
| COV-04 state gates resolve only against boolean-typed rows with token-overlap predicates | gate "account_status" vs row "status" | usually UNKNOWN | conservative; aligned for trusted rows by SND-09, lexical token bridging kept (EMP-02) | CONSERVATIVE_COVERAGE_LIMITATION | documented |
| REP-01 field-level read contracts absent | flat single-entity envelope `{"account_id": "A-1", "status": "SUCCESS"}` vs business field at top level — indistinguishable | envelope row refutes state claims | requires `reads: [{output_path, entity_ref, predicate, freshness}]` in T1; cannot be retrofitted to the frozen corpus; pinned as the ONE known open soundness risk (xfail test B05) | REPRESENTATION_LIMITATION (soundness-relevant) | deferred to V2 by directive §12/§36 |
| REP-02 no semantic-equivalence declarations | SND-04's replacement | — | `semantic_equivalences: [{lhs: {predicate, value}, rhs: {predicate, value}}]` in T1/application metadata | REPRESENTATION_LIMITATION | deferred |
| REP-03 no schema-declared canonicalization for cross-type literals | "42"↔42 (see EMP-01) | declared adapter convention | contract-declared canonicalization | REPRESENTATION_LIMITATION | deferred |
| REP-04 tool-level freshness cannot express mixed freshness | `{"balance": 100 (fresh), "monthly_summary": 4250 (cached)}` | tool-level fresh-read declares both fresh | per-field freshness; T1 is trusted, so the residue is a contract-authoring risk, not a proof error | REPRESENTATION_LIMITATION | documented |
| REP-05 eventual consistency unrepresentable | write committed → immediate replica read shows old state | T1 trusted fresh-read taken at face value | T1 must characterize consistency; outside Guardian's proof scope while T1 is trusted | REPRESENTATION_LIMITATION | documented |
| REP-06 machine-readable success/failure semantics for reads absent | `failure_semantics: "documented"` (free string) | SND-05 precondition gate is the best available proxy | structured success semantics in read contracts | REPRESENTATION_LIMITATION | documented |
| REP-07 async lifecycle stages unrepresented | start_export → accepted | distinct literals stay distinct (G01 test) | contract-level stage semantics (accepted/queued/started/completed) | REPRESENTATION_LIMITATION | documented |
| REP-08 DESIRED_OUTCOME vacuous without target calls | goal unfulfilled + non-committal response | no violation from the goal axis (claims axis is the usual net) | "must act" existential semantics deliberately outside V1 program space | REPRESENTATION_LIMITATION | documented |
| EMP-01 canonical-encoding literal coercion | claim "42" vs observation 42; claim "true" vs true | TRUE under the adapter's declared canonical-encoding convention (predicate+entity pin the same field; "001"/"01234" already UNKNOWN) | keep; harden with REP-03 declarations | EMPIRICAL_HYPOTHESIS | no production change; pinned by tests D01-D04 |
| EMP-02 lexical token bridging for state gates | gate "account_status" ← trusted row "status" | resolves when boolean-typed | kept for B0-frozen compatibility; corpus-neutral; recommend exact-predicate gates in V2 | EMPIRICAL_HYPOTHESIS | no production change |
| EMP-03 entity refs extracted only from `id`/`_id`/`name` keys | `{from_account, to_account, ...}` binds no entity refs | claims stay unbound → marker | conservative; broader key conventions are a V2 representation question | EMPIRICAL_HYPOTHESIS | no production change |
| EMP-04 machine suffixes in normative text (`POLICY_ATOM_CATALOG=`, `POLICY_STATE_CONSTRAINTS=`) | frontends see raw policy text; suffixes only make atom keys groundable for binding | grounding-only in every audited path | architectural risk recorded: the suffix must never be interpreted as normative content; quotes are validated against the extended text by design | EMPIRICAL_HYPOTHESIS (Area L) | documented; no soundness violation found |

Benchmark hardcoding (§32): static audit of production decision modules
(world_integration, claim_adapter, certificate_context, goal/policy lowering
and composition, policy_historical, ledger, tools, proof_evidence, binder,
grounding) found ZERO benchmark-specific production logic: no `hold-`/`dev-`/
case IDs, no corpus tool names, no domain values, no `SUCCESS`/`FAILURE` value
checks in deterministic semantics. The only domain-adjacent strings are
LLM-prompt example lists in `backend_v1.py` overlays
(`"(status, balance, deleted, exists, subscribed)"`), which guide claim
extraction but decide nothing deterministically. `case_id`/`family` are record
plumbing. Production benchmark-specific logic count: **0** (directive §32
requirement met).

Deterministic repair audit (§31, Area M): the four registered transport
repairs in `backend_v1._registered_repairs` and the frozen C-ALR one-repair
protocol were re-audited with input/output representations and preservation
arguments:
1. JSON extraction (first balanced object; fences/prose) — transport-only.
2. `arguments`/`args`/`parameters` path prefix strip — path-form normalization
   against the call-argument root convention (payload root IS the arguments);
   syntax-level, value-preserving.
3. Non-canonical `allowed_json` re-encoding (bare `14C` → `"14C"`) — canonical
   JSON re-encoding of the same literal; typed literals stay typed.
4. Trailing-punctuation quote variants — adds stripped variants for literal
   grounding; the literal itself is unchanged.
5. Action-clause field-check drop — the action clause is validated by tool
   name (`item["tool"]`, covered-clauses set equality); checks emitted there
   are schema-emission artifacts, and the compiled rule's semantics come from
   its declared scope clauses, so dropping an extra check RESTORES the
   compiled-rule semantics (a kept check would under-enforce).
6. H0 one machine-validation repair re-ask (frozen) — transport/schema failure
   only; schema-valid-but-wrong answers are never retried.
7. GRS canonicalizer + missing-envelope repair (frozen, byte-identical) —
   structure-preserving RULE wrapper, token-multiset audited.
8. Cycle-3 literal coercion — see EMP-01: kept as a declared convention.
No repair decides a verdict or changes a value's identity; no semantic repair
was introduced by this audit.

---

## 2. Answers to the fifteen directive questions (§48)

1. **Hidden semantic assumptions found**: (a) "no assistant mutation between
   evidence points ⇒ state persisted" (SND-01); (b) "staleness only matters
   for refutations" (SND-02); (c) "a pure reader's every output field with a
   matching name is entity state" (SND-03/REP-01); (d) "claim value V is
   boolean-ally encoded by a same-named predicate" (SND-04); (e) "a failed
   contracted read still observed the state" (SND-05); (f) "complete trace =
   complete state timeline" (SND-06); (g) "ANY_OF words authorize satisfaction
   of any requirement in the request" (SND-07); (h) "operation-status rows can
   establish evidence freshness" (SND-08); (i) "operation rows can resolve
   action gates" (SND-09); (j) goal frames with conditions never compile
   (SND-10, crash).
2. **Really unsound**: SND-01..SND-10 — each has a minimal counterexample in
   `tests/e2e_soundness/` where pre-audit code produced a definitive verdict
   (or a crash) the premises do not prove. All ten are fixed in B4h-sound-v1.
3. **Just coverage-limiting**: COV-01..COV-04 (readers with unrelated writes;
   nested field paths; flag-channel coverage lost with SND-04; boolean-token
   gates) — sound abstentions, documented, deliberately not "fixed".
4. **Implicit persistence assumption**: YES — SND-01 (cross-time BOTH from
   absence of intervening mutations). Removed: BOTH now requires a
   same-position (single-event) contradiction; cross-time pairs are decided
   by the freshest trusted evidence.
5. **Implicit field-level freshness assumption**: YES — SND-03/REP-01/REP-04:
   tool-level fresh-read + predicate-name matching treated every same-named
   output field as fresh entity state. Partially fixed (subtree scope,
   multi-entity ambiguity, failed-read gating); the flat single-entity
   envelope residue requires T1 field-level read contracts (REP-01) and is
   the one known open soundness risk, pinned by an xfail test.
6. **Implicit enum↔flag equivalence**: YES — SND-04 (`_flag_channel`
   deriving `status=="cancelled" ↔ cancelled==true` from the claim token
   alone). Removed; returns only with explicit `semantic_equivalences`
   (REP-02).
7. **Implicit type coercion**: the cross-type comparison exists but is a
   declared, deterministic canonical-encoding convention (adapter code, not
   domain guess): support only on exact canonical-encoding equality
   ("42"↔42, "true"↔true), family-consistent mismatch for refute,
   leading-zero/precision-distinct literals ("001", "01234") already UNKNOWN.
   No counterexample constructible without unrepresentable text-type
   distinctions ⇒ EMP-01, kept and pinned by tests D01-D04; contract-level
   canonicalization declarations are the V2 hardening (REP-03).
8. **Read-only tool output mistaken for entity state**: YES pre-audit
   (SND-03: envelope rows refuted nested-entity claims; SND-05: failed reads).
   Fixed for nested envelopes, multi-entity flat objects and failed reads;
   the flat single-entity envelope remains representation-limited (REP-01).
9. **External actor change breaking temporal reasoning**: YES pre-audit
   (SND-01: legitimate state transitions were certified INCONSISTENT; also
   user-text statements between reads were ignored by the persistence
   inference — test H02). Fixed: cross-time pairs are historical; the
   freshest trusted read decides.
10. **Eventually-consistent read creating a false definitive**: not within
    Guardian's proof scope — a T1 `fresh-read` contract is a trusted premise,
    so a stale replica is a contract-authoring error, not a proof error
    (REP-05). No code path invents freshness beyond the contract.
11. **Snapshot mismatch creating false INCONSISTENT**: YES pre-audit — the
    cross-time BOTH branch (SND-01) is exactly "different snapshots declared
    one material snapshot". Removed. Same-event contradictions (one read
    emitting contradictory values / one contract emitting contradictory
    verified effects) still surface BOTH → INCONSISTENT, which is sound.
12. **Benchmark-specific production hardcode**: NONE (see §32 result above;
    the only domain strings are prompt-overlay example lists that decide
    nothing).
13. **Old development F1 after soundness fixes**: binary metrics are
    IDENTICAL — combined 144 viewed-development cases: TP 54, FP 0, FN 15,
    precision 1.000, recall 0.7826, F1 0.8780 both before and after
    (regression run `outputs/vnext/pre_benchmark_soundness_regression.json`,
    fully offline, 0 cache misses). Five core-status verdicts changed, all
    binary-neutral: dev-023/hold-099/hold-100 INCONSISTENT→PROVED_ERROR
    (SND-01: the sound refutation replaces the unproven contradiction; their
    gold INCONSISTENT encodes the closed-world assumption the premises never
    state, and their gold_binary is None); hold-042 PROVED_NO_ERROR→UNRESOLVED
    (SND-04 coverage cost, gold_binary None); dev-019 UNRESOLVED→PROVED_NO_ERROR
    (SND-07 linkage fix un-degenerated the alternative-actions case — an
    improvement). false_certified_ERROR (binary) stays 0;
    false_certified_NO_ERROR stays 0; uncertified definitive stays 0.
14. **Known remaining soundness risks**: exactly ONE open formal risk — the
    flat single-entity envelope (REP-01, xfail test B05): a T1 pure reader
    returning `{"account_id": "A-1", "status": "SUCCESS"}` where top-level
    `status` is an operation envelope is indistinguishable from a business
    field in the current representation; the sound fix needs field-level read
    contracts and cannot be retrofitted to the frozen corpus. Additionally
    documented empirical risks: EMP-01 (canonical-encoding coercion), EMP-02
    (lexical gate-token bridging on trusted rows, B0-shared), EMP-04 (machine
    suffixes as grounding context). All are recorded with mutation tests.
15. **Exact commit for the shared fresh benchmark**: the FINAL_FROZEN_COMMIT
    of B4h-sound-v1 in section 5 below.

---

## 3. What was changed (and what was not)

Changed (all gated behind the cycle-3 semantics flags — B0 keeps the frozen
E2E V1 semantics byte-for-byte, verified by the replay gate):

* `world_integration_v1.py` — SND-01/02 (rewritten `_conservative_state_proof`:
  same-position BOTH only; symmetric staleness gate; freshest-evidence-wins),
  SND-03 (`_row_binds_entity` object-scope alignment + ambiguity skip),
  SND-04 (flag channel removed), SND-05 (precondition-gated
  `_pure_reader_event`), SND-06 (`_historical_state_proof` FALSE
  unreachable), SND-09 (trusted-evidence-only observation fallback in
  `_prove_deterministic_action_atom`).
* `certificate_context_v1.py` — SND-08 (`_state_evidence_fresh` counts only
  pure-reader observations and verified effects under conservative
  semantics; solver/checker parity preserved by construction — both sides
  call the same functions with the same `bundle.semantics`).
* `goal_lowering_v1.py` — SND-07 (`_linked_alternatives`: frame-level or
  operational linkage; extension excludes already-bound tools).
* `goal_composition_v1.py` — SND-10 (missing `bound` argument crash).

Not changed (directive §37): H0/GRS prompts and the frozen historical line,
Conservative Goal prompt, RuleFrames, operational binding strategy, world
selection, max_worlds, semantic retries, temperature, LLM provider, benchmark
corpus. No domain/keyword heuristics, no confidence router, no judge model,
no majority vote. The only representation-level extraction change
(object-scope entity binding) is syntax-level (uses only JSON path structure),
conservative in direction (strictly narrows admissible evidence), and
corpus-neutral by replay.

Independent checker parity (§40): every changed primitive semantic
(`_conservative_state_proof`, `_historical_state_proof`,
`_collect_state_rows`, `_pure_reader_event`, the gate fallback) is consumed
by `solve_world`, which the checker re-executes with `bundle.semantics`;
the closure premise change lives in `e2e_completeness_assumptions`, called
identically by `make_e2e_certificate` and `check_e2e_certificate`. Solver
semantics and checker semantics remain the same code.

---

## 4. Verification evidence

* Adversarial micro-suite `tests/e2e_soundness/test_pre_benchmark_soundness.py`:
  38 tests, one formal invariant each, expected epistemic result stated in
  every docstring; 37 pass + 1 strict xfail (the documented REP-01 open
  risk). Every fixed bug was first reproduced as a failing test (directive
  §39), then fixed, then re-run.
* Cycle-3 controlled tests re-pinned to the sound semantics (6 tests updated
  with per-finding rationale; the file header documents the re-pinning).
* Full e2e suite: 87 passed + 1 xfail. Full baseline suite: 1481 passed,
  9 failed — the SAME 9 pre-existing archival failures as at the frozen
  commit (verified by stash-diff), i.e. zero new baseline failures.
* B0 byte-fidelity gate: 0 divergences from the frozen E0 predictions on both
  corpora (all fixes are gated behind semantics flags B0 leaves off).
* B4h-sound-v1 regression (viewed development data only): see §2 Q13.
  Reproducible offline with zero LLM calls:
  `PYTHONPATH=src:. python scripts/run_soundness_regression.py`
  (merges the persisted per-slice live caches; all soundness fixes are
  LLM-payload-neutral, so every proposal replays from cache).
* All definitive results remain certificate-backed (uncertified_definitive=0
  in both corpora); a rejected certificate still downgrades to UNRESOLVED.

---

## 5. Final freeze — B4h-sound-v1

Per directive §45 the soundness-fixed candidate is a NEW explicit version
( historical B4h at e7eb79c is not rewritten):

* Version: `B4h-sound-v1` = historical frozen H0 (byte-identical Agent-1
  line) + Conservative Goal + cycle-3 B3 evidence/claim/world semantics +
  SND-01..SND-10 soundness fixes (all gated behind the cycle-3 semantics
  flags; B0 replay proves the frozen arm untouched).
* FINAL_FROZEN_COMMIT: recorded in `outputs/vnext/pre_benchmark_soundness_audit.json`
  (field `final_frozen_commit`; filled at commit time — see the freeze
  section below).
* Frozen component digests (sha256 of file bytes, first 16 hex):
  world_integration_v1=1c989f652bfcf972, claim_adapter_v1=69f741389e4529ad,
  certificate_context_v1=1b086542f0090f3d, goal_lowering_v1=cb6fc4565823c0de,
  goal_composition_v1=7e5b4a71d2333c8c, policy_historical_v1=866c2c6ecb718e18,
  core_v1=b2a7ca441182673f, e2e_types_v1=aa3266e179225ef6,
  ledger=a8a08f90cd07aae8, tools=cec9e6ad10e448f0,
  proof_evidence=ddb7ef8da6bcac16, binder=430a2a052e39f050,
  grounding=3df44149558f4684, solver=60571ef82fa24db7,
  c_alr_frozen=14f5c5492c12b30b, policy_grs_frozen=b22d768ac9f3dfdd.
  Frozen frontend task/schema hashes: see `HISTORICAL_PROVENANCE` in
  `policy_historical_v1.py` (h0/grs task, repair-task, schema digests and
  frozen config, unchanged from e7eb79c).
* Reproducible commands:
  * tests: `PYTHONPATH=src python -m pytest tests/e2e/ tests/e2e_soundness/ -q`
  * regression replay (offline): `PYTHONPATH=src:. python scripts/run_soundness_regression.py`
  * B0 fidelity gate: same script (`B0_byte_faithful` must be true).

Acceptance criteria (§42): all discovered FORMAL_SOUNDNESS_BUGS have minimal
tests (SND-01..10 — yes, 38-test suite); no benchmark-specific production
logic (yes — zero); no implicit semantic equivalence without a trusted source
(yes — flag channel removed, coercion is a declared adapter convention,
EMP-01/02 documented); no cross-time contradiction without a valid temporal
premise (yes — SND-01 removed, BOTH is same-event only); solver/checker
semantics match (yes — same code paths, same semantics object); all
definitive results remain certificate-backed (yes — uncertified=0).

HARD STOP per directive §47: no new benchmark, no fresh evaluation, no further
code changes after the freeze commit. The shared benchmark is to be created
by an independent process.
