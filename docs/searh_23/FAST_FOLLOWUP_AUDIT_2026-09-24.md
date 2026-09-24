# Fast follow-up audit — 2026-09-24

Purpose: choose only short, falsifiable follow-ups from the existing Guardian
research. This is a review of saved runs, not a new quality result. `public46`
has been repeatedly inspected; hotel v2 was used to develop v4. Synthetic
contrasts establish a mechanism, not hidden-test performance. Mistral runs
through an API; availability in the final contest runtime is unverified.

## Controls before any new candidate

- Freeze and run the *same* new cases through: response-call bit, structural
  Guardian, Granite 3.3 groundedness, C1 OR, pgjudge, v3.1/v4, and TQ. Include
  Granite `function_call` as an isolated local diagnostic, not an automatic OR.
- Balance the new set by `(gold 0/1) × (target has assistant tool call yes/no)`.
  The call bit alone is TP21/FP2/FN2 on public46, so aggregate F1 without this
  stratification can reward response format instead of policy understanding.
- Keep policy and entities disjoint from public46 and hotel. For each proposed
  mechanism, include matched positive/negative cases that actually give it an
  opportunity to change a base alarm. Author the label rubric before inference.
  If cases are synthetic, report mechanism transfer only.
- Record paired per-case decisions, TP gained, FP removed/added, TP lost, valid
  inputs, execution time, model/API calls, and exactly which evidence changed
  the label. A missing opportunity is inconclusive; a lost TP blocks promotion.
- Verify the competition `scripts/predict.py` path separately: it currently
  invokes the structural detector, while C1/pgjudge/TQ are research runners.

## Fast candidates, in order

### 1. Freeze and test the existing FP-refutation stack on a third domain

What is already measured: fresh pgjudge public46 TP23/FP16/FN0; corrected v3.1
TP23/FP6/FN0; TQ TP23/FP4/FN0 after tuning on public46. On hotel, v3.1 changed
zero decisions; v4, designed after hotel FP inspection, gives TP14/FP3/FN0;
TQ changed zero decisions there. The hotel residuals did not exercise TQ's
future-offer or not-yet-due-obligation clearance paths. TQ's final FN score
is corrected in `codex/tq-audit`; the final zero-loss counts do not change.

Run the repaired v4/TQ implementation from `codex/tq-audit` without new rules.
Use matched examples for future offer versus executed action, obligation not yet
due versus already due, same versus different entity/amount, and satisfying
observation before versus after the target action. The target call, required
premise, entity, amount and time must be source-bound. This tests a real missing
boundary exposed by the old v4 wrong-reservation counterexample. Do not add a
large general-purpose graph; use typed event edges for these joins.

Stop if the frozen layer loses any new TP, or if it cannot remove FP despite
base-positive opportunities. A gain on authored scenarios remains a mechanism
result; require a separate untouched contest-like set for a quality claim.

### 2. Targeted action-feasibility witness for C1's semantic false negatives

C1's three public46 FN are two premature transfers (`banking_003`,
`banking_018`) and one wrong feasible exchange plan (`retail_29`). A tool's
existence or a policy quote alone cannot prove that an alternative is feasible.
The candidate should emit one exact response refusal/transfer or plan claim,
requested outcome, available action, applicable policy clause, entity match,
observed prerequisites, and an explicit unknown for each missing premise.
Require a source-backed *feasible alternative*, not a generic agent opinion.

Test on new matched justified/unjustified refusal and exchange cases. Compare
C1 alone, C1 plus this checker, response-call bit, and pgjudge/TQ. This is
worth implementing only if the first gold-free witness inspection finds
source-supported alternatives; otherwise stop before model calls. Its public46
FN recovery would add nothing to pgjudge, which already flags all 23 positives,
but it could matter for an offline/local C1 path with fewer FP.

### 3. Local `function_call` criterion and context-budget controls

Granite's official `function_call` criterion was tested on 23 call-containing
public rows, but never reliably joined as a third channel to the current C1.
The earlier slice had only two negative calls, so zero FP there is weak. Run it
on the new balanced call subset and measure *incremental* TP/FP over C1; do not
promote its standalone score. Run C1 with the frozen 12k/24k/60k context
settings in the same paired evaluation: public46 OR results are respectively
TP20/FP2/FN3, TP19/FP1/FN4, TP18/FP0/FN5. The choice may depend on unseen
error prevalence; one viewed set cannot settle it.

### 4. Atomic source-linked claim check, only if text errors remain

C2's deterministic response-span inventory with typed mapping was a real
component result (recall .8163, precision .9449 on its span task). Whole-context
DeBERTa NLI returned neutral on all 23 public text-only rows, including two
positives; LettuceDetect supplied zero operation-grade claim sentences. Those
results do not test a short `(atomic response claim, exact earlier observation)`
pair. A cheap local NLI/Granite probe could test contradictions and fabricated
result claims, with exact entity/time joins and an `UNKNOWN` state. First
measure whether C2 actually supplies the material claim on a new balanced text
subset; only then run a pair verifier. Saved C2 proposals did not change X5's
label on 44 valid public pairs, so span recall alone is not a promotion argument.

## Approaches to stop or keep as components

| Family | Evidence / next decision |
| --- | --- |
| Graph/fact digest as Granite's sole document | TP19/FP21; flat facts TP16/FP16. More suspicion text makes harmless gaps look like violations. Keep graph only for targeted source joins. |
| LangExtract/NuExtract/GLiNER | Extraction and spans improved; they do not decide applicability. Historical `+LangExtract` judge regression lacks surviving matched raw judgments. Use narrow extraction only after a specific missing fact is identified. |
| Investigator/agent tool choice | Original interface was broken, but repaired agent v3 executed 148 tools versus fixed 165, found the same 16 safe cards, changed zero labels, and averaged 9.07 s/case versus 0.0047 s. Do not retest routing without a new evidence target. |
| Broad Q interpretation blocks | The corrected 12-case run's apparent gain was mostly reproduced by irrelevant cross-case placebo text. TQ's narrow, code-checked operations are the viable question form. |
| Holistic Mistral | Matched head/tail context improved five of six changed labels, but still had 16 FP on 44 paired cases. Keep as candidate generator, not final verdict. |
| S7 claim-level Granite | The original groundedness risk-token polarity was reversed. Corrected/rerun variants still lacked selectivity. No reason for another generic suspicion verifier. |
| Clingo/RuleIR/P2/V9/full E2E | Engine mechanics work on typed facts; real policy meaning, entity binding and source authority fail first. Seven of ten claimed E2E TP depended on unsupported catalog/object closure; corrected TP3/FP0. No new solver or broad compiler until a narrow source-supported rule family shows marginal TP. |
| Goal/plan, T1/T2 effect models | Controlled typed binder succeeded 34/34, but natural-language Goal v3 failed its early gate; T2 candidate precision/recall were weak. Use the binder as a component only when explicit source events/contracts are available. |
| Broad decomposition, top-k, LettuceDetect | Material extractor missed anchors, top-k omitted needed policy evidence, LettuceDetect yielded no operation-grade fragments. No short promotion path from these exact implementations. |

## Decision after the short run

Promote no arm from public46 F1 alone. If v4/TQ shows new FP reduction with no
TP loss on cases where it could act, it earns one untouched contest-like
comparison against the simple response-call and C1 controls. If it does not,
freeze the simpler local path. If the new cases expose C1 semantic FN with a
source-supported feasible alternative, test candidate 2; otherwise do not
start a new broad policy/graph/agent architecture.
