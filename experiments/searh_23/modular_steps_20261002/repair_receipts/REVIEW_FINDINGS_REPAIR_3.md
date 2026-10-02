# REVIEW_FINDINGS_REPAIR_3 — Independent audit #3 (final pre-report gate)

- **Auditor:** independent code-auditor subagent (AUDIT-R3)
- **Date:** 2026-10-02
- **Scope:** offline final gate before the final report + push — secrets scan of the
  whole diff since base, §13 artifact completeness, freeze/ledger invariants at HEAD,
  dual-F1 scorer correctness, honest-disclosure check, worklog continuity.
  No paid calls, no `--run`, no ledger modification, no fixes, no push.
- **Base..HEAD:** `ff4366cd..b6160067` (9 commits, 39 files, +6814/−3 lines;
  worktree clean at audit time; HEAD = `b6160067c892aa1489ea8502d9b737a4bbf57022`).

## 1. Secrets scan (whole diff ff4366cd..HEAD) — CLEAN

Full diff (7094 lines / 599,514 bytes) dumped and scanned with independent patterns:

| Pattern | Hits |
|---|---|
| `Authorization` / `Bearer` headers | 0 (one prose word "authorization" in a budget note in `budget_reconciliation.json` — describes assignment §10 spending authority, no credential) |
| `api_key` with a value | 1 — `test_single_layer_budget.py`: `self.api_key = 'test-slot-key'` — a placeholder inside the offline fake-client fixture; not a credential |
| known key names `mistral`/`ukisai`/`vireonix` as env VALUES | 0 for `ukisai`, 0 for `vireonix`; all `mistral` hits are the model/channel name in prose and receipts |
| base64 blobs > 100 chars | 0 |
| hex blobs > 64 chars | 0 |
| token prefixes `sk-` / `ghp_` / `gho_` / `AIza` / `xox*` / JWT `eyJ` | 0 |
| URLs with embedded credentials or `?key=`/`token=` | 0 |
| `os.environ` / `getenv` in diff | 4, all test scaffolding (`GUARDIAN_MODULAR_RESULTS` temp dirs, `GUARDIAN_MODULAR_BUDGET_PHASE` override in tests) — no secret reads |
| binary files in diff | 0 (`git diff --numstat` clean) |

Committed content is only case text (dataset banks), receipts (JSON/JSONL
measurements), code (.py) and documents (.md). **No secrets, tokens, Authorization
values or API keys are present in the committed diff.**

## 2. §13 artifact completeness — all 7 items present

1. **REPAIR_CAUSE_AUDIT** — `experiments/searh_23/modular_steps_20261002/REPAIR_CAUSE_AUDIT.md`
   (18,250 B, 10 sections: method/data, attribution, T1–T19 mechanism atlas with
   counterexamples, mechanical quote check, payload audit, assignment-cause mapping,
   gold-dispute preservation, fixes+counterexamples, non-conclusions, reproducibility)
   + `repair_receipts/fp_cause_atlas.json` (21 cases / 19 mechanisms / 9 fixes;
   attribution carries the R-102-corrected `18/21 B_invented_additional_error...`)
   + raw corpora `repair_receipts/routing_fp.jsonl` (21 rows, each with prompt,
   response, `B_raw_content`, `gold_basis`, `source_sha256`) and
   `repair_receipts/temporal_fp.jsonl` (12 rows, paired with/without advisory).
2. **Offline regression tests + independent REVIEW_FINDINGS** —
   `test_single_layer_budget.py` 7/7 PASS, `test_atomic_v2.py` 10/10 PASS
   (re-run at HEAD by this auditor); older suites also green: `test_boundaries.py`
   16/16 (unittest OK), `test_budget_breaker.py` 12/12, `test_evidence_binding.py`
   9/9 — 54/54 offline tests pass. `REVIEW_FINDINGS_REPAIR_1.md` / `_2.md` are
   committed in `repair_receipts/` and md5-identical to the results-dir originals
   (`2f143e55…`, `b7458a02…`).
