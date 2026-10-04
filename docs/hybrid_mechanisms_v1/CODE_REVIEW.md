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
