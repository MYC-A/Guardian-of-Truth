# V6: targeted verification, fallback and evidence ordering

## Frozen baseline and decision rule

The frozen reference is `outputs/claim_gate_20b_full` on all 46 rows of
`valid.parquet`: TP=14, FP=5, FN=9, TN=18, precision=0.7368, recall=0.6087,
F1=0.6667. There are 18 fallbacks, 40 logical semantic calls, 99 HTTP attempts
and 143389 reported tokens. Six mechanical positive decisions bypass the LLM.

Every experiment must compare the same row IDs and report confusion counts,
precision, recall, F1, fallback, changed rows, calls/attempts and tokens. A lower
fallback count is not a quality result. Gold labels and the manual reason audit
must not enter model prompts, evidence selection or prediction rules.

## Shortlist frozen before implementation

| Rank | Hypothesis | Expected upside and coverage | Main risk | Cost / effort | Cheap falsification |
|---:|---|---|---|---|---|
| 1 | Deliver the most applicable complete policy section, including conditions and exceptions, within the existing evidence budget. | Broadest observed opportunity: audits contain five FN and two FP with material sources not delivered. No additional LLM call. | A policy section can displace entity/state evidence and regress existing TP. | Medium implementation; same inference cost. | Offline delivery audit on all 46 first; reject if target conditions remain absent or audited TP evidence is displaced. Then paired, frozen screen only. |
| 2 | Remove duplicated top-level rationale/citations from the one-shot output contract and derive them from strictly validated per-claim citations. | Directly targets 13 rejected, otherwise structured JSON outputs and one truncation; up to four current FN are in grounding rejection classes. | Validator relaxation can admit false accusations. Existing `overall` ablation already produced +1 TP and +2 FP with no F1 gain. | Low/medium; still one call and likely fewer output tokens. | Eight frozen fallback/control rows; keep all per-claim grounding and verdict-consistency rules. Reject on any new control FP or reduced fallback without a verified material reason. |
| 3 | Present the already selected evidence chronologically while preserving its exact membership. | Narrow precision opportunity: at least one FP compares an older state with a selected newer state. Zero extra tokens/calls. | Recency can be confused with authority or a different entity/state. | Very low. | Six frozen cases, identical evidence set and prompt; only packet order changes. Reject if the known state FP remains or any counter-control regresses. |

Mandatory hypothesis, evaluated independently of the ranking: **targeted
accusation verification**. The one-shot judge proposes concrete accusations; a
narrow second judge classifies their relation to the exact selected evidence as
ENTAILED, CONTRADICTED, RELATED_ONLY or INSUFFICIENT. A row-level hard gate keeps
an error only when at least one material accusation is verified. This adds 13
calls on the current 13 semantic-positive rows (+32.5% logical calls end to end)
and cannot repair any current FN, so it must beat a demanding stop rule.

## Pre-experiment bounds and stop rules

The manual audit has 13 semantic-positive rows and 23 accusations. Only four
rows have a correct material reason; four TP have a correct label but a wrong
reason, and all five FP lack a confirmed valid material reason. Consequently an
oracle hard gate over all accusations is bounded at TP=10, FP=0..1, FN=13,
TN=22..23 and F1=0.5882..0.6061: below baseline. An H1-only oracle fixes two FP,
regresses one TP and leaves F1 at 0.6667. The live judge run remains required to
test the mechanism, but the hard gate is rejected unless corrected rows exceed
regressions, full F1 is at least 0.6667, all outputs are valid, reason-precision
lower bound reaches 0.60, wrong-reason TP falls to at most one, and token overhead
stays below 50%.

Fallback decomposition is frozen as follows:

| Cause | Total | FN | TN |
|---|---:|---:|---:|
| `language_missing_grounding` | 8 | 3 | 5 |
| `language_claim_missing_grounding` | 4 | 1 | 3 |
| `language_inconsistent_claims` | 1 | 0 | 1 |
| `language_http_request` | 4 | 1 | 3 |
| `language_truncated` | 1 | 0 | 1 |

There are no JSON/parser/schema failures and no explicit semantic-unknown
fallbacks. The compact-contract experiment must therefore remove duplication,
not simply bypass grounding.

## Experiment log

- Targeted-verifier inputs were re-frozen as 16 model-blind claim/evidence cases
  (eight original accusations and eight exact-source contrast controls) because
  the previous prompt hash no longer matched the current verifier instruction.
- The first Gemini 3.5 Flash run used an insufficient one-second pace and was
  aborted after five cases. A second run at 20 seconds between every HTTP attempt
  still returned repeated 429 responses and was stopped after two complete
  failures. These are transport/quota observations, not semantic results.
