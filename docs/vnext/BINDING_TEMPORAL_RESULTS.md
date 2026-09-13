# Binding / temporal / causal stage

Current status: source-backed typed v2 stage COMPLETE; symbolic v1 NOT_RUN.
Native frontend integration, whole-Core resolution/certificates and end-to-end
gain remain NOT_ESTABLISHED. Original v1 inputs/annotations stay unchanged.

## Frozen v1 source-sufficiency audit

Source: `outputs/vnext/binding_temporal_v1_source_audit.json`.
The original 32 rows contain 16 distinct symbolic inputs; variant alone changes
no trace semantics. Every event is a short string rather than an adapter-owned
role/kind/source/pairing/time record. No input supplies version/schema-bound
trusted contracts or an explicit complete-history premise. Gold complete_search
flags cannot supply those missing premises.

The original tool reference only adjudicates archive status/version/prior-state
tuples. It does not execute unarchive/delete/restore/rename or these arbitrary
binding traces. The dataset's generic annotation-basis string must not be read
as an independent executable validation of every binding verdict.

Consequently source grounding is NOT_ESTABLISHED for all 32 rows. This audit
does not run the Binder, infer 32 Core verdicts or report a causal precision/F1.
Per-case missing-source components are EVIDENCE_COMPLETENESS, SOURCE_BINDING and
TOOL_EFFECT (overlapping). All original benchmark bytes and labels stay unchanged.

For example two symbolic `archive` entries do not distinguish two completed
mutations from a completion followed by a no-op/timeout. `GET exists=true` without
its source/result/version/entity/time data cannot establish restored state or
the causal identity of an earlier timed-out restore. A false causal-support flag
is not itself evidence that the action had no effect.

Next: freeze a separate executable source-backed fixture extension with actual
schemas/contracts, role-separated trace records, conditional/no-op/timeout effects,
identity declarations and explicit typed temporal query inputs. This isolates the
Binder/proof layer from separately measured NL frontend errors; it must not be
reported as native end-to-end understanding. Reference results must be independent
of the candidate prover. Missing new primitives get a new implementation version
only after these source inputs/reference rules are frozen. Run genuine native
regression/end-to-end comparisons separately, with sealed predictions before gold.

## Source-backed v2 extension

An independent executable fixture and 34 typed-query cases are frozen separately
in `binding_temporal_v2.spec.json`. Reference validation passes 34/34; this is not
a candidate result. Eight reference/projection checks pass. The protocol is
[BINDING_TEMPORAL_V2_PROTOCOL.md](BINDING_TEMPORAL_V2_PROTOCOL.md).
This preimplementation reference milestone is superseded by the completed
candidate experiment below. Native semantic integration remains NOT_RUN.

## Completed frozen typed v2 experiment

Implementation `09badb8`; `binding_temporal_v2_freeze.json` pins 130 executable
sources, byte-archived in `binding_temporal_v2_source_archive.json`. Full 34-case
predictions were persisted and sealed before the reference-scoring join.
Machine source of truth: `binding_temporal_v2_results.json`; complete per-case
audit: `binding_temporal_v2_failure_audit.json`.

- Typed truth correct: **34/34**; bindings and scoped completeness: **34/34** each.
- TRUE 14, FALSE 8, UNKNOWN 12. All twelve expected UNKNOWN remain explicit.
- Ambiguous identities retained: **2/2**; false forced binding: **0**.
- Five causal cases; one positive causal proof, no false/unsupported causal proof.
  Observed source-scoped precision 1/1 is NOT evidence of broad causal reliability.
- Independent typed receipts: **34/34** valid, including **22/22** definite
  primitive results. These are NOT whole-Core ERROR/NO_ERROR certificates.
- Runtime p50 **4.0983 ms**, p95 **471.35235 ms**. Two 2002-record sources each
  preserve 4004 observations across two snapshots; complete source/index/replay
  runtime **1336.2599 / 1378.1544 ms**, with **1 / 0** target bindings.
- API requests/tokens **0**; provider transport/schema/cost NOT_APPLICABLE.

Per-case semantic failure taxonomy is empty for this controlled stage. The audit
separately records expected uncertainty, remaining native/Core boundaries and
performance limits. ID/field and method queries use indexes, but name/alias-history
branches still scan cached alias observations. Any optimization gets a new version,
not an edit of these frozen sources/results. No real-provider guarantees, native
NL extraction improvement, production gain or blind accuracy is claimed.

The 26 primitive development checks use separate entity IDs. Three artifact tests
verify complete prediction sealing, all 130 archived source bytes and audit scope.

## Actual event-count scaling supplement

`binding_scaling_v1_results.json` freezes and scores nine runs: field-ID,
field-name and mutation-count at **100 / 1000 / 10000 actual ledger events**.
All nine truth/binding/candidate-count/receipt checks pass, with full per-case
audit before any optimization. This is different from the prior 2002-entity test.

At 10000 events, exact field-ID query time **0.1556 ms**, source/index build
**209.3268 ms**, independent receipt construction/recheck **504.4204 ms**,
total **713.9028 ms**. Mutation count keeps **4998** call occurrences and **9996**
call/result events: query **278.1902 ms**, build **524.6863 ms**, receipt replay
**9075.043 ms**, total **9877.9195 ms**. No top-k truncation was used.

These are single-run measured stage timings on explicit executable fixtures,
not population latency, native model throughput or a general complexity theorem.
The replay cost and linear name/alias scans remain documented optimization targets;
old candidate and result bytes are unchanged. Two artifact checks verify all nine
seals, source hashes and actual counts. No API/whole-Core certificate is involved.
