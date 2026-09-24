# Cross-branch decision audit — before the demo

This corrects the scope of `FAST_FOLLOWUP_AUDIT_2026-09-24.md`. That audit
covered `big_researh` and `searh_23` in detail but omitted the later
`competition-real-valid-codex` branch. Consequently its list of remaining
candidate mechanisms was incomplete. All public46 numbers below are **viewed
development results**, not hidden-test estimates. The new service-desk suite
is authored and its Granite/Mistral run has not happened.

## Rechecked evidence

| Line | What is actually measured | What the result does **not** establish |
| --- | --- | --- |
| C1 structural OR Granite 3.3 | On public46, TP20/FP2/FN3, F1 .8889. Per-case replay confirms 46/46 input IDs. Structural alone is **TP12/FP0/FN11**, not TP6 as a row in `RESULTS.md` previously claimed. | Independence from the viewed public46; hotel semantic contrasts had many Granite FP. |
| Response-call bit | On public46, TP21/FP2/FN2, F1 .9130. | General policy understanding; this dataset strongly correlates response format with gold. All candidates need shape-stratified evaluation. |
| P + graph | Fresh pgjudge on public46 TP23/FP16/FN0; graph adds +3 TP and +2 FP to pjudge. Hotel recall held but FP remained high. | That graphs are useless: the digest adds recall. Nor that graph alone is a good verdict source: standalone graph-as-document was TP19/FP21. |
| Refutation v3.1 / v4 / TQ | public46: v3.1 TP23/FP6/FN0, TQ TP23/FP4/FN0. Hotel v4 TP14/FP3/FN0 after v4 was built using hotel FP; TQ changed zero hotel decisions. | Transfer of v4 or TQ to untouched domains. The hotel residuals gave TQ no eligible future-offer/not-yet-due FP. |
| Investigator | Repaired v2 agent/fixed-router arms found the same 16 safe cards and made zero label changes under the fixed evidence controller; longer budget caused one TP loss. | That every agent design fails. This tests routing over the **existing** tools and evidence target; discovering new proof obligations was outside that test. |
| E2E-agent-2, prompt-only competition adapter | Latest `competition-real-valid-codex` @ `300dc2e`: TP9/FP0/FN14/TN23, F1 .5625 on the same public46. Catalog axis, goal-format repair and completion-invariant witness have concrete paired improvements. | That its 144-case internal F1 .834 transfers to real prompt+response input. Those richer research cases had T1 contracts/metadata; the real adapter must abstain without them. |

### Marginal value of the latest E2E branch

Rejoin by exact ID:

- C1 record: `outputs/searh_23/baseline_frozen/control_repro_percase.csv`,
  decision `baseline OR granite_repro`.
- E2E record: `origin/competition-real-valid-codex` at
  `outputs/vnext/witness_masking_fix/fix_predictions.csv`.
- IDs match 46/46. E2E flags nine cases, eight already flagged by C1. The
  single E2E-only TP is `banking_knowledge__task_018::t6`. C1 OR E2E would
  be TP21/FP2/FN2, F1 .9130 **on the viewed public46**.
- Every one of E2E's nine flags is also in the 23 response-call cases. Thus
  this marginal F1 equals the trivial response-call control on this set.
  E2E's value is the *specific source-backed certificates*, not the aggregate
  public46 lift. No text-only violation was newly detected by it.

The old report saying “E2E only TP3” describes an earlier adapter state. It
must not be used as the final assessment of the branch. The E2E's latest
9/0 is real on public46, but does not justify replacing C1 by a system that
misses 14/23 positives on that same set.

## Genuinely open mechanisms, ranked by evidence and cost

