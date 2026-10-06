# Contracts and architecture (universal repair, `guardian-universal-repair-v5`)

Code: `src/guardian_truth/repair/`. Frozen V4 modules are untouched; V5 with no flags (`V4r`) reproduces V4 on all
472 stored rows (same decisions, same accusation origin/target; 0 new requests) — `experiments/universal_repair/score.py:parity`.

## 1. Five contracts (each produces its own receipt; there is no single `code_proven` boolean)
| # | Contract | Owner | Receipt field(s) | Values |
|---|---|---|---|---|
| 1 | Transport / schema | `clients.ReadThrough`, `common.call`, JSON-schema requests | `admission`, `schema_valid` | ADMITTED · INVALID_JSON · TRANSPORT_FAILURE · NOT_EXECUTED |
| 2 | Source support | `evidence.support`, `sourcejson.addressed` | `source_supported` (+ `how`, JSON pointers) | JSON_ADDRESSED · VERBATIM · NEAR_VERBATIM_POLARITY_KEPT · UNSUPPORTED |
| 3 | Semantic binding / applicability | `proof5.execute`, `df5.evaluate`, `confirm5.binding`, `closure` | `binding_status`, `applicability_status`, `closure_status`, `orientation` | BOUND · ROLE_SWAPPED · DUPLICATE_LEAF · ENTITY_CONFLICT · NO_TARGET_OPERAND; APPLICABLE · EXCEPTION_OR_CONDITION_UNBOUND; COMPLETE · PARTIAL · NA; MODEL · REORIENTED_FROM_POLICY |
| 4 | Execution | `proof5._run`, `df5.dec_arith`, `numeric` | `execution_status` | HOLDS · VIOLATED · UNRESOLVED(+note) |
| 5 | Cause adjudication / final | `v5.verify`, `v5.decide`, `cause.py` (judge) | `verification_status`, `final_owner` | SUPPORTED · REFUTED · UNRESOLVED · TECHNICAL_FAILURE · NOT_EXECUTED · UNCHECKED_QUEUE_BOUND; owner GUARD · A_adm2 · DF4 · Ems · AT · CB |

A mechanical certificate (`proof5.certificate`) = schema_valid ∧ source_supported ∧ binding ∈ {BOUND, ROLE_SWAPPED} ∧
applicability APPLICABLE ∧ closure ∈ {NA, COMPLETE} ∧ execution VIOLATED. Only the diagnostic arm `*_mech` lets a
certificate stand without a SUPPORTED verdict, and never over REFUTED.

## 2. Flow
```
row → A (frozen guard request; ERROR final, owner GUARD/A_adm2)
    → triggers (T_calc, T_multi, T_quant[, T_confirm])
    → components: DF5 (code claims + binder) · Ems5 (E1 requirements, E2 proof plans → proof5) · AT5 (all-target)
      [· CB5 shadow]   each returns ALL candidates with receipts
    → queue (V4: first candidate per component; pool: all, priority order, dedup, bound K=4, rest UNCHECKED)
    → verifier per queued candidate (witness bundle optional) → verification_status
    → aggregation: ERROR iff ∃ SUPPORTED   |  selection: first SUPPORTED by priority (explanation only)
```
Priority (selection only, never aggregation): Ems certified proof > DF code self-check > DF bound > Ems proof >
Ems semantic > AT > CB.

## 3. Layer repairs (all universal: no branching on ids, gold, domain or tool name)
* I/O: explicit UTF-8 everywhere in the new runner/scorer; LF attributes for frozen records; exact cache keys
  (provider, endpoint, model, request, attempt); validated record loading (no silent last-wins).
* Evidence: addressed JSON leaves with one shared parent; verbatim/stitched; fuzzy only with identical polarity
  tokens in and around the window; JSON-looking quotes on JSON sources must be addressed.
* Execution: Decimal, stated-precision equality (integer statements held to cents), lazy ops, datetime seconds+tz,
  dedup by leaf identity, membership closure + policy-oriented MEMBER_OF/NOT_MEMBER_OF, entity conflict for
  entity-attribute relations, applicability receipt for exception/condition clauses.
* DF: assertion scope (rejected/attributed/negated/quoted values are not the move's assertions), scoped copy
  (cited result or same-entity/key leaf), entity binding for operands, overflow claims bound (offline: UNCHECKED).
* Confirmation: proposal → consent → revision state; courtesy turns neutral; conditional/question "yes" is not
  consent; exact identifiers; negated requirement is not a trigger. Closure: unconditional sentences only.
* Verifier: witness closure adds older tool results sharing the target's identifiers/values and user
  affirmations/retractions; a technical failure is a receipt (`TECHNICAL_FAILURE`), the candidate stays unverified.

## 4. Stability contract
Same raw replies → same decisions (V4r parity on 472 rows; P0 replay 903 requests). Live calls: temperature 0,
attempt = rep−1, cache keyed by the full wire identity, HTTP tries ledgered (`http_tries.jsonl`), bounded backoff on
429/5xx inside one ledgered attempt, failed calls never cached, resume re-runs only failed rows, scorer validates
retry chains. Judge variance is reported separately from detector variance.

## 5. Cause categories (source-seeing judge, `cause.py`)
`supported_correct_core` · `supported_core_with_unsupported_extra` · `unsupported` · `unresolved` ·
`technical_unjudged` · `alternative_supported_cause` (a real violation, different from every gold cause) ·
`gold_conflict` (the sources contradict the gold cause). "Correct cause" = first two categories. GUARD/A accusations
are judged like every other accusation (no automatic correctness). The old SAME vs SAME+PARTIAL split is replaced by
these categories.
