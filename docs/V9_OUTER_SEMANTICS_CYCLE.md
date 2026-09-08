# V9: falsification of underspecified outer semantics

## Outcome

The architectural idea is **partly kept, but the current translator is rejected
for production integration**. The safety kernel works: it preserves value,
binding, subtree and whole-rule holes; separates `Phi_working` from
`Phi_outer`; ignores heuristic exclusions in `Phi_outer`; supports revision;
runs two-query invariant evaluation; and refuses strict output when discovered
coverage is incomplete. It also passes all 15 controlled metamorphic pairs.

The real-language result is negative. On 16 frozen Guardian policy rules, the
minimal construction layer represents only `45/84 = 53.6%` of unique per-rule
construction feature requirements. `15/16` rules lose at least one annotated
feature and the remaining rule has an unresolved concept, so **0/16 pass the
frozen gold audit gate**. This is an evaluation audit, not an automatic runtime
eligibility signal. The
mean finite outer width is `167.2`, maximum `1536`: width is not yet the limiting
factor; missing meaning is.

On the 19-row error-heavy diagnostic, keeping only the existing exact routes
gives strict results on `3/19 = 15.8%`, with `0/3` confident wrong. It abstains on
`7/10` manually invariant rows and on all 11 old FP/FN rows. This is a safety
improvement only by severe abstention, not a quality improvement. No production
or contest label changed, and full validation was deliberately not run.

Machine-readable evidence: [benchmark](../experiments/v9_outer_semantics_benchmark.json),
[result](v9_outer_semantics_result.json), [PlantUML](12_v9_outer_semantics.puml).

Reproduce the offline result without any model API:

```powershell
python scripts/benchmark_outer_semantics.py
pytest -q
```

## Mathematical contract

Let `theta` choose semantic structure and bindings, and `w` complete missing
trace facts. The candidate represents a finite approximation

```text
Omega_outer = {(theta, w) | Completion(U, theta)
                            and Observations(trace, w)
                            and HardConstraints(theta, w)}
Phi_working subset-of Phi_outer
```

Only `EXACT` and `VERIFIED_DERIVATION` exclusions constrain `Phi_outer`.
Heuristics and LLM preferences may order or narrow `Phi_working`, never the
strict proof universe.

For violation predicate `V` and outer constraint `K`:

```text
Q1 = K and V
Q0 = K and not V
```

| Q1 | Q0 | Internal result |
|---|---|---|
| SAT | UNSAT | `PROVED_VIOLATION` |
| UNSAT | SAT | `PROVED_NO_VIOLATION` |
| SAT | SAT | `UNRESOLVED`, with opposite witnesses |
| UNSAT | UNSAT | `EMPTY_SPACE`, never compliance |
| UNKNOWN | any | `COMPUTATION_UNRESOLVED` |

The prototype enumerates the bounded finite space rather than adding an SMT
dependency. It implements the same two satisfiability questions. This proves an
invariant only relative to the represented outer. It does not prove the crucial
language-side premise `Omega_human-admissible subset-of Omega_outer`.

