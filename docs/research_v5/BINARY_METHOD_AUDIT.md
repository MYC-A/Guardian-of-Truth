# Binary-task audit, 2026-10-04

This is a post-hoc contract audit, not an architecture improvement. Original V4
gold, inputs, predictions and HTTP ledgers are preserved. The first V5 checkpoint
at `cef9d89` was partial, untested code; it made no model calls. The initial
protocol remains historical planning evidence. All checks below use zero HTTP.

## V4 labels

The six custody/reagent/calendar `identity` and `chronology` cases require a
successful check **before** the change, bound to the **same** object (and the
specified actor/parameters). The original UNKNOWN interpretation concerns an
unobserved world state or a possibly incomplete log. A complete recorded process
contract instead makes the missing mandatory prior check a procedural ERROR.
A check for R-20 does not satisfy the R-19 process; later approval does not satisfy
the earlier action. Neither interpretation proves false authorization in the world.
Exceptions do not rescue these six traces: no applicable supervisor exemption is
asserted; the reagent override only substitutes for certification.

The separate [label sidecar](../../outputs/research_v5/binary_audit/v4_label_sidecar.json)
gives each original policy, target, source hash, rationale and both log contracts.
Original UNKNOWN maps explicitly to binary 0. Rescoring the same full-context
Gemma A0 cache changes TP/FP/FN from **7/3/0** to **10/0/3**, and F1 from
**0.8235 to 0.8696**. This verifies the user's calculation. The former conclusion
that false accusations dominate is conditional on the original synthetic labels;
the alternative points to missed prior-process violations. Changing the evaluation
contract is not a model improvement. Other stored arms are rescored in the
[machine-readable table](../../outputs/research_v5/binary_audit/v4_rescore.json).

## Original 46 rows

`valid.parquet` contains 46 unique cases, 23 positive and 23 negative. The copy in
`three_architectures/data` has identical decoded contents. All cases are known
development data, not an independent hidden test. The [46-case audit](../../outputs/research_v5/binary_audit/valid46_case_audit.json)
records official gold, rationale, source hash, all current native targets, latest
user message, parser issues, diagnostic category and historical predictions.
This is a source diagnostic, not independent human relabeling or a claim that
all 46 gold rationales have been verified as correct.

Recomputed from `control_repro_percase.csv`, with exact case-ID/gold alignment:

| Archived arm | TP | FP | FN | TN | Binary F1 |
|---|---:|---:|---:|---:|---:|
| Guardian structural archive | 12 | 0 | 11 | 23 | 0.6857 |
| Granite 3.3 archive | 16 | 2 | 7 | 21 | 0.7805 |
| Guardian OR Granite | 20 | 2 | 3 | 21 | 0.8889 |

The historical one-shot report `docs/V6_RESEARCH_CYCLE.md` reports TP14/FP5/FN9/TN18,
F1=0.6667. Its `outputs/claim_gate_20b_full` per-case snapshot was not recovered
from the checked local worktrees/server repository search. Treat this as a
reported aggregate, not a freshly reproduced per-case baseline. Do not synthesize
the missing predictions from the aggregate.

R0 F1=0.9714 is confirmed in the sealed160 score archive (TP68/FP4/FN0/TN88),
which uses a different, constructed dataset. It cannot be compared directly with
valid46. The older `vnext/real_valid/R0_predictions*` files refer to a different
formal pipeline also called R0, not the Gemma→counterevidence reviewer.

## Actual R0 transfer/context preflight

The unchanged `r0-service-v1` was executed on all 46 rows with network and judge
tripwires. It returns **11 ERROR / 35 UNKNOWN**, zero calls/tokens. Structural
findings bypass the model context guard; every clean row exceeds its 12,000-char
guard. With UNKNOWN→0 its diagnostic binary F1 is **0.6471** (TP11/FP0/FN12).
This is a context-limited service result, not a test of full-context R0 quality.

The actual pure `build_judge_user` function was also executed offline. The sealed
R0 profile's larger outer context limit does not eliminate the inner J window:
J still uses explicit 12k head/tail trimming, with omission metadata. This is
disclosed truncation, but still unsuitable for the requested full-source transfer.
A valid transfer needs a new frozen full-context configuration and model capacity
preflight, or explicit abstention. No model window was silently enlarged and no
sealed160 replay was joined to valid46 by row ID. See the [runtime receipts](../../outputs/research_v5/binary_audit/r0_service_valid46_dryrun.json).

## Real residual FN and oracle limits

The OR residuals are banking task003, banking task018 and retail29. Task003 has
an available complementary lexical search with no recorded attempt; relevance
to the unsolved question is a semantic relation, not a universal business rule
requiring every search tool. This is the promising process-closure oracle probe.

Task018's gold proposes Latin `Fatima Al-Hassan`, absent from the actual input.
Only the Russian name is provided, and the system forbids transliteration.
The oracle must not invent the Latin argument. Retail29's latest user explicitly
rejects item 5206946487, whereas gold calls it desired; a pending-order item also
does not prove inventory availability. Four parallel same-tool order calls have
ambiguous receipts under the existing strict unique-call checker. These are
separate intent, evidence and pairing issues, not solved by giving a graph an
idealized matching product ID. Official binary labels remain unchanged; the
conflicts need adjudication before causal claims about recovering these FN.

Several positive valid moves contain an error in the **second or later call**.
First-target adapters from the synthetic pilot cannot be transferred unchanged:
the final binary decision must cover all current calls and material prose claims.
The new audit explicitly records this scope gap rather than reporting the first
call's status as the whole move's correctness.

Next: source-grounded oracle relationships with native receipt/identity checks,
an explicit complete-process absence contract, and separate incomplete-log
results. No large model run precedes that gate.
