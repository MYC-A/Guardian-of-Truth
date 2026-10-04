# Oracle decomposition (valid46 ref15; diagnostic only)

Oracle arms read gold reference spans. They exist only to locate the bottleneck. They are never candidates for production. n = 15 rows (9 positive, 6 negative), 1 run.

| Arm | Evidence given | Complete ref sets (offline) | Packet size | TP | FP | FN | F1 | reason-correct TP |
|---|---|---|---|---|---|---|---|---|
| A (U2 20k) | retrieval | 6/15 | ~17.4 KB | 6 | 1 | 3 | 0.750 | 4 |
| B (U2 48k) | retrieval | 13/15 | ~40 KB | 3 | 3 | 6 | 0.400 | 2 |
| ORACLE_E | gold spans only + targets/declarations + last user | 15/15 | ~13.4 KB | 6 | 2 | 3 | 0.706 | 5 |
| ORACLE_R | A, then a 2nd packet with the gold spans A missed | 15/15 (union) | — | 7 | 2 | 2 | 0.778 | 5 |
| G4_S (best non-oracle) | A + recursive gap search | 6/15 → (extra units) | — | 7 | 1 | 2 | 0.824 | 5 |
| D3 / D2-sticky | A + gap packets | 11/15 (D3) | ~43 KB | 7 | 1 | 2 | 0.824 | 5 |

## Decomposition
1. **Retrieval is not the main bottleneck on ref15.** Perfect evidence (ORACLE_E: every required norm and history span, nothing else) does not beat A: F1 0.706 vs 0.750, with the same TP count. It also adds one FP. Recall stays at 6/9 even with 100% of the needed evidence.
2. **More complete evidence through a bigger window hurts.** B holds 13/15 complete sets yet falls to F1 0.40. Completeness is not the variable that drives accuracy. Dilution is (see the 20k/48k diagnosis in MULTIPACKET_RESULTS.md).
3. **Supplying exactly the missing evidence as a second look (ORACLE_R)** gains +1 TP (one row fixed, one broken). That is the same size of gain as non-oracle second-pass arms and CTRL (same packet, sampled again).
4. **The errors left on ref15 are reasoning/decision errors.** The 3 ORACLE_E FNs, each with the needed evidence present:
   - airline__23: the reviewer anchored on the "no simultaneous tool call" norm and never compared the `payment_methods` fields with the tool schema.
   - retail__27: it read "the user confirmed" as covering both return *and* exchange of the same delivered order (policy: return OR exchange).
   - telecom mms…t7: it noticed `check_network_status` is not in the declared catalog and still rationalised the call as "permitted diagnostics".
   The 2 FPs (banking t30, retail__87) are over-strict REQUIRE readings (confirmation/prerequisites demanded when they are not required yet).

## Conclusion
On this data, the order of bottlenecks is: (1) reviewer judgement and stability (sampling variance of a single T=0 call over the cached attempts, and leniency on long contexts) > (2) context dilution > (3) evidence coverage. Oracle Questions and Oracle Relations arms (spec §11) were **not run**: ORACLE_E already shows that complete evidence does not fix the verdict, so they would not change this decision. They stay open for a future suite where the evidence is complete but the reasoning fails on multi-hop rules.
