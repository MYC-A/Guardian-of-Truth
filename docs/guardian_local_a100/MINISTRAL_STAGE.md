# Ministral-3-14B local A100 stage — CLOSED (2026-10-07)

Owner directive (2026-10-07): close the Ministral stage, do not launch new
Ministral cells, do not wait for the rest of the previously queued verification
batch; finish the currently executing cell only, keep everything obtained,
recompute offline with corrected decision accounting, commit and push.

## 1. What was executed (all cells COMPLETE, rep 1, model_id
`ministral-3-14b-instruct-2512@29439f81c2be:bf16:vllm-0.31.0`, vLLM bf16)

| set | variants | rows |
|---|---|---|
| dev, devT, frozen, contrast | AM (A+M from one execution), B, Bopen, T, E, L | 10/8/14/14 |
| valid46 | AM, B (pre 1700), B2 (pre 3400), L | 46 |
| lb_long | AM, B2, L | 57 |
| ext_tau2 | AM, B2, L | 70 (68 binary gold; 2 unlabelled in coverage only) |
| lb2_long | AM, B2, L | 47 |
| lb3_long | AM, B2, L | 56 |
| hold_tau2h | AM only (the in-flight cell, completed 51/51 before the queue was stopped) | 51 |

Postponed (NOT executed, NOT deleted — available for the final full-evaluation
phase on the selected candidates): hold_tau2h L/B2, hold_holdout2 (all variants).

## 2. Scorer fix (offline re-classification; zero new inference)

`score_local.py` now separates four mutually exclusive row classes:

- `verdict` — valid final decision through the variant's intended path;
  for B2 the blind analysis was actually DELIVERED to the review request
  (created-but-not-transmitted is NOT a delivered pre-pass);
- `fallback` — valid decision via a degraded path: review valid but the blind
  analysis was not delivered (a B-variant row then behaves as plain AM), or the
  strict layers/verifications were technically unavailable so the model rule
  alone decided;
- `extra_pass` — valid verdict while an optional additional pass did not execute;
- `no_solution` — no valid decision at all (review transport/parse failure,
  exception, decision field absent). NEVER scored as NO_ERROR: excluded from
  the confusion matrix (the previous scorer scored such rows by their raw
  binary field, which could silently inflate TP/TN).

TP/FP/FN/TN are computed over verdict+fallback rows (valid decisions);
`clean` repeats the matrix over verdict-only rows. Full re-classification of
all saved records: `recompute.json` (network_calls=0). Numbers in earlier
commit messages (pre-fix) differ where no_solution rows were previously
scored by their raw binary field, e.g. ext_tau2 L: previously reported
TP38 FP1 F1 .835 -> honest TP37 FP1 F1 .831 (1 row had no valid decision);
valid46 AM TP13 -> TP12 (nosol=1); Bopen frozen TP5 -> TP4 + nosol=1.

## 3. Honest reclassified results (recompute.json, binary gold only)

