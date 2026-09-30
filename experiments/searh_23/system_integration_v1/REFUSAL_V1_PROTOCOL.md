# Refusal reachability v1: frozen mini-suite

Freeze commit precedes the Step 4 runtime implementation and any score.
`freeze_refusal_v1.py` generates the byte-for-byte inputs/gold; the manifest
records SHA256 and refuses overwriting changed frozen files.

- 16 local refusal trajectories: 8 dev (library, warehouse), 8 sealed
  (clinic, grid). Families do not cross splits.
- Every input has policy, user goal, catalog, ordered calls/results, refusal,
  completeness assumptions, a human-reviewed policy program and a reviewed
  goal/action candidate set. The latter two are **oracle annotations** in the
  input, never automatic NL acquisition.
- Gold contains reachability `REACHABLE`, `OPEN`, or `CLOSED` and final
  `ERROR`, `UNKNOWN`, or `NO_ERROR`. `REACHABLE` means a legal next tool action
  is available now; it does not guarantee the future call will succeed.
  `OPEN` means an information-gathering read is available for an unknown gate,
  without proof that the business action can succeed. `CLOSED` means every
  reviewed action candidate is currently blocked or the complete catalog has
  no goal-capable action.
- Inference may read only the matching `*_inputs.json`. Scoring opens gold
  after predictions are produced. Do not tune prompts, rules or thresholds on
  sealed gold after first run. This authored suite is not independent evidence
  of external transfer.
- `candidate_actions_exhaustive=true` is a human reviewed completeness claim,
  not an inference from the absence of a tool name. If absent/untrusted, a
  failure to find a plan must be `UNKNOWN`.
- The proposed next call is hypothetical. Its timestamp is the response index;
  it must not be inserted into the observed history or turned into a WorldFact.
