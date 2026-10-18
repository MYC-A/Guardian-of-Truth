# V3 B: source and data protocol, before download/normalization

Recorded2026-10-18. The user attachment is the authoritative specification.
Base7bc4a0b4; branch research/v3-threshold-data-lora-20261019, seed20261019.
New data must address target policy/tool adjudication; sample count is not proof
of quality. Do not train or fabricate compliance with unmet data requirements.

Pin source commit/HF revision, license file/card, upstream file digests, bytes,
download URLs and local SHA256 in sources_manifest.json. Prefer downloads on the
authorized SSH server. Bounded retries3, resume/preserve partial files, finite
supervisor jobs. Run downloaded external code only after inspecting it. No
driver, system service or production profile modifications.

Sources: tau2-bench (existing official96a3ef92329baf908ffe9dfe188cea34e8701d2a,
MIT, original archive digest recorded in v2); CompliBench (reuse pinned source
revision only after license inspection, generate new dialogues); ToolRM-train-data;
ParticleMedia/RAGTruth; PatronusAI/HaluBench; Salesforce/APIGen-MT-5k. Inspect
actual schema and provenance, not assumed chosen/rejected names. A preference
loser or merely different valid tool argument is not automatically a violation.
Keep only source-grounded, unambiguous binary labels and count all exclusions.
Noncommercial/other restricted sources cannot be admitted without affirmative
competition compatibility evidence; otherwise exclude and record the reason.
Data component licenses may be narrower than repository code licenses.

Implement the complete attachment B2 schema and literal governing-rule/evidence
references. Render into production prompt/response and call the exact production
Qwen judge renderer; a roundtrip equality test is mandatory. Annotation fields,
future turns, original answer labels and rationales never enter evaluation inputs.

tau2 simulations:3 agents of different quality, multiple seeds, tasks across all
available domains; retain raw tasks, tool calls/results, DB transitions and first
unambiguous erroneous target only. Wrong task-goal argument is not necessarily a
policy violation: evaluate actual policy, user intent and effects. Never turn
whole-trajectory failure into per-turn gold. Ambiguous labels are excluded/counts
retained. Successful prefixes may produce one-mutation paired twins from the
declared taxonomy; verify policy applicability and feasible consent/state.

Targets15-25k total,30-40% positive, no source>40%TRAIN; Compli<=6k,ToolRM<=3k,
RAG/Halu<=2k. Hard negatives>=30% of negatives. At least20%TRAIN>16k tokens,
measured with pinned Qwen4B tokenizer; no padding or irrelevant appended history
to satisfy length. Record full distributions/exclusions; initial cap32768, only
memory pilot may lower to24576 before final training data freeze.

Rename tools/parameters consistently in30%, preserving JSON schemas, references
and semantic values. Paraphrase policy in30% only with semantic review; machine
review and the requested100 human reviews must be distinguished. Protected data:
valid46,seen397,real191,dev520,eval1893 and all derivatives, including earlier
LoRA diagnostics; never use them as new training examples or mutation seeds.
Exclude exact and near-duplicates and matching source user/resource IDs.
Normalize across train/eval with fixed token5-shingles and MinHash128, Jaccard
threshold.80; exact hashes plus metadata group/scenario/pair connected components
are binding. Remove all conflicting-label identical inputs, log both sides.

Split whole group/scenario/pair components. Telecom isDEV except frozen holdout;
~300 whole-turn holdout examples across domains use new scenarios. Generate
human review cards and freeze inputs/gold plus lineage before training; do not
inspect holdout scores for checkpoint selection. Natural splits and nearby
variants are not independent if their source scenario is shared.

35B current-max audit gets input only, never labels. Every label disagreement
plus random5% must be adjudicated from full source/rule/history, not automatically
relabeled to agree with35B. Audit label error>10% means stop/repair generator.
All correction/exclusion records retained. L2 explanations may know TRAIN gold;
verify exact rule citation and matching verdict; explanation agreement alone
does not validate the label.

## Known human-review dependency

User answered2026-10-18: human review cannot currently be supplied. Therefore
mark holdout HUMAN_UNVERIFIED and paraphrase review HUMAN_UNVERIFIED until actual
human records arrive. Automated/second-model reviews may be prepared but cannot
be represented as human review. These requirements and E/F readiness cannot be
declared passed. Continue source acquisition, safe normalization, audit tooling
and review-card preparation independently; report remaining dependencies.

Every phase keeps START/DONE, finite jobs, logs, exact requests, SHA256, source
licenses, dropped and ambiguous counts. Failures are evidence, not silently
replaced by a more favorable run. No C optimization before its own committed
protocol and required data/holdout freeze. D/E/F each get their own pre-result
committed criteria before respective work; no retrospective acceptance changes.
