# Independent source coverage audit

All 600 frozen offline packets (15 original cases ? 10 methods ? four budgets) were independently checked. Original-interval union scoring, alternative completeness, and full source-array UTF-8 costs match the saved scorer: **zero per-packet discrepancies, zero aggregate discrepancies, zero source-integrity failures**. All current assistant targets are present in 600/600 packets. No fixture, selection, runtime, or model request was changed for this audit.

Protocol: `4a4c4bb630aac8108afe93d91a73e5eec55af884f35ca9c421ed2bf39d1ea5d5`. Canonical frozen references: `63214a04b15c131352cb938a3cbf583f17855958a50cf13041353809f1ff57cf`. The split is development 8 and known evaluation 7, not a hidden holdout.

## Eight-read comparison

Each complete count is relative to a curated valid evidence alternative, not binary F1. `Raw / operational` separates address coverage from a supported executable packet: operational means raw complete AND no packet failure. Targets and current declarations are explicitly supplied and count as evidence; they are not retrieved reads. `Qualified norms` excludes exactly two declaration-ENUM units incorrectly annotated as reason-code semantics in bank081. Frozen raw metrics and method selection remain unchanged.

| Method | Dev raw / operational complete | Dev norms | Dev history | Known-eval raw / operational complete | Eval raw / qualified norms | Eval history | Failures dev / eval |
|---|---:|---:|---:|---:|---:|---:|---:|
| A | 2/8 / 1/8 | 3/13 | 2/22 | 0/7 / 0/7 | 2/15 / 0/13 | 0/30 | 6 / 7 |
| local_bm25 | 1/8 / 1/8 | 5/13 | 6/22 | 3/7 / 3/7 | 12/15 / 10/13 | 2/30 | 0 / 0 |
| B1 | 2/8 / 2/8 | 5/13 | 8/22 | 1/7 / 1/7 | 6/15 / 4/13 | 6/30 | 0 / 0 |
| B2 | 1/8 / 1/8 | 6/13 | 4/22 | 3/7 / 3/7 | 12/15 / 10/13 | 1/30 | 0 / 0 |
| B3 | 1/8 / 1/8 | 6/13 | 4/22 | 2/7 / 2/7 | 10/15 / 8/13 | 4/30 | 0 / 0 |
| exact_graph | 1/8 / 1/8 | 0/13 | 4/22 | 0/7 / 0/7 | 2/15 / 0/13 | 4/30 | 0 / 0 |
| bm25_exact | 2/8 / 2/8 | 5/13 | 6/22 | 1/7 / 1/7 | 7/15 / 5/13 | 8/30 | 0 / 0 |
| bm25_exact_graph | 2/8 / 2/8 | 5/13 | 6/22 | 1/7 / 1/7 | 7/15 / 5/13 | 8/30 | 0 / 0 |
| rrf | 2/8 / 2/8 | 4/13 | 7/22 | 1/7 / 1/7 | 7/15 / 5/13 | 5/30 | 0 / 0 |
| coverage | 2/8 / 2/8 | 4/13 | 6/22 | 0/7 / 0/7 | 6/15 / 4/13 | 4/30 | 0 / 0 |

B1 was selected by the already frozen development criteria. Its two development complete cases are airline23 (automatic booking-schema alternative) and retail106 (invented ZIP with the matching user source). Its one known-evaluation complete case is airline9 via the multi-call rule. Known evaluation favors local_bm25/B2 on this metric (3/7 versus B1 1/7); this observation does not retune the frozen choice.

A is unsupported on 13 of 15 cases and retains its intrinsic eight-read limit even at an advertised twelve-read comparison. A has raw 2/8 development but operational 1/8: airline23 supplies a genuine payment-schema alternative through mandatory declaration+target despite A having zero reads and an unsupported-case failure. This is legitimate reference coverage and an unsuccessful A execution simultaneously. On the only two cases supported by A, the matched result is **A 1/2 versus B1 0/2**, for all four budgets. Therefore the broader operational 1/8 versus 2/8 result cannot be called a comparable improvement over A.

## Selected B1 across budgets

| Split | Budget | Complete raw / operational | Raw / qualified norms | History |
|---|---|---:|---:|---:|
| dev | k8 | 2 / 2 | 5/13 / 5/13 | 8/22 |
| dev | k12 | 2 / 2 | 6/13 / 6/13 | 13/22 |
| dev | k8_t20000 | 2 / 2 | 5/13 / 5/13 | 8/22 |
| dev | k12_t20000 | 2 / 2 | 6/13 / 6/13 | 12/22 |
| evaluation_known | k8 | 1 / 1 | 6/15 / 4/13 | 6/30 |
| evaluation_known | k12 | 1 / 1 | 6/15 / 4/13 | 7/30 |
| evaluation_known | k8_t20000 | 1 / 1 | 6/15 / 4/13 | 6/30 |
| evaluation_known | k12_t20000 | 1 / 1 | 6/15 / 4/13 | 7/30 |

Moving B1 from eight to twelve reads improves development history coverage 8/22 ? 13/22 (12/22 at the conservative 20,000 UTF-8 source-array bound), and known-evaluation history 6/30 ? 7/30. It does not increase complete-alternative counts. That bound is a reproducible byte budget, not provider-token usage, and whole model prompt overhead is measured separately by the runner.

## Reference and interpretation limitations

The independent source-semantic sidecar identifies bank081 offsets **8654?8796** and **8697?8796** as declaration enum symbols, not historical KB definitions or priority semantics. The actual KB definition rows are **18023?18190** and **18191?18363**, preserved only as diagnostic sidecar evidence. They were not added to frozen references or retrieval input. Excluding the enum units changes known-evaluation B1 normative recall 6/15 ? 4/13 and A 2/15 ? 0/13. It does not alter the local four-request alternative, which never included those units. Qualified recall still concerns the curated inventory, not all policy norms.

Two cases were already marked partial: airline9 has unresolved airline-cancellation world status although its multi-call ERROR is clear; bank081 has supported local transfer permission with unresolved whole-move reason-code/summary scope. No method/budget completes bank081's local curated alternative. Complete local evidence is not a whole-move NO_ERROR certificate.

**All six original label-0 cases fail the curated complete-set criterion under every method and budget.** Some alternatives require contextual facts beyond a minimal ERROR proof; negative cases also need richer claim and scope discrimination. This creates class asymmetry in the reference-completeness selection metric. It cannot substitute for binary accuracy or F1, and it does not prove that the model necessarily fails those cases. No independent holdout conclusion follows.

Nine cases never achieve a complete curated alternative in any of the 40 method/budget variants: airline3, bank057, bank068, retail87, Telecom USER-device-call t7, bank080, bank081, Telecom permissions t15, and bank083. Their per-category omissions and every alternative's numerator/denominator are retained in the audit JSON. For long-context bank080/bank081, this establishes incomplete critical-source access in this bakeoff; it is not a model quality or absence-based violation result.

Every history-missing flag is an omission relative to manual reference spans. It is a **risk marker**, not an observed model false-absence inference and not proof that the complete journal lacked an event. Reads called unnecessary are unnecessary only relative to this nonexhaustive curated inventory; they can still have legitimate semantic relevance.

## Artifacts

- `outputs/retrieval_bakeoff_v1/independent_coverage_audit.json`: 600 independent per-packet category/alternative checks, 80 aggregates, integrity/discrepancy results, operational and class-specific counts, matched A-supported comparison.
- `outputs/retrieval_bakeoff_v1/reference_semantic_audit.json`: frozen-versus-qualified normative sensitivity on all 600 packets, exact enum defect and independently located KB definitions, without changing any frozen inputs.
