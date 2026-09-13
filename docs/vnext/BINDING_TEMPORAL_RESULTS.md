# Binding / temporal / causal stage

Status: NOT_RUN. Binder/temporal stage metrics and whole-Core gain are
NOT_ESTABLISHED. Unit tests on existing source-owned indexes/primitives are not
a substitute for the frozen adversarial evaluation.

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
# Source-backed v2 extension

An independent executable fixture and 34 typed-query cases are prepared separately
in `binding_temporal_v2.spec.json`. Reference validation passes 34/34; this is not
a candidate result. Eight reference/projection checks pass. The protocol is
[BINDING_TEMPORAL_V2_PROTOCOL.md](BINDING_TEMPORAL_V2_PROTOCOL.md).
Candidate implementation/evaluation and native semantic integration remain NOT_RUN.
