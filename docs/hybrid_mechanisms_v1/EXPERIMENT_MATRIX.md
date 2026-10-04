# Comparable experiment matrix

All new cases are preselected known valid46 development examples; no holdout or overall valid46 improvement claim. Source/parameter/response-mode hashes are frozen in protocol.json. Temperature 0, output cap 1700, one attempt per request, no retries or hidden clipping. Models actually returned `ministral-14b-2512` and `gemma4:31b`.

Strict admitted F1 is conditional on the displayed denominator. A missing full-subset F1 is unmeasured because technical/source admission failed. Raw labels are diagnostics, not admitted pipeline outputs. The two extra cases are separated from the two-case factorial, even though they share I4. Empty admitted-set F1 is undefined; use controlled_scores.json rather than the earlier broad score.py aggregate.

| Dataset/subset | Model | Arm | Strict admitted / planned | Full-subset strict F1 | Raw diagnostic F1 | Core causes / audited | Tokens |
|---|---|---|---|---|---|---|---|
| telecom,bank | mistral | I1 | 2/2 | 0.0000 | 0.0000 | 1/2 | 11689 |
| telecom,bank | mistral | I2 | 1/2 | unmeasured | 1.0000 | 2/2 | 11735 |
| telecom,bank | mistral | I3 | 2/2 | 0.6667 | 0.6667 | 1/2 | 11990 |
| telecom,bank | mistral | I4 | 1/2 | unmeasured | 1.0000 | 2/2 | 11706 |
| telecom,bank | ollama | I1 | 0/2 | unmeasured | unmeasured | 0/0 | 12233 |
| telecom,bank | ollama | I2 | 0/2 | unmeasured | unmeasured | 0/0 | 12317 |
| telecom,bank | ollama | I3 | 0/2 | unmeasured | unmeasured | 0/0 | 12290 |
| telecom,bank | ollama | I4 | 0/2 | unmeasured | unmeasured | 0/0 | 12465 |
| telecom,bank | mistral | K1 | 2/2 | 1.0000 | 1.0000 | 2/2 | 13342 |
| telecom,bank | mistral | K2 | 1/2 | unmeasured | 1.0000 | 1/2 | 12905 |
| telecom,bank | mistral | C1 | 1/2 | unmeasured | 1.0000 | 1/2 | 12162 |
| telecom,bank | mistral | C2 | 1/2 | unmeasured | 1.0000 | 2/2 | 12702 |
| telecom,bank | mistral | STAGE_B | 2/2 | 1.0000 | 1.0000 | 2/2 | 13930 |
| telecom | mistral | R0_final | 1/1 | 1.0000 | 1.0000 | 0/1 | 7018 |
| telecom | mistral | R1_final | 0/1 | unmeasured | 1.0000 | 0/1 | 3089 |
| telecom | mistral | coverage_final | 1/1 | 1.0000 | 1.0000 | 1/1 | 6103 |
| multicall,exception | mistral | EXTRA_I4 | 1/2 | unmeasured | 0.6667 | 1/2 | 20470 |

The eight Gemma strict results are formatting failures, not eight measured semantic mistakes. A separately versioned zero-HTTP diagnostic removes exactly one complete JSON Markdown fence and applies unchanged inner JSON/source/actor admission. For each I1-I4, both cases admit, TP1/TN1/FP0/FN0, diagnostic F1=1.0000. These are four correlated repeats of two known cases, not an eight-case holdout. All requested key orders are honored after decoding the complete inner JSON.

Stage A consumed 12503 tokens (two calls), gives no final verdict. Stage B consumed 13930 tokens (two calls). Their combined 26433-token cost must be counted when comparing the separated workflow. The typed hypothesis adapter gives UNKNOWN on both cases, including one real positive; independent proof remains UNKNOWN.

R1 uses 2 actual calls (one rejected plan and the empty-evidence final), not the 3-call ceiling. R0 final spends 7018 tokens; its historical plan spent 4398 in the preceding frozen phase and is not charged again. Full R0 workflow accounting is therefore 11416 tokens with historical planning included. Coverage is code-selected and spends 6103 tokens in one final call. Working two-round recursion was not measured.

V1 flags zero eligible typed contradictions; bank I4 is inadmissible. V2 executes zero calls (NO_TYPED_CONTRADICTION_FLAG). V3 is an explicitly oracle/source-audit-assisted offline proof ceiling, zero inference calls.

