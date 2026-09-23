# Local validation (2026-09-23)

All results below use the viewed public46 development set. No new Mistral or
Granite model inference was run locally.

| Check | Result |
|---|---|
| New regression checks plus existing X5 tests | 12 passed |
| Q dry selection | 12 deep candidates from 12 distinct cases, across airline, retail, telecom and banking domains |
| S7 saved-score reinterpretation | 103 suspicions from 23 cases; `any risk=no` diagnostic TP2/FP3/FN11/TN7 |
| Typed fixed router, 4 executed tools | 46 cases, 165 tool observations; base and guarded output TP23/FP16/FN0/TN7, 16 safe-card candidates, zero automatic flips |
| C2 → X5 saved-proposal replay | 44/46 schema-valid paired cases; X5 C0 and C2 both TP7/FP0/FN16/TN21; zero binary changes; 12 `PROVED_NO_ERROR` → `UNRESOLVED` |
| Resume check | Dry Q, S7, holistic and two-case typed router successfully reopened matching configs with `--resume` |

An earlier unrestricted test of the typed router promoted a matched card's
`safe` verdict into whole-response clearance and changed TP23/FP16 to
TP17/FP12. It removed four FP but lost six TP. The guarded controller keeps
these cases as review candidates and preserves the base label. This is the
reason for the explicit 1→0 boundary in `agent/run.py`.

The server agent should preserve the per-case `records.jsonl` for every run,
not only the aggregate F1, and identify any cases where the score changes.
