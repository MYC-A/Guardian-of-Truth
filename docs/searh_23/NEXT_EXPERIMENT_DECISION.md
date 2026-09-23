# SEARCH_23: what the witness audit changes

Update after the independent cross-arm audit: the recommendation in section 3
is a **conditional follow-up**, not the immediate priority. A parsed
target-tool-call indicator alone reaches TP21/FP2/FN2/TN21 (F1 .9130) on the
viewed public46, versus OR's TP20/FP2/FN3/TN21 (F1 .8889). See
`INDEPENDENT_REVIEW_2026-09-23.md`. First build and freeze a new
format-faithful set balanced across gold label and target response type, then
measure whether any semantic arm beats this trivial control. Otherwise a
false-refusal checker can be tuned to the three known FN without evidence of
general value.

Update after `52de20c`: hotel v2 now passes the structural transport gate and
shows 4/4 mechanical/formal controls detected, 10/10 prose-policy violations
unresolved. The immediate unsealed result is pgjudge FP-removal v3: its
reported TP23/FP4/FN0 requires committed per-case predictions, source-backed
refutation traces, and one replay after the interrupted final run. Compare it
with the response-shape control on a new, response-type-stratified set before
promotion. See `INDEPENDENT_REVIEW_2026-09-23.md` update.

Date: 2026-09-23. This is a diagnostic decision note, not a new quality result.
The input inspection uses only `id`, `prompt`, and `response`; labels and
explanations are consulted below solely to audit the five already known errors
of the frozen Guardian OR Granite 3.3 control.

## 1. Transport gate before transfer claims

`python experiments/searh_23/transport_coverage_audit.py` writes
`outputs/searh_23/transport_coverage_audit.json`. It reuses the production
parser and detector; it does not infer natural-language policy meaning.

| Input | Cases | Complete parsed catalogs | Named / all history results | Candidate tool calls | Cases with mechanical findings |
|---|---:|---:|---:|---:|---:|
| public `valid.parquet` | 46 | 46 | 372 / 372 | 37 | 12 |
| hotel contrast suite | 20 | 0 | 0 / 22 | 0 | 0 |

Hotel prompts omit `[AVAILABLE TOOLS]`, and `⟦TOOL_RESULT lookup_reservation⟧`
does not supply the `name="..."` attribute that `parse_events` reads for this
marker form. All 20 structural reviews are `unknown`. Consequently the hotel
suite is useful for probing Granite's decision behavior (2/10 contrast pairs
separated), but its structural `0/20` cannot isolate domain transfer from
transport/representation mismatch. Re-run the structural arm only after a
format-faithful hotel suite with a source-declared catalog and named results.
Do not add a catalog retroactively to the frozen original suite and call it
the same experiment; version the new suite separately.

## 2. The five errors of the frozen OR on public46

| ID | Error | Source-side deciding material | Current gap | Next witness to seek |
|---|---|---|---|---|
| `banking_knowledge__task_003::t7` | FN | `KB_search_bm25` is declared but unused; the previous `grep` pattern cannot find a fee split across lines; the transfer summary contradicts the agent's earlier Gold Rewards table. | Applicability of the transfer precondition and contradictory summary are not checked together. | A named available search path or a direct contradiction between the summary and an earlier observed statement, with source spans. |
| `banking_knowledge__task_018::t6` | FN | Case-sensitive name lookup used Cyrillic, while the original Latin name remains in the dialogue; the user asked for a human once. | Identity-form and request-count conditions are not joined to the transfer rule. | Exact original-name span, attempted lookup argument, policy transfer condition, and request count. |
| `retail__29::t13` | FN | The received and desired hose items share a `product_id`; the policy and catalog contain the delivered-order exchange path. | Entity/product join and feasibility of exchange are missed. | Two exact item records joined by `product_id`, order status, exchange rule, and tool declaration. |
| `banking_knowledge__task_057::t2` | FP | The answer asks for information needed before verification; it does not claim that verification or account opening happened. | Granite flags the response, but its risk token does not disclose a deciding claim. | Identify a concrete false assertion or action before retaining a positive; otherwise this is a negative control for a refusal/identity checker. |
| `retail__87::t6` | FP | The answer proposes future address changes and distinguishes pending orders from processed/delivered orders. | Granite flags the response; the precise model mistake is unobservable from the saved yes/no output. | Separate proposed action from completed action and check entity/status binding; keep as a negative control. |

The first three rows come from gold explanations and are **development
diagnostics**, not production rules. A named tool's existence alone does not
prove that its use is feasible. A source quote's existence alone does not
prove the model's interpretation. The two FP rows describe distinguishing
facts, not a verified explanation of Granite's internal decision.

## 3. One next experiment and its stop rule

**Experiment:** source-backed false-refusal / premature-escalation checker.
Restrict the trigger to a transfer tool call or an explicit inability claim.
It must emit a candidate alternative action plus the exact policy clause,
required conditions, matching entity, observed facts, and an unresolved field
for every condition it cannot establish. The model or retrieval component may
propose this tuple; source offsets, event order, and structured joins are
checked independently. `tool_exists` and `quote_exists` alone must never flip
the label. Compare a fixed deterministic candidate generator against any local
model proposal under the same validator; do not add an agent loop by default.

Measure on all 46 public cases: which of the three known FN receive a valid
witness, how many of the 23 gold-negative cases are newly flagged, and which
stage loses each candidate (trigger, retrieval, entity join, policy condition,
or aggregation). This is a *mechanism test on viewed data*, not evidence of
hidden-test gain. Before promotion, freeze the implementation and run on a new
format-faithful, policy-disjoint contrast set containing both justified and
unjustified refusals. Report paired decisions and FP, not only F1.

**Stop:** if the validator cannot substantiate a feasible alternative action
without interpreting an unstated tool effect or assuming a closed tool universe,
do not force a positive. If new negatives are flagged at a rate that erases the
FN gain, abandon this checker as a binary decision component. Retain its
trace only for diagnosis.

The existing `docs/vnext/e2e/REAL_COMPETITION_VALID_CODEX.md` and
`HIDDEN_ASSUMPTIONS_AUDIT.md` already document broader policy/closure failure
classes. This cycle narrows the question to one actionable contest mechanism.
