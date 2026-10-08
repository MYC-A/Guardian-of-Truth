# Independent methodological review of the Qwen branches

Reviewed frozen Git objects `4172683b` (complementarity) and `51160fcd0b7b9354f8a63615430aeae0c95b591a` (binding). Read-only offline audit; no model calls, SSH, gold edits, or historical output edits. Numbers below refer to those revisions, not subsequent repairs in this worktree.

## What is established

The development improvement from the deterministic checks is reproducible: on the 237 labelled development rows, the saved binary projection changes from TP130 / FP8 / FN34 / TN65 (F1 .860927) to TP136 / FP8 / FN28 / TN65 (.883117). This is a real change in saved decisions under the existing labels. It is not an independent estimate of a universal detector's quality.

The five B improvements are `ext_tel_008`, `ext_tel_011`, `ext_tel_037`, `hold_tel_052`, and `hold_tel_069`. Every improvement is the same concrete scenario family: `enable_roaming`, used line `L1001`, object phone `555-123-2001`, user phone `555-123-2002`. The rows have different task IDs, but share the same binding pattern and fixture identifiers. The sixth improvement is C on `ext_ret_041`, whose current move contains both a message and a call. There are no A improvements. On development B fires on 12 rows, C on 35, and their union on 43; most were already positive under QB2.

The useful general idea is to separate value binding and turn constraints from the general reviewer. The observed gains do not validate the current heuristic as a universally sound enforcement layer. In particular, avoiding literal benchmark IDs in code does not establish semantic universality: the choice of attribute, entity, object identifier, current user intent, and applicable norm still requires justification.

## Coverage differs from INTERIM

| Frozen Qwen B2 cohort | Expected inputs | Saved unique IDs | Labelled scored IDs |
|---|---:|---:|---:|
| valid46 | 46 | 46 | 46 |
| ext_tau2 | 70 | 70 | 68 |
| hold_tau2h | 51 | 51 | 51 |
| hold_holdout2 | 72 | 72 | 72 |
| lb2_long | 47 | 47 | 47 |
| lb3_long | 56 | 56 | 56 |
| lb_long | 57 | 39 | 39 |

Development is fully present: 239 inputs, 237 labelled. Test is incomplete: 160 expected, 142 observed, 18 missing in lb_long. On those 142 observed test rows the binary projection is TP69 / FP2 / FN1 / TN70, F1 .978723, unchanged by ABC. The missing 18 remain undecided; this is not a result on all 160.

`INTERIM.md:21` instead claims 148 test rows and 71/2/2, F1 .973. Those numbers cannot be reproduced from the committed revision. The protocol says lb_long was completed by resume, but its saved B2 file still contains 39 rows. This may be a server-progress versus commit-capture discrepancy; the Git evidence does not support inferring fabrication or choosing the undocumented cohort.

`ext_tau2/B2_rep1.jsonl` has 72 physical records and 70 unique IDs. `ext_ret_000` and `ext_ret_003` each appear twice. Their raw primary and pre-pass contents are identical; differences are cached flags in the receipts/layer trace. Their saved decisions agree. These duplicates do not demonstrate choosing a better fresh answer. The frozen combiner nevertheless uses last-row-wins without asserting duplicate consistency (`combine.py:15-22`).

## Technical failures are still projected into binary scores

`combine.py:21` retains both the binary and the classification. `combine.py:33-44,83-93` then computes scores from the binary without using the classification. `eval_idcheck.py:17-20` similarly checks only whether the stored binary exists. This violates the complementarity protocol's promise that technical failures are not imputed as NO_ERROR.

Concrete case: `ext_ret_062` has gold label 1, primary review admission `INVALID_JSON`, saved binary 0, and class `no_solution`. It is counted as a FN in the published binary projection. The primary JSON records themselves report one labelled no_solution but zero undecided. Two unlabelled ext_tau2 inputs are correctly excluded from binary gold, while remaining present in execution coverage.

There is an additional classification weakness. Frozen `score_local.py:141-158` rejects a fixed list of admission strings, but not `REJECTED:ValueError:...`. Such primary reviews can be classified as verdict/fallback. For example, ext_ret_000 has `REJECTED:ValueError:EVIDENCE_REFERENCE_OR_ACTOR_INVALID` and is called fallback. This means the original scorer's usable subset is not a proof-admitted subset.

The accompanying script explicitly reports three distinct scopes:

| Development scope | n | QB2 TP/FP/FN | ABC TP/FP/FN |
|---|---:|---|---|
| All saved labelled binaries, including invalid/rejected reviews | 237 | 130/8/34 | 136/8/28 |
| Original scorer verdict/fallback subset | 236 | 130/8/33 | 136/8/27 |
| Original usable and primary review ADMITTED | 193 | 109/6/17 | 113/6/13 |

The last row is a conservative diagnostic subset, not a replacement competition score and not a claim that all mechanically owned decisions outside it are invalid. Filtering on technical success changes the cohort. Neither filtered score should be presented as performance on the full expected set.

On test the original scorer's usable subset has the same 142 observed rows. Requiring primary review ADMITTED leaves 117, with TP55 / FP2 / FN1 / TN59, unchanged by ABC. These distinctions prevent a successful binary score from silently becoming a claim of a successfully verified explanation.

## Complementarity H1

The fresh Granite 3.3 valid46 gate is independently reproducible: all 46 raw model outputs match the archived `full21_control_repro` outputs; all 46 risk tokens match the matrix's `granite:flash`. Granite held-out runs are fresh local transformers records; valid46 Qwen is an archived first-circle sample, whereas held-out Qwen was generated in this phase. The attempted valid46 replay was aborted and disclosed rather than replacing the baseline.

| Pool | QB2 TP/FP/FN, F1 | QB2 OR Granite TP/FP/FN, F1 |
|---|---|---|
| valid46, development | 13/1/10, .7027 | 20/2/3, .8889 |
| ext_tau2 | 38/1/14, .8352 | 47/6/5, .8952 |
| hold_tau2h | 34/1/7, .8947 | 35/7/6, .8434 |
| hold_holdout2 | 45/5/3, .9184 | 47/13/1, .8704 |
| Primary, 191 labelled binaries | 117/7/24, .8830 | 129/26/12, .8716 |
| lb2_long | 22/0/1, .9778 | 22/8/1, .8302 |
| lb3_long | 28/2/0, .9655 | 28/9/0, .8615 |

The primary OR gains 12 TP at 19 extra FP; it fails the preregistered deltaTP >= 2*deltaFP condition. The saved row-bootstrap CI for deltaF1 is [-.0477, .0262]. Thus there is no demonstrated primary gain, and declining this OR configuration is justified. This is not evidence that every Granite model, prompt, context budget, or combination must be unhelpful.

The failure-projection bug does not reverse this decision. If the common invalid ext_ret_062 row is reported separately, the remaining common cohort gives QB2 117/7/23 (.886364) versus OR 129/26/11 (.874576). Granite itself says no on that row. These are diagnostic comparable-cohort counts, not a retroactive replacement of the frozen results.

Granite's configured 12,000-character budget actually allocates 4,800 characters to the prompt and uses head/tail truncation. This is visible in raw `bounded_input_chars` and `input_truncation`. The experiment evaluates that inexpensive truncated groundedness control. It does not test a full-history policy-specific Granite reader. OR-added TPs have no supplied cause assessment, as the protocol explicitly acknowledges.

The primary set definition was narrowed through committed amendments before the final scoring commit. The four amendments disclose failed cache replay, absent response bodies, dropped QAM control, concurrency changes, and the stopping rule. This is substantially more transparent than silently selecting the completed subset after inspecting its score. However, pre-result commit timing and self-reported noninspection do not create independently blinded labels or an independent annotator.

The valid46 QAM-subset observation is development evidence only; it does not prove a same-family control could not help elsewhere. Dropping that control limits interpretation of whether complementarity is specifically a model-family effect.

## H2 wire cap

The 60 KB to 80 KB phase is not a clean delivery-only causal comparison. The protocol discloses that all 14 fresh pre-pass texts differed from baseline, so the changed final answers combine delivery and resampling effects. Thirteen of 14 cap rows were delivered; changes against the original baseline were +1 TP and +1 FP. The stated no-new-FP acceptance criterion was not met.

Raising a cap with token-based context accounting remains a reasonable technical hypothesis. This experiment does not establish that it improves quality, costs no quality, or proves cap loss is irrelevant to the remaining FNs. A matched-input comparison needs the exact saved pre-pass as injected data and comparable review sampling, not a freshly generated pre-pass whose text changed. The report's attribution of the old/new Ministral difference exclusively to serving/weights is likewise stronger than request capture alone establishes: `capture.py` captures the primary R_fix request fields, not an experimental separation of serving, sampling, transport, and postprocessing effects.

## Granite 4.2 and H3 are partial probes

