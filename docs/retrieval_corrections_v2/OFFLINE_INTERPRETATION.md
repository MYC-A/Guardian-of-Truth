# Offline interpretation and metadata probe

This note separates the frozen old/new source audit from a subsequent offline
research probe. The frozen code is `8dfb7a06`; its protocol still verified after
the probe, with hash
`53122156ca3c5697bcace1f1d5b9977619315b558be5c8c8cc0f333b8cb7fe5e`.
No frozen source, audit, request or model result was changed. The probe performed
zero API calls and has no LLM replay.

## What the frozen audit demonstrates

The source scores below use the same 15 previously used addressed reference
cases. A complete set means one scorer-defined alternative evidence set is
fully covered by original source spans. It does not certify semantic
applicability, journal completeness, an authorization or a final verdict.

| Source-record budget | OLD U2 complete | NEW U2 complete | OLD FC complete | NEW FC complete |
| --- | ---: | ---: | ---: | ---: |
| 20,000 | 8/15 | 9/15 | 3/15 | 3/15 |
| 40,000 | 11/15 | 12/15 | 8/15 | 6/15 |
| 48,000 | 13/15 | 13/15 | 10/15 | 9/15 |
| 80,000 | 14/15 | 14/15 | 12/15 | 12/15 |
| Unbounded U2 | 15/15 | 15/15 | Not run | Not run |

Both U2 gains are the same real row,
`telecom__mms_issueairplane_mode_on-bad_wifi_calling-break_app_both_permissions-data_mode_o::t15`,
at 20k and 40k. The required normative span `[23417,23849)` describes
app-specific permissions and user-side grant instructions. The old splitter
classified the heading and its immediately following body together as
`kind=heading`, excluding the body from the ranked pool. The corrected splitter
separates the heading `[23417,23463)` from its rankable body `[23463,23849)` and
keeps their dependency. This is an observed extraction improvement on that
input, not two independent successes or a measured reviewer improvement.
At 20k, total U2 required-history coverage decreases from 40/52 to 39/52 despite
the increase in complete alternatives; gains are not uniformly monotone.

## Why corrected verbose FC loses source coverage

The frozen FC correction adds three source-record fields:
`parent_source_length`, `explicit_window`, and `parent_coverage`. Their bytes are
included in the selector's source-record budget and cost-benefit denominators.
On these policy units they add 105 bytes per record. The reviewer adapter's
`slim()` does not transmit these three fields. Thus this pressure concerns the
rich serialized source-record cap, not additional policy text or additional
fields sent to the reviewer.

The 55% whole-policy threshold can switch discontinuously to ranked policy
selection after that overhead is added. The following are the exact real rows
that lose complete reference-set coverage, including the offset ranges of the
lost norms in the original prompt.

| Budget and row | Lost required normative spans | Observed cause |
| --- | --- | --- |
| 20k: `retail__106::t3` | `[817,1027)` valid lookup operands; `[1535,1687)` no invented ZIP | Both lie in unit `[553,1958)`, selected by OLD `FILL` at cost 1,727 but omitted by NEW at cost 1,832. The same five history spans are retained. Policy records fall from 14 to 12; NEW finishes with 492 bytes free, less than the required unit cost. There are no selected tool-result parents, so this loss is not caused by expanding a qualified receipt. |
| 40k: `airline__21::t7` | `[767,1018)` baggage detail list then YES; `[1179,1382)` one current tool call; `[3980,4413)` Silver baggage allowance | Whole policy costs 19,009 OLD versus 20,794 NEW, against allowance 20,093.15. OLD takes whole policy; NEW switches to ranked policy, retaining 4 of 17 policy units and losing all three required norms. Required history improves 3/4 to 4/4. Atomic grouping and changed history selection coexist here; the threshold change is directly established by accounting. |
| 40k: `banking_knowledge__task_068::t11` | `[759,2331)` no invented information/actions and actual account identity | Whole policy costs 18,399 OLD versus 20,289 NEW, against allowance 20,285.65. A 1,890-byte metadata increase puts NEW just 3.35 bytes above the whole-policy threshold. Required policy coverage falls 1/1 to 0/1, with history unchanged at 3/3. |
| 48k: `telecom__mms_issueairplane_mode_on-bad_network_preference-bad_wifi_calling-data_usage_exce::t7` | `[7385,7613)` user-executable actions and agent assistance scope | Both runs use ranked policy and retain exactly the same 16 history spans, including the same five result parents. The required unit was OLD `FILL` at cost 534; NEW cost is 639 and it is omitted with only 106 bytes free. Policy records fall 49 to 41; complete policy-bank cost increases 45,720 to 51,810. OLD selected receipts already have their qualified calls, so adding missing receipt dependencies does not explain this row's loss. |

The 20k aggregate 3-to-3 also conceals one gain:
`banking_knowledge__task_057::t2` changes from incomplete to complete. OLD selects
windows of result parent `h4` and no policy; NEW omits that result parent and
selects 15 policy units, covering the authentication norm `[5593,7142)`. The
retail loss cancels this gain in the aggregate.

A separate accounting projection preserves each OLD selected source span and
re-serializes it with the corrected record metadata, without reselection:

