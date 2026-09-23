# Independent review of Guardian experiments (2026-09-23)

The later [re-audit of rejected approaches](REJECTION_REAUDIT_2026-09-23.md)
supersedes earlier negative interpretations of Investigator v2, Q, S7 and
holistic Mistral: those runs contain tool-contract, verifier, sampling or
context-selection confounds. Their observed scores remain as recorded, but
they do not establish an architectural ceiling.

## Update after `52de20c`

The new hotel v2 suite fixes the input transport: all 28 catalogs parse and
the local structural detector reproduces its saved decisions 28/28. Structural
checks detect all four deliberately mechanical/formal violations (P11-P14)
with no FP, while leaving all ten prose-policy violations unresolved. The
public46 structural trace records `rules:no_supported_system_policy` for
46/46 cases, so the old hotel 0/20 involved both broken v1 transport and a
real representational limit of the current policy engine. P1 versus P14 is a
useful controlled demonstration of the representable-rule mechanism.

On hotel v2, Granite is TP14/FP11/FN0/TN3; only 3 of 14 compliant controls
are accepted. OR is identical because the structural positives are already
Granite positives. This strengthens the earlier finding that Granite's
unconditional binary risk token poorly separates these authored contrasts.

The reported pgjudge FP-removal v3 result (TP23/FP4/FN0, F1 .9200) is
promising but currently cannot be independently reproduced from this commit:
`52de20c` includes the 16 original pgjudge FP reasons, not the v3 code,
per-case refutation certificates, or final run. The server SSH alias refuses
connections at this review time. The committed `fp_list.json` contains model
reasons and confidence, not the eight proposed counterevidence operations.
Treat v3 as a development-set claim pending its promised final run and a
fresh, versioned per-case artifact. Even if reproduced, .920 versus the
response-shape baseline .913 is a one-example-scale F1 distinction on the
same viewed 46, so independent, response-type-stratified validation remains
necessary.

Scope: fetched `origin` and reviewed the major experiment branches and their surviving
artifacts. `searh_23/investigator-v2` is current at `52de20c`. All public46
comparisons below use the same 46 **viewed development** examples (23 positive,
23 negative). The hotel suite is a single-author synthetic contrast probe, not
an independent competition sample. This review did not run new GPU inference.

## Verdict

Guardian OR Granite 3.3 groundedness at the 12k-character budget is the best
*observed F1 among the tested Guardian/Granite research arms*: TP20/FP2/FN3/TN21,
F1 .8889. A newly audited **one-bit response-shape baseline** (does the
target response contain an assistant tool call?) actually scores
TP21/FP2/FN2/TN21, F1 .9130 on the same 46 cases. This is not a useful
general solution by itself; it reveals severe response-type confounding in
this selected sample. It invalidates any unqualified claim that the OR is
the best observed classifier on public46. The four positives
added by Guardian to Granite are real paired gains in those records, with no
new FP. Reproduction agrees 46/46 with the prior frozen run. This is more than
an all-zero or all-one coincidence **on that sample**. It does not establish
that the configuration is the best general detector, or even the best choice at
a different error prevalence. The selected context size, OR rule, and many
follow-up ideas have all been examined on the same 46 labels.

The current competition `scripts/predict.py` invokes `guardian_truth.cli`,
whose default `--backend none` runs the structural detector. The researched
Granite OR is implemented as a separate demo/experiment, not that entrypoint.

## Paired evidence and sample composition

| Arm | TP | FP | FN | TN | F1 |
|---|---:|---:|---:|---:|---:|
| Structural Guardian | 12 | 0 | 11 | 23 | .6857 |
| Granite 3.3 groundedness, 12k | 16 | 2 | 7 | 21 | .7805 |
| OR of these two | 20 | 2 | 3 | 21 | .8889 |
| OR with Granite 3.3, 24k | 19 | 1 | 4 | 22 | .8837 |
| OR with Granite 3.3, 60k | 18 | 0 | 5 | 23 | .8780 |
| OR with Granite 4.1 | 20 | 2 | 3 | 21 | .8889 |
| Any target assistant tool call (no model) | 21 | 2 | 2 | 21 | .9130 |

The 60k aggregate comes from the historical flash report in
`docs/full21/CONTROL.md`; its row-level decisions were not included in this
paired recomputation.