This distinction follows the useful parts of MRS—flat elementary predications,
explicit handles and unresolved scope—without adopting a complete grammar
([Copestake et al.](https://www.cl.cam.ac.uk/~aac10/papers/newmrs.pdf)). Hole
semantics motivates constraints between fragments, but a general dominance
engine is unnecessary while our actual failure is construction recall
([Koller et al.](https://aclanthology.org/E03-1024/)). Certain-answer semantics
provides the possible-world reading for missing trace facts
([Libkin](https://homepages.inf.ed.ac.uk/libkin/papers/aij.pdf)); abstract
interpretation motivates returning a conservative set of outcomes when precision
is lost ([Cousot & Cousot](https://www.di.ens.fr/~cousot/COUSOTpapers/POPL77.shtml)).

## Why the previous architecture is insufficient

The old path commits to one AST before verification. Typed slots can preserve
`field in {arrival, departure}` or `operator in {>, >=}`, but cannot recover an
exception, negation scope, condition direction, quantifier or whole clause that
never became a node. The V8 live sentinel demonstrated the danger directly:
strict typed output accepted one translation and that sole accepted translation
was false-verified. A perfect downstream solver would only make that wrong
translation look more authoritative.

The V9 split is:

```text
text -> semantic concepts + obligations -> structural holes
     -> Phi_outer -> invariant evaluator
```

Every detected construction must end as `FORMALIZED`, `HOLE`, `RESIDUAL`, or
`UNSUPPORTED`; every formal node must cite an obligation. Token coverage alone
is explicitly not treated as semantic coverage.

## Real benchmark and taxonomy

The row benchmark contains all 11 residual label errors after V7, five
correct-label/reason-or-binding controls, and three successful exact controls.
All 86 half-open source intervals were checked against `valid.parquet` and are
in bounds. Labels, baseline status and expected invariant are evaluation-only
and are never inputs to a translator or judge.

The 19 cases cover:

- entity/date scope, versioned state and stale intent;
- semantic field binding and missing concepts;
- temporal filter/anchor and scoped date comparison;
- lost conditions, `IF`/`ONLY IF`, exceptions and negation;
- quantifier/cardinality and positional array binding;
- catalog incompleteness and absence-as-false;
- structured standards and correct-label/wrong-reason cases;
- action-cardinality and expired-contract exact controls.

A critical annotation result is that only one of the six current FNs
(`airline__7::t6`) has a clearly invariant hard violation from already available
facts. Five other FNs should remain `UNRESOLVED`; forcing all six toward their
binary reference would be label-shaped narrowing of the outer.

## Prototype inventory

Implemented in `underspecified_semantics.py`:

- semantic concepts before schema binding, including arrival/departure roles;
- `UNBOUND_CONCEPT` instead of nearest same-typed field substitution;
- source-grounded translation obligations;
- value, binding, subtree and whole-rule/residual holes;
- finite `Phi_outer` and ranked `Phi_working`;
- exclusions with source, contract, assumptions, assurance and dependencies;
- reversible exclusions;
- two-query invariant evaluator with two witnesses;
- coverage-gated strict solver;
- information-insufficiency witness;
- hard/structured/open-textured standard classification;
- structured factors, residual invariance and counterfactual sensitivity.

The controlled adapter and independent test layer are in
`semantic_feature_adapter.py` and `semantic_metamorphic.py`. The 15 pairs cover
arrival/departure, before/after, strict/inclusive boundaries, cardinality,
may/must, all/some, if/only-if, exception add/remove, active/passive, explicit
name/pronoun, ambiguous pronoun, stale-state insertion and distractor fields.
This follows CheckList's behavioral-test principle, but the `15/15` is explicitly
not natural-language accuracy evidence
([Ribeiro et al.](https://aclanthology.org/2020.acl-main.442/)). Typed holes are
inspired by partial programs, but Guardian evaluates all retained completions
rather than synthesizing one preferred completion
([Solar-Lezama et al.](https://people.csail.mit.edu/asolar/papers/asplos06-final.pdf)).

## Experiments

### Real policy constructions

| Measure | Result |
|---|---:|
| Rules | 16 |
| Unique per-rule feature requirements | 84 |
| Represented feature requirements | 45 |
| Formalization feature coverage | 53.6% |
| Rules with no missing annotated construction | 1/16 |
| Frozen gold audit gate passed | 0/16 |
| Automatic strict verdicts from the new semantic path | 0 |
| Outer width, mean / max | 167.2 / 1536 |

This set-based metric counts each feature tag at most once per rule; it does not
measure occurrence-level attachment, arguments or source-grounded obligation
coverage. Most frequent losses were implicit/universal `ALL` (8), `ONLY_IF` (7), implicit
`MUST` (6), cardinality (5) and inclusive `LE` (4). These failures are systematic,
not row-specific. They show why a lexical registry cannot be the sole
construction view.

The two required known controls also fail automatic reproduction:

- action cardinality loses `COUNT`, `LE` and universal scope;
- expired-contract exception keeps negation/exception/entity hints but loses the
  normalized `IS_PAST` relation and implicit prohibition modality.

Therefore existing exact checks stay unchanged and authoritative.

### Missing concept and information insufficiency

With only `departure_time` available, `arrive after 18:00` remains
`UNBOUND_CONCEPT`; it is not rebound to departure. A finite witness contains two
worlds with identical observable projection `{departure_time: 17:00}` but
opposite outcomes because unobserved arrival is `19:00` versus `16:00`. The
catalog is therefore insufficient for a deterministic verdict.

### Residual and structured standard

- `HardViolation OR Residual` is invariantly violating when the hard core is
  true.
- A result equal to the residual is `UNRESOLVED`.
- A structured preference standard is violating only when all four positive
  factors are established and neither hard constraint nor explained override
  applies.
- An explained override alone returns `NO_EXPLICIT_VIOLATION_FOUND`, not proved
  compliance: the toy factor function has no policy contract establishing that
  the override is authorized or adequate.
- Removing `feasible_alternative` makes the result `UNRESOLVED`; flipping it
  changes the decision, so the explanation is counterfactually sensitive.

The prototype deliberately does not force every rule into
`FormalCore AND Residual`: the connective itself can require a structural hole.
Precedent matching is not implemented because this frozen policy slice contains
no independently labelled precedent set. Adding similarity RAG would not test
material differences and is rejected for this cycle.

## A/B/C/D/E comparison

The rows below have different evidence scopes and must not be read as one common
leaderboard.

| Branch | Evidence | Result | Decision |
|---|---|---|---|
| A — production | Full 46-row V7 replay | TP 17, FP 5, FN 6, TN 18, F1 0.7556 | Keep current baseline |
| B — free formalization | V8 network-limited 4-rule sentinel, 12 attempted calls | 4 valid, 3 accepted; 1 false-verified; 1/12 semantic-correct | Reject as proof path |
| C — typed slots | Same sentinel, strict schema | 6 valid, 1 accepted; accepted item false-verified; 1/12 semantic-correct | Keep only as diagnostic baseline |
| D — obligations/holes/outer | 16 real rules + 19 row audit, offline | 53.6% unique feature recall; 0/16 pass the gold audit; 0 automatic new semantic strict verdicts; 3/19 exact-only determinate | Keep kernel, reject integration |
| E — D + metamorphic | Same D result plus independent controlled suite | 15/15 controlled pairs, no additional real strict row | Keep as test gate, not a classifier |

Provider failures and the different sample mean B/C numbers are not comparable
to full-row F1. No new model call was needed for the V9 decision.

## Invariance, uncertainty and changed rows

Manual outer annotations on the 19-row diagnostic contain 8 invariant
violations, 2 invariant non-violations and 9 unresolved cases. If every baseline
binary answer is provisionally treated as a strict decision, only 7/19 are
invariant under those annotations; 12/19 are either opposite or collapse a
genuine ambiguity. This is a diagnostic, not a calibrated baseline confidence
measure.

D/E produce strict results only for the three existing exact controls. Their
confident-wrong rate is `0/3`, while determinacy is `3/19`. They over-abstain on
`7/10` manually invariant cases. All 11 old FP/FN become unresolved, which meets
the literal useful-uncertainty count but is not a useful classifier improvement.

There are 16 internal status changes from binary A decisions to shadow
`UNRESOLVED`; contest predictions changed: zero. A full-validation F1 was not
computed because the small benchmark failed the predeclared coverage and
determinacy gates.

## Mechanism decisions

| Mechanism | Decision | Evidence / next condition |
|---|---|---|
| Finite outer + supervaluation | KEEP kernel | Correct monotonicity and witnesses; conditional on coverage |
| `Phi_working` split | KEEP | Heuristics no longer narrow strict universe |
| Obligations + provenance | KEEP as audit | Exposes losses; discovered coverage is not semantic completeness |
| Semantic concept before schema | KEEP | Prevents arrival→departure forced binding |
| Value/binding/subtree/whole holes | KEEP | Necessary safety escape; correlate repeated choices next |
| Lexical construction registry | REJECT as sole translator | 53.6% unique feature recall, 0/16 pass gold audit |
| General MRS/dominance/VSA engine | REJECT now | Width is manageable; recall fails first |
| Metamorphic suite | KEEP test gate | 15/15 controlled; add held-out generated templates and real paraphrases |
| Residual invariance | KEEP | Hard result can bypass residual; connective must also remain uncertain |
| Structured factors/counterfactual | KEEP experiment | Works on controlled example; needs real annotated standards |
| Precedent similarity | REJECT now | No precedent corpus or material-difference labels |
| LLM/API outer proposals | NEXT, shadow only | Add diverse views after obligations are frozen; LLM cannot exclude outer |
| Full validation / production integration | REJECT this cycle | Small-slice stop condition triggered |

## Next experiment

Do not enlarge the ontology or add row-specific patterns. The next highest-value
test is a **two-view construction recall experiment**:

1. Freeze obligations on held-out policy clauses, including paraphrases of the
   16 rules.
2. Add one syntax/scope view for implicit modality, cardinality and
   `IF`/`ONLY_IF`, plus one event/entity-state view.
3. Union newly detected obligations into a packed outer; disagreement widens or
   creates a whole-rule residual.
4. Add occurrence/argument/attachment-level gold, then require at least 90%
   source-grounded obligation recall, zero forced wrong bindings, zero
   metamorphic regressions and exact reproduction of both known controls.
5. Only then add Groq/Gemini as proposal generators in `Phi_working`, with no
   authority to remove an outer reading.
6. Only after that run the 19-row trace compiler and, if its semantic strict
   determinacy materially exceeds 15.8% without confident errors or excessive
   abstention, run all 46 rows.

The main question therefore has a mixed answer: the project now has a general
mechanism that **can preserve represented structural uncertainty and gate strict
verdicts**, but it has not yet built a general mechanism that reliably discovers
all material meanings. The residual risk `phi* not-in Phi_outer` remains high at
the language-to-obligation boundary. That boundary—not a bigger solver, debate,
RLM graph or more model confidence—is the next target.
