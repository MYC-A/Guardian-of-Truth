# Vast semantic component probes — 2026-09-26

## Scope and environment

This was **not** a full Guardian benchmark or a new whole-case classifier.
Only a 48-response speech-act component probe and 24 claim-to-tool proposal
rows were run. Identical supported/unsupported requests were cached in the
fresh completion suite, so the 24 proposal rows used 20 Mistral API calls.

The user-specified `guardian-vast-agent` hostname did not resolve in this
Windows environment; the existing `guardian-vast` SSH alias connected to the
same RTX 3090 instance. `/etc/vast-agents-guide.md` was read in full before
using the instance. `nvidia-smi` showed RTX 3090 24 GB. The existing
`/workspace/guardian/venv/bin/python` was Python 3.11.16 with PyTorch
2.9.1+cu128; a one-element CUDA tensor succeeded. The repository was cloned
into `/workspace/guardian/repos/Guardian-of-Truth`. Mistral was called through
its API using the existing `MISTRAL_API_KEY` and `MISTRAL_MODEL` in the
untracked server secret file. No dependency or model was installed, and no
long GPU or full-benchmark run was started.

All action-state prediction JSONLs were SHA-256 sealed before their separate
gold file was read. The local archive in
`outputs/searh_23/action_state_probe_2026-09-26/` preserves predictions,
manifests, seals and scores. The copied prediction hashes and the input/code
Git blob hashes match the remote manifests. Completion proposal runs are
archived with input/frame/code hashes; their post-inspection mapping audit is
`completion_mapping_audit.json`.

The two new component test files passed 4/4 on Vast and the four related
local test files passed 19/19 on Windows. The broader historical follow-up
test file could not be collected in the Vast environment because an unrelated
old import chain needs the absent `openai` package. That package was not
installed for this probe.

## 1. Action state was easy; actor was not

The model saw only the target assistant response. Actual tool calls were
classified by the parser as `CALL_ATTEMPT`, never business success. The
evaluated text subsets were 16 original service-desk responses, their 16
renamed counterparts, and 16 new authored responses from travel, shipping and
payment language. The new cases and labels were written before any score was
opened. They remain authored diagnostics, not a contest holdout.

| Suite | Correct action kind | Correct actor | Both |
| --- | ---: | ---: | ---: |
| Service desk | 16/16 | 13/16 | 13/16 |
| Renamed service desk | 16/16 | 12/16 | 12/16 |
| New domain | 15/16 | 14/16 | 13/16 |

Every one of 48 API responses parsed and carried an exact response quote. The
single new-domain kind miss was `Сейчас соединяю вас со специалистом`: it was
classified as a future offer rather than a handoff. All user-action requests
were assigned `actor=ASSISTANT` despite the correct `USER_REQUEST` kind. Thus
the model's actor field is not safe to use. A request classified as
`USER_REQUEST` logically has the user as the requested actor, so this field
could be normalized by code, but that would be a post-score correction and
still would not prove policy compliance.

## 2. Quote anchoring and catalog membership did not validate tool meaning

The second probe used only the sealed `COMPLETED_CLAIM` responses. Mistral
proposed a declared tool and a policy clause; the existing code checked exact
source, entity, amount and result match. Version 1 supplied only tool names.
Version 2 supplied the exact first catalog line describing each tool and
required the chosen line verbatim. Version 2 was built after inspecting v1,
so the old cases are development data.

| Arm | Correct claim-to-tool mapping | Raw absence verdicts |
| --- | ---: | ---: |
| v1, original | 2/4 | 4/4 `UNSUPPORTED_COMPLETION_CANDIDATE` |
| v1, renamed | 3/4 | 4/4 `UNSUPPORTED_COMPLETION_CANDIDATE` |
| v2, original | 3/4 | 4/4 `UNSUPPORTED_COMPLETION_CANDIDATE` |
| v2, renamed | 3/4 | 4/4 `UNSUPPORTED_COMPLETION_CANDIDATE` |

The raw verdict count is **misleading**. For a claim that a replacement had
completed, v2 chose the *audit-recording* tool in both lexical variants.
Because no audit result was present, code emitted the same unsupported result
as it would for the correct replacement tool. Source quotation, declared-tool
membership and absence of a result cannot catch this semantic error. These
rows cannot be promoted as proven violations.

The newly frozen claim-to-tool suite used four different claims, each paired
with and without a matching successful result. Oracle action-state frames
isolated mapping from the first probe. Version 2 chose the correct tool for
all four unique claims (8/8 rows), and code distinguished both members in two
families (4/8 verdicts). In the other two families Mistral returned an
abbreviated policy quotation with ellipses; the exact-source validator
returned `UNKNOWN`. In a **post-score oracle replay** replacing the quote by
the suite's sole policy clause, all 8/8 verdicts matched the component gold.
That shows a citation-serialization problem on this simple source, not a
general rule-selection solution for multi-clause policies.

## What the attached formalization ideas change

The cited [NL-to-FOL study](https://arxiv.org/abs/2509.22338) itself identifies
predicate extraction as the bottleneck and reports a large gain when predicates
are supplied. Our trace shows the same distinction: selecting an existing tool
name or an exact policy quote is structurally easy, but whether *that tool's
successful result entails that claim* is still wrong on the replacement/audit
pair. The [T5-3B model card](https://huggingface.co/fvossel/t5-3b-nl-to-fol)
describes short English NL-to-FOL inputs, not deontic agent policies or tool
effect semantics. Downloading its float32 weights would not test the measured
missing link, so no 12 GB checkpoint was fetched.

[GraFT](https://proceedings.mlr.press/v267/english25a.html) makes a good case
for constraining syntax. Here, choosing a clause ID from source spans would
prevent the two ellipsis quotes. It would not by itself stop an audit tool from
being mistaken for proof of replacement. [NL2TL](https://aclanthology.org/2023.emnlp-main.985/)
similarly separates atomic-proposition extraction from temporal structure;
our prior RuleIR/Phi tests already showed the atomic binding gap. The
[P2T schema](https://github.com/gautamvarmadatla/Policy-Tests-P2T-for-operationalizing-AI-governance/blob/main/policy_dsl_schema.jsonl)
records source, conditions and evidence but stores the latter as strings;
those fields alone are not an executable same-entity, same-time proof. A
conformal guarantee would require a clean representative calibration set,
which this project does not yet have.

## Decision

Keep the action-state frame as a **diagnostic component**. Do not add it or the
completion proposal to C1 as a whole-case OR/veto. The next meaningful test,
if undertaken, is pairwise claim-to-tool-result entailment with exact catalog
and result excerpts, including replacement-vs-audit and authorization-vs-
execution counterexamples. It must reject a related tool as `UNKNOWN` and then
survive new multi-clause policies and matched valid calls. A syntax-only
compiler or larger FOL/TL model is lower priority until this link works.
