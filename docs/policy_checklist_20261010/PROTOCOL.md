# Policy checklist (step 3, PolicyGuard-style) — protocol

Committed BEFORE any GPU run of this arm.

## Idea
The B2 reviewer gets the policy (as retrieved spans) and must find the relevant rules itself. The arm adds
a short per-move checklist: conditions from the policy for the tools called in the current move, plus rules
for any move (refusal, escalation, claims). The checklist is a MODEL_HYPOTHESIS hint; the reviewer decides,
code never sets a label.

## Universality
- Built at runtime, once per unique (policy, catalog) pair of the input (sha256), through the same model
  client (`guardian_truth.checklist.build`). No domain knowledge, no hand-written rules, no valid46 tuning.
- Prompt is generic; tool names constrained by JSON schema to the row's own catalog (+ `ANY`).
- Validation in code: known tool, non-empty check, policy_quote ≥15 chars and verbatim in the policy
  (whitespace/case-normalised), de-duplicated. 3 samples (T=0.7, seeds 1–3); a rule is kept if ≥2 samples
  state it (same tool and overlapping quotes: containment or word-Jaccard ≥0.5); cap 60 rules/policy.
- Injection (`guardian_truth.checklist.hook`): only the first review request; only rules for tools in
  `current_targets` + `ANY`; only rules whose quote lies inside a normative source PRESENT in the packet
  (each item carries that `policy_source_id`, so it is citable); ≤30 items; if the request would exceed the
  60 000-byte cap the checklist is dropped and the unchanged B2 request is sent.
- Off by default: without `--checklist` the adapter call and the review request are byte-identical to B2
  (tested). Known limitation: rules absent from the retrieved spans are not shown (adding new sources would
  break admission, which validates against the original packet).

## Offline checks done before GPU
213+1 tests (new: 7 checklist, 1 adapter flag; all old submission/adapter tests unchanged and passing).
Dry run with a synthetic model over all 445 local rows (42 policies): every row processed, injection on 420,
6 budget drops, max request 43 KB, no crash; binary unchanged vs B2 under the same fake model.

## Stage 1 — short GPU test (this run): technical + early signal, NOT a decision
valid46, vLLM graph16 config (16 slots/workers), `--checklist`. Compared with the existing B2 graph16 run
(TP16 FP0 FN7, F1 .8205, same engine/config). valid46 is contaminated and small (run-to-run noise ≈ ±0.05 F1),
so this stage only decides whether a stage 2 run is worth it.
Gates: 0 technical failures; checklist built for every policy (≥2 valid samples); injected on ≥80% rows;
total wall (incl. startup and checklist build) ≤ 1800 s. Also reported: checklist sizes, unlocated rules,
manual inspection of the checklists for quality, per-row label changes vs B2 graph16.

## Stage 2 (only if stage 1 passes and is not clearly negative) — decision
Same-engine A/B on decision pools (B2 vs B2+checklist), protocol to be committed before that run.
