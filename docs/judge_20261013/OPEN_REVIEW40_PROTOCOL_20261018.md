# Frozen candidate: open answer audit + MAX .40

Base b3316b0ddeb1da1bc59f210c98967fbed427260c, 2026-10-18.
Owner reports previous 6q MAX .30: F1 .45578, precision .40854, recall .51538.
Platform logs, row predictions, real per-key coverage and run time unavailable.
Those scores do not establish six-question delivery or a failure cause.

Owner authorized open review plus .40 in one submission, then explicitly rejected
replacement/fallback of useful scores and requested the same MAX behavior as 6q.
No new candidate model output has been observed. Fixed profile:
submission/JUDGE_OPEN_REVIEW40.json. ReviewContent answer_audit, open, per_chunk,
review_ranking max_exact, quota .40. No blind, six questions, voting or trained weights.

Per row max of all available exact overall and exact final log-odds. One final
failure or duplicate invalidates only that final row. Never average, substitute
NO, drop other rows, or globally revert a completed final. A lower final cannot
erase a higher overall, including an overall false alarm. Different prompt
calibration is unmeasured. Final-only rows are eligible even without primary score.
The hard findings and scored-row quota accounting are unchanged.

Primary snapshots are durable and integrity checked before each review portion.
The audit addresses actual source spans (including the shown response), not gold,
baseline score, model label or a rebuilt context. It examines material actions,
fact binding, applicable rules, exceptions/counterevidence and unknowns. At most
3 compact checks, each field <=160 characters, max3refs; max384 generated tokens.
No prepass verdict. Invalid/truncated notes are excluded without model retries.
Final uses original source, optional MODEL_HYPOTHESIS and existing checklist.

One pinned Qwen/vLLM engine, same runtime/model identity as previous MAX. Input
reserve2048, generation384 at T0/top_p1/seed0, scoring1token T1/seed0/exact probe.
Window49152, seq64, batchedtokens16384, memory.90, APC/chunked prefill enabled,
chunk16. No result cache. Deadlines1380/1530/1680/1800 unchanged. Review per chunk
reserves remaining primary input tokens using observed primary throughput (initial
6000tokens/s planning prior). Review admission counts actual prepared input tokens
and reserved generated tokens, then projects from observed stage tokens/wall;
before those exist, prior3x measured primary wall adjusted for input length is
a heuristic, not a measurement of generation throughput. Error retries
and health probes are existing deadline-aware generate_rows behavior. External
supervisor still terminates in-flight work at kill time. No GPU throughput claim.

Compare all-row platform F1/P/R with .45578, retaining the previous artifact.
No independent/grouped quality CI can be computed from one aggregate result.
EXPLORATORY: leaderboard-informed combination, not independent proof of gain.
Report exact/model coverage, valid/truncated/delivered notes, actual score source,
tokens/wall/cache availability, trimming and configuration in durable local receipts.
CPU/fake model tests prove wiring only. Quality verdict INSUFFICIENT_EVIDENCE
until measured, GPU_UNTESTED/NOT_EXECUTED for real candidate metrics/time/VRAM.
