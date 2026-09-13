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
changing a source premise changes it. Five local tests cover all 36 projections,
gold isolation, replacement permission, event order and unknown-field rejection.

The `authorization_universe_closed_by_system` field is a controlled fixture
premise only: its false value follows the explicit `open_permission` replacement
source. Capability metadata is **not** a real provider schema, T1 contract or
business-effect observation. An `ATTEMPT_FORBIDDEN` fixture annotation must not
independently override the replacement SYSTEM permission text. The v3 frontend
and independent checker still need to establish applicability and preserve
unknown meaning/guards. No model request or v3 outcome is claimed here.
