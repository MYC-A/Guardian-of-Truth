# Universal repair — pre-registered protocol (written before any P2 measurement)

## Arms (all on the same frozen inputs; A is never changed)
| Arm | Definition |
|---|---|
| `A` | guard_adm2 control, frozen request (unchanged). |
| `V4` | frozen V4 default (A ∪ first verified DF4/Ems/AT candidate). Re-derived from the stored records. |
| `R_fix` | V4 control flow + pure deterministic fixes only (numeric/Decimal, datetime seconds/tz, lazy ops, strict addressed-leaf evidence, leaf identity, DF assertion scope, scoped copy, no silent slice, polarity/applicability receipts). Candidate choice = first, as V4. |
| `R_pool` | V4 code + candidate pool only: every admitted candidate of DF4/Ems/AT is queued (bounded K=4 per row, rest `UNCHECKED`), each needs its own verifier reply; ERROR iff any candidate SUPPORTED. |
| `R_wit` | V4 code + witness-closure verifier bundle only (counter-evidence search + technical-failure receipt). |
| `R_df` | V4 + focused DF/binding fixes only (assertion scope, scoped copy, entity binding, overflow claims). |
| `R_comb` | all fixes + pool + witness. |
| `R_comb_mech` | `R_comb`, but a candidate with a FULL certificate (schema_valid, every leaf source_supported, binding BOUND, applicability APPLICABLE, closure COMPLETE where needed, execution VIOLATED) is admitted unless its verifier says REFUTED. Diagnostic arm. |
| `R_comb_alone` | `R_comb` without A's ERROR (repair candidates only) — separate A-preserving-OR contrast. |

## Replay rules
* Model calls go through a read-through client: an exact cache hit (key = provider, endpoint, model, request, attempt)
  in the frozen caches is reused; anything else is a NEW request. Offline mode marks such requests `NOT_EXECUTED`
  and the affected candidate `UNCHECKED` (never ERROR, never SUPPORTED). A changed verifier input always needs a new
  reply; SUPPORTED is never transferred between different requests.
* Live completion (P2b) sends only the missing requests: Mistral `ministral-14b-2512`, temperature 0, attempt = rep−1,
  cache `outputs/universal_repair/cache/mistral`. Budget cap: 2500 new Mistral calls for P2–P4 together. HTTP 402/429
  that persists after the transport's explicit retries → `BLOCKED`, rows reported as NOT_EXECUTED.
* Record files are validated per (set, rep): exactly the expected id set; duplicate ids allowed only as
  failure→success retry chains, otherwise `DUPLICATE_CONFLICT` aborts scoring (no silent last-wins).

## Sets and gold (frozen; no gold edits)
valid46 (r1), LB1 (r1), LB2 (r1), LB3 (r1, r2), external tau2 on gold v2 (r1, r2, r3) and strict-65. Each set is
reported separately; no pooled headline across different gold sources.

## Metrics
TP/FP/FN/F1 per set and rep; min–max over reps; per-row flips between reps; correct-cause counts from the
source-seeing cause judge (categories in CONTRACTS_AND_ARCHITECTURE.md §5) — judged separately from detection,
judge variance reported separately. Preserved regressions: the audit's correct findings H5e (LB2 lb2L_037), CL3e
(LB3 lb3L_000), BK3e (LB3 lb3L_055), TL3e (LB3 lb3L_003 r2) must stay detected with a correct cause; G3e (LB2
lb2L_018) is tracked as the known V4 regression.

## Adoption rule (fixed now)
`R_comb` (or a narrower arm) replaces V4 as default only if, on every set and every rep: FP ≤ V4 FP, TP ≥ V4 TP − 0
on frozen lockboxes, external F1 (gold v2) ≥ V4 on ≥ 2 of 3 reps, and no preserved regression is lost. Otherwise
V4 stays default and the fixes are kept as correctness fixes with their measured effect. Fixes that are pure
correctness bugs (wrong arithmetic/time/ids) are kept even if metric-neutral.

## Live phase (P4) — budget and thresholds fixed before execution
Mistral baseline46/candidate46: ≥3 reps (attempt 0,1,2). Gemma: Ollama Cloud returned HTTP 429 "monthly usage
limit" at preflight (2026-10-06) → BLOCKED; AI Horde (anonymous) answers but is a queued, thinking-mode transport —
at most one bounded rep (cap 400 calls) if json_schema replies validate, else NOT_EXECUTED.
New blind holdout: drawn by seed from the unused tau2 pool (excludes the 70 frozen external rows and their tasks),
gold = tau2 reward/action labels plus a policy-compliance annotation frozen and committed BEFORE any arm runs on it;
target ≥25 positives. Thresholds for holdout success: candidate F1 ≥ V4 F1 and FP ≤ V4 FP + 1.
