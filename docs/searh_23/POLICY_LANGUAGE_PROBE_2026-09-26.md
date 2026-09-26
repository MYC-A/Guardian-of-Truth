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

## Decision

Do not promote the canonical-language translation path. The model sometimes
changes the action governed by a rule, while the current exact parser has no
useful coverage on new wording. The next experiment should classify each
source bullet *against declared tool effects* without rewriting the original
policy text. Keep exact source bullet IDs and test read/check versus mutation
as a contrastive pair. The output must still be checked against the source,
and unsupported or contradictory classifications must abstain. A changed
binary label needs untouched policy-language controls.

Reproduce the local scoring with
`python experiments/searh_23/policy_compile_probe_v1.py score until_latest`
and the other two suite names. Frozen inputs, raw Mistral translations,
prediction seals, and per-case reports are under
`outputs/searh_23/policy_language_v1/`.