Guardian and Granite have eight overlapping TP; Guardian contributes four
otherwise missed positives. Those four are `airline__9::t6`, `retail__27::t10`,
`telecom__mms_issuebreak_apn_mms_setting-user_abroad_roaming_enabled_offPERSONA_Hard::t27`,
and `telecom__service_issueairplane_mode_on-break_apn_settings-lock_sim_card_pin-overdue_bill_s::t15`.
Thus the OR gain over Granite is not explained by predicting zero in a lucky
case. The OR still has five errors: banking `task_003::t7` and `task_018::t6`,
retail `29::t13` are FN; banking `task_057::t2` and retail `87::t6` are FP.

The `12k` versus `24k` OR comparison changes only two rows: 24k correctly
rejects banking `task_057::t2` (one fewer FP) but misses banking
`task_068::t11` (one fewer TP). Calling 12k uniquely optimal overstates two
discordant examples. The 60k arm sacrifices two TP but has zero observed FP;
zero on only 23 negatives is weak evidence of zero population FP.

The development sample is perfectly balanced. Holding measured TPR/FPR fixed
as a sensitivity calculation, 12k has higher expected F1 than 24k/60k only
above approximately 43.9% positive prevalence. This is **not** a prediction
of hidden prevalence or stable rates. It shows why the preferred arm depends
on an unknown property of the hidden set and the relative cost of FP/FN.

Per-domain OR counts: airline 6TP/0FP/0FN/6TN; banking 4/1/2/4; retail
4/1/1/5; telecom 6/0/0/6. Two of three FN and one of two FP are banking.
The apparent perfection on airline and telecom is 12 and 12 examples,
respectively, and should not be extrapolated.

More decisively, target response type almost predicts the label. Exactly
23/46 responses have a parsed assistant tool call: 21 positive and 2
negative. The other 23 responses are 2 positive and 21 negative. There is
no hidden adapter selection in this count: the old function-call adapter
marks exactly those 23 call responses `ready`, and all other 23 as
`missing_target_assistant_tool_call`; direct `parse_events` gives the same
partition. The shape baseline's four errors are positive text answers
`airline__8::t7`, `retail__29::t13` and compliant calls banking
`task_063::t8`, `task_081::t35`. Relative to this naive baseline, OR fixes
three errors but introduces four others; both miss `retail__29::t13`.
This explains why high public46 scores can arise without understanding the
policy. A hidden set with a different mix of compliant calls and erroneous
text answers could reverse the ranking. The response type must be reported
as a stratification variable in every subsequent comparison.

The first table in `docs/searh_23/RESULTS.md` mistakenly prints structural
Guardian as TP6/FP0/FN17/F1 .4138. Its audited per-case records and
`docs/searh_23/BASELINE_AUDIT.md` give TP12/FP0/FN11/F1 .6857. The final
`RESULTS.md` table should be corrected before using it as a source of truth.

## What Granite is doing here

IBM's checkpoint configuration is `GraniteForCausalLM`, a 40-layer causal
language model with a 131,072-token position limit. Guardian is trained to
produce criterion-conditioned `<score> yes/no </score>` judgments; it is not a
symbolic policy interpreter. IBM defines `groundedness` as whether response
claims are supported by RAG documents, and `function_call` as whether a call
has syntax/semantic problems relative to the user request and available tools.
Neither criterion is equivalent to the competition's complete agent-step
error definition, especially premature escalation, wrong feasible plan, or
misread policy exceptions. The current control passes the assistant response
as a message and the *whole prompt blob* as one `prompt_context` document.
The document role tells the model to look for factual support, not to compile
obligations or counterfactual feasible actions.
IBM states that this checkpoint was trained and tested only on English data.
The hotel probe asks for Russian responses, so its failure mixes policy-domain
transfer, language transfer, and response-format effects; it cannot isolate
which caused the eight compliant false positives.

`max_context_chars=12000` does not give the prompt 12,000 characters:
`bound_pair` reserves 2/5 for prompt (4,800) and 3/5 for response. All 46
public prompts are truncated at 12k, retaining the beginning and end with the
middle omitted. A typical 46,646-character prompt is reduced to 4,800.
Thus the current result may exploit a favorable slice of a very long input;
the model cannot reason from omitted policy/history. 24k and 60k are different
information treatments, not simply more compute. The non-monotone result can
be caused by distraction, missing salient spans at 12k, or both; these data
do not identify which.

