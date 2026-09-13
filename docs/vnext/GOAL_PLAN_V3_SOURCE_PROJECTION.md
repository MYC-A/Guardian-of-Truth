# Goal/Plan v3 controlled source boundary

`benchmarks/vnext/goal_alignment_source_adapter_v1.py` projects the 36 frozen
mechanism cases into source-only inputs for a future v3 candidate. It is not a
semantic parser, oracle, solver or proof checker. The original reference
implementation and v2 result remain untouched.

The projection copies explicit USER/SYSTEM fixture text, selected SYSTEM
obligation text, fixture capability metadata, the attempted target action and
ordered source events. It expands event templates deterministically, gives each
event a stable ordinal, and records only the fixture's stated history/session
completeness. Assistant plans remain separate from SYSTEM obligations.

Case ID, family, reference status/alignment and `meaning_universe` annotation
are excluded even when present in the benchmark file. Unknown case fields fail
closed. Changing an answer label leaves the projected input hash unchanged;
changing a source premise changes it. Six local tests cover all 36 projections,
gold isolation, replacement permission, event order and unknown-field rejection.
The 36 per-case input hashes, adapter hash and specification hash are pinned in
`outputs/vnext/goal_alignment_v3_source_projection_v1_freeze.json` before any
v3 inference. This is an input freeze, not a prediction or result seal.

The `authorization_universe_closed_by_system` field is a controlled fixture
premise only: its false value follows the explicit `open_permission` replacement
source. The fixture's `ATTEMPT_FORBIDDEN` reference shorthand is deliberately
reduced to `ACTION_ATTEMPT` in the interface catalog, so it cannot silently
override that replacement SYSTEM text. Capability metadata is **not** a real
provider schema, T1 contract or business-effect observation. The v3 frontend
and independent checker still need to establish applicability and preserve
unknown meaning/guards. No model request or v3 outcome is claimed here.