3. **MODEL_ROLE_PROTOCOL + availability receipts + frozen banks/configs** —
   `MODEL_ROLE_PROTOCOL.md` (§1 availability matrix incl. aihorde no-usage and
   glm-5.3-flash 402-blocked; §2 frozen banks/contracts/rules);
   `repair_receipts/model_census.json` (7 probe receipts with usage+latency; aihorde
   usage honestly `null`; glm excluded without spend; mistral covered by existing
   production receipts); `role_selection.json` / `deferred_selection.json`;
   `dataset/deferred_bank/{input,author_gold,manifest}.json` — manifest
   `input_sha256`/`gold_sha256` recomputed and match, 24 rows (11 error / 13 clean),
   selection's `bank_manifest` equals the file, `gold_access: runner never reads
   author gold; post-run scorer only`.
4. **Full safe raw responses/predictions/source/config/model hashes/costs** —
   `results/.../role_pilot/role_predictions.jsonl` (174 rows; 201 per-call records;
   each call carries `request_sha256` + `usage` {prompt/completion/total tokens} +
   raw `content` + `elapsed_s` + seed/temperature; rows carry `source_sha256`,
   `code_sha256`, `contract`, `model`) and `results/.../deferred_pilot/predictions.jsonl`
   (54 rows; 78 calls; 78/78 with content+usage+request hash; row-level
   `source_sha256`/`code_sha256`/`contract`/`model`/`wall_seconds`). Three sample
   rows per file verified in detail (see R-303 for the two honest empty-content calls).
5. **Unified scorer + paired comparison + role-level error atlas** —
   `score_roles.py` / `score_deferred.py` both implement the auditor-R2 dual F1
   (`frozen_mapping` block: UNKNOWN → correct-on-clean / miss-on-error) and write
   paired transitions vs C0; `fp_cause_atlas.json` is the role-level error atlas.
6. **Decision on working chain + reproducible command** — MODEL_ROLE_PROTOCOL.md §6:
   best single judge = gpt-oss:20b with V1 contract (dual-F1 1.0 on both banks),
   cross-candidate gptossE→gemmaJ, honest negatives (k=3 / 3-role no gain), R0/C0
   default unchanged (production change out of mandate); reproducibility commands
   (`role_pilot.py --run`, `deferred_pilot.py --run`, `score_roles.py`,
   `score_deferred.py`) + raw-journal and receipts locations listed.
7. **Remaining-work census** — tail of `docs/searh_23/MODULAR_METHOD_CENSUS_2026-10-02.md`
   contains the "Repair/model-roles assignment — COMPLETE" section (§4–§9.6 receipts,
   both auditor verdicts) ending with an explicit remaining-work list (human review
   of deferred author gold; structural-shortcut temporal arm; conditional third-role
   routing arm; X_gemmaE_gptossJ measurement; graph ID/time-hint arm; C1/M3/A4 +
   sealed protocol work). Push SHA: see R-301.

## 3. Freeze / ledger invariants at HEAD — ALL HOLD

| Invariant | Expected | Recomputed at b6160067 | Verdict |
|---|---|---|---|
| reviewer_repair api attempts | exactly 300 | `SUM(api)=300` (382 rows: 299 COMPLETE + 1 COMPLETE_USAGE_UNKNOWN_UPPER_BOUND + 82 CACHE_HIT) | OK |
| pending reservations | 0 | `RESERVED` rows = 0; breaker_state empty | OK |
| reviewer_repair tokens | ≤ ceilings | known 465,984 / unknown 593 / logical 597,414 (300/1M/200k/1.2M) | OK |
| module isolation | census(7)+atomic-v2(25)+role(189)+deferred(79) | module api sums reproduce exactly 7/25/189/79 | OK |
| dev2 ledger unchanged | 263 api, md5 `613bbdff…`, mtime 07:27:39 | `SUM(api)=263`, md5 `613bbdff848272b319ee691811c98116`, mtime 2026-10-02 07:27:39 | OK |
| negative-pilot freeze | `d41f244f…` | recomputed code_identity over the 6 declared files = `d41f244f35cb196da0a21761fe18d17bb7523210c93969c3ea67d6298e0fe627` == `negative_review_pilot_v4/selection.json` | OK |
| role selection | FROZEN_BEFORE_RUN, sha of `role_pilot.py`+`role_prompts.py` | recomputed `9c5fb1056253d0fa69ee4e735e1c2abfb64d34916885167a6a0e28d8c69ecec0` == `repair_receipts/role_selection.json` == results copy | OK |
| deferred selection | FROZEN_BEFORE_RUN, sha of `deferred_pilot.py`+`role_prompts.py` | recomputed `d34b673270901acb7f35d4729b5e3127378aa10df8282caf80b2cc5d7133e887` == `repair_receipts/deferred_selection.json` == results copy | OK |
| sealed | untouched | no modular sealed/heldout ledger exists; legacy hybrid sealed dirs untouched | OK |

## 4. Dual-F1 correctness — VERIFIED

`score_roles.py` and `score_deferred.py` re-run by this auditor (offline; they read
predictions+gold only): both reproduce their receipts **byte-identically**
(role `score.json` md5 `1bfcd1fe2652ff91f002dde9558bce62`, deferred `score.json` md5
`301d4d3aa85091a17184ac0b515255bb`, unchanged before/after re-run); the committed
copies in `repair_receipts/` are equal to the results-dir scores.

| Check (auditor-R2 expectation) | Expected | Actual | Verdict |
|---|---|---|---|
| `EJ_gemma_gemma/J` frozen-mapping F1 | .9091 (raw 1.0) | frozen `.9091`, raw `1.0` (frozen TP/FP/FN/TN 5/0/1/6 — the 1 UNKNOWN falls on the gold-1 case → FN) | OK |
| `C0_J_control` deferred frozen F1 | .5 (raw .6154) | frozen `.5`, raw `.6154` (frozen 4/5/3/6 — 7 UNKNOWN → 3 FN on error + 4 TN on clean) | OK |
| `D_V1_gptoss` both mappings | 1.0 / 1.0 | role 1.0/1.0 and deferred 1.0/1.0 | OK |

All other rows reproduce the protocol tables exactly (D_V1_gemma .9091/.9091;
D_V1_mistral .9231; D_V1_nemotron 1.0 with the abstention→TN in frozen; Gk3 seeds
.9091 each; deferred D_V1_gemma .875/.875 with the 2 equal-instant FPs).

## 5. Honest-disclosure check (MODEL_ROLE_PROTOCOL.md) — all six present

| Required disclosure | Location | Present |
|---|---|---|
| banks small / PENDING human gold | §7 bullets 1–2 ("Банки малы (12 + 18 измеренных троек)… Авторский gold … PENDING"; disputes preserved) | YES |
| EJ/Gk3/G3/cross not re-measured on deferred | §7 bullet 3 | YES |
| X_gemmaE_gptossJ unmeasured | §7 bullet 3 + §4 note | YES |
| 18/24 triples measured | §4 header + §7 bullet 1 + §4 "6 кейсов банка не измерены (BUDGET_STOP на 300/300)" | YES |
| aihorde no-usage | §7 bullet 4 + §1 table | YES |
| R0 default unchanged | §6 decision section (also census "Default service config R0 unchanged" + ENVIRONMENT.md addendum) | YES (placement: §6, see R-302) |

## 6. Worklog continuity — CONFIRMED

`/home/z/my-project/worklog.md` contains sections through TA-8, TA-9, TA-10 (§6
repair + §7 census + §8 role matrix + §9.6 deferred), AUDIT-R1
(PASS_WITH_LIMITS, R-101..106 closed) and AUDIT-R2 (PASS_WITH_LIMITS,
R-201 closed via dual-F1, R-202..206 disclosed). AUDIT-R3 appended by this audit.

## Findings (R-3xx)

### R-301 — NOTE — push SHA not yet recorded in repo artifacts (pre-push timing)
- **ID/Severity:** R-301 / NOTE (no action required before push; bookkeeping).
- **SHA-file:** HEAD `b6160067`; census `docs/searh_23/MODULAR_METHOD_CENSUS_2026-10-02.md`; `MODEL_ROLE_PROTOCOL.md`.
- **Counterexample:** census/protocol cite per-stage SHAs (160a4e98, 2000afff,
  191c70e7, 697e419e, 2efb7163, 0a592cfb, da654292) but neither document records
  the final HEAD `b6160067`; `origin/research/modular-step2-4-20261002` is still at
  `ff4366cd` (8 local commits unpushed) — expected, since the push is gated on this
  audit and the final report.
- **Expected vs actual:** expected: final report records the pushed SHA; actual: the
  SHA exists only as HEAD at audit time.
- **Re-check:** after push, `git rev-parse origin/research/modular-step2-4-20261002`
  must equal the SHA stated in the final report. Recommended (matches the R1/R2
  pattern): commit `REVIEW_FINDINGS_REPAIR_3.md` into `repair_receipts/` before the
  push so the receipt chain is complete — then the push SHA is that successor commit,
  not `b6160067`.

### R-302 — NOTE — "R0 default unchanged" disclosed in §6, not the §7 limitations list
- **ID/Severity:** R-302 / NOTE (content present; placement-only deviation).
- **SHA-file:** `experiments/searh_23/modular_steps_20261002/MODEL_ROLE_PROTOCOL.md` @ b6160067.
- **Counterexample:** audit brief expects the limitations section to state "R0
  default unchanged"; §7 lists the other five disclosures, while the statement
  "default R0/C0 не менялся и не заменён (изменение продакшн-маршрута — вне мандата…)"
  sits in §6 (decision on the working chain).
- **Expected vs actual:** expected: disclosure present in the protocol; actual:
  present, in §6, additionally in the census ("Default service config R0 unchanged")
  and the ENVIRONMENT.md addendum. A reader cannot miss it; no misleading omission.
- **Re-check:** none required; optionally move/duplicate one line into §7 in a
  future doc revision.

### R-303 — NOTE — raw-journal completeness nuances (honest, already disclosed)
- **ID/Severity:** R-303 / NOTE (no defect; recorded for receipt transparency).
- **SHA-file:** `results/modular_steps_20261002/role_pilot/role_predictions.jsonl`.
- **Counterexample (a):** 2 calls (arm `D_V1_nemotron`, case
  `dev_refusal_inventory::00`) have empty `content` with `usage.completion_tokens=2000`
  (token-cap hit), `valid=False`, `reason=unparseable_json`, `request_sha256`+usage
  recorded — this is exactly the reported "1 abstention" (gold 0 → TN in frozen
  mapping), not missing data.
- **Counterexample (b):** 7 `G3_counterevidence` rows have empty `calls` with
  `reason=no_accusation_to_review` — the role only runs when the checker accused;
  consistent with the 5 measured G3 rows and with AUDIT-R2 R-206 (G3 row is
  UNKNOWN×12 in the binary table; real result in the journal).
- **Expected vs actual:** expected: every journaled call carries content+usage+hash;
  actual: 199/201 role calls and 78/78 deferred calls do; the 2 exceptions are
  transport-honest cap-hits with full usage/hash provenance, and empty-call rows are
  role-semantics (no accusation to review), both reflected in the reported
  UNKNOWN/abstention counts.
- **Re-check:** none; numbers already disclosed in protocol §3/§4 and AUDIT-R2.

## Overall verdict

**PASS** for the final report and push.

- Secrets scan of the entire `ff4366cd..HEAD` diff: clean (two benign hits: one
  prose word in a budget note, one test-fixture placeholder key).
- All §13 artifact items (1)–(7) present and internally consistent; all 54 offline
  regression tests pass at HEAD.
- All freeze/ledger invariants hold exactly: reviewer_repair 300/300 api with 0
  pending; dev2 untouched (263 api, md5 `613bbdff…`); negative-pilot freeze
  `d41f244f…` and both pilot freezes (role `9c5fb105…`, deferred `d34b6732…`,
  FROZEN_BEFORE_RUN) re-derived and matching; sealed untouched.
- Dual-F1 scorers reproduce receipts byte-identically with the required
  frozen-mapping values (EJ_gemma_gemma/J .9091; C0_J_control deferred .5;
  D_V1_gptoss 1.0 under both mappings on both banks); committed receipts equal
  results-dir receipts.
- All six mandated honest disclosures are present (R-302 notes one placement nuance).

The study-level limits (small banks with PENDING human gold, 18/24 deferred triples,
unmeasured multi-call arms incl. X_gemmaE_gptossJ, aihorde upper-bound accounting,
R0 default unchanged) are already disclosed in MODEL_ROLE_PROTOCOL.md §4/§6/§7 and
must be carried into the final report as-is; AUDIT-R3 adds no new blockers.

*Audit method: independent recomputation (own SQL on read-only sqlite URIs, own
sha256 re-derivations of every code-identity, own diff-wide pattern scans), scorer
re-runs with md5 before/after comparison, offline test execution, and document
review. Nothing was fixed, modified or pushed; the only writes were this file and
the local worklog entry.*