| set | variant | TP | FP | FN | TN | F1 | verdict/fallback/extra/nosol | pre-pass delivered |
|---|---|---|---|---|---|---|---|---|
| dev | A/M | 2 | 1 | 4 | 3 | .444 | 10/0/0/0 | — |
| dev | B | 6 | 0 | 0 | 4 | **1.000** | 10/0/0/0 | 10/10 |
| dev | Bopen | 4 | 0 | 2 | 3 | .800 | 9/0/0/1 | 10/10 |
| dev | T | 6 | 2 | 0 | 2 | .857 | 10/0/0/0 | 10/10 |
| dev | E | 6 | 2 | 0 | 2 | .857 | 10/0/0/0 | 10/10 |
| dev | L | 3 | 1 | 3 | 3 | .600 | 10/0/0/0 | — |
| devT | B | 5 | 1 | 1 | 1 | .833 | 8/0/0/0 | 8/8 |
| devT | T | 6 | 0 | 0 | 2 | **1.000** | 7/1/0/0 | 7/8 (1 not delivered) |
| devT | E | 5 | 0 | 1 | 2 | .909 | 7/1/0/0 | 7/8 (1 not delivered) |
| frozen | B | 6 | 0 | 1 | 7 | .923 | 14/0/0/0 | 14/14 |
| frozen | Bopen | 4 | 2 | 2 | 5 | .667 | 13/0/0/1 | 14/14 |
| contrast | B | 6 | 0 | 1 | 7 | .923 | 14/0/0/0 | 14/14 |
| contrast | Bopen | 5 | 0 | 2 | 7 | .833 | 14/0/0/0 | 14/14 |
| valid46 | A/M | 12 | 9 | 10 | 14 | .558 | 43/2/0/1 | — |
| valid46 | B | 12 | 9 | 10 | 14 | .558 | 7/38/0/1 | **7/46 delivered** (35 length-truncated pre-pass) |
| valid46 | B2 | 14 | 9 | 9 | 13 | **.609** | 24/21/0/1 | **26/46 delivered** (20 still truncated at 3400) |
| valid46 | L | 13 | 11 | 9 | 12 | .565 | 44/1/1/1 | — |
| lb_long | A/M | 23 | 2 | 5 | 27 | .868 | 50/7/0/0 | — |
| lb_long | B2 | 25 | 4 | 3 | 25 | **.877** | 51/6/0/0 | 57/57 |
| lb_long | L | 25 | 4 | 3 | 25 | .877 | 50/7/0/0 | — |
| lb2_long | A/M | 19 | 5 | 4 | 19 | .809 | 46/1/0/0 | — |
| lb2_long | B2 | 21 | 1 | 2 | 23 | **.933** | 46/1/0/0 | 47/47 |
| lb2_long | L | 19 | 5 | 4 | 19 | .809 | 45/2/0/0 | — |
| lb3_long | A/M | 26 | 5 | 2 | 23 | .881 | 54/2/0/0 | — |
| lb3_long | B2 | 26 | 4 | 2 | 24 | **.897** | 55/1/0/0 | 56/56 |
| lb3_long | L | 24 | 4 | 4 | 24 | .857 | 55/1/0/0 | — |
| ext_tau2 | A/M | 36 | 2 | 15 | 14 | .809 | 62/5/0/1 | — |
| ext_tau2 | B2 | 35 | 3 | 17 | 13 | .778 | 62/6/0/0 | 70/70 |
| ext_tau2 | L | 37 | 1 | 14 | 15 | **.831** | 67/0/3/1 | — |
| hold_tau2h | A/M | 25 | 5 | 15 | 5 | .714 | 46/4/0/1 | — |

(only AM/B/B2/Bopen/T/E/L rows shown; full tables in recompute.json /
score_verification.json; RU/EN and family splits included there.)

## 4. Stage conclusions (Ministral local, frozen control)

- Blind pass B remains the best architecture on short diagnostics
  (dev F1 1.0 / frozen .923 / contrast .923) and beats its equal-call open
  control Bopen everywhere — the blindness effect reproduces on the local model.
- On real long sets B2 is the best arm on lb_long (.877), lb2_long (.933),
  lb3_long (.897) with 100% pre-pass delivery on lb*/ext_tau2; on valid46
  (longest inputs) B2 delivers only 26/46 — 21 rows decided via valid fallback.
- OLD v6fix (L) is the best arm only on ext_tau2 (TP37 FP1, P .974).
- Honest transfer vs historical API ministral: valid46 .609 (B2) vs .732 API —
  the local model is markedly more accusation-prone (FP 9 vs 3); lb_long .877
  vs .830 API; ext_tau2 .831 (L) vs .809 API. A==M on every set so far — the
  strict new v6fix layers add nothing on this model.
- No further Ministral experiments will be launched (owner directive);
  the cell is frozen as the completed control for the model comparison.

## 5. Weight cleanup

vLLM server stopped and the Ministral-3-14B bf16 blobs
(snapshots/29439f81c2be) deleted after this commit+push; runs, receipts,
attempt ledgers and recompute artifacts remain in git. The checkpoint can be
re-downloaded at the pinned revision if the final phase needs it again.
