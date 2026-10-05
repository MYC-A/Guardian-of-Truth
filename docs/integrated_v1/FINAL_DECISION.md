# Final decision: integrated v1

## Recommended default
**`profile=guard` (A2): corrected U2 20k + direct I4 reviewer + declaration guard**, via `guardian_truth.integrated.review` / `guardian-review --profile guard`.
- The pre-registered A2 rule holds: the guard added 0 FP in every scored run, and it added 1 mechanically proven, cause-correct TP on valid46.
- Mistral valid46: F1 0.681 vs A1 0.659.
- This is the best measured configuration of the new unified path. The archived Guardian OR Granite system (0.889 on the same 46 rows) is a different, older stack and has not been reproduced here.

## Shadow / off
| Component | Status | Why |
|---|---|---|
| A3/A4 frozen relations + controller (`integrated`) | **off** | Pre-registered comparison failed. Mistral valid46: 0.492 vs 0.659 (4 better / 7 worse). SYN-M1: 0.725 vs 0.768 (2/8). The cause is reassurance/dilution from non-decisive confirmations |
| A3g/A4g decisive-gated relations (`integrated_gated`) | **shadow candidate** | Post-hoc (amendment 2). valid46 0.686 vs 0.659 (3/1, p=0.63). SYN-M1 0.833 vs 0.768 (2/0, p=0.5). ccTP +1.3 on valid46 and +2.7 on SYN-M1. Not significant; SYN-M1 is authored/seen and overlaps the relations by construction. A new independent lockbox is needed before it becomes the default |
| Conditional controller pass | **off** (kept in code) | Fires on 1–4/46 rows; changed one decision in 13 runs; +3–9% calls |
| Gemma reviewer | **not decided** | A1 complete (F1 0.611; 82% of TPs wrong-cause). Integrated run partial 16/46 (Ollama monthly limit); paired pilot identical across arms |

## Defects
**Fixed** (ISSUES_AND_FIXES.md):
- D1: error receipts. This is the only one reached by real data: 13/46 rows.
- D2, D3, D5, D6, D7, D8, D9, D12.
- D4: framing ambiguity is now reported as a gap. It cannot be resolved in a text transport.

**Unfixed and documented:**
- D10: compact v2 polarity; that interface is not in the path.
- D11: research_v5 supersession by tool name; not in the path.
- The I4 receipt-actor admission contract. A tool receipt has role `assistant`, and `system` is rejected; this caused 2–5 rejections per run, among them a gold-positive row.
- Relations: `ID_LIKE` misses digit-free placeholder IDs, and provenance does not distinguish "observed only in the assistant's own earlier calls".
- Unavailable-tool calls stay a gap: the catalog audit is incomplete and no closed-universe contract exists.

## Honest scope
- valid46 is development data.
- SYN-M1 is authored, previously seen and derived from valid46.
- No independent external holdout was available.
- The SSH server was unreachable, so there was no raw readmission of historical caches; phase0 is saved-prediction replay.
- n = 46, and differences of 1–4 rows are within noise. The cause judge is self-judging for Mistral reasons (amendment 3).
- Not "universal" and not "production-ready". Verified scope: this input format (tau-style SYSTEM/USER/ASSISTANT transcript with `[AVAILABLE TOOLS]`), Linux, Python 3.13, two remote model families.

## Cost of this phase
| Ledger | Sent | OK | Tokens |
|---|---|---|---|
| Mistral reviewer | 526 | 526 | 2.68M |
| Ollama Gemma | 218 | 62 | 0.32M (156 × 429 monthly limit) |
| Judge | 687 | 194 | 0.12M (493 × 429; rate limit, then paced) |

All of it is within the frozen caps.

## Review (substitute for subagents)
No subagent tool was available in this environment. A separate self-review pass was done after implementation, and its findings were turned into checks:
1. **Offline replay** of a full run from the cache, with sockets blocked: 46/46 identical decisions, 0 HTTP.
2. **Fresh venv install + installed CLI** replaying SYN rows offline: OK.
3. **Byte-identity:**
   - A1 requests are identical to the historical I4 body (46/46).
   - Gated requests are identical to A1 when there is no decisive fact (test).
   - The ported guard is equal to the experiment guard (test).
4. **FREEZE code hashes after the freeze changed only in:**
   - `transport.py` / `reviewer.py`: the AI Horde provider branch (amendment 1).
   - `pipeline.py`: the gated flag, default off (amendment 2).
   - `score.py`: judge model and pacing (amendments 1 and 3).

   Mistral A1/A3/A4 requests are unaffected; the offline cache hits confirm this.
5. **Concurrency:** gated and SYN runs shared the Mistral cache directory concurrently, so their budget counters were per process. The combined 526 calls stayed under the 900 cap.
6. **Audit claims rechecked against code,** and two corrected: banking_068 was not caused by a relation fact, and the tool-absence gap is due to the incomplete catalog.

## Next steps (if continued)
1. A new independent lockbox: new τ²-style traces annotated per turn and checked for overlap with valid46. Use it to test `integrated_gated` against `guard`.
2. Fix the receipt-actor contract (a `tool` actor) as a separately measured change.
3. Complete Gemma integrated46 when the quota renews (RUNBOOK).

> **Superseded default (2026-10-06):** verification v2 changed the recommended default to `guard_adm2` (guard + admission v2); see `docs/verification_v2/FINAL_DECISION.md`.
