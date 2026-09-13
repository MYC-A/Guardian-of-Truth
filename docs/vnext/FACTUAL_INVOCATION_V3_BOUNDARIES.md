# Value-aware, indexed factual invocation v3

`analyze_factual_fields` now runs one actual chain with an explicit backend:

`original source -> role-preserving normalizer -> C2 Claim Graph -> indexed
identity/result candidates -> narrow field meaning -> typed scalar proofs ->
independent source/evidence receipt`

This is a reusable factual-evidence layer for the eventual joint Core, not a
replacement for the required policy/goal/claim/effect-world composition.

The extra semantic pass chooses deterministic target JSON literal IDs and actual
source record-field IDs. It generates neither offsets nor facts. The model sees
field names, not the result values it is meant to check. Numeric, Boolean, string,
null and structural JSON values remain distinct; quoted `"42"` is not numeric
`42`. Nonliteral values, conversions and unsupported meanings remain unknown.
Undefined units/scale or natural-language conversions are not certified by an
exact JSON-field comparison.

Actual source declarations establish record layout, stable ID namespace/type
and aliases. They are application/source metadata, never LLM-generated T1.
Candidate lookup uses name and stable-ID indexes. All compatible declared
identities and result events are retained, not top-k or a convenient latest row.
Different entities' values are never flattened together. Incomplete source,
missing identities/fields, different candidate values and unresolved material
meaning remain explicit. The layer supports positive, unspecific-past
TOOL-result attribution; dates, NOW/freshness and ungrounded event references
remain TIME_UNBOUND rather than being inferred from equal field values.
current state, completion, causality, negative attribution and other kinds are
retained as unsupported/unknown rather than given the same proof requirements.
Non-verifiable spans retain their original disposition without becoming a
spurious untyped-material failure.

The new normalizer preserves the target's ASSISTANT provenance: embedded USER,
SYSTEM and TOOL-result markers cannot become privileged events or effects.
Candidate ASSISTANT invocation serialization remains an attempted action only.
Original history USER/ASSISTANT call roles remain distinct. This does not
authenticate arbitrary raw transcripts or solve ambiguous/unescaped delimiters
inside source history; an authoritative structured source adapter is still needed.
The frozen older Goal/T2/Policy model versions do not use this new normalizer.

The independent checker reconstructs the original source, deterministic response
inventory, literal values, declared identity records and compatible query set.
It rechecks actual field primitives and rejects omitted alternatives, changed
expected values, modified completeness, changed proof scope and role/kind
substitution. Its lookup tables are rebuilt independently; it imports neither
the semantic backend nor the binding builder/solver. Receipts contain source and
evidence hashes plus explicit conditional/scope assumptions, **no Core status**.
An agreement value is conditional evidence under retained mappings, not proof
of unrestricted NL meaning or full safety. Existing certificate formats are not
silently widened to accept these new primitives.

Fifty-five controlled tests cover the new invocation/binding/checker/role/time behavior,
including 2000 records with a one-record indexed candidate lookup. Full project
verification at this checkpoint: `python -m pytest -q`, 1114 passed. These are
unit/runtime checks, not a frozen model benchmark or end-to-end improvement.

Remaining: attach the independently checked field primitives to the joint Core
certificate/problem format; add state freshness, units/nonliteral value and
negative-attribution lowering under real source semantics; connect native Goal
and direct Policy programs; complete frozen stage/regression/ablation/blind
evaluations. No blind labels were read and nothing is promoted.
