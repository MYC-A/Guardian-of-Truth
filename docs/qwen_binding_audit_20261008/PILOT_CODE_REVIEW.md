# Independent pre-pilot code review

Reviewed on 2026-10-08 by the independent code-review subagent before pilot inference. Scope: `experiments/guardian_binding/blind.py`, `pilot.py`, their focused tests and the reused parser, packet builder, client, reservation ledger and transport. Reviewer made zero SSH, model API, tokenization API or metadata API calls. All runner probes replaced metadata, token counting and inference with local fixtures. Only this document was intentionally edited by the reviewer.

**Verdict: no remaining blocking code issue found in the reviewed pilot.** This is a bounded diagnostic implementation, not a semantic correctness guarantee or a code certificate of policy violation. The live server identity, tokenizer/template behavior and model quality are not independently measured by this review.

## Findings resolved before inference

1. The initial runner counted tokens against default port 8081 while the reused client defaulted to 8080. The corrected runner resolves one endpoint through `backend_endpoint`, uses it for native preflight and inference, restricts it to loopback, verifies the served model alias/context limit and freezes endpoint plus served metadata in its manifest.
2. Initial technical failures inherited `automatic_addition=False`. The corrected runner starts with null, preserves technical/parse/schema failures, unverified remaining candidates and current-argument parse gaps as null, and retains an already supported positive if a later candidate fails. `False` means no addition by the measured mechanism; it does not certify compliance.
3. A malformed current-call JSON could otherwise produce an empty inventory and a false negative addition flag. `coverage.current_gaps` now prevents that projection.
4. An initially suspected invalid empty-enum schema was checked and the allegation withdrawn: the local schema validator accepts the schema. The implementation additionally uses a zero-length reference array without an impossible item enum for the no-policy case. The local no-policy regression passes.

## Verified boundaries

- Blind requests omit current scalar values and current prose. They retain action names, argument paths/types and original history. Historical coincidences are not scrubbed. Blindness remains conditional on the supplied packet; an upstream retrieval choice can itself depend on the action. The visible control adds current values; Decimal numbers are serialized as exact decimal strings alongside their explicit NUMBER type.
- Code compares exact, typed scalar leaves addressed by strict RFC6901 pointers. It rejects ambiguous JSON keys, nonfinite numbers, malformed call/result framing, wrong target/path identity, duplicated assessments and non-result expected sources. Genuine parser-owned assistant/tool receipts are allowed; assistant prose cannot serve as the expected JSON receipt.
- Exact citations and typed leaf inequality yield `SOURCE_SUPPORTED_ONLY`, unresolved semantic/applicability authority and `certificate=False`. The verifier receives the full supplied packet, checks local schema/exact quotations, and requires a cited current target plus policy/evidence references for SUPPORTED. Its result remains `MODEL_JUDGMENT`, with `code_certificate=False`; applicability, temporal relevance and entity meaning remain model judgments.
- Runtime input allows only id/prompt/response, and row IDs are not serialized into the model packet. Gold is not read by this runner. The 16 author-controlled diagnostic rows traverse the production packet builder with complete coverage, one or two scalar paths and no current-call parse gaps. They are not an independent holdout.
- Reservation writes are fsynced before dispatch, cumulative across resume and conservative across abandoned/cached calls. The phase lock protects the shared output/cache; transport retries default to zero. Manifest changes, duplicate resume identities and incomplete final inventories are refused. With 86 rows, two modes and at most two verifiers, the maximum is 516 inference requests, within the proposed 520 reservation cap. Metadata/template/tokenization requests are separate non-generation preflight traffic.

## Independent offline validation

System Python 3.13, `PYTHONPATH=<worktree>;<worktree>/src`:

```text
python -X utf8 -m pytest -q tests/test_qwen_blind_binding.py tests/test_qwen_binding_pilot.py tests/test_qwen_binding_receipts.py
61 passed in 0.68s
```

Additional adversarial in-process probes, with no network:

- Duplicate-key extraction reply rejected locally.
- Successful blind/visible extraction and verification: four mocked calls, two supported rows; resume preserved records byte for byte and made no further calls.
- Context overflow: zero inference calls; both rows retained null addition.
- One-reservation budget: one mocked call total; verifier refusal and subsequent extraction refusal retained null additions.
- Duplicate-key current argument JSON: both rows retained explicit parse gaps and null addition.

The first test attempt used an older unrelated replay environment lacking `jsonschema`; it did not collect tests. Validation above used the installed system dependencies. Test imports initially refreshed three tracked generated `guardian_addons/__pycache__` files; the parent restored them from HEAD, and subsequent tests used `PYTHONDONTWRITEBYTECODE=1`.

## Limits for interpreting the pilot

The schema caps assessments at 12 scalar leaves and output at 1700 tokens; omitted arguments remain visible in coverage. A valid model abstention or empty assessment can yield no addition and therefore a binary FN under an explicit OR projection. No addition must not be described as proof of no violation. Empty-norm packets cannot establish a policy violation through this verifier. Native live preflight and malformed server-response behavior have not been exercised by the independent reviewer. This review does not claim improved F1, generalization or independence of the synthetic diagnostics.

## Phase 2 compact-format addendum, 2026-10-08

**No blocking code issue found for the separately frozen compact diagnostic phase.** Reviewed `blind_compact.py` and the runner's new `--wire compact` / `--timeout 240` routing without SSH or API calls. The parent reported Phase 1 explicitly stopped after transport timeouts; partial records, reservations and manifest are preserved under `phase1_transport_stop`. This review does not certify completion of that stopped phase or reuse its incomplete inventory as a completed evaluation.

