# Final decision — multipacket / gap controller v1

## Verdict
**No multi-packet, sequential, gap-controller or recursive arm meets the pre-registered success rule against A (U2 20k) on SYN-M1.** All p-values are ≥ 0.29 except B, which is significantly *worse* (p=0.09). **A stays the production default.**

| Rank (SYN F1) | Arm | F1 | rcTP | calls | Verdict |
|---|---|---|---|---|---|
| 1 | CTRL (A ×2 + aggregator, no new evidence) | 0.819 | 15.0 | 1.8 | best, not significant (5/2 rows) |
| 2 | G4_S recursive | 0.792 | 14.3 | 3.4 | = A, +FP, 3.4× cost → reject |
| 3 | G2_L gap sufficiency | 0.790 | 14.7 | 1.7 | = A, best reason purity → optional audit mode |
| 4 | **A U2 20k** | **0.789** | 14.0 | 1.0 | **keep** |
| 5 | D1 / D2 | 0.770 / 0.757 | 14.0 | 1.7 | no gain → reject |
| 6 | C1 parallel | 0.759 | 13.7 | 2.0 | +FP → reject |
| 7 | FULL | 0.753 | 13.3 | 1.0 | reject |
| 8 | B U2 48k | 0.729 | 12.3 | 1.0 | worse → reject |
| — | C2 policy/evidence split | valid46 0.488 | — | 1.7 | harmful → reject |
| — | G3B blinded scan | valid46 0.640 | — | 2.4 | +9 FP → reject |

## Recommendation at reasonable cost
1. **Keep A (U2 20k, 1 call).**
2. If a second call is affordable: **self-consistency (CTRL)**, i.e. A twice (attempt 0/1) with the structured aggregator. It is the best arm on both suites (+0.03 F1 on SYN, +0.06 on valid46) at 1.8 calls and with no extra evidence code. It has not passed the significance bar, so ship it behind a flag and confirm on a fresh labelled set.
3. Optional **G2 as an audit/explanation mode**: it does not change verdicts much, but it yields the most grounded reasons (valid46: 12/14 reason-correct TPs, 2 DIFFERENT).

## Safe to port now
- Packer hooks `extra_queries` / `exclude_uids` / `shared_anchors` (opt-in; defaults byte-identical).
- `multipacket.ledger` (typed claims, no EXACT promotion, cycle detection, R1 flags) as an audit structure.
- `multipacket.controller` (deterministic, bounded, deduped tool search) as a library. Off by default.
- Analysis tools: `diag_20k_48k`, `r1_offline`, `syn_strata`, `aggregate`, `stats`.

## Not to port
B/FULL as the default, C2, G3B, G4 in the hot path, and R1 as a veto (it never fires on admitted ERRORs).

## Hypotheses not confirmed / not tested
- Not confirmed: "more evidence → better verdicts" (B, D3, ORACLE_E); "gap-directed > fixed second pass" (D2 = D1); "independent blinded obligation search raises recall without FP" (G3B); "recursion beats fixed search" (G4 ≈ A).
- Not tested: Oracle Questions / Oracle Relations arms; full E ablation matrix; BFS/DFS at the LLM level (offline coverage identical); D3 / G3 on SYN (not selected); a second reviewer model (gemma / gpt-oss as the reviewer); hidden/official data; missed-obligation and exception errors in a synthetic suite (SYN-M1 contains only fabrication/contradiction mutations).

## Next step suggested
A **move-vs-evidence verifier** (deterministic extraction of the IDs, amounts and fields in the current call or claim → exact comparison with the last tool results and the tool schema, fed to the reviewer as EXACT facts). It targets the dominant failure (FACT_NUMBER recall 0.39 with the evidence present) without adding context.