Total new inference: 34 calls; 217722 known/charged tokens; 233.417 summed provider-request seconds. Metadata GETs and all offline replays are outside inference counts. No unknown-usage reservations, provider failures, budget stops or context clipping occurred in this new series.

Operational comparison: K1 admits one bank result that I4 rejects; no raw binary FP/FN is repaired. No new binary repair is obtained by K2, C1/C2 or the split workflow relative to the raw I4 labels. Relative to source-starved R0, coverage corrects exactly one explanatory cause with the same ERROR label, at 6103 tokens per additional correct cause; it saves 915 final-call tokens (5313 including the historical plan). A cost per corrected binary FP/FN is undefined for these arms.

Technical counts: 8 fenced-format failures, 6 actor/source failures, 1 final norm-reference failure, plus the separate R1 plan namespace failure. Stage A is not a failed verdict: no verdict was requested. All failures retain null admitted semantic decisions; admitted UNKNOWN maps to zero explicitly.

## Semantic target and critical-norm coverage audit

`target_norm_coverage_audit.json` separately audits the actual charged action
stage and complete regulated inventory. A legal current ID alone does not imply
that the model evaluated the right action. The hand-audited critical inventory
is deliberately nonexhaustive; strict recall below measures faithfully scoped
structured primary relations, not all policy clauses or just correct prose.

| Separate reporting population | Current IDs valid | Semantic target correct | Complete regulated inventory | Strict critical norm units | Admission |
|---|---|---|---|---|---|
| Mistral 23 final replies | 23/23 | 20/23 | 22/23 | 14/25 | 16/23 |
| Mistral 2 Stage A replies | 2/2 | 2/2 | 2/2 | 1/2 | 2/2; no verdict requested |
| Gemma 8 alternate-fence diagnostics | 8/8 | 8/8 | 8/8 | 8/8 | 8/8 alternate; frozen 0/8 |

These totals include repeated correlated cases and arms; they are not a paired
effect estimate or independent model ranking. Multicall regulated_action selects
only t0 (1/4), although supporting evidence mentions all four calls. Its grouped
payment schema coverage is 0/1, and atomic missing-field detection is 0/16.
Bank I3 substitutes accepted authentication for a credential request; Silver
inherits update consent in an informational response. These are semantic target
errors despite valid IDs. Stage A Telecom omits the principal FORBID relation.

`component_metrics.json` records the 23 Mistral final source audits separately:
core cause 16/23, norm scope 4/23, exceptions 18/23, source grounding 10/23,
decision/reason consistency 22/23. Correct core causes can coexist with wrong
auxiliary scope or source claims. There are two raw UNKNOWN replies, both
technically inadmissible; there is no admitted final semantic UNKNOWN. The
separate code aggregation returns UNKNOWN on both Stage A cases and creates one
FN under projection to zero. Technical rejection is never projected to zero.

## Complete per-call provenance matrix

All rows below use frozen protocol `e4b2ea299d8d2004489d7aca222318bd64cb35e9c2a4bfad109e7cfa786efcfa`; `P1` denotes this exact hash. Its source/fixture/model/parameter seals are in protocol.json. Dataset abbreviations are original known valid46 cases, not new holdout. Per-row full protocol/request/raw hashes and latency are in per_call_matrix.json. Source views expose omissions; complete selected spans never imply complete original coverage.

