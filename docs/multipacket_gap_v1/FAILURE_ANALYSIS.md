# Failure analysis

## Where errors come from
| Failure class | Evidence | Share / size |
|---|---|---|
| **Verification failure with evidence present** | SYN: 22/23 positives contain the original value inside A's packet, and 6 of those are caught in ≤1/3 runs. ORACLE_E on ref15 still has 3 FN with 100% of the required spans. | dominant |
| **Leniency under long context (dilution)** | 48k/FULL ERROR rate on positives 26–27/69 vs 20k 43/69 (valid46, 3 runs); B worse on 10 SYN rows vs better on 3 | consistent, large |
| **Sampling instability** | A run-to-run: 9–10 of 46 SYN decisions change between attempts; CTRL gains come purely from resampling | ~20% of rows unstable |
| **Over-strict REQUIRE readings (FP)** | ORACLE_E FPs (banking t30, retail__87); G3B blinded scan fires on 14 label-0 rows | main FP source |
| **Retrieval misses** | A ref15 complete sets 6/15, but completing them (B 13/15, ORACLE_E 15/15) does not raise TP | minor for the verdict |
| **Aggregation FPs** | C1 / G4 on SYN: FP 3.3–3.7 vs 2.0 (an OR over more independent looks) | moderate |
| **Technical** | 1 schema-admission null per arm on valid46; B/FULL 2.7–3 tech nulls/run on SYN (long prompts) | small |

## Typical FN patterns (ORACLE_E / A, valid46)
1. **Anchoring on a salient generic norm** ("no simultaneous tool call + reply") instead of checking the tool schema or the arguments (airline__23 payment_methods fields).
2. **Over-broad reading of user confirmation** (retail__27: return *and* exchange of one delivered order).
3. **Rationalising an undeclared tool** (telecom check_network_status: noticed it is missing from the catalog, still "permitted diagnostics").
4. **SYN FACT_NUMBER:** the changed amount or count is not cross-checked against the earlier tool result (A recall 0.39). CALL_ARG_ID (wrong ID in a call) is much easier (0.82).

## What did not fail
- No arm produced cycles or unbounded search; all controller budgets held.
- No EXACT promotion of model claims (ledger tests).
- With default hooks, packer output is byte-identical to U2 (138/138 requests).

## Implications
The next gains are in **verification of the move against the evidence already in the packet**: an explicit field-by-field / value-by-value comparison of the current call or claim against the last tool results and the tool schema, plus stability (self-consistency). More context or deeper search will not supply these.