The saved 12k control has a risk token on all 46 examples but
`probabilistic_score=null` on all 46. In the alternate modes runner,
`probability_from_logprobs` reads candidate fields with `getattr`, while
`generate` supplies dictionaries; a synthetic yes/no pair returns `None`.
That is a verified score-extraction bug in that runner. The control runner
has a different scorer, but also saved zero usable margins. Consequently no
claim about score separation, calibrated thresholds, or uncertain-case routing
is supported by the current artifacts. Repairing margin extraction is a
diagnostic experiment, not a guaranteed F1 improvement.

## Why extra machinery did not win

### Investigator v2 mechanism audit

The zero-flip result is **not** a clean rejection of agentic investigation.
The code and saved traces identify several test-design bottlenecks:

- In arms A/B at four `max_steps`, the last orchestration call is treated as
  final even when it requests a tool. The agent received at most **three**
  actual tool calls per case, while fixed arm C used up to **four**. A/B made
  134/138 tool calls over 46 cases versus C's 172, so the claimed equal tool
  budget was not equal. In 45/46 A and 45/46 B traces, the last model response
  still requested `action=tool`; the requested action was discarded.
- `graph_query` checks whether the *whole* free-text query is a substring of
  an argument path/value. The agent passed arrow paths, filters, or prose.
  **82/82** graph queries in A and **77/77** in B returned `NOT_FOUND`.
  Fixed C supplied short entity/status strings and got 35 structured graph
  results in 88 calls. The agent/tool interface, not just route choice,
  prevented graph evidence from reaching the controller.
- `premise_check` expects a leading integer card index. Non-numeric text is
  silently converted to card **1**; an out-of-range index also falls back to
  the first card. The agent supplied non-numeric input on **14/14** A checks
  and **22/23** B checks. On at least 4 A and 11 B checks, the selected
  suspicion was a different numbered card. Fixed C supplied numeric indices
  on 47/47 checks. A `safe` result for card 1 was then attributed to P2/P3
  as if it refuted that hypothesis. This is an evidence-binding bug.
- The orchestrator saw only the first 4,000 characters of policy, the first
  2,000 of response, labels, a registry, and prior result summaries; it did
  not see the conversation/history it was supposed to investigate. Its
  registry description was serialized once before the loop and never updated
  with dispositions. The tools had history access, but the router could not
  inspect it to formulate precise calls.
- A/B at four steps never chose `langextract_targeted` or `nuextract_rules`.
  They mainly called the unusable graph query, `nl_question` (which can only
  yield a quote/status insufficient for a label flip), and `premise_check`.
  For B, the three OR false negatives remained at 0: policy questions yielded
  unverified/quote-only evidence, graph queries missed, and the formal check
  returned unknown or `safe`, not a supported violation.
- B adds a generic `G0` suspicion for **every one of 22 OR-positive cases**.
  None of those G0s was refuted in the four-step run. The fixed aggregator
  requires **all** violation suspicions refuted to clear a positive, so the
  generic unresolved G0 blocks every FP removal regardless of whether a
  particular pgjudge card is refuted. Four of A's 39 positives have no
  concrete violation suspicion at all, and cannot be cleared by that
  aggregator either.
- In A, three single-card suspicions were *marked* refuted: two are real
  FP (`airline__24::t14`, `airline__5::t1`) and one is a TP
  (`airline__8::t7`). None had the required counter-scan, so none flipped.
  The two FP marks came from P2 queries that silently checked card 1, so
  they are not valid P2 refutations. Simply deleting the counter-scan gate
  would appear to recover two FP **and lose one TP** on these labels, but it
  would rely on invalidly bound evidence. At six
  steps B did lose a TP after a `safe` card verdict refuted generic G0.
  Thus the refutation semantics need repair; loosening the threshold is not
  safe.
- The orchestrator's `final_label` is not used by the binary decision. That
  was a deliberate safety boundary, but it means this experiment measured a
  tool selector plus fixed controller, not an agent with authority to make
  the final judgment.

