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
   relation, condition, exception, temporal, identity, provenance, and
   quantification separately.
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

The benchmark includes the critical count distinction through worlds where
add/delete operations carry `effect:passenger_count_changed`, while rename does
not. It also includes `only if` direction, exception scope, actor/resource/facet,
BEFORE/AFTER and DURING, stale evidence, provenance, cardinality, entity/source
binding, nested qualifiers, distant definitions/exceptions, and cross-reference.

The builder refuses to overwrite the frozen file. Any post-result change must
create a new version and belongs to a later research cycle.
