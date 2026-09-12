# Claim Graph development extension — fixed comparison

Runner: scripts/evaluate_vnext_claims.py, scorer: scripts/vnext_claim_scoring.py.
Compare only frozen C2 semantics and ten-pass vNext on all 41 frozen extension
cases using the same B.AI qwen3.8-flash transport configuration. This is not another
arm search, nor a comparison to a historical score from a different provider.
Original C2 prompt/schema contract remains unchanged; provider start interval
is ten seconds for both C2 and vNext.

Exact messages/payload/schema hashes are written before requests. Each case and
request is independently durable. Failed tasks never receive hidden retries.
Complete predictions are separately sealed before any metric/gold join.
Quota rules are shared across both arms. Schema reliability is reported per arm.

Report raw verifiability-disposition span detection separately from final typed
UNKNOWN and inventory coverage. Unknown nodes are not silently dropped or counted
as typed semantic success. Score partially annotated cases only on provided fields;
do not invent precision gold or directed relation labels.

C2 provides kind, entity mentions and source. It does not provide actor, predicate,
object, polarity, modality or semantic time anchors. These unavailable fields are
NOT_MEASURED, never fake zero accuracies. Only genuinely paired shared fields enter
the mean gain gate; new-field accuracy and causal semantics are separately reported.
An unqualified verifiable C2 UNSPECIFIED source is deterministically the candidate
ASSISTANT speaker, not an authority or proof of the claim.

Response-only extension unsupported-claim recall and binding identity correctness
remain NOT_ESTABLISHED without contextual gold. The old 209-span dataset is needed
for unsupported-claim regression; it is not new blind evidence.
Run, audit all failures, then propose any new-version repair. No post-result
replacement of v1 scores or benchmark annotations is permitted.
