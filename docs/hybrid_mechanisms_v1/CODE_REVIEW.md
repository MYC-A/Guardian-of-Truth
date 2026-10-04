# Code review and verification boundaries

An independent subagent inspected the inherited source/graph/receipt/review
interfaces before implementation, authored the isolated transport with mocked
edge tests, and reviewed the new packet/interface/controller/consistency code.
The parent and a separate logic reviewer provide independent review of the
subagent-authored transport. Authorship is not an independent certification.
No live model requests or credentials were used by this reviewer.

The focused command executed in this worktree was:

```powershell
$env:PYTHONPATH="$PWD;$PWD\src"
python -m pytest tests/test_hybrid_transport.py -q
```

It passed **26 tests**. This number refers to the focused transport run, not an
unexecuted full-suite claim. The tests include interrupted reservations,
provider-shared limits, 402/429 breakers after restart, malformed usage, request
and raw mutation, exact serialization order, and zero-network offline behavior.
See [the tests](../../tests/test_hybrid_transport.py).

## Historical A/C: traced, not repaired

The reviewer independently read original provider JSON for A, B and C under
[the frozen Telecom artifacts](../../outputs/telecom_causal_recovery/v1/predictions.json),
checked each raw-file SHA256 against its ledger, and compared the decoded object
with the stored admitted reply. All three checks matched. Actual model IDs were
`ministral-14b-2512`.

| Transformation | A | B | C |
|---|---|---|---|
| Raw provider decision | NO_ERROR | ERROR | NO_ERROR |
| Admitted and saved decision | NO_ERROR | ERROR | NO_ERROR |
| Reason describes the current expired-contract prohibition | Yes | Yes | Yes |

The exact explanations accuse the current `resume_line` for L1002 under q7;
C says the action is not permitted. The original h10 observation contains
`contract_end_date=2025-01-31`; q7 supplies current time 2025-02-25. Payment does
not waive that prohibition. A/C therefore contradict their own explanatory
conclusion. No Python label inversion was found. Historical decisions remain
unchanged. Provenance/actor admission intentionally did not parse prose into a
normative theorem.

[Windows replay](../../outputs/telecom_causal_recovery/v1/offline_replay.json)
and [server replay](../../outputs/telecom_causal_recovery/v1/server_offline_replay.json)
record identical predictions and ledger bytes with zero new HTTP. These are
historical replay receipts, not evidence that a newly changed interface has
already been replayed. Property order, absent explicit label definitions,
structured decoding and model behavior remain competing causal explanations
until the new factorial observations are audited.

## Nine implementation boundaries reviewed

| Requirement | Evidence and limitation |
|---|---|
| Preserve production and historical research | `git diff 6035918cdcef6d5600aecfd91bc2f01a4d5cf73c --name-only -- src service experiments/research_v3 experiments/research_v5 experiments/telecom_causal_recovery outputs/telecom_causal_recovery outputs/research_v5` returned no paths during this review. New files live in separate research directories. |
| Preserve original source spans | [packets.py](../../experiments/hybrid_mechanisms/packets.py) validates every supplied original string against immutable prompt/response offsets. Oracle selections and omitted spans are explicit; selected packets are not full-input coverage. |
| Assess the whole current move | Current assistant source inventory includes prose and every assistant event, rather than requiring one native t0. Native calls remain attempts, not completed effects. The compact review exposes one primary regulated action; multi-action completeness must be assessed separately. |
| Check source roles and namespaces | [interfaces.py](../../experiments/hybrid_mechanisms/interfaces.py) checks current target, policy source, evidence source and evidence actor. Valid IDs certify provenance, not applicability, exception closure or entailment. |
| Keep factual and normative assurance distinct | K1 retains comparisons/receipts whose source evidence is present in K0. System-time references map to an actually supplied covering original policy span. K2 selects raw operand-overlap candidates generically; it does not certify semantic identity or business relevance. |
| Preserve factorial wire order | [transport.py](../../experiments/hybrid_mechanisms/transport.py) hashes exact serialized UTF8 request bytes. Sorted JSON digest or dictionary equality alone would erase the ordering intervention; regression tests cover both collisions and replay order mutation. Actual completion key order still needs measurement. |
| Keep consistency conditional | [consistency.py](../../experiments/hybrid_mechanisms/consistency.py) flags typed contradictions without rewriting the input decision. Hypothesis aggregation stays labeled as model-derived. The limited proof adapter requires a separately supplied source audit and cannot certify universal NO_ERROR. |
| Bound exploration without inventing evidence | [retrieval.py](../../experiments/hybrid_mechanisms/retrieval.py) enforces at most eight distinct full reads and four planning rounds; the protocol can use a lower cap. Read windows reconstruct exact originals. Search excerpts remain navigation; gap closure remains a semantic hypothesis. Repeated reads and explicit stop reasons are retained. |
| Keep one durable experiment budget | All providers share one ledger capped at 36 attempts/280,000 charged tokens. Reservation precedes HTTP. Unknown usage and interrupted calls retain conservative reservations; no retry or automatic provider fallback exists. Cache identity includes provider, endpoint, protocol and exact wire bytes. |

## Findings raised before freezing

The reviewer raised the following issues with the parent before inference:

