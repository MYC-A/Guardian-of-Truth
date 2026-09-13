# Goal/Plan v3 contract kernel — implementation boundary

This new version leaves frozen Goal v2, its 22/22 UNRESOLVED result and Policy
program v1 untouched. The Policy stage was completed, sealed and audited before
implementation of this v3 kernel. The 36 controlled Goal v3 source inputs and
their hashes were also frozen before any v3 candidate execution.

`goal_alignment_records_v3.py` defines source-grounded versioned capabilities,
rule kinds, per-world obligations and certificate records. The separate
`goal_alignment_primitives_v3.py` queries only ordered source events before the
target, checking actor, paired requestor, provider, version, entity, freshness,
commit and completeness. Agent-authored result fields cannot satisfy a guard;
missing results are UNKNOWN external facts, although a complete prefix can prove
omission of a *mandatory qualifying result*. Conflicting qualifying results
remain BOTH. A result can evidence an attempted call without proving its effect.

The controlled adapter `goal_alignment_fixture_contract_v3.py` compiles the
exact pinned SYSTEM fixture premises into generic rules. It recognizes explicit
mandatory verification, unconditional inventory lookup, an exogenous inventory
guard, mandatory cache order, a session-completion deadline and a cancellation
exception. It does not parse arbitrary natural-language policies, accept a
model-proposed contract as trusted, or use case IDs, families or reference labels.
Optional assistant plans create no mandatory-order rule. Multiple read tools
share one goal-compatible path; auxiliary reads remain distinct from direct
status reads.

`goal_alignment_v3.py` evaluates every supplied world. A proved applicable
violation is decisive even if an unrelated rule is UNKNOWN or BOTH; uncertainty
in the *decisive* rule still blocks that witness. NO_ERROR requires closed
authorization, no unresolved material term or due obligation, complete relevant
history and a valid independently checked certificate. An unknown guard does not
become FALSE; a conditional prerequisite already satisfied may make that guard
irrelevant. The checker `goal_alignment_certificate_v3.py` does not import the
solver. It rebinds the pinned source contract, recomputes source primitives and
all rule/world statuses, and rejects dropped/tampered worlds or changed hashes.

Without the pinned trusted fixture replay, the current entry point returns
UNRESOLVED even if its conditional calculations look decisive. This is a
controlled contract mechanism, **not** a general Goal/Plan semantic frontend,
real competition policy interpretation, factual claim check or whole Guardian
Core verdict. A separate grounded LLM proposal/challenger frontend and real
source-authority adapter are still required. The forthcoming 36-case evaluation
will measure only this controlled mechanism, not open-vocabulary generalization.
