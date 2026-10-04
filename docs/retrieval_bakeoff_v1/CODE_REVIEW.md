# Independent code review

Verdict: **no blocking code or saved-packet integrity issue found** in the frozen
offline phase. This review did not run inference, repeat retrieval selection,
tune against evaluation cases, or change frozen code. Its machine-readable
evidence and all 600 packet hashes are in
[independent_code_audit.json](../../outputs/retrieval_bakeoff_v1/independent_code_audit.json).

Base: `f89d271b21deeb5e2820a8c9111857223ca26015`. Freeze commit:
`968a49f1a29826208cdf1b6baf9594983c60eca4`. Protocol:
`4a4c4bb630aac8108afe93d91a73e5eec55af884f35ca9c421ed2bf39d1ea5d5`.
The reviewer inspected adapters, corpus, dataset, scorer, gap controller and
runner, plus their inherited source/actor/admission/transport dependencies.

## Findings fixed before freeze

| Finding | Correction reviewed |
|---|---|
| Manifest used `dev`, runner filtered `development` | Frozen development split used consistently |
| Removing one excess impact job did not reserve twelve S2G slots | Remove excess intermediate jobs until impact has at most six eligible jobs |
| Malformed provider choices/messages could crash decoding | Strict shape guards; technical null result and no semantic projection |
| A short seed allowed more than four new S2 reads | Four-new-read cap includes call/result dependency groups |
| Uncapped seed could be replaced by a smaller capped final context | Common capped seed and explicit S2 seed-retention guard |
| Budget-invalid/no-norm packets could still reach final review | Final review eligibility checks retain explicit technical nulls |
| Replay checked raw transport/final labels without reconstructing S2 controller | Rebuild gap status/plan, S0/S1/S2 packets and invalid-plan outcomes; ignore elapsed time only |
| Valid alternative evidence could be counted as unnecessary | Relevance union includes every annotated alternative source set |
| Group-wise JSON costs made S1 silently lose seed evidence | Exact whole-source-array charge and explicit `SEED_RETENTION_BUDGET_STOP` |
| Inherited A runtime/package drift escaped the seal | Inherited Telecom dependencies hashed; package versions checked in `verify()` |

The S1 defect was reproduced independently: a call/result pair fit when selected
together but the result disappeared when the same pair was reassembled under
the same bound. Both grouping-independent charging and explicit retention failure
were reviewed after correction. No frozen result was repaired retrospectively.

## Independent checks

- **49 focused tests passed**, with actual BM25S and no skips, in the isolated
  bakeoff environment (0.82 seconds). The parent's broader relevant suite was
  reported as **103 passed**; that receipt is distinguished from the reviewer's
  own execution.
- Temporary preparation/replay generated 15 catalogs and passed with **zero HTTP
  and zero ledger attempts**. An injected package-version drift was rejected as
  `FROZEN_PACKAGE_VERSION_CHANGED`.
- Every one of **245 annotated span memberships**, including alternatives,
  matched the SHA256 of its exact original document slice. Five manually read
  units covered Silver economy policy, a current airline call, retail tool
  declaration, a Telecom USER result, and a banking transfer exception. Their
  explanations corresponded to the source text; this does not certify exhaustive
  reference annotations.
- The diff against the base contains the current research files and scoped
  `.gitattributes` rules. Production, historical implementations and source
  dataset/gold were unchanged.

Queries and runtime packets use original prompt/response, declarations and
mechanical source links. Reference labels/explanations do not enter retrieval or
model prompts. Development-reference scores are used by the explicitly frozen
selection rule; the known evaluation split does not choose or tune the method.
USER actors remain USER; only uniquely qualified original receipts obtain
call/result dependency grouping. Model-produced sufficiency is never code proof.

## Read-only post-freeze offline audit

All **600 saved cells** were audited: 15 original cases, ten methods and four
read/token settings. The audit checked **6,254 source records**, including
**4,854 retrieved records**, and all **80 summary groups**. There were zero audit
errors. Saved technical failures were **52 `UNSUPPORTED_BASELINE_CASE` cells**;
the other 548 had no packet failure. These failures were preserved.

For every packet the reviewer independently checked original source slices,
bounds, source/input hashes, immutable catalog metadata, actor/receipt grouping,
selected-ID uniqueness, complete mandatory target/declaration inventories, read
caps and serialized UTF8 costs. Over-budget packets require explicit failure;
elapsed time is not a source-integrity assertion.
All 6,254 source roles also matched a containing original native event, including
the inherited A packets whose read units differ from the new catalog.

Scoring was independently recomputed from saved packets using interval merging,
without calling the author's `covered()`, `score_reference()` or `retrieve()`.
Category recall, missing units, valid alternative-set success, unnecessary-source
classification and aggregate counts/costs matched. Saved selection contained
development-only `k8` candidates and matched its recorded winner and frozen
priority ordering. No selection
was rerun or changed.

This is a code/integrity verdict. Reference recall is not semantic sufficiency,
successful identity binding, an authority certificate, or binary Guardian F1.
Raw observations and recorded graph adjacency retain those limits. A keeps its
original read units and unsupported-format behavior, so source/token costs must
remain visible in comparisons. `valid.parquet` is known diagnostic data, not an
independent hidden holdout. Official S2G was not executed; any API diagnostic
must retain the separate `S2G_INSPIRED_API_BASED` name.