- K1 initially computed facts over omitted evidence; it now restricts supporting
  sources to the paired original packet. K2 was made a genuine compact,
  source-constrained operand-overlap selection.
- Clock provenance originally referred to omitted h0 even when the supplied
  q7 contained the clock assertion. It now resolves a covering original span.
- Historical fixed h27/h30 conflict logic is unsuitable for C1. The new
  diagnostics derive cited IDs from retained direct predictions and describe
  metadata conflicts as potential scope/actor problems, not proven violations.
- Stage-A `condition` needs an explicit interpretation: forbidden-state truth
  for FORBID, requirement satisfaction for REQUIRE. Without that definition,
  downstream typed aggregation could invert a model's intended antecedent.
- Comparing an independently generated Stage-A assessment with an I4 decision
  creates a cross-call diagnostic; it must not be described as checking one
  answer's own typed reasoning.
- Historical prediction/plan inputs used by C and R0 need source hash seals;
  sealing only Python files is insufficient.
- Adaptive replay must reconstruct planner/controller/gap outputs as well as
  re-decode final semantic replies before claiming end-to-end replay.

The latter protocol/replay points were sent to the parent for final freeze
verification. This review does not turn pending work into a completed gate.
Model availability, actual returned IDs, provider decoding differences, causal
scoring and final phase replay are evidenced by the corresponding retained run
artifacts and reports, not by the focused transport tests alone.

No review establishes bug-free software or generalized Guardian reliability.

## Initial post-run audit: 32-request checkpoint

The code-control reviewer independently replayed a temporary copy of the final
retained artifacts with HTTP and credential-access tripwires. Replay passed for
**32 charged requests** and **31 semantic prediction rows**; the remaining
request is the failed R1 planning call. Actual usage is 197,252 tokens, including
147,947 Mistral tokens and 49,305 Ollama tokens. The original raw files, requests,
predictions, ledger and format diagnostic retained identical SHA256 hashes.
No inference or credential access occurred during this audit.

The reviewer ran all four focused new test files together:

```powershell
python -m pytest tests/test_hybrid_transport.py tests/test_hybrid_logic.py tests/test_hybrid_packets.py tests/test_hybrid_fenced.py -q
```

All **80 tests passed**. Frozen source-code hashes match the protocol.
The complete machine-readable receipt is
[final_code_review.json](../../outputs/hybrid_mechanisms_v1/final_code_review.json).

The retained failed R1 plan was additionally reconstructed directly from its
hashed raw provider response. The controller raises exactly
`ValueError:GAP_SOURCE_NAMESPACE_INVALID` before any source read or round trace,
matching both `R1_plan_failure.json` and the saved empty `R1.json` controller.
Its gap `policy_sources` includes declaration ID `d9`, which is outside the
read catalog; its `target_sources` contains historical IDs rather than current
`t0`. In isolated post-hoc diagnostic copies, removing the declaration reference
still exposes the historical-target namespace error, and clearing those invalid
target references exposes the separate `READ_ARGUMENT_INVALID` for the planned
`d9` read. The original plan and runtime were not repaired. The declaration was
already provided in the initial context but was not selectable through this
read catalog. This is a disclosed planning-interface failure, with zero reads;
it does not demonstrate exhausted retrieval or inability to interpret policy.

The separate full-string JSON-fence diagnostic's code hash, protocol hash and
all 16 factorial raw-file hashes also match. Its eight additional admitted Gemma
objects use the existing strict inner parser and source/actor admission. These
remain post-hoc results under an alternate format contract; the frozen strict
predictions remain unchanged. Neither this diagnostic nor a model-generated
norm or consistency flag becomes a code certificate of semantic truth.

## Final audit: 34 requests and separate orchestration guard

After the two additional pre-registered case requests were retained, the reviewer
independently repeated full offline replay on a temporary copy. The final ledger
contains **34 requests**, **33 semantic prediction rows**, and **217,722 actual
tokens**: 168,417 Mistral tokens and 49,305 Ollama tokens. Unknown usage is zero.
All raw/request/prediction/ledger/format-diagnostic hashes remained unchanged;
HTTP and credential tripwires recorded zero accesses. The failed R1 plan still
reproduces its original namespace error before any read, matching its retained
failure and empty controller state. Frozen runtime code hashes still match.

The reviewer separately inspected
[guarded_plan.py](../../experiments/hybrid_diagnostics/guarded_plan.py), which
lives outside the frozen runtime. The future adapter blocks semantic review
after a rejected plan or navigation-only exploration with no complete source.
These paths retain a null decision and technical status; they do not manufacture
semantic UNKNOWN or binary zero. A valid full source only permits review and
does not prove a verdict, applicability, exception closure or sufficient scope.
The guard has not been applied retrospectively to the retained experiment.

Its three regressions passed independently. All five focused test files then
passed together: **83 tests**, including the 80 tests at the earlier checkpoint.
The updated [review receipt](../../outputs/hybrid_mechanisms_v1/final_code_review.json)
preserves the earlier checkpoint and records the final replay, guard code hash,
null-decision behavior and unchanged frozen artifacts. This corrective diagnostic
uses zero new model calls and is not a new measurement of semantic accuracy.
