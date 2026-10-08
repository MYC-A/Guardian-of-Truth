# Independent code review: Qwen binding contract repair

Reviewed the working-tree changes based on `51160fcd` in branch
`fix/qwen-binding-contracts-20261008`. This is a separate code review by a
subagent, with production-parser regression fixtures and offline probes. It is
not an independent annotation exercise or a new inference experiment. No model,
API or SSH calls were made, and historical outputs/gold were not edited.

Reviewed modules: `experiments/guardian_binding/{idcheck,audit,eval_idcheck}.py`
and `experiments/guardian_complementarity/{combine,combine2}.py`; inspected their
transport, schema, freeze and scorer dependencies. Runtime implementation was
owned by the parent agent. This reviewer authored
`tests/test_qwen_binding_boundaries.py` and this document.

## Reviewed improvements

- **Proposal authority:** every A/B/C discovery is now explicitly an unverified
  `HYPOTHESIS`, with binding/applicability unresolved and no final authority.
  The default projection in `eval_idcheck` preserves Qwen's existing decision;
  the former heuristic OR requires the explicit `HISTORICAL_UNSAFE_OR` arm.
- **Exact current arguments:** source admission resolves the named current-call
  argument, including RFC6901 paths, instead of searching for a value anywhere
  in the serialized target. Missing fields, substrings, identity case changes
  and duplicate JSON keys cannot pass this admission.
- **Source boundaries:** quotes are checked exactly. An assistant prose claim
  cannot impersonate a tool observation; a parser-owned tool result remains
  usable despite its enclosing assistant turn. Successful string checks yield
  `SOURCE_SUPPORTED_MISMATCH`, never `VERIFIED_MISMATCH`.
- **Transport/schema separation:** failed transport, non-`stop` completion,
  malformed JSON, schema failures and duplicate argument assessments remain
  nonbinary technical statuses. An empty assessment array is explicitly only
  model-selected coverage, not proof that every argument is correct.
- **Runner integrity:** a new output namespace prevents mixing old enforcement
  receipts with source-only receipts. Inputs/config/module hash are frozen;
  max calls, workers and timeout are included. Per-row exceptions preserve a
  technical record; resume validates IDs/version/duplicates and completion
  checks the full expected ID set. Model-level process locking protects the
  shared cache/budget across these runner processes.
- **Crash-safe cap:** the runner's `ReservedClient` fsyncs a reservation before
  delegating a call. An abandoned reservation is not released on resume. This
  closes the reproduced underlying-transport gap where a crash before its
  post-response `SENT` entry allowed a second dispatch with `max_calls=1`.
  The cap deliberately counts cache lookups as well as live/abandoned calls;
  it is a conservative attempt cap, not a count of actual HTTP calls.
- **Scoring:** technical `no_solution` rows are no longer silently converted
  into binary zero by the combiner. Binding-only source checks remain unknown.
  Granite loading rejects duplicate IDs and requires successful status before
  using a risk token. The scorer exposes conditional F1, unresolved positive
  and negative counts, explicit unknown-to-zero F1 and full-completion bounds.

## Defects found during this review

Two independent offline probes reproduced failures before their fixes: distinct
content-only successful receipts were silently deduplicated, and an interrupted
sender could exceed the underlying transport cap after restart. Regression tests
now cover content-only duplicate conflicts and durable pre-dispatch reservation.

The duplicate signature now includes receipt key, request hash and both raw
content fields. A final corner was found where a present `raw_content=None`
hid conflicting `content` values; retaining both fields closes it. The dedicated
regression test passes alongside the content-only and raw-content cases.

## Remaining limits and interpretation

1. **Semantic binding is not implemented.** Exact argument and quote support
   does not establish that the quoted field belongs to the requested entity,
   that a snapshot is current, or that a policy actually requires this value.
   Applicable scope, exceptions, consent, chronology and closure remain
   unresolved. A source-supported mismatch is a proposal, not a policy proof.
2. **Historical six TP additions are not retained as decisive gains.** Five
   arise from the same phone/line pattern and one from the turn-format heuristic.
   The corrected default shadows all of them. Their old labelled improvement is
   useful diagnostic evidence, but not measured quality of a repaired universal
   enforcement layer.
3. **Discovery remains heuristic.** Tool-name prefixes, ID shapes, first object
   ID, substring grounding, historical snapshots and broad textual prohibitions
   can still create false suspicions or miss true ones. Parser-level contrasts
   cover lawful mutation, stale records, JSON field reordering and unrelated
   prohibitions. They establish that such suspicions cannot certify violations;
   they do not establish a complete or invariant discovery algorithm.
4. **Typed coverage is partial.** Current argument admission supports strings;
   numeric, boolean, object and array values are rejected as unsupported even
   though the historical prompt mentions quantities. Empty/partial model
   assessment lists remain unchecked coverage, not a clean bill of health.
5. **Historical base scoring is not source proof.** The inherited
   `review_valid` dependency does not reject every prefixed `REJECTED:...`
   admission, so surviving base fallback/verdict rows must not all be described
   as evidence-admitted. Correcting that definition requires its own explicit
   cohort/projection comparison. None of these repairs validates a base reason.
6. **No new automatic quality claim:** this review performed no new inference,
   no blind holdout or independent gold adjudication. A partial `QB2|BIND`
   comparison on the no-current-call subset is not an improved full Qwen system.
   Conditional F1 and completion bounds must remain visible when technical or
   unresolved rows exist. No universal gain or production readiness is proved.

## Validation

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
$env:PYTHONPATH='src;.'
python -X utf8 -m pytest tests/test_qwen_binding_boundaries.py tests/test_qwen_binding_receipts.py -q
```

At the reviewed snapshot: **35 passed**. The tests use no network. Production
parser fixtures exercise the declared input format and retain original actor,
event and argument structure. A passing test set supports the listed boundary
repairs, not general semantic correctness or a binary F1 improvement.