The compact module reuses the exact v1 user-message source view and blind/visible intervention, with six output fields and a 900-token output budget. Source-address admission delegates to the same strict typed-leaf and target-identity code. Duplicate JSON keys, unknown IDs, noncanonical pointers, failed receipts and assistant-summary request sources remain rejected or unresolved. `request_quote` is the full code-owned source text, explicitly marked `CODE_SOURCE_TEXT`; it is not a quote selected by the model. Both records and mismatch candidates retain `MODEL_HYPOTHESIS`, unresolved binding/applicability, no certificate and no final code authority. The unchanged full-packet policy verifier remains necessary before an addition.

This changes more than key length: the system prompt changes, model rationale/policy selection/quotes are removed, and request references are restricted to historical USER text rather than all history. Therefore Phase 2 must remain a distinct output/cache/config phase, and it is not a pure output-length latency ablation or a repair of frozen Phase 1 predictions. The paired blind/visible comparison within Phase 2 uses the same compact contract in both arms. Lower latency is a hypothesis until measured.

The runner freezes `wire`, timeout and compact-module hash, and passes the chosen timeout to the actual client. Existing phase fingerprints refuse an incompatible resume; extraction request/cache identity changes with the compact prompt/schema, and verifier hypotheses carry the compact provenance fields. The durable reservation cap, null technical-failure projection, native context check and complete paired output inventory are unchanged. Timeout 240 changes inference waiting time; preflight HTTP helpers retain their existing shorter timeouts. The 520-call limit applies to Phase 2's own reservations, not retrospectively to the sum of separately stopped phases; report cross-phase attempts separately.

Independent validation with bytecode writing disabled:

```text
python -X utf8 -m pytest -q tests/test_qwen_blind_compact.py tests/test_qwen_blind_binding.py tests/test_qwen_binding_pilot.py
60 passed in 0.76s
```

An additional offline main-runner probe exercised compact extraction and the existing policy verifier in both modes: four mocked calls, 900-token requests, timeout 240 passed to the client, `wire=compact` and compact-file hash frozen in the manifest, compact admission version retained, and byte-identical resume with no additional calls. Reviewer HTTP/SSH/model inference calls: zero. The v1 binding module was not edited by this review.

## Offline scorer review and independent regressions

Reviewed `scripts/qwen_binding_pilot_score.py` while Phase 2 ran; no live Phase 2 quality results were read. Added only `tests/test_qwen_binding_pilot_score.py` and this documentation. Scorer fixes were implemented by the parent, outside the frozen inference modules.

The initial scorer had three reproduced reporting issues: a complete subset of expected inputs could claim quality eligibility while scoring additional gold IDs; a non-boolean integer addition could be quality-eligible yet counted as an undecided detector prediction; and the two unlabeled external inputs were omitted from `unlabelled_external_ids` because they were absent entirely from the 68-key gold file. The corrected scorer rejects gold outside expected IDs, overlapping external/contrast gold and non-boolean/non-null additions, and reports expected IDs outside labeled external/contrast gold explicitly.

The initial archived-baseline loader used last-write selection whenever binaries agreed. The frozen blob contains 72 records for 70 IDs. The parent inspected the two duplicate records and found differences confined to nested cache-hit flags; no changed raw answer or validity was established. The revised loader explicitly selects the first record, requires equivalence apart from cache metadata and reports the duplicate IDs. Independent tests reject equal-binary duplicates with changed raw reply, request key or admission. The actual archived loader returns 70 IDs and reports `ext_ret_000` / `ext_ret_003` as equivalent duplicates. This is metadata deduplication, not selection of a better answer.

Independent regression result:

```text
python -X utf8 -m pytest -q tests/test_qwen_binding_pilot_score.py
25 passed in 0.16s
```

The tests cover partial/unequal mode inventories, null detector predictions versus explicit cached-base fallback, an unusable baseline remaining unknown unless a positive candidate rescues it, independent external/contrast FP lists, foreign/duplicate rows, strict addition types, gold cohort identity, unlabeled execution coverage, input immutability, receipt/usage accounting, duplicate expected inventory, and archived duplicate equivalence. No model/network calls occur.

Read-only scoring of the stopped Phase 1 artifact confirms four records per mode, quality eligibility false in both modes, and the two unlabeled external IDs `ext_ret_005` / `ext_ret_033` explicitly reported. The saved Phase 1 score was not overwritten. Failed/missing extra-detector rows remain undecided; the candidate combination may explicitly fall back to a usable cached base, which is separately named and must not be confused with a successful extra-detector verdict. Per-mode metrics with missing or null outputs have different decided cohorts; any paired quality comparison must respect the complete/eligibility flags rather than compare conditional F1 as if denominators matched.

Accounting/provenance limits: `receipt_calls` counts saved extraction/verifier receipts, not durable reservations, unfinished requests or actual HTTP attempts; totals require the transport/reservation ledgers. The analysis reads the provided inventory and gold, but does not itself authenticate input text against the inference manifest; use the frozen manifest/input hashes when assembling final reports. The cache-equivalence helper's recursive `cached` normalization is broader than the known receipt paths, so it must not be treated as arbitrary source/business-data equivalence. Actual archived differences were independently narrowed to receipt cache flags. Cause correctness remains pending independent source review; binary recoveries alone do not establish a correct cause. No remaining blocker was found for scoring the frozen known pilot inputs under these stated limits.
