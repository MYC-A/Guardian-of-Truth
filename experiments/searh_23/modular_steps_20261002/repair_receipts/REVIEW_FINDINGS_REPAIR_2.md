# REVIEW FINDINGS — AUDIT-R2 (independent code audit #2, pre-freeze gate)

Role: code_auditor subagent. Task AUDIT-R2. Branch `research/modular-step2-4-20261002`,
HEAD `da654292` (pins verified: 160a4e98 §4, 2000afff §5, 3f8e5101 §6, 697e419e census,
2efb7163+0a592cfb §8, da654292 §9.6). Date: 2026-10-02. Method: OFFLINE ONLY — no paid
calls, no `--run`, no gold edits, no ledger writes; the two mandated scorer re-runs
(score_roles.py, score_deferred.py) were executed and both reproduce byte-identical
receipts (role md5 b1bfecf02d315945c1641a3790d10613, deferred md5 a2a34051d658eead4fc5bca6974dd028).
Independent recount scripts left at server `/tmp/audit_r2.py`, `/tmp/audit_r2_out.json`.

## What was independently reproduced (all PASS)

1. **Gold & freeze hashes.** dev_gold/dev_input sha256 match manifest.json; deferred bank input/gold match its manifest (11 error / 13 clean). Both selection.json files: FROZEN_BEFORE_RUN, recomputed `code_sha256` == frozen, per-case `source_sha256` all match; every journal row carries the frozen code+source hashes.
2. **Role matrix recount (own binary mapping, gold read post-run).** Exact match to all reported numbers: D_V1_gptoss TP6/FP0/FN0/TN6 F1 1.0; D_V1_gemma TP5/FP0/FN1 .9091 (FN = dev_inclusive_timezone::02, 1s-after-deadline); D_V1_mistral TP6/FP1 .9231 with FP ids == [dev_units::00] (5/6 B_V0 FPs repaired); D_V1_nemotron TP6/FP0/TN5+1 UNKNOWN (on a CLEAN case → no hidden miss); EJ_gptoss_gptoss/J and X_gptossE_gemmaJ/J 6/6; Gk3 arms TP5/FP0/FN1; B_without_A 6/6 ERROR. 174 rows, no duplicate (arm,id).
3. **B_V0 reference.** Archived v4 `strict_always` (mistral, V0): ERROR on ALL 12 bank cases (TP6/FP6). Archived C0 primary on bank: 5 ERROR + its known FN (inclusive_timezone::02) + 6 NO_ERROR on clean.
4. **V1 calibration actually used (cryptographic).** Recomputed `request_sha256` from `role_prompts.DIRECT_V1` (V0+CALIBRATION) + rebuilt payloads: byte-equal to journaled hashes for D_V1_gptoss/gemma/mistral and Gk3 s11/s22 ({temperature, seed} in the hash preimage). Deferred: C0_J_control recomputed from `judge.JUDGE_SYSTEM`+`build_judge_user` matches (official V0 control), D arms match DIRECT_V1 — the calibration text is provably in the measured system prompts.
5. **Quote verbatimness (5/5).** D_V1_gptoss ERROR (dev_necessary::00), D_V1_mistral FP (dev_units::00), EJ_gptoss_gptoss/J checker (dev_necessary::00), C0_J_control ERROR FP (def_temporal_new::01), D_V1_gptoss NO_ERROR (def_temporal_new::01, type NONE, empty quotes): every nonempty quote is a verbatim substring of the named source.
6. **Gk3.** 12/12 cases: 3 distinct request_sha256 (seeds 11/22/33 in the hash), temperature 0.7 recorded in every call record, labels identical across seeds (majority == single sample). See R-202 for the content caveat.
7. **G3 counterevidence.** 5 accusations (checker had 0 FP), 5/5 NOT_REFUTED, `refutes` false ×5 — no false refutation, as claimed.
8. **B_without_A anchoring test.** Archived B-with-A rows have non-empty `findings` on all 6 error cases and decided ERROR; B_without_A (findings=[]) also ERROR (label 1) on all 6 — no case where A's presence flipped the verdict.
9. **Deferred recount.** 54 rows, 18 complete triples (first 18 frozen ids — round-robin honored), 0 incomplete, 6 unmeasured (def_effect_new::05, def_mixed::00-02, def_perm_new::06-07; 4 error + 2 clean), all declared. Recount: C0 TP4/FP5/TN2/UNKNOWN7 .6154; gemma TP7/FP2/TN9 .875; gptoss TP7/FP0/TN11 1.0 — exact. C0's 5 FPs are all clean def_temporal_new; gptoss repairs ALL 5 (ERROR→NO_ERROR); gemma repairs 3/5, its 2 FPs are exactly the equal-instant constructions ::01 (+09:30 half-hour zone, 00:00+09:30 == 14:30Z deadline) and ::03 (+14:00 cross-day, 04:30+14:00 == 14:30Z) — as claimed. C0's 7 UNKNOWNs are all JSON-contract failures (bad source_refs / missing keys) on perm/effect cases.
10. **BUDGET_STOP accounting (own SQL).** reviewer_repair: SUM(api)=300 exactly, known 465984 ≤ 1M, logical 597414 ≤ 1.2M, unknown 593 ≤ 200k, pending 0, 984.4s ≤ 14400; ceilings exactly 300/1M/200k/1.2M. Modules: channel-probe 7 (= census, 7 probes / 4 independent families, aihorde non-independent) + atomic-v2 25 + role 189 + deferred 79 = 300; no unexplained modules, no TRANSPORT/RESERVED/BREAKER rows.
11. **Freeze-before-results timing (ledger timestamps).** Role calls 10:06:25–10:23:33Z after role freeze (10:06:24Z); deferred calls 10:25:16–10:28:51Z after deferred freeze (10:24:03Z) AND after commit 0a592cfb (10:25:15Z, which committed bank + deferred_pilot.py); nothing after the stop. The prepare() freeze guard makes post-hoc edits raise on the next run.
12. **dev2 ledger untouched.** md5 613bbdff848272b319ee691811c98116 (matches AUDIT-R1), 263 api / 805401 logical / 659829 known, last row 07:27:38Z (pre-assignment). Worktree clean.
13. **Calibration clauses grounded in the §5 atlas.** Each CALIBRATION clause maps to REPAIR_CAUSE_AUDIT §8 fixes/atlas mechanisms: no-error-is-valid↔F2/T9; observation-sufficiency↔F3/T5/T10; request-vs-execution↔T4/T12; stated-policy-governs↔F4a/T6; catalog vocabulary↔F4/T14; implications/converses↔F5/T15; absolute-instant inclusive deadlines↔T1/T7/T2. No ungrounded clause.