These points also explain why fixed routing was faster but did not improve
F1: it obtained more structured graph evidence, yet the evidence-to-label
contract did not use it to settle the relevant policy hypotheses. A fair
agent-versus-fixed comparison needs a typed graph API, the same number of
executed tool calls, current disposition state in the agent prompt, and the
same evidence validator for both arms. The new pgjudge FP operations are
more relevant candidate tools than free-form graph search for this test.

| Experiment family | Observed effect | Bottleneck exposed |
|---|---|---|
| Granite 4.1 | Standalone TP17/FP2 versus 3.3 TP16/FP2; OR unchanged | New 4.1 hits were already caught by structural Guardian. |
| P+Graph | Fresh pjudge TP20/FP14 to pgjudge TP23/FP16; recall 1.0 | Graph adds three real positives and two false alarms; coverage is not discrimination. |
| Graph as Granite document | TP19/FP21/F1 .6032; flat fact list also FP16 | Replacing source context with a suspicion/fact digest makes the RAG judge flag many harmless statements. Quotes reduce but do not solve it. |
| S7 per-suspicion Granite verification | On 23 covered cases, TP13/FP10; graph changed 1/103 suspicion calls, no final case | The verifier endorses nearly every suspicion; more graph text provides little counterevidence. |
| S8 Clingo | 88 cards, 44 bound, 0 violations, 60 unknown | Applying a sound solver needs observable premises, exact binding, and policy semantics; the solver is not the missing step. |
| Q v2 | 3,434 extractor divergences; 12 deep questions; 5 verified; 0 downstream flips | Span disagreement locates ambiguity but does not establish the final label. Earlier claimed one flip was an incorrect comparison. |
| Investigator v2 | A/B/C all unchanged at 2/4 steps; B at 6 steps loses a TP | Conservative evidence controller mostly returns unknown; more calls cannot create a missing premise and can wrongly clear an error. Fixed routing was about 10x faster than LLM routing at the same labels. |
| Mistral single judge | TP22/FP18/FN1, F1 .6984 | Broad semantic recall comes with many false alarms. |
| NuExtract/LangExtract cards | Extraction/span coverage improved; cards-as-judge context F1 .23-.38 | Extracting text is not deciding applicability, entity identity, or policy meaning. |
| Earlier formal E2E | Claimed TP10/FP0, but 7 TP required unstated catalog/object closure; corrected sound version TP3/FP0 | Proof validity depends on source-supported premises. A valid certificate can certify the wrong formalization. |

These are mechanism-specific negatives. They do not prove graph retrieval,
formal reasoning, or questioning inherently useless. They show that the
tested versions either did not alter the final decision, or altered it with
too many FP. In particular, P+Graph did improve recall by three TP, contrary
to a blanket claim that graph had no effect.
Some `big_researh` raw outputs were lost after the remote server reset; the
S9/card figures are retained historical summaries rather than a fresh
per-case reproduction. The principal 12k, 24k, 4.1, and response-shape
comparisons above are backed by surviving per-case artifacts.

An older branch already evaluated Granite's official `function_call` mode:
23/46 eligible public examples, standalone TP8/FP0/FN15/TN23; OR with the
old structural baseline gained one TP, no FP. The run used a last-user-turn
and explicit available-tools adapter, omitting broader policy/history. Its
eligible slice has 21 positives and only 2 negatives, so 0 FP is a weak
precision test. It was not evaluated as a third channel
on top of the current groundedness OR, and no surviving per-case raw record
was found for a reliable marginal join. This is a specific unfinished
comparison, not an untried criterion.

The `evasiveness` arm flagged 4/46, all positive, but all four were bare tool
calls; it found none of 12 refusal/handoff cases. Treating it as evidence of
false-refusal competence would be wrong. `think` mode produced missing scores
at one budget and lower F1 on rerun. A reason trace is not a correctness check.

## Independent checks and their limits

The hotel contrast suite has 10 positive/negative minimal pairs. Granite
predicts 18 of 20 rows positive: all ten constructed violations and eight of
ten compliant twins. Only two of ten pairs receive opposite labels. This is
strong evidence that its *binary discrimination on those authored contrasts*
is poor, despite 100% positive recall. It is not an unbiased estimate for
the competition or proof that it always predicts one.
All 20 hotel target responses are text rather than tool calls, so the naive
response-shape rule predicts zero throughout and misses all ten violations.
Its public46 win therefore demonstrates benchmark confounding, not transfer.

