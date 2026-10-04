# Evidence packer U2 — fixes, equal-budget comparison with Facet Cover V2, frozen LLM A/B

Branch `research/universal-evidence-packer-20261004`. Code: `src/guardian_truth/evidence_packer/`, tests `tests/test_evidence_packer.py` (17 pass).

## 1. Review fixes (U1 → U2)
| Review finding | U2 behaviour |
|---|---|
| `_merge()` merged across actors | merge only within same document / role / event / tool / category; members kept in audit sidecar `span_members` (not charged to budget) |
| non-native IDs (`p<offset>`, `h0+h1`) | IDs come from SourceStore: `h<i>`/`t<i>` for whole events, `q<n>` for registered quotes; `resolve(packet,row)` checks text, ID, actor, event, kind |
| FIFO call→result pairing | pairing from `policy_table_v11.provenance.observations` (QUALIFIED_ASSISTANT_RECEIPT / UNIQUE_SAME_ACTOR / AMBIGUOUS_UNPAIRED / ACTOR_MISMATCH_UNPAIRED); ambiguous calls are not paired |
| incomplete call→result groups | whole call + result events form one group; `receipt_groups` marked COMPLETE/PARTIAL, PARTIAL listed in `uncovered` |
| "undeclared tool" without catalog check | `declaration_status`: DECLARED / UNDECLARED_IN_COMPLETE_PARSED_CATALOG (only if catalog parse is complete and the structural splitter agrees) / NOT_FOUND_IN_UNVERIFIED_CATALOG; undeclared ⇒ whole catalog span attached |
| last-user anchor could silently drop | anchor statuses SELECTED/PARTIAL/BUDGET_SKIPPED/ABSENT; required anchor overflow ⇒ explicit failure `REQUIRED_ANCHOR_BUDGET_EXCEEDED` |
| — (found during this run) | BM25 summed over a `set` ⇒ float order depended on `PYTHONHASHSEED`; fixed (sorted), test across seeds added. It changed only one audit-trace entry; no review request changed |

All 46 rows × {20k, 48k}: no failures, no budget overruns, all packets pass `resolve`, ~0.1 s/row.

## 2. Offline coverage at equal byte budgets
Complete reference sets (dev 8 | known-eval 7). Reference rows = 15; known-eval was seen during design (contaminated).

| budget | local BM25 | FC2 | U1 | U2 |
|---|---|---|---|---|
| 12k | 1 \| 0 | 1 \| 1 | 4 \| 3 | 4 \| 3 |
| 20k | 2 \| 3 | 2 \| 1 | 7 \| 3 | 5 \| 3 |
| 32k | — | 3 \| 1 | 7 \| 3 | 7 \| 3 |
| 48k | — | 7 \| 3 | 7 \| 4 | 8 \| 5 |
| 64k | — | 7 \| 4 | 8 \| 6 | 8 \| 6 |

U2 ≥ FC2 at every budget. At 20k U2 < U1: it pays bytes for complete provenance groups (this is the intended trade). Script: `scripts/compare_u2_facet_cover.py` (FC2 and U1 loaded verbatim from git).

## 3. Frozen LLM A/B
Protocol (`experiments/evidence_packer_v2/llm_eval.py`): arms FULL (full input), U2_20k, U2_48k, FC2_48k; 46 rows; reviewer Mistral `ministral-14b-2512`, T=0, unchanged I4 contract (strict schema, ID+actor admission); requests frozen by manifest (`outputs/evidence_packer_v2/llm/manifest.json`, sha in file) before inference; retries only on 429/5xx/timeout (none needed). Reason judge: Ollama `gpt-oss:120b` vs gold `explanation` (SAME/PARTIAL/DIFFERENT) for TP only. **3 independent runs** of identical requests, because T=0 is not deterministic: on the 31 rows where U2_48k request is byte-identical to FULL, 5 decisions flipped within one run.

F1 (all 46; technical nulls → NO_ERROR):

| arm | run1 | run2 | run3 | mean | unseen31 mean | prompt tok/row |
|---|---|---|---|---|---|---|
| FULL | 0.556 | 0.471 | 0.529 | 0.519 | 0.500 | 13.3k |
| **U2_20k** | 0.684 | 0.727 | 0.700 | **0.704** | **0.646** | **3.7k** |
| U2_48k | 0.579 | 0.400 | 0.444 | 0.474 | 0.531 | 7.2k |
| FC2_48k | 0.258 | 0.485 | 0.214 | 0.319 | 0.253 | 7.3k |

Per-row correctness summed over 3 runs (sign test): U2_20k vs FULL 14 better / 7 worse (p≈0.19, **not significant**); vs U2_48k 20/7 (p≈0.02); vs FC2_48k 18/5 (p≈0.01).

Means over 3 runs:

| arm | TP | FP | TP reason SAME / PARTIAL / DIFF | admission rejections | ref15: required norm cited | required-norm recall | median cited policy bytes |
|---|---|---|---|---|---|---|---|
| FULL | 9.0 | 2.7 | 3.7 / 3.7 / 1.7 | 1.0 | 15/15 | 0.92 | 7257 |
| U2_20k | 14.3 | 3.3 | 5.3 / 4.0 / 5.0 | 0.7 | 12/14.7 | 0.71 | 3053 |
| U2_48k | 8.7 | 4.7 | 4.0 / 4.0 / 0.7 | 1.3 | 14.7/14.7 | 0.92 | 7257 |
| FC2_48k | 5.0 | 2.7 | 1.7 / 2.3 / 1.0 | 3.7 | 9.7/13.3 | 0.55 | 2423 |

Citation verifiability = admission: every admitted citation resolves to a packet ID with the right actor; all cited policy texts were locatable verbatim in the prompt. Rejections are `EVIDENCE_REFERENCE_OR_ACTOR_INVALID` (FC2 highest). Norm scope (`llm_extra.py`): overlap of cited policy sources with reference normative spans on the 15 reference rows; FULL/U2_48k score high partly because their policy units are coarse (≈7 KB cited), so the metric is lenient for them.

## 4. Conclusions and limits
- U2 is the safer evidence layer: provenance-correct, deterministic, ≥ FC2 on coverage at every budget, and clearly better than FC2 in the LLM test.
- U2_20k gives the best F1 at ~28% of FULL tokens, but **≈1/3 of its extra TPs have a DIFFERENT reason**: reason-correct TP (SAME+PARTIAL) is 9.3 vs 7.3 for FULL. The gain over FULL is not significant on 46 rows and is partly "more ERROR flags", not better understanding.
- U2_48k ≈ FULL (2/3 of its requests are the full input); differences there are reviewer noise.
- n=46, one reviewer model, judge is an LLM; ref15 is contaminated (used in design); unseen31 is the cleaner subset. Coverage ≠ verdict quality.
- FC2 is not deterministic across machines/processes (set iteration under `PYTHONHASHSEED`): 2/184 frozen requests differed between local and server builds; the server build is canonical.

Reproduce: `python -m experiments.evidence_packer_v2.llm_eval prepare|run|judge|report --out DIR`, then `llm_extra DIR`, `llm_repeats DIR1 DIR2 DIR3`. Compact per-call results: `outputs/evidence_packer_v2/llm/decisions.jsonl`.
