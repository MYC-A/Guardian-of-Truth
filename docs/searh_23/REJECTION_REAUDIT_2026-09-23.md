# Re-audit of rejected and deferred approaches (2026-09-23)

This review uses tracked code and surviving per-case artifacts after fetching
`origin` through `52de20c`. A negative result is assigned to the **exact
tested pipeline**, not automatically to its underlying architecture. No new
GPU/API inference was run. Historical summaries without raw records are
identified separately.

## 1. Earlier rejection is not supported by the test

### Investigator v2 / autonomous tool choice

The measured A/B runs had zero useful flips, but the agent/tool contract was
broken. `graph_query` requires the entire query to occur literally in a graph
argument path/value; A/B returned `NOT_FOUND` on 82/82 and 77/77 graph calls.
`premise_check` silently uses card 1 for non-numeric input; A/B sent such
input on 14/14 and 22/23 calls, and at least 4/11 checks targeted a different
numbered suspicion. The harmful B@6 flip used a `safe` verdict for card 1 to
refute generic G0. Four configured steps allowed A/B at most three executed
tools but fixed C up to four. The last agent response still requested a tool
in 45/46 cases in each arm. The agent did not see history when choosing, and
its final label was ignored. B's generic G0 was never refuted at four steps
and blocked clearing every OR positive. The result rejects the **implemented
Investigator v2**, not agentic routing with a valid typed tool interface.

### Q / discriminating questions

All 12 deep questions came from divergences of the first sorted case,
`airline__10::t19`. The five `verified` questions all rejudged this same
gold-negative case to 0; all five rejudge outputs explicitly said
`used_repaired_element=false`. The purported formal component
`clingo_minimal_check(rule)` ignores its `rule` parameter and runs a fixed
program that has `violated` in its only model. Thus `formal_conclusive` is
true for essentially every candidate with a rule; it does not verify the
candidate policy interpretation. Finally, Q compares the new Mistral direct
rejudge label with an old **pgjudge** label (`q_v2_baseline_pgjudge.csv`),
despite saying they are the same configuration. There is no unmodified
Mistral rejudge on the same input for a causal Q ablation. The correct
result is: **this Q implementation measured no benefit; the Q architecture
was not tested validly**. Earlier v1's one flip was also unverified after
the raw-output loss.

### S7 Granite as claim verifier

`s7_claim_verifier.py` submits each proposed-violation sentence as the
assistant response under IBM's [`groundedness` criterion](https://huggingface.co/ibm-granite/granite-guardian-3.3-8b). Under that
criterion, `risk=yes` means the submitted sentence is **unsupported** by
the documents. The code records `yes` as `CONFIRMED` violation, reversing
the evidence meaning. In the saved 103 plain judgments, 96 are `yes` and 7
are `no`; the published TP13/FP10 case score is just all 23 covered cases
flagged. Reinterpreting `no` as the supported suspicion gives only
TP2/FP3/FN11/TN7 (F1 .222) with an `any no` aggregation, so a simple sign
flip does not rescue performance. The published test cannot establish that
Granite is a useful or useless *properly prompted* hypothesis verifier.

### Mistral single holistic judge

Arm M was given `case["prompt"][:10000]` and response[:3000]. All 46 public
prompts exceed 10,000 characters (min 13,634; median 30,498.5; max 233,104).
The comparison against Granite's head-and-tail input therefore confounds
model choice and context selection. TP22/FP18/FN1/F1 .6984 rejects this
first-10k prompt, not holistic Mistral with the relevant recent history.

### Hotel v1 structural transfer

The v1 suite omitted the declared tool catalog and named result markers.
Hotel v2 at `52de20c` repaired the transport and locally reproduced 28/28
saved structural decisions: all 4 mechanical/formal positives detected,
no FP; all 10 prose-policy violations unresolved. The old blanket claim
that structural mechanics do not transfer was wrong. The narrower finding
is that its current policy-rule engine requires explicitly representable
`[GUARDIAN_RULES]`; public46 lacks that section in all 46 cases.

## 2. Valid negative for the exact configuration, not the broader idea