1. **Typed argument provenance / repeated failed action.** The independent
   real-valid FN audit reproduced the canonical E2E TP8/FP0 result twice with
   zero cache misses, then traced all 15 FN. Six first losses involve argument
   provenance. The narrowest source-exact candidates are the unsupported
   account ID (`banking_068`), ZIP fabricated from email digits (`retail_106`),
   and an identical retry after a failed call (`retail_48`). The first two
   demand exact value *and field/entity* provenance, never substring search;
   the third demands `(tool, canonical arguments, observed failure)` identity.
   No final implementation/result for this candidate exists at the latest
   branch HEAD. Two of the six provenance cases also require policy
   rules, so “+6 TP” is not a valid expectation. Do the three narrow paired
   tests with negative transformations and renamed entities before promotion.
2. **Source-backed inability / absent-information / fabricated-action claims.**
   Three real-valid E2E FN first fail at claim typing: `airline__8` asks for a
   DOB already present, `retail__29` falsely says exchange is impossible,
   telecom `t27` claims diagnostics ran without matching calls. C1 also misses
   `retail__29` and two premature-transfer cases (`banking_003`, `018`). An
   action-feasibility witness needs the precise response claim, requested
   outcome, declared action, matching entity, observed prerequisites and
   explicit unknowns. A generic NLI or tool-existence check does not test this.
   It is a plausible **text-only** recovery path that the latest E2E branch
   lacks; no marginal result exists yet.
3. **Targeted policy sections / rule source authority.** Five E2E first losses
   are policy extraction or KB-as-policy source failures. H0 emits one flat
   structure for a long multi-section policy, so it can drop the decisive
   rule or invent a must-act rule. A small target-action clause extractor with
   exact quotes and condition/exception attachment is a different experiment
   from using LangExtract or a graph as the judge's whole document. Its
   risk is wrongful applicability; first check the specific FN clauses and
   matched compliant turns. Do not revive a general policy compiler yet.
4. **Granite `function_call`, context and FP refutation transfer.** These are
   now prepared in `fast_followup_run.py` on 32 balanced service-desk cases,
   but inference is pending. Its authored labels can establish mechanism
   behavior only. The suite lacks the three argument-provenance contrasts
   above; add a separate frozen v2 suite rather than edit the sealed v1.

## What was fairly rejected, and what was over-rejected

- More graph text as Granite's sole context and the old whole-context NLI
  settings genuinely failed on their measured inputs. The useful graph
  question is an exact, source-bound event join; a short atomic claim pair
  was not tested by the whole-context NLI negative.
- `+LangExtract`/NuExtract judge ablations do not refute extraction as a
  component. P extracted grounded requirement cards even in cases pjudge
  missed; the failure was often the applicability/verdict step. Some old raw
  matched judgments were lost in the server reset.
- The E2E solver/Clingo mechanics were not disproved. On real input the
  bottleneck was missing source/representation and unsupported T1-style
  premises. The latest 9 certificates show narrow mechanics can work; broad
  solver integration has not beaten the simpler C1 control.
- The original agent-v1 gain was against standalone Granite, not C1; the
  repaired investigator showed no gain against its proper control. Repeating
  the same tool router has low value. A new agent would require a **new
  evidence target**, such as argument provenance, plus an ablation against a
  fixed deterministic schedule of the same checks.

## Pre-demo decision gate

Do **not** claim that the solution family has been exhausted. Do **not** delay
an executable demo for another broad architecture. The smallest decisive
study is: (a) run the already frozen service-desk paired comparison; (b) test
source-exact provenance and a source-backed inability claim on separate
matched contrasts; (c) validate any gain on an untouched, contest-like set
with independent label adjudication and response-shape stratification. A
candidate earns integration only with a real incremental TP/FP change over C1
and the response-call control. A zero gain on cases where it had a base-positive
opportunity is a stop signal; no opportunity is inconclusive.

The current `scripts/predict.py` imports the structural CLI, while C1,
pgjudge, E2E and TQ run as research arms. The demo path therefore needs a
separate end-to-end packaging and input/output smoke test after candidate
selection. No result in this note is a live server run of the new suite.
