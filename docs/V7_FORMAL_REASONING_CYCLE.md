# V7: routed formal verification instead of one universal semantic judge

## Outcome

The best current end-to-end development candidate is now **TP=17, FP=5,
FN=6, TN=18, F1=0.7556**, up from V6 F1=0.7273. The gain comes from one exact,
zero-LLM `DATE_GATED_ACTION` check. It recognizes an explicit authoritative
system prohibition, binds the candidate `resume_line` action to the same
`line_id`, reads the latest structured `contract_end_date`, and compares it with
the unique system current date. Missing or ambiguous inputs abstain.

This is a real paired replay improvement on the 46 development rows, but not a
hidden-test guarantee: the new predicate activates on only one row and its
paired bootstrap interval for delta F1 is `[0.0000, 0.0942]`.

The LINC-like bounded translator is promising but not production-ready. It gave
the correct final relation in 4/4 repeated calls, including the critical
`only if` control, while its normalized translation changed in 2/2 cases. The
FaiRR-like application protocol achieved only 2/4 valid records because two
outputs failed exact clause-quote validation. These branches remain shadow-only.

## Frozen A–E experiment

The screen was frozen in `experiments/v7_ae_screen.json` before implementation
and live calls: all 12 V6 residual errors plus eight real controls. Gold labels,
explanations, IDs and the manual routing table are local evaluation metadata and
never enter model messages or runtime rules. One FN is a transport failure and
one FP is a serialization/materiality ambiguity; both remain in row metrics but
are separated from reasoning claims.

| Branch | Evidence obtained | Decision |
|---|---|---|
| A — current judge | Full 46 rows: 16/5/7/18, F1 0.7273 after V6 | Comparator |
| B — narrow entailment | 16/16 valid, 12/16 relations correct; real accusations 4/8, controls 8/8 | Diagnostic only; clean controls overstate real performance |
| C — FaiRR rule/facts/application | 2/4 valid and correct; 2 invalid exact clause quotes | Reject current protocol |
| D — LINC bounded facts/rules + solver | 4/4 valid/correct; final relation stable 2/2, normalized translation stable 0/2 | Keep shadow-only |
| E — exact code | One exact FN correction, zero regressions; full F1 0.7556 | Keep narrow candidate |

The exact-only detector now observes TP=12, FP=0, FN=11, TN=23 on this file:
precision 1.0, recall 0.5217 and F1 0.6857. “FP=0 on 23 development negatives”
is evidence for high precision, not a guaranteed percentage on unseen data.

Detailed machine-readable results are in `docs/v7_formal_methods_result.json`.
Raw bounded calls and HTTP-attempt logs are under `outputs/` and intentionally
remain untracked.

## What is implemented

`formal_reasoning.py` provides a non-executable formal boundary:

- at most 16 named ground atoms and eight rules;
- explicit positive/negative literals under an open-world assumption;
- correct `IF`, `ONLY_IF`, and `IFF` compilation;
- finite forward closure, conflict detection and proof certificates;
- exact source-ID and unique-quote validation;
- no Python, shell, arbitrary functions, variables, quantifiers or generated
  expression execution;
- `FOLLOWS`, `CONTRADICTS`, or `INSUFFICIENT`, always scoped as relative to the
  supplied translation.

The FaiRR-like record separates the rule, facts, entity scope, time scope,
conditions, exceptions and applicability. The validator recalculates
`APPLIES`, `NOT_APPLIES`, or `UNKNOWN`; a scope mismatch only invalidates that
rule application and never proves the opposite row label.

The production pipeline does not call either translator. Only the exact date
gate is integrated, before semantic inference, so its one hit skips an LLM call.
Logical semantic calls fall from 35 to 34 and replayed reported tokens from
121024 to 116494.

## Translation errors learned from the screen

The solver behaved deterministically relative to each accepted program. The
remaining risk sits before it:

- `only if` can be reversed into a sufficient rule. Correctly,
  “Q only if A and B” means `Q -> A AND B`, not `A AND B -> Q`.
- Stable final labels can hide unstable internal translations. The real D case
  used three atoms in one run and five in another.
- Generic entity annotations appeared in one `only if` run and disappeared in
  another.
- C invented source identifiers in the first corrected-schema run, then still
  paraphrased two clause quotes. Strict provenance validation correctly rejected
  these rather than silently accepting plausible structure.
- Missing conditions, wrong entity, stale state, exceptions, may-to-must,
  some-to-all and possible-to-guaranteed remain mandatory controls.

Therefore an exact solver does not certify that an LLM translated the source
faithfully. D stays shadow until format validity is 100%, translation agreement
is at least 90%, and polarity/entity/condition errors are zero on a broader
frozen screen.

## CEL decision

Do not add a CEL runtime yet. CEL is designed as a safe, portable expression
language, and an official Python implementation now exists, so it is a credible
future execution backend ([CEL overview](https://cel.dev/overview/cel-overview),
[official CEL Python repository](https://github.com/cel-expr/cel-python)). It
does not solve the hard part observed here: natural-language translation,
authority, missing conditions, entity/time binding, and source provenance.

The existing `rules.py` already gives this project a smaller bounded AST with
typed operands, comparisons, dates, latest entity-scoped facts, exact sources
and conservative `UNKNOWN`, while keeping project runtime dependencies empty.
Adding CEL now would add a parser/runtime/type/cost surface without improving the
two tested residual rule classes. Reconsider it only after at least three kept,
transferable predicates genuinely need collection comprehensions or reusable
cross-language expressions.

## Routing decision

The intended runtime router is conservative and model-blind:

1. complete typed operands and a whitelisted operation → E/code;
2. an explicit rule that fits the bounded fragment → D/LINC, shadow until the
   translator passes stability and faithfulness gates;
3. uncertainty about conditions, exceptions, entity or time scope → C/FaiRR,
   currently rejected;
4. remaining modality and semantic strength → B/narrow entailment, diagnostic;
5. unsupported or incomplete translation → current A/fallback.

No negative row label may be inferred merely because one accusation was
refuted. A positive exact label needs one material proved violation; a negative
label needs complete material coverage, which B–E do not yet provide.

## Proof trees and RLM-style graphs

A separate whole-history proof graph is stopped. Only `airline__7::t6` clearly
needs a short chain (date → past flight → excluded aggregate operand). The new
solver already emits bounded proof certificates for any derived conclusion, so
a second LLM that draws trees would add cost without fixing premise selection.

The existing graph-guided reader remains useful for locating entity/state
evidence. It should not assign decorative confidence percentages to facts.
Confidence should come from inspectable dimensions—source authority, exact
binding, recency, conflicts and unknown conditions—then route uncertain cases
to abstention.

## Next experiment

Keep the exact date gate but describe it as a narrow candidate because it has
one activation. The next transferable predicate should be
`LATEST_SCOPED_STATE_BASIS`: invalidate an accusation source when a later state
for the same entity and field exists. It must remain premise-level until a
complete row-level verifier exists. After that, test `BOUND_RATIO_THRESHOLD`
using integer cross multiplication and a separately verified tier mapping.

Any next full claim requires a fresh paired A run on all 35 semantic rows,
no new FP on the frozen real controls, F1 strictly above 0.7556, and external
validation not used during rule design.

