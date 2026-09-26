# Generality results (frozen validation) — 2026-09-26

This document records what transfers, untouched, from the isolated probes to
frozen suites, and what remains unproven. Nothing in this cycle modified the
frozen suites, the frozen v2 code, or any sealed artifact; all replay work is
read-only post-processing of frozen traces (prediction-seal discipline
preserved: the v2 predictions were sealed on 2026-09-24/26 and are not
re-scored — the v3 replay is explicitly a POST-HOC diagnostic layer on those
sealed traces, reported separately).

## 1. The frozen perturbed-suite replay (B3) — the cycle's headline

Suite: `service_desk_v1_renamed` (32 cases; lexical perturbation of
`service_desk_v1`: all tool names and case/device IDs renamed; policy text,
tool descriptions, argument schemas, and result schemas unchanged). Frozen
v2 trace: `outputs/searh_23/tq_generality/sd_renamed_frozen_v2/` (produced
2026-09-26, worker job 6914e753, code unchanged since the dev loop closed).

| arm | TP | FP | FN | F1 | vs base |
|---|---:|---:|---:|---:|---|
| modal-safe base (v4-safe family replay) | 16 | 14 | 0 | 0.6957 | — |
| TQ v2 (frozen; lexical joins) | 13 | 7 | 3 | 0.7222 | −3 TP, −7 FP (safety gate FAILED) |
| TQ v3 joins (same sealed model answers; value-anchored binding + kind-aware directions) | **16** | **7** | **0** | **0.8205** | **0 TP lost, −7 FP (gate PASSED)** |

Reading of the three previously-lost TPs under v3 (from the replay traces):

- `call_bad_no_identity` — the precondition clause now binds to the
  executed mutation by effect CLASS (clause governs a mutation;
  `perform_swap` is typed MUTATION), so verification proceeds;
  IDENTITY_VERIFIED finds no verification-shaped observation joined by
  case-id VALUE ⇒ UNKNOWN ⇒ card kept ⇒ TP.
- `call_bad_wrong_amount_auth` — the granted authorization observation
  (amount 150) joins to the call (amount 250) by case-id but MISMATCHES on
  amount ⇒ FALSE ⇒ KEEP_VIOLATED ("authorization observed for another
  case/amount") ⇒ TP.
- `text_bad_stock_claim` — stock TRUE (latest inventory observation for the
  REQUESTED device, bound via the request context) + obligation_kind
  `refusal` ⇒ the PERMISSION branch returns KEEP_VIOLATED (mandate branch
  active; refusal not justified) ⇒ TP.

The seven v2 FP removals all survive the v3 replay (read-tool cards escape
via effect-class mismatch — principled rather than lexical; the
call-condition cards escape via value-joined all-TRUE certification).

## 2. Perturbation robustness, measured per mechanism (directive §22)

| perturbation | v2 mechanism outcome | v3 mechanism outcome |
|---|---|---|
| rename tool (`execute_replacement`→`perform_swap`) | lexical governed-action join breaks both ways (false "not governed" AND false governance) | effect-class join unchanged (MUTATION→MUTATION); explicit policy tool mention (`with perform_swap`) still binds by name from the POLICY, which is authoritative |
| rename entity ids (`SD-5101`→`CS-7824`) | ID_SHAPE regex may drop/shift ids; empty id-set defaults to permissive joins | parsed-kv value joins: `case_id` key present in both call and observation; equality semantics unchanged |
| rename result keys | (n/a — keys unchanged in this suite; noted as residual risk) | joins rely on generic key families (`*_id`, amount keys, boolean/status values); key renames degrade to NOJOIN⇒UNKNOWN, not to false joins |
| same words different effect (audit vs mutation; schedule vs execute) | model judge at 42–56% hard-negative rejection | class typing 100% (B2); renamed vocabulary included |
| wrong entity (authorization for another case) | v2 caught it only when id regex happened to parse both ids | value join ⇒ MISMATCH ⇒ FALSE (B3 restored `call_bad_wrong_case_auth` class) |
| wrong amount (authorization 150 vs call 250) | `call_amount is None` path skipped the check | amount-value equality required ⇒ FALSE (B3) |
| stale observation (older stock obs superseding) | order-based latest (already sound) | unchanged (order is a transport fact) |
| failed result (`error`) | `ok_flag` heuristics | NEGATIVE_VALUES ⇒ effect not established (B2 pair r6/o6) |
| action proposed instead of executed | tense question (v1 mechanism) | kept; B1 shows code-side markers are the stronger signal |
| user action instead of agent action | user_self_test clause + ask detection | kept (transport actor markers; B1 23/23) |
| user DECLINES confirmation | v2 CONFIRM_YES regex matches "не подтверждаю" (latent bug, found via the ablation stress set) | negation-window check ⇒ not confirmed; DECLINE fact feeds B6 reachability (justified refusal) |

## 3. What does NOT transfer yet (honest residuals)

1. **The v3 replay is post-hoc on sealed traces.** A genuine promotion
   requires a fresh frozen run of the v3 layer end-to-end (new prediction
   seal) on: hotel (untouched by v3 design decisions), service_desk
   renamed (re-run), AND a fourth untouched domain. Per directive §21/E
   this is the next gate, deliberately not attempted in this cycle
   (development-before-validation rule).
2. **The policy compiler remains the coverage bottleneck.** The condition
   typing still comes from COND_PATTERNS + concept nouns
   (identity/confirmation/authorization/stock) + model-proposed condition
   lists. The union-of-clauses derivation fixed the mandate clause, but
   open-vocabulary condition nouns (e.g. "verify the requester is a
   representative", "only during business hours") are untyped ⇒ UNKNOWN.
   This is the same bottleneck cycle-2 named (open-vocabulary policy
   semantics) — now narrowed to the CONDITION layer specifically.
3. **Effect typing is proposer-grade at the tool level.** The six classes
   are measured 31/31 on three catalogs, but trust-grade effect claims
   (T1) still require per-domain sign-off per the ceiling experiment's
   rule (11.67% internal coverage of human-signed contracts remains the
   honest number for CONFIRMED-effect evidence).
4. **Public46/banking transfer of the planner semantics is untested** —
   the reachability overlay was validated on service-desk only; the
   banking refusal cases (transfer_to_human_agents terminations) need the
   same fact typing over their tool set (get_user_details,
   authenticate, ... — plausible but unmeasured).
5. **The sd_orig dev trace is stale** (pre-final-gates model answers);
   v3-vs-v2 on the original vocabulary is reported as diagnostics, not
   evidence.

## 4. Frozen-status summary

- Nothing promoted into the frozen candidates (FREEZE.md untouched).
- The v2 negative result STANDS as sealed (it was produced by frozen code).
  The v3 replay is documentation that the negative result's CAUSE is
  isolated to the join layer — the architectural conclusion the directive
  asked for, not a new score claim.
- New artifacts committed read-only alongside the frozen outputs:
  `experiments/generality26/` (probes + results) and these five documents.
