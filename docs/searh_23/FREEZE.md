# SEARCH_23 — Frozen candidates (§7.2)

Frozen after the §4.5 decisive comparison + §5 ablations. No further tuning on
public46 after this point; public46 is development data (§7.1) and its numbers
are diagnosis, not a guarantee.

Code state: `7c058526b43e` (branch searh_23/investigator-v2).
Input: outputs/full21/input/public46_label_free.csv (sha256 in outputs/searh_23/baseline_frozen/INPUT_HASHES.txt).

## C1 (primary): Guardian+Granite(3.3) OR — F1 .8889 (TP20/FP2/FN3) on public46

- Structural channel: `guardian_truth.pipeline.Detector()` (all check families) +
  `guardian_truth.decision.decide(threshold=0.5, use_semantic=False, unknown_label=0).label`
  Integration re-validated on public46: 12/12 labels match the frozen baseline column
  (outputs/full21/control_repro_percase.csv).
- Granite channel: granite-guardian-3.3-8b @ b3421eda (local dir
  /mnt/data/guardian/models/granite-guardian-3.3-8b-b3421eda), criterion
  `groundedness`, doc mode (messages=[assistant: response],
  documents=[{doc_id: prompt_context, text: bounded prompt}]),
  max_context_chars=12000 with 2/5 prompt + 3/5 response head-tail bounding
  (4800/7200), temperature 0 (greedy), think=false, max_new_tokens=200,
  label = 1 iff `<score> yes </score>`. Runner: experiments/full21/run_granite_modes.py
  (byte-compatible scoring contract with the flash control runner).
- Aggregation: `label = structural_label OR granite_label` (fixed, no thresholds tuned).
- Per-case: outputs/searh_23/baseline_frozen/control_repro_percase.csv (audited, MATCH).
- Run (demo, new inputs): `venv/bin/python experiments/searh_23/demo_frozen.py --input <cases.csv>`.

## C2 (recall channel): P+Graph judge (pgjudge) — R 1.0, F1 .7419 fresh (TP23/FP16/FN0)

- Pipeline: experiments/big_researh/p_precond_api.py (P extract via Mistral API
  ministral-14b-latest + NuExtract template b43f615; pjudge; graph flip).
- Fresh post-reset per-case: outputs/big_researh/p_api/pgjudge/records.jsonl (in git).
- Property: R=1.0 reproduced twice (pre-reset and post-reset runs);
  precision is the open problem (FP 14-16). Graph contribution isolated in
  outputs/searh_23/p_factor.json: +3 TP / +2 FP from 5 graph flips.
- NOT to be OR-ed into C1 without FP-cost accounting (directive §4.5):
  OR(C1, C2) = TP23/FP16/FN0 = F1 .74 < .8889.

## C3 (experimental, no measurable gain — kept as experimental mode, not candidate)

- Investigator v2 arms A/B/C/M (§4.5): zero flips everywhere at steps 2/4/6 and
  all verifier contexts; agent routing == fixed routing (.8889 both, latency 1.0s
  vs 10.1s); single-Mistral judge M F1 .6984. Honest negative.
- Q v2 (§5.5): 3434 divergences, 12 deep, 5 verified, 0 downstream flips under
  correct same-configuration measurement.

## Frozen auxiliary facts (for honest reporting, not candidates)

- Gate 4.1: standalone F1 .8095 (+1 TP vs 3.3, same FP); NO gain in OR hybrid
  (both 4.1 wins already covered by structural Guardian). Outputs: outputs/searh_23/gate41_*.
- Evasiveness (conv, 12k): P=1.0 on 4 flags; flags BARE TOOL_CALL responses
  (non-engagement), NOT refusals (0/12 refusal cases flagged). Within the
  bare-TOOL_CALL class (17 cases, 15 gold=1): recall 4/15. Characterization:
  outputs/searh_23/evasiveness_targeted/.
- function_call criterion: applicable in principle (tool defs documented inside
  <policy>), extractor not built — documented gap, not a result.

## External/contrast evaluation status (§7.3)

- Synthetic contrast suite (NEW hotel domain, 10 minimal pairs / 20 cases,
  expected labels by construction): outputs/searh_23/contrast_hotel/
  (cases.csv, expected.json, suite.json).
- Open external benchmarks: NOT integrated in this cycle — honestly recorded
  as an open limitation (the directive allows recording this rather than a
  fictitious test).

## Known limits

- public46 = development set; all numbers above are dev numbers.
- MISTRAL API channel (C2, investigator) is not verified for the final contest
  environment (VRAM/API availability) — C1 is fully local.
- Structural channel returns `unknown_fallback` (label 0) on many cases;
  its recall is carried by the granite channel in the OR.

---

## Post-freeze development note (not frozen)

Mechanical FP-refutation layer over pgjudge (candidate C4): public46 in-sample
TP23/FP6/FN0, F1 .8846, R 1.0 after the v3.1 grounded-card indexing correction
(v3.0's .9020 was inflated by the bug; v3.1 does NOT beat the frozen OR F1 —
it is the recall-complete tradeoff point). Out-of-sample hotel port: pgjudge
recall transfers (R=1.0), the refutation families do not (0/12 FP removed,
0 TP lost — conservative abstention). NOT added to the frozen set: in-sample
development + non-transferring families. v4 (checkpoint 11) built and
validated: structural guard (ported catalog checks) + history-satisfaction
+ scope entailment + temporal threshold — hotel 9/12 FP removed with
0 TP lost (F1 .9032 R 1.0), public46 unchanged (.8846). STILL NOT FROZEN:
public46 is in-sample for v3 families, hotel is in-sample for v4 families;
a third unseen domain is the honest validation frontier.
C1/C2/C3 above are unchanged.