- Groq GPT-OSS 20B was then selected only after a separate tiny connection smoke
  succeeded. The frozen 16-case run produced 16/16 valid outputs, 12/16 correct
  relations (0.75), and 8/8 correct exact-source contrast controls. On the eight
  real one-shot accusations it was only 4/8. It used 19 HTTP attempts, 36414
  reported tokens and 278.2 seconds. This shows that the narrow relation task is
  viable, but also that clean controls substantially overstate behavior on real
  accusations.
- A replay containing all 13 semantic-positive rows and all 23 raw accusations
  was frozen before calls. A per-accusation Groq run was stopped after five cases
  because repeated transport/rate-limit failures made it incomparable. It is an
  aborted transport artifact, not a quality result. The precomputed oracle bound
  already falsifies the row-level hard gate even with a perfect verifier.
- The model-blind policy-section selector was executed on all 46 rows before
  loading annotations. It reduced annotated character coverage from 44.82% to
  37.29% and semantic-TP coverage from 36.66% to 25.82%. Although undelivered
  strict-error spans fell from 23 to 19, the loss of existing TP evidence violates
  the stop condition. The tested selector is rejected without model calls.
- The compact one-shot contract is implemented behind the explicit `compact`
  protocol and keeps per-claim grounding strict. Groq 20B was token-rate limited;
  two paced screen attempts did not yield a comparable run. A 120B probe showed
  both possible recovery and instability on the same row (one grounded TP and one
  claim-grounding fallback), followed by rate limits. No quality claim is made;
  the protocol remains disabled and experimental.

## Production candidate: explicit turn cardinality

FN inspection exposed a simpler invariant outside the initial shortlist. When
the authoritative system policy explicitly says either “only make one tool call
at a time” or “at most make one tool call at a time”, two or more assistant tool
calls in the candidate turn are a directly inspectable violation. Likewise, a
message plus a tool call is rejected only when the system block contains the
explicit mutually-exclusive action rule. User text cannot introduce either
rule. Multiple calls remain unknown when no such system rule is present.

The check was integrated before semantic inference and replayed over the frozen
46-row baseline. It fired on eight rows, all gold-positive. Three were already
mechanical positives. Five semantic calls are now safely short-circuited; two of
those rows were FN and changed from 0 to 1:

- `airline__9::t6`
- `retail__27::t10`

An independent execution of the current no-LLM detector on all 46 rows now finds
11/23 positives with zero FP: precision=1.0000, recall=0.4783, F1=0.6471. The new
turn-cardinality findings themselves cover eight positives (seven multi-call and
one mixed text/call), again with zero FP on this file. This is the strongest
high-confidence part of the system, but “zero FP on 23 negatives” must not be
described as a mathematical guarantee on unseen data.

Full validation comparison:

| Variant | TP | FP | FN | TN | Precision | Recall | F1 | Fallback |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Frozen one-shot baseline | 14 | 5 | 9 | 18 | 0.7368 | 0.6087 | 0.6667 | 18 |
| Baseline + explicit turn cardinality | 16 | 5 | 7 | 18 | 0.7619 | 0.6957 | **0.7273** | 16 |

Delta F1 is +0.0606, precision +0.0251 and recall +0.0870. The paired
provenance-group bootstrap interval for delta F1 is [0.0000, 0.1632] on only 45
groups, so it includes zero and is not proof of hidden transfer. The invariant is
nevertheless a production candidate because every hit has an exact system-rule
span plus candidate-action spans, it introduces no LLM call, and it created no FP
on the full development file.

Exact replay cost falls from 40 to 35 logical semantic calls and from 143389 to
121024 reported tokens. Per-row HTTP attempts were not retained in the old
baseline, so the exact attempt reduction cannot be reconstructed; it cannot add
attempts and should skip the five newly mechanical rows. The candidate does not
change any surviving one-shot model generation.

Reason quality also improves structurally: the five newly short-circuited rows
receive an exact policy/action reason. Among them, three were existing TP (two
had valid material reasons and one had a wrong reason) and two are corrected FN.
This does not magically validate the remaining semantic rationales.

## Cycle decision

**KEEP** explicit turn cardinality as the production candidate.

**REJECT** targeted accusation verification as a row-level hard gate: its oracle
F1 ceiling is below baseline, the live judge solves only 4/8 real accusations,
and it cannot recover any FN. Keep the verifier only as an optional reason-audit
diagnostic.

**REJECT** the tested policy-section selector: it loses too much TP evidence
before inference. The broader idea may be revisited only with a replacement-aware
packer that proves it preserves entity/state evidence.

**NEXT / disabled:** compact contract and chronological packet order. The former
needs a fresh paired run after provider quota recovery; the latter has narrow
expected upside and ranks behind the now-proven zero-cost deterministic gain.

The remaining bottleneck is semantic precision/reason quality, not JSON parsing:
five FP remain, and the old reason audit found only 4/13 to 5/13 correct material
reasons among semantic-positive decisions. The next highest-value experiment is
a model-blind state-version/recency predicate or a paired chronological-order
screen, followed by independent external validation rather than more tuning on
these 46 inspected rows.
