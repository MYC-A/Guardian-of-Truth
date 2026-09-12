# External step dataset audit

## Source and pin

- Repository: `Alkur123/agentic-redteam-benchmark`
- Pinned commit: `12ddc82333e5df3581341493df4513a24cfc61bb`
- Upstream validator result at that commit: `2288/2288 samples valid`
- Source-declared composition: 513 `gold`, 1775 `augmented`
- Data license: CC-BY-4.0

The source is compatible with a target-step Guardian evaluation. Every sample
contains a declared goal, declared plan, ordered trajectory, and
`ground_truth.drift_step`. At that exact index it supplies
`expected_decision_at_drift` (`KILL_SESSION`, `WARN`, or `CONTINUE`), expected
signals, and a rationale. Therefore an adapter can construct
`history prefix + target assistant step -> ERROR/NO_ERROR` without converting a
trajectory reward into a turn label.

## Gold/review audit

The machine-readable tier supports a clean split: 513 records declare or inherit
`gold`; augmented records explicitly carry `tier=augmented` and are excluded.
The repository README describes `gold` as hand-authored and human-reviewed, and
100 records are marked as an IAA subset. However, `metadata.reviewed_by` is empty
for every one of the 2288 released records. Consequently this cycle treats the
data as source-declared step-level gold with a review-provenance limitation, not
as independently verified adjudication.

The source does not ship executable schemas for trajectory tools. The adapter
publishes only source-derived action signatures and explicitly labels them as
not effect documentation. Training-data contamination of the remote model is
also unknown because the public release predates this evaluation but model
training provenance is unavailable.

## Decision

Use a frozen `gold`-tier subset as
`EXTERNAL_INDEPENDENT_STEP_LEVEL_WITH_SOURCE_REVIEW_LIMITATION`. It is eligible
for the main step-level comparison because target localization is explicit and
machine-readable. Any claim depending on human-review quality must retain the
review limitation above. The old trajectory-success evaluation remains only
`EXTERNAL_PROXY_DIAGNOSTIC`.
