# Gap controller results (G0–G4)

| Level | Implementation | Arms |
|---|---|---|
| G0 | no controller (A) | A |
| G1 | static gap packet from A's open questions | D2 |
| G2 | evidence sufficiency of the *proposed* claim: deterministic PRIORITY search for the conditions/exceptions of the cited norm, facts and entity bindings → ledger review | G2_S (4 hops/8k chars), G2_L (8/16k) |
| G3 | independent missed-obligation scan: blinded (B) vs verdict-seeing (V) | G3B, G3V |
| G4 | recursive: questions → tools → typed QA answers (ESTABLISHED/REFUTED/UNKNOWN) → follow-ups (≤2 rounds, depth ≤1) → final review | G4_S, G4_L |

The tools are deterministic (`retrieve_relevant`, `read_policy_neighbors`, `lookup_entity`, `find_call_results`). They dedupe, skip cycles and enforce hop/char budgets. The LLM never chooses a tool.

## SYN-M1 final (3 reps)
| Arm | F1 mean [min–max] | TP | FP | rcTP | DIFF | calls | prompt tok/row | rows better/worse vs A | success |
|---|---|---|---|---|---|---|---|---|---|
| A | 0.789 [0.750–0.818] | 16.3 | 2.0 | 14.0 | 2.3 | 1.0 | 3.5k | — | — |
| G2_L | 0.790 [0.750–0.829] | 16.3 | 2.0 | 14.7 | 1.7 | 1.7 | 6.6k | 1/1 (p=1) | no |
| G2_L sticky | 0.799 | 16.7 | 2.0 | n/j | | 1.7 | 6.6k | 1/0 | no |
| G4_S | 0.792 [0.732–0.826] | 17.3 | 3.3 | 14.3 | 3.0 | 3.4 | 12.3k | 4/6 (p=0.75) | no |
| CTRL (reference) | 0.819 | 17.3 | 2.0 | 15.0 | 2.3 | 1.8 | 6.8k | 5/2 | no |

Strata: G4_S has the highest FACT_NUMBER recall (0.56 vs A 0.39) but the FP rate rises from 0.087 to 0.145. G2_L equals A on every stratum.

## valid46 pilot (run 1)
| Arm | TP | FP | F1 | rcTP | DIFF | fixed/broke | calls | prompt tok/row |
|---|---|---|---|---|---|---|---|---|
| A | 13 | 2 | 0.684 | 8 | 5 | — | 1 | — |
| G2_S | 15 | 2 | 0.750 | 11 | 4 | 2/0 | 1.74 | 6.4k |
| G2_L | 14 | 2 | 0.718 | **12** | **2** | 2/1 | 1.74 | 7.0k |
| G3B blinded scan | 16 | **11** | 0.640 | 10 | 6 | 3/9 | 2.35 | 9.3k |
| G3V verdict-seeing | 15 | 4 | 0.714 | 10 | 5 | 2/2 | 2.09 | 8.1k |
| G4_S | 16 | 2 | **0.780** | 11 | 5 | 3/0 (p=0.25) | 3.39 | 13.2k |
| G4_L | 16 | 3 | 0.762 | 11 | 5 | 3/1 | 3.41 | 14.5k |

## Controller behaviour (`reports/stats_*.json`)
- **G2:** always stops on BUDGET_EXHAUSTED (8 hops at L). Mean questions 10.5–10.9; mean units added 9.3; loops prevented 3 on valid46 and 14 on SYN run 1. The question mix is dominated by MISSING_EXCEPTION_CHECK (193) and MISSING_ENTITY_BINDING (79).
- **G4_S:** mean 3.1 hops. Stops: BUDGET_EXHAUSTED 19, NO_OPEN_QUESTIONS 10–11, HOP_BUDGET 2. Depth-1 follow-ups: 16 on valid46. QA answers: valid46 150 answered → 104 ESTABLISHED (69%); SYN run 1 193 → 124 (64%). 4 rows ended degenerate with NO_NEW_EVIDENCE. Latency is 18–28 s/row vs ~5 s for A.
- **BFS / DFS / PRIORITY:** at these budgets, the offline deterministic-only variants reach identical ref15 coverage (6/15; `offline/rows.json`), so an LLM-level comparison was not run (not tested, not "no difference"). The order only matters at larger budgets, where dilution already hurts.

## Missed-obligation search (G3)
- **Blinded scan (G3B):** it flags 14 label-0 rows vs 8 label-1 rows, i.e. it fires more on *correct* moves. Rechecks fixed 3 FNs and introduced 9 FPs. Independence from the verdict buys no precision.
- **Verdict-seeing (G3V):** 2 fixed / 2 broken, net zero.
- Missed-obligation recall is limited by the same reasoning failure as the first pass. A scan that does not see the move's context reads every REQUIRE norm as applicable.

## Answers
- **The gap controller on its own (G2, non-recursive):** it is safe (never worse than A by more than 1 row; FP unchanged) and it gives the cleanest reasons: on valid46, 12/14 reason-correct TPs and only 2 DIFFERENT. It does not add detections on SYN. Its value is **reason grounding**, not recall.
- **Recursion (G4) vs a fixed pass:** it finds more TPs (+1 on SYN, +3 on valid46) but adds FPs on SYN (+1.3) and costs 3.4 calls and 3.5× tokens. Net F1 is equal to A on SYN and below CTRL. Not justified at this cost.
- **Graph/ledger value:** the typed ledger is useful as an *audit structure*: no EXACT promotion, cycle prevention, explicit UNKNOWN. It does not improve verdicts. On SYN, the D/G2 continuation with a ledger is the most conservative family (FP = A).
