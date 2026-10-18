# V3 continuation, before new acquisition, simulation or training

2026-10-18. User explicitly requested full completion and delegated source and
implementation choices while retaining the plan. Existing A result is frozen:
R0 selected, no retuning. Existing B5000 draft and all earlier receipts retained.

CompliBench's published revision has no new-dialogue generator; its already used
eval policies/dialogues cannot become training seeds. Add Team-ACE/ToolACE as a
fourth independent acquisition source, subject to pin/license/schema/label and
contamination checks. This is a documented replacement for unavailable new
Compli generation, not a claim to have run that unpublished pipeline. Do not
count a second generator on tau2 as a different source to evade the40% cap.
Inspect native conversations for faithful current-turn adaptation. Empty/no-call
targets or syntactically corrupted representations must not encode class labels.
If source labels or format cannot be supported, exclude and report failure.

Provisional mixture before quality results:15000 TRAIN rows; tau2<=6000,
ToolACE<=4500,ToolRM<=3000,RAGTruth<=1500;30-40% violations. Preserve B hard-negative
and genuine-long-context requirements. No irrelevant padding, repeats presented
as independent scenarios, or semantic weakening just to meet counts. Final
selection may only satisfy these published constraints using validated rows;
if impossible, report a data-quality rejection rather than claim full compliance.
Native train splits only for supplementary datasets. Entire pair/scenario/user
components stay together. Re-run existing exact/near/entity contamination checks.

tau2: inspect pinned source; install a separate environment, no mutation of the
judge/training runtime. Start with finite technical pilots, preserve actual tool
execution, before attempting all source tasks across three agent configurations
and multiple seeds. Agent may see only policy/tools/user-visible history, never
hidden task criteria. User simulator may see task scenario, not future results.
No remote paid default models: explicitly bind every generation to local vLLM.
No automatic user-agent review provider or cache. Pin third agent weights/license
before loading; existing4B and35B pins stay unchanged. Completed task reward is
not a current-turn label: require source/policy/state evidence and stop after
first provable violation, dropping ambiguous attribution and subsequent turns.

Independent acceptance criteria are not waived. Human reviews unavailable:
freeze new holdout inputs/gold/scenario lineage before optimization, keep
HUMAN_UNVERIFIED until genuine human evidence exists. No model or source-code
audit is described as human review. After other machine data requirements are
met, C/D and machine E may be conducted as EXPLORATORY_ONLY to honor the renewed
full-work instruction; they do not establish a completed original B5 or E gate.
This separates executing the requested experiments from accepting a submission.
Original ZIP acceptance remains blocked by any unmet human/quality/runtime gate.
No production edits, ZIP assembly or platform submission based on exploratory
results. C/E protocols must still be committed before their respective results.

Record every deviation and failure. Stop scaling a defective source/labeler;
fix before optimization, with before/after source evidence and no eval tuning.
If the required data cannot be produced reliably, that is a terminal failed
experiment, not permission to substitute the short5000-row draft for v3.
