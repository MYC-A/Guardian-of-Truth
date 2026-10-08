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
