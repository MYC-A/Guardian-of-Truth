# Action-state component probe (frozen before API calls)

This is a short diagnostic for the text half of the new service-desk suite,
not a whole-case Guardian benchmark. The source cases and lexical renaming were
already viewed while developing other arms; neither result is an independent
quality estimate. No Guardian verdict is changed by this code.

## Question

Can one narrow Mistral API call distinguish a completed-action assertion from
a future/conditional offer, a request for the user to act, a refusal/handoff,
and a state report? The existing typed-question arm made 67 calls but changed
zero decisions on this suite; its questions were routed through pgjudge cards.
This probe sees only the target response text and runs independently of cards.
Actual assistant `TOOL_CALL` events are classified mechanically as attempts,
never as proof of business success.

## Frozen evaluation

The 16 original text responses in `service_desk_v1/cases.csv` and their 16
lexically renamed counterparts are the inputs. The expected action-state and
actor fields are in `action_state_gold_v1.json`, frozen before the first API
call. Inference reads only `id,prompt,response`; scoring reads the gold file
after predictions are sealed. Every model quote must be an exact response
substring. `UNKNOWN` is the result of an invalid quote or schema.

Primary component measure: exact action-state class on each 16-case arm.
Secondary measures: actor class, all-field agreement and paired renaming flips.
The predeclared next-step gate is at least 14/16 exact action-state classes on
each arm and no more than one paired flip. Passing it would justify a fresh
domain and a source-bound event verifier; it would **not** justify vetoing C1.
Any new text error can coexist with a correctly classified future offer.

Before opening either original or renamed score, a further 16-case response-
only challenge was authored under `action_state_fresh_v1/` with travel,
shipping and payment language in English and Russian. Its input and separate
gold file were written while the renamed API run was in progress. The model
prompt and parser are unchanged. This is still authored data, not a contest
holdout; it checks whether the small speech-act vocabulary survives a domain
change. The same 14/16 action-state threshold applies.

## Vast execution

Run inside `/workspace/guardian/repos/Guardian-of-Truth` with the existing
`/workspace/guardian/venv/bin/python`. Mistral comes only from the API and the
existing `/workspace/guardian/secrets/mistral.env` file; no secret is copied
into Git or printed. These are 48 short API calls across all three suites, not the
full benchmark. The runner resumes from append-only JSONL and freezes the input
and code hashes. Run original and renamed to separate output paths, then score
each output with the frozen gold file.

## Literature triage

The attachment's strongest general lesson is to limit the output vocabulary
and check the predicates, not to add a new solver. [GraFT](https://proceedings.mlr.press/v267/english25a.html)
improves valid temporal-logic translation by restricting decoder choices.
The [NL-to-FOL study](https://arxiv.org/abs/2509.22338) reports large benefit
from supplied predicate lists and calls predicate extraction the bottleneck.
Its [T5-3B checkpoint](https://huggingface.co/fvossel/t5-3b-nl-to-fol) is
English/FOL, trained on short inputs, and does not encode policy deontics or
agent-event binding. [NL2TL](https://aclanthology.org/2023.emnlp-main.985/)
abstracts propositions before temporal translation; our earlier RuleIR and
Phi paths already reached this separation but failed at binding and applicability.
[Policy-to-Tests](https://arxiv.org/abs/2512.04408) gives a useful evidence
field in its DSL, which our source-linked records already have. Conformal
coverage would need a clean representative calibration set that we do not have.

Thus the first GPU-server step is a cheap Mistral component probe using existing
dependencies. No FOL/TL model weights are downloaded unless the action-state
and subsequent source-binding gates show a missing formalization capability.

## Follow-up after the action-state score

The action-state kinds passed the predeclared small gate, but Mistral repeatedly
assigned assistant actor to a request for the *user* to act. This is a semantic
error, despite the right class. A separate diagnostic `completion_frame_probe.py`
therefore uses only sealed `COMPLETED_CLAIM` frames. It asks Mistral to map the
claim to a declared tool and an exact policy clause, then runs the existing
source/entity/amount/result validator. The initial opportunity is four
completed-claim cases per lexical suite. A useful result requires anchored
proposals for all four and matching results to refute paired supported claims.
It remains diagnostic: model-proposed tool/claim semantics are not a proof.

The first mapping run returned four absence candidates in both lexical suites,
but inspection found three incorrect tool choices across eight proposals.
This is exactly the failure that quote anchoring and catalog membership cannot
catch. Version 2 supplies the source line describing each declared tool,
requires the selected line verbatim, and otherwise keeps the validator fixed.
This is a post-inspection correction, so the old eight cases are development
data. The separate `completion_fresh_v1` suite was generated and frozen before
v2 API calls: four unseen-domain claims, each paired with and without a matching
successful tool result. It uses an explicit oracle action-state frame to isolate
the mapping problem. Identical model requests across each pair are cached, so
only four fresh API calls are needed. The v2 gate is 8/8 correct tool maps and
8/8 correct supported/unsupported component verdicts. Passing still would not
certify end-to-end Guardian accuracy.