## Findings

### R-201 — MAJOR — score_roles.py / score_deferred.py (and receipts role_score.json, deferred_score.json)
**Counterexample:** EJ_gemma_gemma/J on dev_inclusive_timezone::02 (gold 1): both the vote
and its schema-repair reask returned fenced ```` ```json ```` with `"label": 0` — unparseable
per the strict JSON-only contract → counted UNKNOWN → excluded from P/R/F1 → reported
F1 1.0 ("1 abstention"). Under the frozen binary mapping ("INVALID/missing→UNKNOWN counts
correct-on-clean and miss-on-error") this row is a miss (FN): frozen-rule F1 = .9091
(= D_V1_gemma, same FN case — the gemma family temporal weakness reproduces in the EJ role).
Similarly C0_J_control's 7 UNKNOWNs include 3 on ERROR cases (def_perm_new::00,
def_effect_new::01, ::03): frozen-rule C0 = TP4/FP5/FN3/TN6, F1 0.5, vs reported .6154.
**Expected:** UNKNOWN → TN on clean / FN on error (and reported separately). **Actual:**
UNKNOWN excluded from TP/FP/FN/TN; F1 computed over valid rows only; UNKNOWN reported
separately (no silent NO_ERROR counting anywhere — the leakage question of this audit
returns "none found"). **Impact:** no headline conclusion flips (gptoss 1.0 and gemma .875
have 0 UNKNOWN; "EJ self-pipeline does not lose to direct" still holds at .9091 == .9091;
C0-weak-on-temporal holds at FP5; the C0 direction is conservative for the fix-chain
claim). **Re-check:** before freezing the final comparison, dual-report the affected
numbers (C0_J_control .6154 valid-only / .5 frozen-rule; EJ_gemma_gemma/J 1.0 / .9091) or
re-run the scorers with the frozen mapping; state that nemotron's abstention (clean case)
leaves its F1 unchanged under either mapping.

### R-202 — MINOR — role_pilot journal, Gk3 arms
**Counterexample:** dev_inclusive_timezone::02 and dev_negative_scope::02: the three seed
arms produced only 2 distinct answer contents (one seed's answer is byte-identical to
another's). **Expected (commit message):** "seeds honored (contents differ)". **Actual:**
contents differ in 10/12 cases; request hashes differ in 12/12 (seeds provably sent);
labels stable in 12/12 at temperature 0.7. **Impact:** none on the correlated-samples
conclusion (hashes+labels are the operative facts). **Re-check:** word the final report as
"request-level sampling honored; contents differ in 10/12; labels stable 12/12".

### R-203 — MINOR — role_pilot/selection.json vs role_predictions.jsonl
**Counterexample:** frozen `arms` list contains 11 arms including `X_gemmaE_gptossJ`; the
journal (174 rows) covers only 10 — the reverse cross direction (gemma extractor →
gpt-oss judge) was never measured. The forecast allocated only "cross +24" (one direction)
and the commit message claims only X_gptossE_gemmaJ. **Expected:** measured arms ⊆ frozen
arms with unmeasured arms declared. **Actual:** undeclared in selection.json (status is
SUCCEEDED, not partial). **Re-check:** the final report/shortlist must list
X_gemmaE_gptossJ as not measured; do not imply symmetric cross evidence.

### R-204 — NOTE — reviewer_repair ledger row 382 / deferred journal
The 300th API attempt (modular/deferred/C0_J_control/0, COMPLETE, 1336 tokens, 10:28:51Z)
is the first attempt of the would-be 55th row (def_effect_new::05); its vote failed
contract validation and the reask's reserve hit the 300 ceiling → BudgetStop → the row
was never appended to predictions.jsonl. Accounting honest (300/300); the answer never
entered any score; flag only so the 1-attempt gap between ledger (79 deferred api) and
journal (78 journaled calls) is not mistaken for tampering.

### R-205 — MINOR — git provenance timing of the deferred scorer and receipts
**Counterexample:** score_deferred.py first appears in da654292 (10:32:58Z, post-run),
while deferred_pilot.py + bank + build_deferred_bank.py were committed pre-run at 0a592cfb
(10:25:15Z, first deferred call 10:25:16Z). repair_receipts/deferred_selection.json is
likewise a post-run commit of the pre-run results-dir artifact (selection.json written
10:24:03Z; content pinned by code_sha256 + bank hashes to the pre-run-committed state).
Similarly role block 1 (10:06:25–10:11Z) ran ~5 min before role code was committed
(2efb7163, 10:11:59Z) — the selection code_sha256 chain covers the code that ran.
**Expected:** scoring code under git provenance before results are viewed. **Actual:**
rules were frozen pre-run (selection.json + hash chain) and my independent recount from
the raw journal + frozen gold reproduces every number exactly, so there is no evidence of
tuning — but the scorer file itself lacked provenance at run time (same class as AUDIT-R1
R-106). **Re-check:** for the final freeze, commit scorers before any future run; cite
the hash chain (selection.json 10:24:03 → ledger 10:25:16) as the freeze evidence, not the
receipt commit.

### R-206 — NOTE — score_roles.py systems table, G3_counterevidence row
The G3 row scores UNKNOWN×12 / F1 0.0 because the counterevidence JSON has no `label`
field; the meaningful G3 result (5/5 NOT_REFUTED, refutes=false) exists only in the
journal and commit message. Harmless as long as the final report does not quote the G3
table row as a "0.0 F1" result. Verified separately (item 7 above).

## Verdict: **PASS_WITH_LIMITS** (for freezing the final comparison)

Every number in the §8 role matrix and §9.6 deferred comparison that I could recompute from raw journals, frozen gold, archived references and the ledger reproduces exactly (per-arm TP/FP/FN/TN, transitions, 300/300 budget with 465984/597414/593 tokens, freeze timing by ledger timestamps, quote verbatimness 5/5, request-hash proofs that the V1 calibrated contract and the official V0 control were actually sent, B_V0/B_without_A anchoring null, Gk3 seed integrity, G3 5/5 NOT_REFUTED); no silent NO_ERROR or INVALID leakage exists. Limits: R-201 (implemented F1 excludes UNKNOWN instead of the frozen correct-on-clean/miss-on-error mapping: C0_J_control .6154→.5 and EJ_gemma_gemma/J 1.0→.9091 under the frozen rule — dual-report at freeze), R-202/R-203 (Gk3 contents differ 10/12; frozen arm X_gemmaE_gptossJ never measured), R-205 (post-run git provenance of the deferred scorer, mitigated by the pre-run rule freeze + exact independent reproduction). None flips a headline conclusion: the causal fix chain (B_V0 6 FP → V1 calibration → 0–1 FP across families), gpt-oss:20b perfect on both banks, the gemma equal-instant temporal weakness, and the deferred new-input confirmation all stand as measured. Freeze is acceptable once R-201's dual numbers and the unmeasured-arm/unmeasured-case disclosures (18/24 triples, X_gemmaE_gptossJ, 6 unmeasured bank cases) are stated in the final report.
