# Source-covered policy normalization probe — 2026-09-26

## Frozen protocol

Commit `75ce0c9` froze three 12-case policy-language suites before Mistral
inference. The target tools and histories are inherited from the authored
repair controls; only the prose policy changes. `until_latest` and
`permission` have six valid and six invalid current calls each.
`extra_supervisor` adds a separately stated supervisor-approval prerequisite,
making eight current replacement/audit calls invalid and four valid.

One Mistral API call per unique policy proposed canonical source-bullet
translations, without histories or labels. Code required one response entry
and exact source quote per bullet; an unsupported bullet remained visible in
the compiled policy. The frozen micrograph then attempted to decide each
target call. No full benchmark or GPU inference ran.

| Policy suite | Mistral calls | TP | FP | FN | TN | UNKNOWN positive | UNKNOWN negative |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| until_latest | 1 | 0 | 0 | 0 | 0 | 6 | 6 |
| permission | 1 | 0 | 0 | 0 | 0 | 6 | 6 |
| extra_supervisor | 1 | 0 | 0 | 0 | 0 | 8 | 4 |

All three model responses were complete JSON with exact source quotes.
**Coverage was still zero.** This is an applicability/translation failure,
not a failed API call. The deterministic validator prevented unsupported
translations from becoming false `SAFE` decisions. Those 36 unknowns are not
binary contest gains.

## Why normalization failed

- `until_latest`: Mistral preserved same-case and latest-result meaning, but
  omitted the template's second sentence from its first canonical bullet.
  The exact narrow grammar rejected it. This looks like a format/coverage
  mismatch; accepting it safely requires a separate parser change and an
  independent test.
- `permission`: the first bullet was transformed from a rule governing
  **device replacement** into a rule governing **approval of device
  replacement**. It also inserted Markdown emphasis and a different
  grammatical shape for the audit condition. Stripping Markdown would not
  repair the changed trigger.
- `extra_supervisor`: Mistral converted “obtain supervisor's approval” into
  “check that supervisor approval is granted.” This might preserve the
  prerequisite **if** an authoritative same-case result proves that approval
  was actually granted. A check call alone does not prove it, and the
  translation supplied no provenance contract. The current grammar rejected
  the multiline topic and Markdown, so this did not create a false `SAFE` in
  the replay. A looser parser without provenance would be unsafe.

The prompt exposed only generic templates, not the repair-domain canonical
sentences or the extra supervisor condition. Tool descriptions were not shown
to the model in this policy-only translation stage. This experiment therefore
does not test action binding using the declared tool catalog. The hard-coded
critical-word/recency guard is a limited regression check, not semantic proof.

An independent audit also found three **constructed false-SAFE
counterexamples** against the prior local certificate: dropping an unlisted
second condition while preserving the source quote, binding a `customer`
requirement to `case_id`, and accepting successful processing of a
*replacement request* as an actual replacement. The last two were fixed by
exact policy-entity keys and stricter effect-tool recognition. Model-produced
canonical text is now diagnostic only: absent exact source equivalence, it
cannot authorize a `SAFE` decision. These in-memory probes are not original
Mistral results or new competition cases.

## Clause-to-tool roles, original wording retained

The next diagnostic kept each original bullet verbatim and showed short
declared tool descriptions. Gold role rows were frozen before inference in
`policy_scope_expected_v1.json`. One Mistral API call per policy returned the
governed current-call tools, prior-result evidence tools, and temporal role.
All seven bullet entries were source-exact and valid JSON; only **5/7 roles
were exact**: `until_latest` 2/2, `permission` 1/2, `extra_supervisor` 2/3.

The permission wording omitted `replace_device` from the governed tools even
though the bullet explicitly constrains replacement. The extra-supervisor
wording omitted `replace_device` as prior evidence for an audit, though it
correctly identified replacement as governed by the supervisor condition.
Source-quote coverage therefore does not establish semantic coverage.

After observing those errors, we froze a narrower post-hoc pairwise prompt
at `e2b58f7`: one API call per policy-bullet/tool pair, with separate
`governs_current_call` and `result_can_establish_prerequisite` Booleans. It
produced 28 valid JSON answers but only **22/28 correct action roles and 20/28
correct evidence roles**. Per suite: `until_latest` 5/8 and 6/8;
`permission` 6/8 and 5/8; `extra_supervisor` 11/12 and 9/12. The pairwise
prompt missed `replace_device` as the governed replacement action in two
policies and confused audit with its prerequisite in other rows. This is a
development diagnostic shaped after a seen failure, not an independent
holdout or a binary Guardian evaluation. Raw responses and sealed scores are
under `outputs/searh_23/policy_language_v1/`.

## Decision

Do not promote either the canonical-language translation or these role
extractors. The canonical parser has zero coverage on the 36 new-wording
cases. The two role extractors have nonzero semantic errors, including omitted
governing actions that would be dangerous in a permissive certificate. The
micrograph remains useful only after its action, entity, condition, and
evidence roles are independently established. A credible next gate needs
typed source atoms, adversarial clauses with two simultaneous conditions,
request-versus-perform tools, distinct entity IDs, stale results, and an
unseen policy/domain holdout. Any unproved atom must leave the result UNKNOWN.
No binary entry-point decision changed here.

Reproduce the local scoring with
`python experiments/searh_23/policy_compile_probe_v1.py score until_latest`
and the other two suite names. Frozen inputs, raw Mistral translations,
prediction seals, and per-case reports are under
`outputs/searh_23/policy_language_v1/`.
