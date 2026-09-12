# Policy Semantics V2

The Cycle 2 benchmark freezes 104 `Natural Language Policy → meaning` cases in
`outputs/cycle2/policy_cases.json`. It contains four variants for each of 24
required semantic families plus two incumbent-control families: an external
fragment or controlled seed, a minimal pair, a paraphrase, and a long-distance
formulation.

The external fragments are regression seeds copied from the policy regions of
`valid.parquet`; neither task labels nor reference explanations were read by the
builder. They do not make the benchmark an independent end-to-end test. The
remaining variants are manually curated or controlled compositions and are
identified as such in every case.

## Three independent scoring levels

1. **Structural accuracy** scores modality, actor, regulated kind, facet,
   relation, typed target clauses, condition, exception, temporal, identity,
   provenance, and quantification separately.
2. **Behavioral semantic accuracy** executes a candidate program on at least
   four frozen distinguishing worlds per case. This is the primary semantic
   metric.
3. **Exact representation** compares the full structure and normalized program
   as a diagnostic only.

Programs contain violation and permission clauses over a case-local catalog of
ground atoms. Negated literals begin with `!`. A violation clause has priority;
otherwise a matching permission clause yields `PERMITTED`, and the default is
`NO_VIOLATION`. Clause and literal order can differ while behavior remains
equivalent, so exact JSON equality is not required for semantic success.

The typed IR has explicit OR-of-AND target clauses. A generic deterministic
compiler combines them with condition, exception, relation and modality; a
freeze test requires the compiled IR to reproduce every gold world for all 104
cases. The compiler receives neither policy strings nor case identifiers.

The benchmark includes the critical count distinction through worlds where
add/delete operations carry `effect:passenger_count_changed`, while rename does
not. It also includes `only if` direction, exception scope, actor/resource/facet,
BEFORE/AFTER and DURING, stale evidence, provenance, cardinality, entity/source
binding, nested qualifiers, distant definitions/exceptions, and cross-reference.

The builder refuses to overwrite the frozen file. Any post-result change must
create a new version and belongs to a later research cycle.

## Frozen P0/P1/P2 result

TokenHarbor completed all 104 P1 transports and 99/104 P2 transports. P1 yielded
100 schema-valid outputs and 77 behaviorally correct meanings; P2 yielded 93
schema-valid outputs and 61 correct meanings. Thus:

| Arm | Reliability | Conditional semantic quality | Strict operational yield |
|---|---:|---:|---:|
| P0 | 1.0000 | 0.0096 | 0.0096 |
| P1 direct rule | 0.9615 | 0.7700 | 0.7404 |
| P2 typed IR + compiler | 0.8942 | 0.6559 | 0.5865 |

The primary paired comparison contains 90 cases valid in both arms. P1 accuracy
is `0.7778`, P2 accuracy is `0.6556`, and P2−P1 is `−0.1222` with case-bootstrap
95% CI `[−0.2222, −0.0222]`. Discordance is 18 P1-only correct versus 7 P2-only
correct; exact two-sided McNemar `p=0.0433`. Both are correct on 52 cases and both
wrong on 13.

This falsifies the Cycle 2 hypothesis that the current typed intermediate
representation improves policy meaning with this admitted model and frozen
compiler. It does not show that typed IR is universally inferior: P2 is better
on necessary conditions, exceptions, negation scope, and cross-reference, but
loses badly on permission, actor, action-name/effect, temporal definitions,
freshness/provenance, and turn exclusivity. P3 is `NOT ESTABLISHED` because no
second stronger model passed the same gate. No P2 repair is made after observing
these results; candidate fixes belong to the next cycle.
