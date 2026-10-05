# Method fit (integrated v1)

The candidate list and its limits come from `docs/integration_handoff_20261005/METHOD_FIT.md`. This file maps only the mechanisms actually used.

| Mechanism | Primary source | Our error addressed | What the original assumes / we lack | Minimal adapter | Comparator | Cost | Failure controls |
|---|---|---|---|---|---|---|---|
| Conditional verification pass (A4) | Self-RAG (arXiv 2310.11511): adaptive retrieval and critique with **trained** reflection tokens | Earlier phases: misses were verification failures with the evidence already present (SYN: 22/23 positives had the evidence inside the packet) | Self-RAG trains a critic; we use prompt-only, one pass, no new retrieval except the relation-cited spans. **This is not a Self-RAG reproduction** | Frozen trigger (UNKNOWN, or NO_ERROR + decisive fact); checklist = decisive facts + earlier open questions | A3 (same run, no pass); historical fixed second pass D1/D2 (multipacket: no gain) | ≤1 call per triggered row | Never on technical failure; a rejected pass falls back; prompt: "unresolved item alone is not a violation" |
| Separate citation/support accounting | ALCE (arXiv 2305.14627) | Correct label with a wrong cause | ALCE scores QA citations; it does not establish normative applicability | Cause judge (SAME/PARTIAL/DIFFERENT vs gold explanation); guard-owned TPs counted apart | Same judge prompt as earlier phases | 1 judge call per predicted-ERROR positive | A judge verdict is not source proof; reported as such |
| Source-boundary handling | AgentDojo (prompt-injection suite) | Role markers inside bodies (D4) | AgentDojo measures attack success; we only flag framing ambiguity | `AMBIGUOUS_ROLE_HEADER_IN_BODY` gap | — | 0 | Not a policy-violation metric; not run as a suite |

Not adopted:
- τ-bench / τ²: new realistic traces would need independent per-turn annotation and an overlap check against valid46. That is out of scope for this phase, so no new external holdout exists.
- Oracle relation arms (retrieval/norms/joins/closure): not run. The previous phase already showed that the evidence is present in the packet for most misses, so the open question is model verification, which A3/A4 test directly. An oracle relation upper bound would need hand-authored gold relations per FN on development data.
