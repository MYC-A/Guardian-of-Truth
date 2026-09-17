# Hidden Closure Assumptions Audit — codex-update-run

Audit-only cycle. Not an optimization cycle: no detection capability was added, no
benchmark-specific heuristic was introduced, and no tuning against `valid.parquet`
occurred. The single question was whether the current gains from declared tool
catalog checking and declared tool schema checking are genuinely source-grounded
architectural proofs, or rest on hidden closure assumptions the competition input
does not justify. Development-data result only; `valid.parquet` is viewed public
development data and nothing here is a hidden-test or generalization claim.

## 1. Frozen starting state

- Branch `codex-update-run`, HEAD `869a93a9417cbd73d00000070cdd352abcad15b8`
  (local checkout was re-synced from `origin/codex-update-run`; the working tree
  contained only file-mode noise, content-identical to HEAD).
- Sealed metrics (`outputs/vnext/real_valid/metrics__fix2_final.json`), identical
  for R0/R1/R2: **TP=10, FP=0, FN=13, TN=23**, precision=1.0, recall=0.434783,
  **F1=0.606061**; PROVED_ERROR=10, PROVED_NO_ERROR=0, UNRESOLVED=36,
  INCONSISTENT=0; false-certified ERROR/NO_ERROR = 0.
- Prediction seals: R0/R1/R2 all sha256 `3828f54852a472da9687be1b6123d823caace694a62dab9ec6d7aa81411fdf2b`,
  provider mistral / `ministral-14b-latest`, input sha256 `de8ed525…`, 46 rows.
