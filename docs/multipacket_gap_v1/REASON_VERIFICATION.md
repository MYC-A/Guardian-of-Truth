# Reason verification (R0–R3)

| Level | What it checks | Implemented | Result |
|---|---|---|---|
| R0 | schema admission: target exists, norm IDs exist, evidence actor matches its source (I4 `admit`) | yes (all arms) | 1 technical null per arm on valid46 (same row as U2); rejected replies count as 0 |
| R1 | programmatic checks: target valid, norms exist, actor correct, cites the current target, has a norm, **historical-only accusation** | yes (`ledger.programmatic_check`), offline on frozen replies | see below |
| R2 | evidence sufficiency: the gap controller searches for the conditions/exceptions of the cited norm and for facts/bindings of the claim (G2), with answers typed ESTABLISHED / REFUTED / UNKNOWN (G4) | yes (G2, G4) | see GAP_CONTROLLER_RESULTS.md |
| R3 | semantic agreement with gold explanation (gpt-oss:120b judge, SAME/PARTIAL/DIFFERENT) | evaluation only | the main reason metric below |

## R1 offline (valid46, frozen 3 runs, ERROR verdicts only, `reports/r1_offline.json`)
| Arm | ERROR verdicts | TP pass / fail | FP pass / fail | cites no current target (TP / FP) |
|---|---|---|---|---|
| U2_20k | 53 | 43 / 0 | 10 / 0 | 10 / 2 |
| U2_48k | 40 | 26 / 0 | 14 / 0 | 12 / 4 |

R1 never fails on an admitted ERROR: R0 admission already removes structurally invalid replies, and the historical-only pattern never occurs. "Cites no current target" is *more* frequent on TPs than on FPs, so it cannot be used as a veto. **R1 does not discriminate** on this data. Its value is as a guard, not as a filter.

## R3: reason correctness (valid46 run 1, TPs judged)
| Arm | TP | SAME | PARTIAL | DIFFERENT | reason-correct (S+P) | FP |
|---|---|---|---|---|---|---|
| A | 13 | 5 | 3 | 5 | 8 | 2 |
| B | 11 | 4 | 5 | 2 | 9 | 4 |
| FULL | 10 | 5 | 4 | 1 | 9 | 3 |
| CTRL | 16 | 7 | 3 | 6 | 10 | 4 |
| C1 | 14 | 4 | 6 | 4 | 10 | 4 |
| D1 | 13 | 8 | 2 | 3 | 10 | 2 |
| D3 | 14 | 6 | 4 | 4 | 10 | 2 |
| G2_S | 15 | 5 | 6 | 4 | 11 | 2 |
| G2_L | 14 | 6 | 6 | 2 | 12 | 2 |
| G4_S | 16 | 8 | 3 | 5 | 11 | 2 |
| G4_L | 16 | 9 | 2 | 5 | 11 | 3 |

- Sequential continuation with a typed ledger (D1/D2/G2_L) mostly **re-grounds** A's existing TPs: D1 keeps the TP count (13) but turns DIFFERENT 5 → 3 and SAME 5 → 8. G2_L has the best reason purity (12/14 correct, only 2 DIFFERENT).
- Arms that add TPs (CTRL, G4) add about half of them with DIFFERENT reasons. The extra detections are partly "right for the wrong reason", as with the earlier U2 finding.
- SYN-M1 reason correctness: see MULTIPACKET_RESULTS.md (mutation-grounded check: the judge compares against the injected mutation description).
