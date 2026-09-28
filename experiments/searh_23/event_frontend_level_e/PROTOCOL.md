# Level E prospective protocol (frozen before inference)

Branch `codex/relation-research-20260928`. The ten `e_*` policies are new
families relative to EVENT_CANON_v1 and are sealed as a single test suite.
`frozen/manifest.json` records byte hashes. Model runners must not import the
gold files. The older Level D dev/calib/val cases are available for algorithm
development, training and calibration; older Level D test is excluded. No
selection or threshold changes are allowed after opening Level E gold.

E1: 95 pre-anchored contextual spans, six gold classes (EVENT,
EVENT_REFERENCE, STATE, ENTITY_ARTIFACT, OTHER, AMBIGUOUS). A1=UD/POS generic
structural; A2=SRL if compatible implementation exists; A3=AMR-like event
graph; A4=narrow LLM with exact span and containing sentence; A5=structural
clear cases, LLM for ambiguous nominals. UNKNOWN is kept unresolved. Report
full six-class confusion, EVENT-like precision/recall, artifact rejection,
true-event loss, and UNKNOWN. Do not tune on E1 labels.

E2: 80 frozen identity pair inputs (60 source mentions and 20 matched clean /
boundary-expanded pairs). Baseline is EVENT_CANON_v1 F pair judge; core
representations B1 raw, B2 core, B3 raw+core, B4 core+local sentence, B5
raw+core+arguments. Evaluate exact SAME precision/recall, RELATED->SAME,
clean/noisy degradation, dangerous false merges. Few-shot 0/3/5/8 is selected
on old Level D dev; number fixed before Level E scoring. Core must preserve
the raw source span. UNKNOWN never merges.

E3: run unchanged structural frontend and evidence/DIR/CLS/GRP relation stack
on the ten policy cases. Compare raw, eventness only, canonicalization only,
eventness+canonicalization, frontend fixes only, combined, gold canonicalization,
and full gold nodes. Member-level CE and all original mention spans remain.
The relation prompt and CE band are fixed from prior work. Report edge
precision/recall/extra/missing/typed/direction/exact, as well as cost.

Only grouped train/dev/calibration data may set model thresholds. No tool-name,
case-id, domain or business-verb rules are permitted. Under rename, equivalent
description/schema inputs must produce identical frontend labels. Negative
results and unrun arms must be explicit in the final report.