The structural channel outputs no positive on hotel, but the suite omitted
`[AVAILABLE TOOLS]` and encoded results as `⟦TOOL_RESULT lookup_reservation⟧`
without the `name="..."` field required by the parser. The transport audit
finds 0/20 complete catalogs and 0/22 named result events, versus 46/46
catalogs and 372/372 named results on public46. Therefore its zero is a
format failure/abstention, **not** measured structural domain transfer.
The claim in `docs/searh_23/RESULTS.md` that this proves domain fragility of
the structural half is unsupported as written.

The earlier independent AgentHallu DEV and ATFD/tau runs use different labels
or a trajectory-level success proxy. Their poor transfer is a warning about
open-world coverage, but their F1 cannot be compared directly to public46
turn-level competition F1. The competition hidden set remains unmeasured.

## Next experiment, in order

1. **Seal and replay the v3 result.** Commit the exact v3 code/config, all 46
   per-case labels, the 16 FP disposition traces, and a short source witness
   for every removed FP; rerun after the interrupted validation and compare
   with pgjudge and the response-shape baseline. Hotel input transport was
   fixed in v2 and should stay versioned beside immutable v1. Separately,
   correct the mode-runner dictionary score parser and inspect why the
   control scorer saved 46 null margins.
2. **Freeze a genuinely new test before looking at answers.** Use policy- and
   trajectory-disjoint examples, with justified/unjustified refusals, tool
   calls, future plans versus completed actions, and source-claim conflicts.
   Balance and report the four `gold × response-has-call` cells; compare
   every candidate against the response-shape baseline. Pre-register the
   primary metric, FP tolerance, paired flip rule, and domain slices. Do not
   select the window or threshold on public46 again.
3. **Run a compact, controlled architecture comparison.** A: current OR 12k;
   B: OR 24k or 60k as precision alternatives; C: A plus official
   `function_call` only where a call and catalog exist; D: an explicit
   policy/goal criterion or evidence-selected source snippets rather than a
   raw head-tail blob. Keep time and input budgets comparable. Report the
   marginal cases each new channel changes, not only aggregate F1.
4. **Test a false-refusal witness only if the data show headroom.** For each
   candidate, require exact policy clause, feasible alternative tool/action,
   entity binding, conditions, and observed history; abstain on unobserved
   premises. Compare deterministic retrieval with a local model proposer
   under the same validator. One public46 TP rescue is a mechanism check,
   never a hidden-test claim. Stop if new negative controls are flagged.

My architectural preference is a small proposal-and-verification pipeline:
parse the actual input; route by response/action type; use official function
call judgment for eligible calls, groundedness for sourced factual claims, and
a narrow explicit policy/goal witness for premature refusal or wrong plan;
let structural checks retain their own definite positives. Keep `UNKNOWN`
internally and make the binary threshold a frozen empirical choice. Avoid a
free-form multi-step agent until a held-out paired comparison shows that its
extra evidence changes labels correctly. No model training is needed for
this experiment.

## Audit anchors

- `outputs/searh_23/gate41_or/percase.csv`,
  `outputs/searh_23/baseline_frozen/s3s5_percase.csv`,
  `outputs/full21/control_repro_percase.csv`
- `outputs/searh_23/transport_coverage_audit.json`,
  `docs/searh_23/BASELINE_AUDIT.md`, `docs/searh_23/RESULTS.md`
- `docs/full21/CONTROL.md`, `docs/full21/S3_S5_MODES_CONTEXT_GRAPH.md`,
  `docs/big_researh/RESULTS.md`, `docs/research/EXPERIMENT_MATRIX.md`
- `docs/vnext/e2e/HIDDEN_ASSUMPTIONS_AUDIT.md`,
  `docs/cycle2/FINAL_DECISION.md`, `docs/next/FINAL_DECISION.md`
- `experiments/full21/run_granite_modes.py`,
  `experiments/full21/run_granite_guardian_flash.py`,
  `experiments/searh_23/contrast_hotel_gen.py`, `scripts/predict.py`
- IBM model card: https://huggingface.co/ibm-granite/granite-guardian-3.3-8b
  and config: https://huggingface.co/ibm-granite/granite-guardian-3.3-8b/raw/main/config.json