The G42 blobs contain eight valid46 and eight lb2_long rows, 16 total, whereas INTERIM describes 15 (eight plus seven). Its observed binary projection has three TP against five for Qwen and no observed positive gain over Qwen. Keeping Qwen as the incumbent is reasonable; a tiny interrupted Q4_K_M sample does not close the Granite 4.2 idea.

The saved G42 valid46 rows classify as two verdict, five fallback, and one no_solution under the frozen scorer, not the report's four fallback rows. On lb2 all eight are classified verdict even though five primary reviews have REJECTED admissions. This reinforces the need to audit admission separately from a saved binary.

The H3 saved blobs contain 66 rows: 42 valid46 and 24 ext_tau2. Their statuses are 23 NO_CALL, 42 OK, and one PARSE_FAIL. There are zero verified mismatches, one unverified mismatch, 118 MATCH arguments and seven NOT_ESTABLISHED arguments. This is 43 call-bearing rows including the failed one, not the INTERIM's 77 call rows. The older sentence saying 59 dev rows is also a different unsaved snapshot. The correct result is zero observed verified hits on the committed partial sample; it is not a completed rejection on all development call rows.

The model-side audit can inherit the reviewer's entity-selection error. Its verifier checks quoted text/value occurrence and value difference, but occurrence alone does not prove the requested entity relation. In particular, `argument` and `requested_entity` need semantic/structural validation, not just a quote containing a different value. Zero hits cannot establish that a sound automatically grounded relation detector lacks potential.

## Exposure, gold, and permissible conclusions

The binding protocol classifies valid46, ext_tau2, tau2h and holdout2 as development, correctly acknowledging prior error inspection. The deterministic B rule was then changed after test false positives: the report explicitly says the first version produced +1 TP / +8 FP and the final first-ID/non-ID restriction was adopted after seeing them (`INTERIM.md:15-18`). The final B result on these same lockboxes is a regression check, not clean holdout evidence. A's create-verb exclusion was also motivated by observed frozen120 traps. These are legitimate development repairs if disclosed; their evaluation data must not simultaneously be sold as untouched validation.

All five B gains are source-consistent with the specific phone/line-binding errors, but the code still has to establish why the attribute is normatively binding for the current action. C's ext_ret_041 gain has an independent turn-format cause. That does not validate the separate old S accusation for the same row, which was disputed in the earlier source audit. A binary TP cannot certify every listed cause.

These are reused, error-enriched development/lockbox/tau2-derived sets, not a newly independently annotated representative distribution. Keeping labels unchanged preserves comparability, but does not repair known label-quality concerns in tau2-derived task-mismatch causes. Row-bootstrap intervals also do not account for scenario-family or paired-template dependence. Final generalisation needs new source-audited, task/family-separated data after the contracts and acceptance rules are fixed.

Recommended disposition: retain Qwen B2 as the incumbent; reject adding this Granite 3.3 control by unconditional OR; keep B and C as research findings to repair and test under explicit binding/applicability contracts. Do not claim an independently validated +6 TP universal repair or a complete 148/160-row test. Preserve the frozen phase and run subsequent repaired arms under a distinct experiment identity.

## Reproduction

Run from this worktree, without inference or network:

```powershell
$env:PYTHONUTF8='1'
python scripts/qwen_branch_metrics_audit.py --out "$env:TEMP/qwen_binding_method_receipt_51160fcd_20261008.json"
```

The output path must be new; the script uses exclusive creation. It reads raw CSV, gold and model records from Git blobs at 51160fcd, executes that revision's idcheck/scorer definitions in memory, and checks imported packet/scorer dependencies against the same frozen Git blobs. It records their SHA256 values, expected/missing/unlabelled IDs, duplicate IDs, technical admissions, changed rows and all three metric scopes. It refuses conflicting duplicate binary values and refuses silently changed parser dependencies. No historical file is rewritten.

Useful source anchors at the frozen revision: `experiments/guardian_complementarity/combine.py:15-44,83-99`; `experiments/guardian_binding/eval_idcheck.py:8-25`; `experiments/guardian_local_a100/score_local.py:63-89,141-158`; `docs/guardian_g42_binding_20261008/INTERIM.md:3-22`; and the protocol's Amendments 1-4. Raw evidence lives under `outputs/guardian_local_a100/llamacpp/.../runs`, `outputs/research_granite_guardian/compl_*`, and `outputs/guardian_binding/...` in Git, including colon-containing paths unavailable as ordinary Windows checkout paths.
