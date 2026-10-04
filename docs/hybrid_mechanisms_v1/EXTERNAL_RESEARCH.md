# External mechanism research: primary-source audit

Checked on 2026-10-04. This is literature evidence, not an inference experiment on
Guardian. No foreign benchmark was reproduced, no model weights downloaded, and
no external work's QA or agent-success score is counted as Guardian binary F1.
Paper sections/tables and implementation paths below were inspected, rather than
relying only on repository descriptions. Numeric results are the authors' reported
measurements, with their task and metric retained.

## Requested works

### S2G-RAG

The [ACL paper](https://aclanthology.org/2026.acl-long.1185.pdf) exists; its
Sections 3–4 describe a trained sufficiency/gap judge, gap-to-query mapping,
sentence-index extraction and a separate answer generator. Evidence sentences
are selected by indices and recovered verbatim. The judge is LoRA-trained from
teacher-labelled execution snapshots, not merely an off-the-shelf prompt.
On HotpotQA, Table 1 reports BM25/Llama-3-8B F1 56.5 versus IR-CoT 41.5;
dense E5 S2G F1 is 53.5 versus standard RAG 35.3. These are answer-token F1,
not policy violation detection. Defaults permit four rounds and six documents
per round. Limitations include coarse gap representation and imperfect multi-entity
joins. Guardian can borrow explicit gap state and exact source-index recovery;
it cannot assume an untrained judge inherits those numbers or that sufficiency
means all applicable obligations were searched.
The [actual loop](https://github.com/nianaaa/S2G-RAG/blob/5d842a67a0a99a7b545bbad0dc402ceaae0e5eff/inference/inference_bm25.py)
lines 595–670 maintains past IDs, appends extracted evidence and answers at either
sufficiency or max turns. Budget exhaustion must remain UNKNOWN in Guardian.

### Recursive Language Models

The [v3 paper](https://arxiv.org/html/2512.24601v3) evaluates long-context tasks
including S-NIAH, BrowseComp+, OOLONG and OOLONG-Pairs. A persistent REPL stores
the input and intermediate values externally; the model inspects portions and
programmatically invokes recursive subcalls. The abstract reports up to two
orders of magnitude beyond native windows and median GPT-5 gains over compaction
26%, CodeAct with subcalls 130%, and Claude Code 13%. Those relative gains depend
on benchmark and scaffold, not Guardian's labels. Appendix D's additional
20-query BrowseComp+ experiment reaches perfect accuracy at 1,000 documents;
it is a small subset, not universal reliability. Section 7 warns of exploding
subcall costs and insufficient guardrail evaluation.
The [implementation repository](https://github.com/alexzhang13/rlm/tree/d04208afbad29ca675ab13478c40ee8bebc84bfe)
confirms external-environment APIs. Guardian should borrow bounded source handles
and persistent evidence references, without deploying unrestricted generated Python,
arbitrary recursion or uncapped subcalls. Local indexed source inspection is a
smaller hypothesis than reproducing the full RLM paradigm.

### Microsoft AgentRx

The [paper](https://arxiv.org/html/2602.02475v1), Sections 3–4, investigates
critical failure step/category attribution on 29 Tau-bench, 42 Flash and 44
Magentic-One failed trajectories. Generated global/dynamic invariants yield
programmatic and semantic validation logs; a judge uses them for attribution.
Table 4 reports Tau step accuracy 32.2% baseline versus 48.3% AgentRx, category
25.3% versus 39.1%. Table 5 supplies a counterexample to universal benefit:
Magentic baseline step accuracy 31.8% versus 25% with violation input.
These are failed-trajectory localization metrics, not binary current-turn F1.
Guardian can test factual diagnostics separately from normative hypotheses and
measure whether violation signals anchor reviewers.
The [checker](https://github.com/microsoft/AgentRx/blob/7a18c79708e7671be15124460f4f7296107c2a55/agentrx/invariants/checker.py)
has separate Python and natural-language checks. Lines 915–929 attempt prose
fallback then parse JSON again; lines 896–898 retry rate limits. Neither behavior
fits this research's immutable no-retry, no-keyword-repair contract. Generated
invariants themselves still require semantic scrutiny; code execution alone
does not establish faithful policy translation.

### Microsoft Universal Verifier / Fara

The [inspected implementation](https://github.com/microsoft/fara/blob/a675d6d61c41c47ae87bacefeab22caad18e3e84/webeval/src/webeval/rubric_agent/mm_rubric_agent.py)
separates process reward, outcome success and critical-point violations, with
criterion-level evidence, a conditional-criteria reconciliation step and an
independent side-effect check. It uses action logs and screenshots; a single
critical-point classification supplies shared scope to downstream reviewers.
The [official benchmark documentation](https://github.com/microsoft/fara#cuaverifierbench-evaluating-the-verifiers-themselves)
lists 106 Online-Mind2Web trajectories/215 annotation rows and 154 internal
trajectories/154 rows, including blind versus verifier-informed human labels.
These dataset sizes establish an evaluation interface, not verifier F1 or
universal accuracy; no independently verified verifier-accuracy number is claimed
here. Agent task success is not verifier agreement.
Guardian can borrow separate outcome/process axes, explicit conditional criteria
and missed-side-effect search. Visual latest-state precedence is domain-specific:
do not transfer it to immutable historical attributes or erase earlier process
violations. This multi-step implementation also costs many model calls and is not
a minimal architecture by default.

### GraphReader

The [paper](https://aclanthology.org/2024.findings-emnlp.746.pdf), Sections 3–4,
constructs a graph of key information/chunks, then plans, explores content and
neighbors, records notes and reflects. LongBench Table 2 gives HotpotQA F1 70.0
with a 4k local window versus full GPT-4-128k 68.4; MuSiQue 47.4 versus 42.7.
LV-Eval Table 3 gives 256k F1* 33.0 versus 10.3 for GPT-4-128k, but the latter
retains only the longest fitting initial fragment. That comparison includes
baseline truncation, not equivalent evidence access. Node-selection ablation
lowers HotpotQA F1 from 70.0 to 54.1. Up to five initial nodes and ten calls per
path are allowed; graph preprocessing is additional cost.
Guardian can reuse existing graph adjacency and exact original reads instead of
constructing another graph engine. An edge produced by an LLM is not normative
truth. This evidence motivates a retrieval experiment with equal read budgets,
not a prediction that graph expansion improves Guardian F1.

### ReadAgent

The [primary paper](https://arxiv.org/html/2402.09727v3) and
[published version](https://proceedings.mlr.press/v235/lee24c.html) evaluate
QuALITY, NarrativeQA and QMSum. Model-chosen episodes are compressed to gists;
selected original pages are reread before answering. Table 1, on QuALITY's
2,086-question development set with PaLM-2-L, gives full raw content accuracy
85.83%, gist-only 77.52%, parallel lookup 1–2 pages 86.16%, sequential lookup
1–6 pages 87.17%. The reported effective-window extension is 3.5–20×, with
pagination/gisting preparation cost and task-dependent lookup prompts.
The author [prompt/demo release](https://read-agent.github.io/) is referenced in
the paper; code was not silently inferred from an unavailable repository path.
Guardian may use episode summaries only as navigation and restore originals for
evidence. Gist-only degradation directly cautions against summary-as-proof.
Reading comprehension accuracy does not prove complete policy coverage or
preservation of actor/order/identity; these must be checked separately.

### Chain-of-Verification

The [paper](https://aclanthology.org/2024.findings-acl.212.pdf) proposes draft,
verification-question planning, independent/factored answers and revised output.
It evaluates entity-list questions, closed-book MultiSpanQA and biographies.
Table 2 gives Llama-65B MultiSpanQA F1 0.39 few-shot versus 0.48 factored CoVe.
Table 1 improves easier-list precision 0.17→0.36, while average correct entities
decline 0.59→0.38: fewer hallucinations may also remove true content. Biographical
FactScore rises 55.9→71.4 while facts decrease 16.6→12.3. These are factual QA
metrics, and closed-book verification need not discover new external evidence.
Guardian can test independent questions without exposing the first verdict,
then compare anchoring and missed obligations. It should not automatically accept
the verifier's unsupported answer or convert fewer accusations to higher quality.
Reason/decision consistency and source correctness remain distinct from an
apparently persuasive revision.

### CRITIC

The [paper](https://arxiv.org/html/2305.11738v2), Section 4, tests tool-assisted
critique/correction on QA, math and toxicity. For QA it caches external search,
allows seven tool interactions and three correction rounds, and stops after
unchanged answers across two rounds. Table 1 gives ChatGPT HotpotQA F1 42.8
CoT→52.9 CRITIC, versus 46.1 without the tool. Oracle-only correction is separately
56.9 and must not be conflated with automatic CRITIC. Rejection sampling reaches
55.6 at a different sampling cost. Search extracts at most 400 characters by fuzzy
snippet matching, potentially losing contextual qualifications.
Guardian can borrow cached read-only tool feedback and bounded correction,
but should retain full provenance/coverage and scope exceptions. A critique
without new evidence can repeat the same unsupported norm. Changes to correct
answers, search cost and scope-preserving retrieval need paired measurement.

### RefChecker

The [paper](https://arxiv.org/html/2405.14486v1) separates subject/relation/object
claim extraction and reference-based Entailment/Neutral/Contradiction checks.
Its benchmark contains 2,100 responses from seven models across zero, noisy
and accurate reference contexts. Table 3's 30-response human extraction audit
reports GPT-4 F1 94.8 and Claude-2 95.7. Section 5 reports Claude-2/GPT-4
correlation gains of 6.8–26.1 points over FacTool; these are hallucination-rate
correlations, not current-turn classification accuracy.
The [aggregator](https://github.com/amazon-science/RefChecker/blob/1df1b25cee792ba2b171302e31ca4f768bd67703/refchecker/aggregator.py)
offers proportion, strict and majority contracts, treating empty claims as
Abstain. Guardian should likewise state its aggregation/UNKNOWN contract.
Triplet entailment cannot alone express temporal obligations, exceptions,
multientity joins or complete missed-obligation search. Its
[LLM parser](https://github.com/amazon-science/RefChecker/blob/1df1b25cee792ba2b171302e31ca4f768bd67703/refchecker/checker/llm_checker.py)
contains label-substring recognition; do not copy this as a semantic decision
adapter. A faithful extracted claim and an applicable norm are separate checks.

## Additional directly relevant studies

| Primary source | What was measured and mechanism | Guardian implication and limit |
|---|---|---|
| [Let Me Speak Freely?](https://arxiv.org/html/2408.02442v2) | Compares text/JSON/XML/YAML and schema constraints. Table 1 gives Llama-3-8B 75.13 text versus 64.67 JSON, and 48.90 with schema. Gemini-1.5-Flash text 89.33 versus JSON 89.66 shows the effect is not universal. Section 5.2 explicitly observes JSON failing requested reasoning-before-answer order. | Measure actual emitted key order, parsing success and semantic accuracy independently. This motivates our factorial test; it does not prove ordering caused the historical A/C failure. Models, prompts and provider constraints differ. |
| [CRANE](https://arxiv.org/html/2502.09061v2) | Allows unconstrained intermediate generation and constrained final output. FOLIO Table 2 gives Qwen2.5-7B accuracy 36.95 unconstrained-CoT, 37.44 constrained and 42.36 CRANE; compile rates differ. GSM-Symbolic and FOLIO are symbolic reasoning tasks. | Reasoning/decision separation is worth measuring. The actual decoding algorithm requires logits and is unavailable through our closed APIs; a two-call adapter is an analogy, not CRANE reproduction. Syntax still cannot certify faithful policy semantics. |
| [Unfaithful Explanations](https://arxiv.org/html/2305.04388v2) | Intervenes with answer-order and suggested-answer biases over 13 BIG-Bench-Hard tasks, GPT-3.5 and Claude-1; accuracy can fall by 36% without explanations acknowledging the bias. | A correct-looking reason is not evidence of the model's internal causal path. Source-based cause scoring and raw-label preservation are necessary; explanations can be audited without treating them as certified proofs. |
| [Faithful Chain-of-Thought](https://arxiv.org/html/2301.13379v3) | Translates to symbolic intermediate forms executed by deterministic solvers; reports 9/10 benchmark wins across math, planning, multihop QA and relational inference, with relative gains 6.3%, 3.4%, 5.5%, 21.4%. | A code adapter can make final output faithful to an intermediate representation, but not make an incorrect semantic representation true. Avoid a universal solver or claiming normative proof from validated field IDs. |
| [Solver-Aided Policy Verification](https://arxiv.org/html/2603.20449v1) | Runtime Z3 interception after policy-to-SMT encoding. Section 5 reports invalid writes reduced to 29% of writes, alongside fewer correct writes. Final encodings needed manual fixes for undefined variables, time conversion and underconstrained implications. | Strong relevance to our semantic-admission boundary: syntactic success is not completeness/tightness. Human-repaired rules do not establish automatic grounding quality. This is intervention during agent execution, not retrospective Guardian F1. |
| [PolicyGuide](https://arxiv.org/html/2608.19861v1) | Compiled workflow graphs, persistent request state and an external verifier on Tau2-bench. Telecom Pass4 0.193→0.614; author-designed process-valid rate 17.5%→56.2%. Guide calls 7.4–11.5/task and end-to-end latency 5.45–5.78× baseline. | Distinguish outcome success from ordered process compliance. Persistent gaps/workflow state may help, but bundled ablations do not isolate every mechanism; policy compilation needs review. These are online guided-agent results, not independent error-detector F1. |
| [Lost in the Middle](https://arxiv.org/html/2307.03172v3) | Changes evidence positions in multidocument QA and key-value retrieval. GPT-3.5's 20-document accuracy ranges from 75.8% at the start to 53.8% at index 9 and 63.2% at the end (Table 6). | Full context fits do not establish evidence use. Test early observation/late action bindings explicitly and preserve index offsets. Older model measurements do not prove the same magnitude for Ministral/Gemma today. |

## Minimal transfer candidates and falsification

These are design inferences from the cited mechanisms, not claims of demonstrated
Guardian improvements. Preserve immutable SourceStore references; keep mechanical
checks separate from semantic hypotheses; retain an explicit gap ledger and
UNKNOWN reasons; measure decision/reason agreement before proposing a second
reviewer. Use original text for proof and summaries/indexes for navigation.

The decisive local tests remain: equivalent I1–I4 sources and observed output
order; paired K0/K1/K2 without a hidden normative hint; C0/C1/C2 plus false-signal
controls; R0/R1 on equal catalogs and eight full reads, and a consistency gate
that flags an unsupported relation without manufacturing ERROR. External work
justifies those experiments, not their outcome. Single-case improvements and
foreign benchmark results cannot substantiate an 80% unseen-data promise.