- The two audited mechanisms were introduced by `92b5d26` ("certify calls outside
  complete tool catalogs", TP 2→7) and `0dbacb5` ("certify target calls that
  violate declared schemas", TP 7→10).
- No live LLM calls were made in this audit. The fix2_final LLM cache itself was
  never committed to the repository; the audit therefore relies on the sealed
  artifacts plus deterministic recomputation (methodology in §8), with LLM-request
  invariance verified directly (see §8).

## 2. Audit Target A — is `[AVAILABLE TOOLS]` a closed universe?

**Classification: FORMAT_CONVENTION_ONLY** (not EXPLICITLY_CLOSED_BY_SOURCE, not
DERIVABLE_WITH_STRONG_CONTRACT).

Source evidence examined (all 46 prompts, regex + manual review):

- The `[AVAILABLE TOOLS]` block follows `</policy>` immediately and contains a
  bare tool list. There is no introductory or trailing sentence at all.
- Zero occurrences across all 46 prompts of any closure-establishing language:
  "only these tools", "only use", "no other tools", "you have access to" (in a
  closure sense), "exhaustive", "complete list", "full list", "following tools",
  "restricted to", "exclusively", "must match".
- The only "you have access" phrasing in the corpus points the OTHER way: the
  banking catalog's own `unlock_discoverable_agent_tool` description — "Use this
  when the knowledge base indicates that you have access to a specialized
  internal tool" — documents that tools beyond the static catalog exist and
  become invocable.
- Counter-evidence inside the sanctioned data:
  - `banking_knowledge__task_081::t35` (gold=0) history contains DIRECT
    assistant calls to non-catalog discoverable tools
    (`get_all_user_accounts_by_user_id_3847`, `get_debit_cards_by_account_id_7823`,
    `close_debit_card_4721`) that **execute successfully** ("User accounts
    retrieved successfully", "Debit Card Closed Successfully"). The runtime
    accepts non-catalog direct calls in this domain.
  - Telecom policies document a second action universe ("What the user can do on
    their device" → Diagnostic/Fix Actions: `check_network_status`,
    `run_speed_test`, `check_sim_status`, …) outside the catalog, assigned to the
    USER actor; the agent's role is to guide the customer through them.
  - One telecom history shows runtime enforcement ("Tool 'can_send_mms' not
    found") for a non-catalog call — enforcement is observed per case, not a
    stated contract.
- The five gold-positive cases corrected by catalog checking all have the called
  tool name PRESENT in the prompt (banking: KB document describing a discoverable
  tool; telecom: user-device action documentation). Their gold explanations
  justify the error by POLICY (wrapper protocol for discoverable tools;
  user-side actor for device actions), not by bare catalog absence:
  - `banking_knowledge__task_083::t10`: "Инструмента … нет в списке [AVAILABLE
    TOOLS]; это agent discoverable tool … Согласно policy такие инструменты
    нельзя вызывать напрямую: сначала нужно разблокировать через
    `unlock_discoverable_agent_tool` … а затем вызвать через `call_discoverable_…`"
  - telecom cases: "Согласно политике, `check_network_status` — это диагностическое
    действие на устройстве пользователя … которое выполняет сам клиент".

**Conclusion**: syntactic completeness of parsing (one block, no ellipsis, no
unrecognized entries, no duplicates — `parsing.parse_catalog`) is NOT semantic
closed-world completeness. Absence from the catalog is a strong signal but the
source never states exclusivity, and the source itself documents invocable
actions outside the catalog. Absence alone must not certify PROVED_ERROR; it may
remain UNKNOWN.

## 3. Audit Target B — is `additionalProperties=False` source-backed?

**Classification: NOT_PROVEN (for OBJECT_CLOSED).**

- `competition_adapter_v1._object_schema` hardcodes
  `"additionalProperties": False` into every object level (top level, nested
  objects, array items) whenever it converts the textual field enumeration to
  JSON-schema shape.
- The textual declaration syntax supports FIELD_EXISTS, FIELD_REQUIRED (`!`
  suffix), FIELD_TYPE (`string|integer|number|boolean|array|object`) and
  FIELD_ENUM (`[enum: a|b]`). It says nothing about forbidding unlisted fields.
- Zero occurrences of "additional properties/field", "only the fields",
  "no additional", "must match", "exactly these" in any prompt.
- Gold-annotation semantics confirm the split: the airline__23 explanation reads
  "`string!`" as required ("схема … требует поля payment_id (string!) и amount
  (integer!)") and treats invented field names as part of the error, while the
  airline__21 and airline__44 explanations do NOT cite the extra flight fields
  at all — their stated reasons are policy calculations (baggage allowance;
  cancellation rules). The extra-field certifications on those two cases fire on
  behavior the gold annotator did not identify as the error; the binary labels
  match only because those responses contained other (policy-level) errors.
- The five properties are therefore separated:
  - FIELD_EXISTS / FIELD_REQUIRED / FIELD_TYPE / FIELD_ENUM: explicit source
    syntax — kept as binding.
  - NO_OTHER_FIELDS_ALLOWED (OBJECT_CLOSED): different closure premise — not
    established by this source format; extra fields alone must not certify.

### Constraint matrix

| Constraint | Source support | Safe definitive violation? |
|---|---|---|
| required missing | explicit `!` syntax; gold-confirmed | YES (kept) |
| wrong enum | explicit `[enum: …]` syntax | YES (kept) |
| wrong type | explicit typed syntax; JSON call encoding is unambiguous | YES (kept; fires on 0 cases in this set) |
| extra field | none — invented `additionalProperties=False` | NO unless OBJECT_CLOSED established (now gated) |
| nested required missing | explicit nested `!` syntax | YES (kept) |
| malformed JSON | call transport requires JSON body | YES (kept; 0 cases in this set) |
| unsupported schema syntax | fail-closed | NO — UNKNOWN (unchanged) |

## 4. Parser → semantic promotion trace

Catalog path (promotion point marked):

```
prompt
→ parsing.parse_catalog            (complete = purely syntactic issues list)
→ competition_adapter_v1.py:118-119 (raises unless catalog.source and catalog.complete)
→ competition_adapter_v1.py:154    tool_catalog_complete=True
→ ★ PROMOTION: 92b5d26 added exactly this one line; syntactic parse
   completeness becomes closed-world semantics
→ source_adapter_v1.E2ESource.tool_catalog_complete
→ core_v1._declared_tool_catalog_component   (gated only on tool_catalog_complete)
→ DisjunctiveGroup(source_invariant=True) over TARGET_CALL_MATCH atoms
→ proof_evidence.prove_target_call           (FALSE for every non-matching tool)
→ world_integration.solve_world              (FALSE safety conjunct)
→ world_integration.source_invariant_violation (FALSE in every world forces completeness)
→ consensus → PROVED_ERROR with certificate
→ certificate_context_v1._check_declared_tool_membership_group (re-validates, same premise)
```

Schema path:

```
textual field enumeration
→ competition_adapter_v1._object_schema    ★ INVENTS additionalProperties=False
→ E2ECaseInput.tool_schemas                (bytes also feed T2 LLM payloads → cache keys)
→ core_v1._declared_tool_schema_component  (embeds full schema incl. closure in atom)
→ proof_evidence.prove_target_call_schema → validate_declared_json
→ ADDITIONAL:* diagnostics → FALSE witness → PROVED_ERROR
→ certificate_context_v1._check_declared_tool_schema_group (same schema compared)
```

Both promotions are **HIDDEN_CLOSURE_ASSUMPTIONS**: neither is backed by a
source quote, and each converts "we parsed everything listed" / "these fields
are declared" into "nothing else may exist".

## 5. All 10 TP dependency breakdown

| # | case | mechanism | classification | survives C3 |
|---|---|---|---|---|
| 1 | airline__21::t7 | D: extra-field rejection (12 ADDITIONAL) | CLOSURE_ASSUMPTION | no |
| 2 | airline__23::t10 | A: explicit required fields (16 REQUIRED + 34 ADDITIONAL) | SOURCE_EXPLICIT (required) | **yes** |
| 3 | airline__44::t22 | D: extra-field rejection (6 ADDITIONAL) | CLOSURE_ASSUMPTION | no |
| 4 | banking_knowledge__task_003::t7 | F: policy witness (premature escalation) | MODEL_SEMANTIC | yes |
| 5 | banking_knowledge__task_018::t6 | F: policy witness (premature escalation) | MODEL_SEMANTIC | yes |
| 6 | banking_knowledge__task_083::t10 | E: catalog closed-world (discoverable tool called directly) | CLOSURE_ASSUMPTION | no |
| 7–10 | telecom ×4 (data_usage t7, break_app t10, mobile_data t6, service t15) | E: catalog closed-world (user-device actions called by agent) | CLOSURE_ASSUMPTION | no |

Counts: catalog closure **5**, object closure (extra-field-only) **2**, explicit
required fields **1**, policy mechanisms **2**. Machine-readable copy:
`outputs/vnext/hidden_assumptions_audit/tp_dependencies.csv`.

## 6. Adversarial counterexamples

All generic (no benchmark names), automated in
`tests/e2e/test_hidden_closure_assumptions.py` (20 tests, all passing):

- Catalog A–F: declared call fine; undeclared call under open universe →
  UNKNOWN (pre-fix: certified ERROR — demonstrated over-strength); dynamic
  discovery announced in a history result → UNKNOWN (pre-fix would
  false-certify); bootstrap discovery with generated names → UNKNOWN;
  versioned aliases `foo`/`foo.v2`/`foo.v3` → UNKNOWN; closed-universe premise
  → absence still certifies (capability preserved).
- Schema A–G: required missing → certified; enum → certified; extra field
  without OBJECT_CLOSED → NOT a violation (pre-fix: certified ERROR);
  counterfactual "Additional properties are allowed" → no violation; nested
  required → certified; unsupported syntax → UNKNOWN; extra field WITH
  OBJECT_CLOSED → certified (capability preserved); declared-type mismatch →
  certified.
- No-manufactured-ERROR metamorphic: with both premises open, no FALSE witness
  is ever produced for out-of-catalog calls or extra fields.
- Empirical counterexamples found in source: see §2 (banking discoverable tools
  executing directly in a gold=0 history; telecom user-device actions; per-case
  runtime enforcement).

Full results: `outputs/vnext/hidden_assumptions_audit/adversarial_results.json`.

## 7. Read-only comparison with `competition-real-valid-codex`

Both branches diverge from `315bee3` (B4h-sound-v2). Neither branch is derived
from the other; no merge or cherry-pick was performed.

| Assumption | codex-update-run (this branch) | competition-real-valid-codex | Safer interpretation | Source support |
|---|---|---|---|---|
| catalog absence → ERROR | yes, via source-invariant disjunction, gated on parse completeness | yes, `CALL_IN_CATALOG` in catalog_conformance_v1, grounded on "call to unavailable tool" reading of the task contract | absence → UNKNOWN unless closure established | none of the two is closure-proven; both over-claim relative to the prompt text |
| extra fields → ERROR | yes, invented `additionalProperties=False` | **no** — "extra fields are not flagged (conservative)" | extra field not a violation without OBJECT_CLOSED | prompt text supports only DECLARED_FIELDS |
| type mismatch → ERROR | yes (TYPE diagnostics) | **no** — "type mismatches deliberately NOT checked (EMP-01 coercion convention)" | judgment call; JSON call encoding is explicit, but coercion concerns are real | declared types are explicit syntax; no case in the 46 fires either way |
| required missing / enum | yes | yes | keep | explicit `!` / `[enum:]` syntax |

The other branch is more conservative on the schema axis precisely because its
session-B authors already refused the object-closure and type-coercion premises;
this branch's audit independently reaches the same conclusion for extra fields
and now gates it. For catalog closure, the other branch's justification cites
the official task contract's hallucination taxonomy ("a call to an unavailable
tool"), which this audit could not verify from any in-repo primary source quote;
against the prompt text itself the premise remains FORMAT_CONVENTION_ONLY.

## 8. Causal ablations C0–C3 (same 46 inputs, zero live LLM calls)

Methodology. The fix2_final LLM cache was never committed, so a mechanical
replay was impossible. Instead the ablation uses a witness-level
counterfactual reconstruction that is exact:

1. `92b5d26` and `0dbacb5` touched only proof-side files (verified from their
   diffs) — no LLM-facing payload construction changed across
   baseline→fix1→fix2 (the worklog records "exact semantic cache replay").
2. The soundness correction of §9 is likewise proof-side only; LLM request keys
   were re-verified byte-identical on a 4-domain probe (62/62 keys equal
   before/after).
3. The structural components are pure deterministic functions of
   (prompt, response); they were recomputed per case under each premise
   configuration, and the C0 recomputation reproduces the sealed fix2 metrics
   exactly (`c0_matches_sealed_fix2: true`).
4. Verdict composition: policy/claim witnesses are configuration-invariant
   (sealed audit); a structural FALSE witness yields PROVED_ERROR; when the
   premise is disabled the case reverts to its sealed pre-fix status (UNRESOLVED
   for every affected case, cross-checked against the baseline and fix1
   predictions).

| Config | TP | FP | FN | TN | F1 | PROVED_ERROR | UNRESOLVED | false-cert ERROR | false-cert NO_ERROR |
|---|---|---|---|---|---|---|---|---|---|
| C0 current | 10 | 0 | 13 | 23 | 0.606061 | 10 | 36 | 0 | 0 |
| C1 catalog closure off | 5 | 0 | 18 | 23 | 0.357143 | 5 | 41 | 0 | 0 |
| C2 object closure off | 8 | 0 | 15 | 23 | 0.516129 | 8 | 38 | 0 | 0 |
| C3 both off (= corrected production) | **3** | **0** | **20** | **23** | **0.230769** | 3 | 43 | 0 | 0 |

C3 retained PROVED_ERROR: `airline__23::t10` (explicit required fields),
`banking_knowledge__task_003::t7` and `banking_knowledge__task_018::t6`
(policy witnesses). Machine-readable:
`outputs/vnext/hidden_assumptions_audit/closure_ablation.json`; corrected
predictions: `outputs/vnext/hidden_assumptions_audit/R1_predictions__soundness_corrected.csv`.

## 9. Production changes made (soundness corrections only)

Allowed-change scope: "strong assumption → explicit premise / UNKNOWN".

1. `e2e_types_v1.py` — `E2ECaseInput` gains two explicit premise fields,
   `tool_universe_closed` (CLOSED_TOOL_UNIVERSE) and `object_fields_closed`
   (OBJECT_CLOSED), both defaulting to False. They may only be set True by a
   source that explicitly establishes closure; they are never inferred from
   format conventions.
2. `competition_adapter_v1.py` — sets both flags False with documenting
   comments; `tool_catalog_complete=True` remains (it is honest parse
   completeness). `_object_schema` keeps its historical byte shape (frozen
   caches key T2 proposals on those bytes) with a docstring stating the
   invented closure is not a source premise.
3. `schema_validation_v1.py` — new `certification_schema(schema,
   object_fields_closed=…)`: strips adapter-invented `additionalProperties`
   markers from the schema tree unless the source established object closure.
   `validate_declared_json` itself is unchanged (it still honors
   `additionalProperties` for sources that truly declare it).
4. `core_v1.py` — `_declared_tool_catalog_component` separates
   DECLARED_TOOL_MEMBERSHIP from CLOSED_TOOL_UNIVERSE: with the premise
   absent, out-of-catalog calls produce `UnresolvedMarker`s (world-level
   UNKNOWN conjuncts: block both PROVED_ERROR and PROVED_NO_ERROR) instead of
   a source-invariant FALSE disjunction; with the premise present the original
   certified behavior is preserved. `_declared_tool_schema_component` embeds
   the certification schema (closure stripped unless established); required /
   type / enum constraints always bind.
5. `source_adapter_v1.py` / `certificates.py` — the two flags flow through
   `E2ESource` and `CertificateContext`.
6. `certificate_context_v1.py` — the independent checker now (a) rejects a
   DECLARED_TOOL_MEMBERSHIP group unless `tool_universe_closed` is established,
   and (b) derives the same certification schema (with
   `object_fields_closed`) before comparing atom expectations and hashes, so
   solver and checker cannot disagree.

No detection capability was added; no policy/provenance/claim feature was
added; no benchmark-specific heuristic was introduced. Explicit facts
(required, enum, declared types) were NOT weakened.

## 10. Hard-coding scan

`src/**/*.py` scanned for domain prefixes, case-ID patterns, gold-label
references, and ID-like tokens extracted from the public input (13 tokens):

- `airline__` / `banking_knowledge__` / `retail__` / `telecom__` prefixes: **0 hits**
- case-ID-like patterns (`::t\d+`, `task_\d{3}`): **0 hits**
- input ID-like tokens vs production source: **0 collisions**
- `gold_label`: 1 hit — `real_valid_v1.py:223`, the post-seal case-audit
  output field (gold is loaded only after every prediction file is written and
  sealed; the adapter rejects non-inference fields before inference).

Production benchmark-specific semantic dependencies: **0**.
Machine-readable: `outputs/vnext/hidden_assumptions_audit/hardcoding_scan.json`.

## 11. Generic benchmark-shaped assumption audit

| Candidate | Source premise | Code premise | Match? | Sound? | Action |
|---|---|---|---|---|---|
| one `[AVAILABLE TOOLS]` block ⇒ it is THE catalog | exactly one block exists | multiple/ambiguous → incomplete → abstain | yes | yes (fails closed) | none |
| parsed catalog list is closed universe | no exclusivity statement | absence → FALSE witness | **no** | **no** | gated behind CLOSED_TOOL_UNIVERSE (this cycle) |
| field enumeration ⇒ additionalProperties=False | no no-other-fields statement | extra field → violation | **no** | **no** | gated behind OBJECT_CLOSED (this cycle) |
| SUCCESS result ⇒ committed effect | none | not implemented (T1/T2 only; no SUCCESS interpretation in structural paths) | — | yes | none |
| tool names as semantics | names are identifiers | membership/identity only, no effect inference | yes | yes | none |
| missing literal ⇒ unsupported provenance | none | not implemented in these mechanisms (claim path treats missing as UNKNOWN) | — | yes | none |
| prompt formatting ⇒ history completeness | none | `history_complete=False` in adapter | yes | yes | none |

## 12. Final classification of mechanisms

| Mechanism | Classification |
|---|---|
| tool existence check (declared tool called) | SAFE_SOURCE_INVARIANT |
| catalog absence check | SAFE_ONLY_WITH_EXPLICIT_CLOSURE (was UNPROVEN_ASSUMPTION; now gated) |
| required-field check | SAFE_SOURCE_INVARIANT (`!` is explicit syntax) |
| enum check | SAFE_SOURCE_INVARIANT (`[enum: …]` is explicit syntax) |
| type check | SAFE_SOURCE_INVARIANT (declared types + JSON transport; 0 firings in this set) |
| extra-field check | SAFE_ONLY_WITH_EXPLICIT_CLOSURE (was UNPROVEN_ASSUMPTION; now gated) |
| nested schema check (required/enum/type) | SAFE_SOURCE_INVARIANT |
| malformed JSON check | SAFE_SOURCE_INVARIANT (transport format) |
| witness completion invariant (FALSE dominates UNKNOWN) | SAFE_SOURCE_INVARIANT |
| goal format repair (registered, frozen) | SAFE_SOURCE_INVARIANT (unchanged this cycle) |
| must-act abstention | SAFE_SOURCE_INVARIANT (unchanged this cycle) |

No BENCHMARK_SHAPED or CASE_SPECIFIC_HARDCODE mechanism was found.

## 13. Final state after soundness corrections

- Development metrics (viewed data, R1; R0/R2 identical by the established
  equality): **TP=3, FP=0, FN=20, TN=23**, precision=1.0, recall=0.130435,
  **F1=0.230769**; PROVED_ERROR=3, UNRESOLVED=43; false-certified ERROR/NO_ERROR
  remain 0.
- The drop from F1=0.606 to F1=0.231 is the honest cost of removing two
  unproven closure premises. Per the audit contract, no compensating rule was
  invented to recover the lost TP; the question answered is "which verdicts are
  actually justified", not "how to preserve F1".
- Tests: `tests/e2e` + `tests/e2e_soundness` = 138 passed (118 pre-existing +
  20 new adversarial/metamorphic); full suite 1620 passed with exactly the 9
  pre-existing archival failures (byte-identical failure list verified against
  pristine HEAD).
- The lost verdicts are recoverable only through source-grounded means, e.g. a
  policy-level reading of the banking discoverable-tool protocol ("discoverable
  tools must be unlocked and called via the wrapper") and of the telecom
  user-device-action actor assignment — both are explicit prompt text, but
  reading them is a POLICY-frontend capability, deliberately NOT implemented in
  this audit cycle.
