# FIX_MATRIX — defect → general mechanism → code → test → measured effect

Arms (pre-registered in PROTOCOL.md, each an ablation on top of V4): `V4r` = stored V4 reproduced (flags ∅), `R_fix` = all deterministic
fixes {exec, evidence, df_scope, df_copy, df_entity, df_overflow}, `R_df` = DF fixes only, `R_pool` = candidate pool only,
`R_wit` = witness verifier only, `R_comb` = R_fix + pool + witness; `*_mech` = same records, aggregation also accepts a full
mechanical certificate that the verifier did not REFUTE. Measured effects: RESULTS.md (live) and phase2_offline/report.md (replay).

| § | Defect (V4) | General mechanism (no dataset/row ids) | Code | Test (defect + contrast) | Flag / arm |
|---|---|---|---|---|---|
| 5.1 | CRLF checkout changed artifact hashes; no LF contract | `.gitattributes eol=lf` for frozen trees; P0 raw replay of 903 requests, 0 diffs | `.gitattributes`, phase0_raw_replay.json | P0 replay | all |
| 5.1 | Silent last-wins on duplicate/retried records | validated loader: one terminal record per id, retry chains checked, conflicts raise | `repair/records.py` | `test_records_reject_silent_last_wins` | all |
| 5.2 | Fuzzy Q2 match with deleted NOT accepted as support | support kinds JSON_ADDRESSED / VERBATIM / NEAR_VERBATIM_POLARITY_KEPT; polarity tokens checked in ±3 window | `repair/evidence.py` | `test_deleted_negation_is_not_support` | evidence |
| 5.2 | JSON subset accepted from scalars anywhere in text | addressed leaves (pointer); all pairs must share one parent object; id fields bound | `repair/sourcejson.py` | `test_json_pairs_must_share_one_parent` | evidence |
| 5.3 | Eager ADD/SUB/MUL evaluation (only DIV lazy) | lazy op graph, zero/division handled per op | `repair/proof5.py` | `test_add_zero_is_not_eager_division` | exec |
| 5.3 | Seconds/timezone dropped; float money | Decimal at stated precision; datetime keeps seconds + tz | `repair/numeric.py` | `test_datetime_keeps_seconds_and_timezone`, `test_money_is_exact_at_stated_precision` | exec |
| 5.3 | Aggregation dedup by quote string | dedup by leaf identity (source, pointer, occurrence) | `repair/proof5.py` | `test_same_leaf_counted_twice_is_unresolved` | exec |
| 5.3 | LATEST/EQ of another entity accepted | ENTITY_CONFLICT for EQ/NE/LATEST/MEMBER when operand entity ≠ target entity | `repair/proof5.py` | `test_latest_value_of_another_entity_is_entity_conflict` | exec |
| 5.3 | MEMBER_OF orientation (G3e) / incomplete set | POS_SET/NEG_SET orientation + membership closure over addressed arrays; open set → UNRESOLVED | `repair/proof5.py` | `test_membership_orientation_and_closure` | exec |
| 5.3 | Exception clause ignored in mechanical bypass | separate applicability receipt; exception present → no certificate | `repair/proof5.py` | `test_exception_clause_blocks_mechanical_certificate` | exec |
| 5.4 | Rejected/quoted claims treated as assertions | assertion scope REJECT / NEG_BEFORE / QUOTED | `repair/df5.py` | `test_rejected_claim_is_not_an_assertion` | df_scope |
| 5.4 | Global accidental copy suppression | copy suppression only when entity+field+unit match | `repair/df5.py` | `test_copy_suppression_is_scoped` | df_copy, df_entity |
| 5.4 | Hidden first-10-claims cap | extra binder batches for overflow claims; coverage receipt | `repair/df5.py` | (coverage in records) | df_overflow |
| 5.5 | "Thank you" reset consent | proposal → consent/courtesy/revision state machine | `repair/confirm5.py` | `test_thank_you_does_not_reset_consent` | confirm (CB shadow) |
| 5.5 | BK-1 == BK-10; conditional yes = consent | exact canonical ids; conditional/question/new value ≠ consent | `repair/confirm5.py` | `test_identifier_identity_and_conditional_yes` | confirm |
| 5.5 | "does not require confirmation" → requirement | negated requirement detection | `repair/confirm5.py` | `test_negated_requirement_is_not_a_trigger` | confirm |
| 5.5 | Catalog closure from co-occurring words | closure must be unconditional and scoped | `repair/closure.py` | `test_closure_must_be_unconditional` | confirm |
| 5.6 | First REFUTED/INVALID candidate hid later ones | candidate pool with priority/dedup, K_QUEUE=4, rest UNCHECKED (never ERROR); OR aggregation separate from selection | `repair/v5.py` | `test_pool_or_aggregation_and_unchecked_never_errors` | pool |
| 5.7 | cited + recent4 only | witness bundle: older counter-evidence, proposals/confirmations, failed receipts, entity chain from full index | `repair/v5.py::witness` | `test_witness_adds_older_counter_evidence` | witness |
| 5.7 | Truncated verifier reply → inferred verdict | TECHNICAL_FAILURE / NOT_EXECUTED keep candidate unverified | `repair/v5.py::verify` | `test_verifier_technical_failure_keeps_candidate_unverified` | witness/pool |
| 5.8 | Cause judged from reason+gold text only | source-seeing judge, 7 categories, technical failures separate | `repair/cause.py` | CAUSE_AND_GOLD_AUDIT.md | — |

Not changed (measured limitation, see FINAL_DECISION): regex NL applicability is not attempted; CB (confirmation branch) stays shadow.
