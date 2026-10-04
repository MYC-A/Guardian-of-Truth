# Evidence packer U1 — universal coverage step

Branch `research/universal-evidence-packer-20261004` (base `8e135f55`, retrieval bakeoff V1).
Code: `src/guardian_truth/evidence_packer/`. Tests: `tests/test_evidence_packer.py`.
Evaluation: `PYTHONPATH=.:src python scripts/evaluate_evidence_packer.py [--ablate] [--dense]`.

## Why the bakeoff coverage was low (diagnosis)

1. **Wrong cost unit.** The budget counted *reads* (8/12) over 4000-char windows. One policy
   window ate a read even when 200 characters were needed; short user turns cost the same as huge KB
   dumps. Measured on the 15 frozen cases, the minimal reference packet costs 2.7–13.4 KB,
   so a 20 KB budget can be enough if units are fine-grained.
2. **Units did not follow document structure.** Windows cut through sections; the scorer
   requires full coverage of a span, so gaps between windows/events lost norms.
3. **Norms and facts competed in one ranking.** Ranking policy chunks against history
   with the same lexical query almost always lost one of the two.
4. **Cross-lingual queries.** Dialogue/targets are Russian; policy, schemas, receipts are English.
   BM25 over target prose barely matches the policy. Identifiers and operation names do.
5. **Absence claims need complete lists.** A call to a tool that is *not* declared can only be
   judged with the complete catalog, never a ranked subset.

## Design (no domain rules, no tool names, no case IDs)

| Step | What | Why it is general |
|---|---|---|
| Units | System text split by its own headings/tags/paragraphs/tool entries; history per event; gapless partition, exact offsets | Any structured document; merged adjacent units are original spans |
| Mandatory | Whole current move + declarations of called tools; full catalog if a called tool is undeclared | Verification target; absence requires full enumeration |
| Policy allocation | Policy gets `min(whole policy, 60 % of budget)`; if it fits, it is included whole; else global-scope (root) blocks, then ranked blocks with their heading parents | Norm text is static per domain (cacheable) and partial norms cannot certify |
| History anchors | Latest user / assistant message, first user message, first+latest mention of each rare identifier of the move, the current segment since the last user message, all user turns (each with a bounded share) | Generic dialogue structure: intent, consent, latest state, provenance |
| Ranking | RRF over BM25 (unique query terms), rare-identifier overlap (IDF), recency; optional multilingual dense encoder (`fastembed`) | Independent signals, no learned weights |
| Closure | Heading parents for policy blocks; call ↔ receipt pairing (FIFO per actor+tool) | Mechanical dependencies only |
| Budget | One UTF-8 byte bound on the serialized source array (same bound as the bakeoff); mandatory overflow is an explicit failure | Comparable; no cropping |
| Output | Exact spans, trace, unread counts, `completeness_certified=false` | Absence is never evidence |

## Results (frozen references; packer sees prompt/response only)

Complete reference sets (dev / known-eval) and policy, history units found. Baselines use the
same byte budget with **no read cap** (fairer to them than the 8/12-read protocol).

| Budget (bytes) | local_bm25 | B1 | bm25+exact+graph | **U1** |
|---|---|---|---|---|
| 12 000 | 1/8, 0/7 | 2/8, 1/7 | 2/8, 1/7 | **4/8, 3/7** |
| 20 000 | 2/8, 3/7 · P19/28 · H16/52 | 2/8, 1/7 · P12/28 · H21/52 | 2/8, 1/7 · P13/28 · H21/52 | **7/8, 3/7 · P22/28 · H41/52** |
| 32 000 | 3/8, 3/7 | 3/8, 3/7 | 3/8, 1/7 | **7/8, 3/7** |
| 48 000 | 3/8, 3/7 | 3/8, 3/7 | 3/8, 3/7 | **7/8, 4/7** |
| 64 000 | 3/8, 3/7 | 3/8, 3/7 | 3/8, 3/7 | **8/8, 6/7** |

Frozen-protocol reference (8–12 reads, 20 000): B1 2/8, 1/7; local_bm25 1–2/8, 3/7.
Optional dense encoder (MiniLM-L12 multilingual): 20 000 → 6/8, 4/7; 48 000 → 7/8, 5/7 —
**no consistent gain**, kept off by default. Runtime ≈ 0.03 s/case without dense, 0 HTTP.
Robustness: all 46 valid rows × 2 budgets — no failures, no budget overrun, all offsets exact.

## Ablation (complete sets dev/eval)

At 20 000: removing root-scope policy blocks is the largest loss (7/3 → 4/1); removing entity
provenance 7/3 → 5/3; any single dialogue anchor −1 dev. **No anchors at all: 6/3** — most of
the gain comes from structure-aware units + byte budget + policy reservation, not the heuristics.
At 48 000 the anchors do not help (no anchors: 7/5) and whole-policy inclusion matters (−whole: 7/3).
Random sweep of 40 share/RRF configs at 20 000: dev 5–7 (median 6), eval 3 always —
the result is not a knife-edge setting.

## Honest limits

* The anchors (current segment, user turns, entity provenance, catalog on undeclared call) were
  motivated by error analysis that looked at **both** dev and known-eval references. Treat known-eval
  as contaminated; validate on a fresh holdout before claiming transfer.
* Coverage ≠ correct verdict. No model was called; binary F1 is not claimed.
* Long banking logs (220–360 KB) still miss long-distance bindings at ≤ 48 KB
  (bank080 card↔account receipts, bank081 early requests/withdrawal).
* Recommended operating point: policy whole (prompt-cache it — it is static per domain) plus
  ≥ 30 KB for history. Retrieval should compress history, not norms.

## Next steps

1. Freeze U1 config, annotate 15–20 new rows (fresh, not from valid46 known-eval), measure.
2. Long-log history: per-entity timeline (first/last/state-changing receipts) instead of plain ranking.
3. Only then plug the packer into the I4 review and measure binary F1 on the holdout.
