# Frozen action-conditioned policy acquisition v1

Frozen on 2026-09-30 before any API calls from this arm. The input, gold,
generation code, prompt, validator, and scorer are committed together. The
query contains the original short policy, one effect-producing tool action,
and the observed predicates documented by the tool catalog. It does not
contain the reviewed policy program. One Mistral call per distinct policy;
same server `MISTRAL_MODEL` and temperature zero throughout the arm.

Dev: six policies from depot, payments, service, records, library, warehouse.
Sealed: two different policies from clinic and grid. These are author-written
synthetic policies, and the condition menu is a strong structured hint. The
experiment tests whether the model can map an action to complete conditions,
exceptions, numeric activation and temporal scope given that hint. It does
not test discovery of all actions in a full natural-language policy.

Score each field separately (required condition IDs, ALL/ANY, exception
pairs, numeric activation, temporal relation), plus exact complete program
and source/schema validity. Preserve all per-case raw answers and usage.
The source quote check is syntactic only; it does not prove the cited clause
entails the chosen predicate. No prediction becomes a `ReviewedProgram`.

Run dev first. No edits to this version after opening sealed gold or results.
Run sealed once. Do not change `scripts/predict.py`. An apparent gain here is
an acquisition hypothesis, not evidence that the complete contest detector
has improved; compare on independently authored policies and full trajectories
before integration.