| Original case | Actual model | Arm | Protocol hash | Admitted / raw label | Core cause | Evidence coverage | Failure | Calls / tokens | Conclusion |
|---|---|---|---|---|---|---|---|---|---|
| telecom | ministral-14b-2512 | mistral_telecom_I1 | P1 | NO_ERROR / NO_ERROR | False | norm 2; history 22; current 1; complete selected spans | none | 1 / 7166 | Admitted label does not establish a correct governing cause |
| telecom | ministral-14b-2512 | mistral_telecom_I2 | P1 | ERROR / ERROR | True | norm 2; history 22; current 1; complete selected spans | none | 1 / 7061 | Correct core cause; auxiliary defects are audited separately |
| telecom | ministral-14b-2512 | mistral_telecom_I3 | P1 | ERROR / ERROR | True | norm 2; history 22; current 1; complete selected spans | none | 1 / 7224 | Correct core cause; auxiliary defects are audited separately |
| telecom | ministral-14b-2512 | mistral_telecom_I4 | P1 | ERROR / ERROR | True | norm 2; history 22; current 1; complete selected spans | none | 1 / 7122 | Correct core cause; auxiliary defects are audited separately |
| bank | ministral-14b-2512 | mistral_bank_I1 | P1 | NO_ERROR / NO_ERROR | True | norm 3; history 3; current 1; complete selected spans | none | 1 / 4523 | Correct core cause; auxiliary defects are audited separately |
| bank | ministral-14b-2512 | mistral_bank_I2 | P1 | None / NO_ERROR | True | norm 3; history 3; current 1; complete selected spans | ADMISSION:EVIDENCE_REFERENCE_OR_ACTOR_INVALID | 1 / 4674 | Technical/source admission failed; no admitted semantic label |
| bank | ministral-14b-2512 | mistral_bank_I3 | P1 | ERROR / ERROR | False | norm 3; history 3; current 1; complete selected spans | none | 1 / 4766 | Admitted label does not establish a correct governing cause |
| bank | ministral-14b-2512 | mistral_bank_I4 | P1 | None / NO_ERROR | True | norm 3; history 3; current 1; complete selected spans | ADMISSION:EVIDENCE_REFERENCE_OR_ACTOR_INVALID | 1 / 4584 | Technical/source admission failed; no admitted semantic label |
| telecom | gemma4:31b | ollama_telecom_I1 | P1 | None / None | None | norm 2; history 22; current 1; complete selected spans | UNFINISHED_OR_INVALID_REPLY | 1 / 7492 | Technical/source admission failed; no admitted semantic label |
| telecom | gemma4:31b | ollama_telecom_I2 | P1 | None / None | None | norm 2; history 22; current 1; complete selected spans | UNFINISHED_OR_INVALID_REPLY | 1 / 7600 | Technical/source admission failed; no admitted semantic label |
| telecom | gemma4:31b | ollama_telecom_I3 | P1 | None / None | None | norm 2; history 22; current 1; complete selected spans | UNFINISHED_OR_INVALID_REPLY | 1 / 7560 | Technical/source admission failed; no admitted semantic label |
| telecom | gemma4:31b | ollama_telecom_I4 | P1 | None / None | None | norm 2; history 22; current 1; complete selected spans | UNFINISHED_OR_INVALID_REPLY | 1 / 7651 | Technical/source admission failed; no admitted semantic label |
| bank | gemma4:31b | ollama_bank_I1 | P1 | None / None | None | norm 3; history 3; current 1; complete selected spans | UNFINISHED_OR_INVALID_REPLY | 1 / 4741 | Technical/source admission failed; no admitted semantic label |
| bank | gemma4:31b | ollama_bank_I2 | P1 | None / None | None | norm 3; history 3; current 1; complete selected spans | UNFINISHED_OR_INVALID_REPLY | 1 / 4717 | Technical/source admission failed; no admitted semantic label |
| bank | gemma4:31b | ollama_bank_I3 | P1 | None / None | None | norm 3; history 3; current 1; complete selected spans | UNFINISHED_OR_INVALID_REPLY | 1 / 4730 | Technical/source admission failed; no admitted semantic label |
| bank | gemma4:31b | ollama_bank_I4 | P1 | None / None | None | norm 3; history 3; current 1; complete selected spans | UNFINISHED_OR_INVALID_REPLY | 1 / 4814 | Technical/source admission failed; no admitted semantic label |
| telecom | ministral-14b-2512 | mistral_telecom_K1 | P1 | ERROR / ERROR | True | norm 2; history 22; current 1; complete selected spans | none | 1 / 8423 | Correct core cause; auxiliary defects are audited separately |
| telecom | ministral-14b-2512 | mistral_telecom_K2 | P1 | ERROR / ERROR | True | norm 2; history 22; current 1; complete selected spans | none | 1 / 8035 | Correct core cause; auxiliary defects are audited separately |
| telecom | ministral-14b-2512 | mistral_telecom_C1 | P1 | ERROR / ERROR | True | norm 2; history 22; current 1; complete selected spans | none | 1 / 7255 | Correct core cause; auxiliary defects are audited separately |
| telecom | ministral-14b-2512 | mistral_telecom_C2 | P1 | ERROR / ERROR | True | norm 2; history 22; current 1; complete selected spans | none | 1 / 7321 | Correct core cause; auxiliary defects are audited separately |
| bank | ministral-14b-2512 | mistral_bank_K1 | P1 | NO_ERROR / NO_ERROR | True | norm 3; history 3; current 1; complete selected spans | none | 1 / 4919 | Correct core cause; auxiliary defects are audited separately |
| bank | ministral-14b-2512 | mistral_bank_K2 | P1 | None / UNKNOWN | False | norm 3; history 3; current 1; complete selected spans | ADMISSION:EVIDENCE_REFERENCE_OR_ACTOR_INVALID | 1 / 4870 | Technical/source admission failed; no admitted semantic label |
| bank | ministral-14b-2512 | mistral_bank_C1 | P1 | None / UNKNOWN | False | norm 3; history 3; current 1; complete selected spans | ADMISSION:EVIDENCE_REFERENCE_OR_ACTOR_INVALID | 1 / 4907 | Technical/source admission failed; no admitted semantic label |
| bank | ministral-14b-2512 | mistral_bank_C2 | P1 | None / NO_ERROR | True | norm 3; history 3; current 1; complete selected spans | ADMISSION:EVIDENCE_REFERENCE_OR_ACTOR_INVALID | 1 / 5381 | Technical/source admission failed; no admitted semantic label |
| telecom | ministral-14b-2512 | mistral_telecom_stageA | P1 | None / None | None | norm 2; history 22; current 1; complete selected spans | none | 1 / 7540 | Verdict-free model hypotheses, no binary scoring |
| telecom | ministral-14b-2512 | mistral_telecom_stageB | P1 | ERROR / ERROR | True | norm 2; history 22; current 1; complete selected spans | none | 1 / 8226 | Correct core cause; auxiliary defects are audited separately |
| bank | ministral-14b-2512 | mistral_bank_stageA | P1 | None / None | None | norm 3; history 3; current 1; complete selected spans | none | 1 / 4963 | Verdict-free model hypotheses, no binary scoring |
| bank | ministral-14b-2512 | mistral_bank_stageB | P1 | NO_ERROR / NO_ERROR | True | norm 3; history 3; current 1; complete selected spans | none | 1 / 5704 | Correct core cause; auxiliary defects are audited separately |
| telecom | ministral-14b-2512 | mistral_telecom_R0_final | P1 | ERROR / ERROR | False | norm 8; history 0; current 1; complete selected spans | none | 1 / 7018 | Admitted label does not establish a correct governing cause |
| telecom | ministral-14b-2512 | mistral_telecom_R1_plan1 | P1 | None / None | None | Initial full catalog and declarations; zero executed reads | ValueError:GAP_SOURCE_NAMESPACE_INVALID | 1 / 7073 | Planner namespace rejection; working recursion NOT_TESTED |
| telecom | ministral-14b-2512 | mistral_telecom_R1_final | P1 | None / ERROR | False | norm 0; history 0; current 1; complete selected spans | ADMISSION:NORM_REFERENCE_INVALID | 1 / 3089 | Technical/source admission failed; no admitted semantic label |
| telecom | ministral-14b-2512 | mistral_telecom_coverage_final | P1 | ERROR / ERROR | True | norm 2; history 6; current 1; complete selected spans | none | 1 / 6103 | Correct core cause; auxiliary defects are audited separately |
| multicall | ministral-14b-2512 | mistral_multicall_I4 | P1 | ERROR / ERROR | True | norm 1; history 25; current 4; complete selected spans | none | 1 / 15276 | Correct core cause; auxiliary defects are audited separately |
| exception | ministral-14b-2512 | mistral_exception_I4 | P1 | None / ERROR | False | norm 1; history 10; current 1; complete selected spans | ADMISSION:EVIDENCE_REFERENCE_OR_ACTOR_INVALID | 1 / 5194 | Technical/source admission failed; no admitted semantic label |

Non-inference records: reused historical R0 plan (prior protocol, 4398 prior tokens, zero new calls); Stage-A code aggregation (two UNKNOWN decisions, zero calls); V1 no flags and V2 skipped (zero calls); source-qualified V3 oracle diagnostic (zero calls); Gemma full-fence format diagnostic (zero calls, a distinct post-hoc admission contract). Additional full-source banking081 local exception and long-context navigation audits are offline, not model accuracy trials.