| OLD span inventory at its budget | Cost using corrected metadata | Amount over budget |
| --- | ---: | ---: |
| Retail at 20k | 21,867 | 1,867 |
| Airline at 40k | 43,404 | 3,404 |
| Banking task 068 at 40k | 43,881 | 3,881 |
| Telecom at 48k | 54,506 | 6,506 |

Those inventories cannot fit the same rich-record cap. This proves cost
pressure, but does not alone isolate every ordering, anchoring or atomic-pair
effect. The controlled probe below supplies additional evidence.

The structural correction also fixes an independent real defect:
`banking_knowledge__task_081::t35` at 20k previously reads a window of result `h28`
`[74809,74987)` without qualified call `h27`. Corrected FC omits both at this
budget. Missing those sources is an explicit retrieval omission; the old
unqualified assembly must not be promoted to a complete observation receipt.

## Research-only compact metadata probe

`scripts/coverage_metadata_probe.py` temporarily patches `selector.build_units`
with a wrapper around the original builder. It removes exactly the three fields
listed above from source records. It leaves source IDs, original offsets,
actors, kinds, tools, parent IDs, text and hashes intact. Packet-level
`parent_coverage` and `receipt_dependencies` remain present and truthful.
The context manager restores the original function. No selector implementation,
ranking weights, budgets, frozen requests or production configuration changes.

The probe artifact is
`outputs/retrieval_corrections_v2/metadata_probe.json`, explicitly marked
`RESEARCH_ONLY_OFFLINE_MONKEYPATCH_NOT_FROZEN_MODEL_ARM`.

| Budget | Corrected verbose complete | Research compact complete | Policy spans verbose → compact, /28 | History spans verbose → compact, /52 |
| --- | ---: | ---: | ---: | ---: |
| 20k | 3/15 | 4/15 | 7 → 8 | 40 → 42 |
| 40k | 6/15 | 8/15 | 15 → 20 | 43 → 43 |
| 48k | 9/15 | 10/15 | 23 → 25 | 43 → 43 |
| 80k | 12/15 | 12/15 | 27 → 27 | 43 → 46 |

Compact metadata restores all four row/budget completeness losses listed above
and loses no verbose-complete alternative. Airline and banking task 068 return
to whole-policy mode at 40k. Retail and telecom recover their missing units
while remaining in ranked-policy mode. Airline's required-history count drops
4/4 to 3/4 under compact selection, even though a valid alternative is complete;
the metadata probe is not a universal dominance result for every source span.
The task 081 result `h28` remains `NOT_READ` in both corrected representations
at 20k, with its missing result windows and call `h27` reported explicitly; the
compact probe does not reintroduce the historical unqualified receipt.

All 120 packets (15 repeated cases × four budgets × two representations) pass
independent checks for exact serialized source cost within budget, original
source text, full interval coverage of each selected qualified result and its
call parent, latest USER text fully read or explicitly failed, retained receipt
diagnostics, and parent statuses checked against original-event interval
coverage. There are zero packet failures. These repeated checks are not 120
independent evaluation cases.

This supports the narrower hypothesis that duplicated record metadata causes
avoidable source-budget pressure. Removing it recovers the observed
completeness losses while preserving the tested structural invariants. The
compact representation remains an offline prototype: it was not used in the
frozen old/new reviewer requests, has no new LLM outcomes, and is not a claim of
semantic correctness or generalization. Any production adoption needs its own
explicit representation contract and separately frozen evaluation.

## Remaining limits and interpretation of reviewer results

- FC remains a phased heuristic with stems, literal matching, recency and
  pseudo-relevance feedback. It has no implemented best-singleton comparison
  or approximation guarantee, and can omit governing norms under a budget.
- Atomic source groups establish the available original call/result context.
  The underlying qualification checks do not prove successful execution,
  identity binding, present-world truth, user consent or policy applicability.
  Unqualified results retain explicit diagnostics.
- Parent completeness concerns parsed original event spans. Parser transport
  delimiters and trimmed boundary whitespace are outside that claim; interior
  whitespace windows are retained. Full source coverage is not semantic proof.
- The references are previously used and can have alternative/partial
  requirements. A complete alternative need not cover every reference category
  span, as the airline example demonstrates. Non-reference rows have no
  equivalent addressed source-completeness score in this audit.
- The reviewer sample is conditional on known labels and source changes/gains,
  with up to three previously used rows per family. Its F1 is not valid46 F1,
  an independent holdout estimate, or an across-family independent sample.
  C1 P2 results concern the isolated second-stage comparison, not final C1 F1.
- UNKNOWN and technical null remain separately counted even when projected to
  binary zero. Reviewer decision changes require the separate original-source
  cause audit; historical SAME/PARTIAL explanation matches are insufficient.
- The frozen reviewer experiment evaluates corrected verbose FC. The compact
  probe is separate and must not be substituted into, or combined with, that
  experiment's model outcomes.

Reproduce the probe locally with `PYTHONPATH=.:src` and
`python scripts/coverage_metadata_probe.py`. It loads the frozen 15-row source
bank, passes references only to post-selection scoring, and never uses the
model transport or calls an API.