| Approach | What the records actually establish | What remains open |
|---|---|---|
| Granite 4.1 | Standalone +1 TP versus 3.3, OR identical on all 46. | Different input/criterion or new data; no current marginal OR gain. |
| Granite `think` | With 1200 output tokens, 46/46 scored but F1 fell to .634 standalone / .783 OR. | Other prompting; not a reason to use think in frozen control. |
| Graph/fact digest as Granite's RAG document | Graph digest TP19/FP21; flat facts TP16/FP16. | Graph as targeted structured evidence, already useful for pgjudge recall. |
| NuExtract cards as sole Granite document | Historical F1 .23-.38 for that compressed RAG context. | NuExtract as source locator or candidate generator, which did produce cards; no full-cycle gain shown. |
| Whole-context DeBERTa NLI | 23 text-only cases all neutral, including two positives. | NLI on atomic, source-backed claim pairs; short synthetic pairs were 16/16 correct, not a realistic transfer test. |
| P+Graph as final binary judge | Fresh TP23/FP16/FN0, F1 .742; +3 TP/+2 FP versus P. | Candidate generator plus sound FP review, including pending v3. |
| Clingo S8 | 88 grounded cards, 44 bound, 0 violated; 60 unknown. | Source-supported policy extraction and premise observability; hotel P14 shows representable rules can fire. |
| Typed policy P2 in cycle2 | On 90 jointly valid cases, lower accuracy than P1 (.656 vs .778). | Other policy representation/producer; this is an exact-implementation negative. |
| Runtime top-k L1 | Missed required evidence in controlled long-policy assembly. | Targeted retrieval with coverage checks; top-k alone is unsafe. |
| Cycle 2 X5_CORE / X5_PROTECTED | The isolated internal CORE found TP7/FP0 versus incumbent TP12/FP0; PROTECTED changed zero incumbent labels. On the 100 external proxy steps, both had TP0/FN85. | This rejects the current end-to-end compiler, claim and effect coverage, not the four-valued solver. The external proxy tests goal/plan drift, a scope different from the competition labels. |
| Cycle 2 exact G1 = X0 OR (X4 AND X1) | X4 gated off all 100 external cases, so G1 exactly equaled X0 and added zero TP/FP. | The frozen formula failed validly; it says little about other routers because X1 transport succeeded in only 2/100 calls. |
| Cycle 2 A0 and T1 | A0 had TP22/FP16/FN1, lower F1 than direct Mistral on viewed public46; seven trusted T1 contracts added five internal effect records but no X5 label gain. | A0's noisy candidate set and this small T1 registry should not be promoted. A sufficient T1 ceiling is unmeasured; T2/T3 were not evaluated. |

The 24k/60k Granite OR variants are also near ties with 12k on viewed public46
(F1 .884/.878 versus .889) and each reduces observed FP (1/0 versus 2).
The data do not justify eliminating them as precision-oriented controls.

## 3. Not established, or valid rejection of an unsafe premise

- **A1 source-grounded suspicions:** 120 model proposals, zero admitted;
  114 quote/offset mismatches and six out-of-range source offsets. This
  rejects the model-to-offset contract, not exact source grounding or an
  extractor that lets code find offsets from exact quotes.
- **Agent v1:** historical F1 .80 removed one FP from Granite standalone
  .7805; its raw records were lost and it was not tested on top of OR .8889.
  It neither validates nor invalidates the later agent architecture.
- **Router v1:** reported routing recall 1.0 but did not execute tools and
  changed no labels. It is a trigger-coverage audit only.
- **External holistic X1:** only 2/100 external calls validated; 98 failed
  transport or output. Its quality cannot be inferred from that score.
- **P3 and X6:** P3 passed transport on 1/16 earlier attempts and produced
  zero schema-valid outputs; fast/slow X6 had no measured routing rule. Neither
  has a valid negative quality result.
- **C2 claim extraction:** this is a real positive component result, not a
  failed architecture: recall .8163, precision .9449 on the frozen claim-span
  task, versus C0 recall .1020 and C1 .0068. No X5 end-to-end ablation with
  C2 establishes a final-label gain.
- **Formal closure and neural binding:** rejecting unsupported closed-world
  tool/schema assumptions and cross-encoder similarity as *proof premises*
  was correct. The repaired formal pipeline loses recall because the needed
  semantic facts are absent, not because Clingo cannot solve valid facts.
- **External ATFD/tau:** trajectory success proxies are not the competition's
  turn-local error labels. Their zero recall diagnoses scope mismatch only.
- **Pending pgjudge FP-removal v3:** TP23/FP4/FN0/F1 .920 was reported by
  the collaborator but its code, per-case decisions and final replay are not
  in `52de20c`; do not promote it as independently reproduced yet.

## Practical order

1. Reproduce the pgjudge v3 FP-removal claim with versioned per-case
   certificates, then freeze it before a new policy- and response-type-
   stratified evaluation. Viewed public46 is a mechanism-development set.
2. Repair Investigator's typed tool interfaces and equalize actual executed
   tool calls. Compare agent tool selection against a fixed router on the same
   eight FP-diagnostic operations and budget.
3. Evaluate the already-positive C2 span inventory as a replacement for X5's
   weak claim input. First measure claim coverage and local runtime, then the
   exact end-to-end label delta; its current remote provider is not an offline
   competition entrypoint.
4. For holistic models, compare matched input assembly (policy, relevant
   history, target response) before comparing checkpoints or routing.
5. Keep Q and S7 as lower-priority targeted probes. Q needs stratified sampling,
   a real source-to-rule check and a same-judge ablation. S7 needs an explicit
   `supported/refuted/unknown` hypothesis verdict; merely flipping its saved
   risk tokens performs poorly.

Code/artifact anchors: `experiments/searh_23/investigator_v2.py`,
`experiments/searh_23/investigator_tools.py`,
`outputs/searh_23/inv2_{A,B,C,B_s6}/traces.jsonl`,
`experiments/searh_23/q_discriminator_v2.py`,
`outputs/searh_23/q_v2/divergences.jsonl`,
`experiments/full21/s7_claim_verifier.py`,
`outputs/research_granite_guardian/full21_s7_plain/records.jsonl`,
`docs/research/DECISIONS.md`, `docs/cycle2/FINAL_DECISION.md`,
`docs/cycle2/X5_EXECUTION_AUDIT.md`, `docs/cycle2/CLAIM_BENCHMARK.md`.
