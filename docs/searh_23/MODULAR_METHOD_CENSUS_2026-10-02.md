# Modular Steps 2–4 — method status census (living document)

Started 2026-10-02 from checkpoint 744fc0c0 (continuation assignment);
current session HEAD 9f17fd84. Statuses follow the assignment vocabulary
(NOT_RUN / IMPLEMENTED / NATIVE_SMOKE / PILOT_PARTIAL / PILOT_COMPLETE /
E2E_COMPLETE / BLOCKED / NOT_SELECTED). Numbers below were independently
re-verified against outputs by the code_auditor (AUDIT-1, R-009: all
spot-checked report numbers match the artifacts).

| Method | Status | Valid decisions | What remains | Continuation |
|---|---|---|---|---|
| C0 frozen R0 (structural v0.2 → judge → reviewer) | PILOT_COMPLETE (dev-pilot 48) | TP25/FP3/FN1/TN19, F1 .9259 | nothing for dev; paired comparison on new dev | `negative_routing.py` replay paths |
| G1 old graph summary | PILOT_PARTIAL | 2 completed cases | paired 6-case run incl. INVALID/missing | mechanism_pilots graph arms |
| G2 selected graph context | PILOT_PARTIAL | 2 completed cases | same paired set; typed binding now fixed (1d9908c7) | mechanism_pilots graph arms |
| G2-linear same facts linear text | PILOT_PARTIAL | 1 case (429-partial on second) | re-run paired after §5 breaker in place | mechanism_pilots graph arms |
| G3 bounded read-only graph queries | PILOT_PARTIAL | 1 case | paired set; GraphAPI now reports matched fields + ambiguity | mechanism_pilots G3 |
| M1 LLM→IR → Steps 2–4 | IMPLEMENTED (SystemV2 call/result fix verified) | oracle probes only | end-to-end dev measurement | modular_runtime profiles |
| M2 CCG→semantics→inference | PILOT_PARTIAL | 16/27 sentences parse; semantic audit done; native inference bounded | bounded correction + counterexamples only-if/unless/modality | ccg_pilot.py / ccg_recovery.py |
| M3 formal channel + fallback w/ coverage | IMPLEMENTED (advisory shadow frozen) | formal coverage scored separately | verdict-level paired dev | formal shadow runner |
| A1 atomization + B | NATIVE_SMOKE | claim bank isolated | end-to-end with real atomization + retrieval | native_claim_pilot.py |
| A2 MiniCheck (native port) | PILOT_COMPLETE (bank 15/15, acc .867) | fixed 6-claim bank 6/6 | nothing for dev bank | native adapters |
| A3 FactCG (native) | PILOT_COMPLETE (bank 15/15, acc .667; fixed 6-claim bank 6/6 scored) | new claims 0.5169 / 0.9272; paired-input layer unchanged | nothing for dev bank | native adapters |
| A4 atomic audit of Guardian explanation | IMPLEMENTED | — | dev measurement | modular profiles |
| U1 SelfCheck-NLI | PILOT_PARTIAL | 1 recovery case (agreement 1.0, entropy 0) | k=3 bank, routing vs random same-fraction control | selfcheck pilot |
| U2 semantic uncertainty (SEP) | NOT_RUN | — | needs hidden states + trained probe (API cannot provide) | BLOCKED-by-design note in docs |
| T1 RAG-Triad (+coverage) | PILOT_PARTIAL | 1 case raw/G2 (G2-linear 429-partial) | paired raw/G2/G2-linear, target vs explanation | trulens adapter |
| R1 negative-decision routing (strict/always/adaptive/random) | PILOT_COMPLETE (dev 48×4 arms, shared B) | baseline reproduces C0 (TP25/FP3/FN1/TN19 F1 .9259); always TP26/FP21/FN0 F1 .7123; adaptive AND random TP26/FP8/FN0 F1 .8667 from different sets (overlap = known FN only); known FN repaired by valid B verdict (review_additional_error); B flags additional error on 6/6 reviewed NO_ERROR per arm | honest negative: adaptive ≡ random at equal query fraction on dev; B precision on clean NO_ERROR governs | negative_review_pilot_v4 + score_negative_arms.py |
| Native Granite BYOC advisory | NATIVE_SMOKE (acc 1.0 bank, VRAM 15.7G) | 15/15 bank | concrete new-contribution check only | advisory arms |
| Bespoke-7B / PRT-Qwen | BLOCKED:disk (measured, ~15GB each) | — | unchanged protocol decision | — |
| Service /v1/check + batch + CLI | E2E_COMPLETE (archived inputs, UNKNOWN>12k, replay-recovery) | 4 archived receipts | real backend outage recovery test (not mock) | remote_service.py |

## Session deltas (2026-10-02, this continuation)

- 24abf256: aihorde provider + new-channel receipts (glm-5.3-flash 402-blocked;
  nemotron-3-*, gpt-oss:120b confirmed; family accounting preserved).
- 1d9908c7: §4.1/R-001 typed entity binding fixed — 96/96 frozen dev fact
  selections identical to the previous implementation (latent defect closed,
  published numbers stand); 9 offline tests.
- dbd99967 + 9f17fd84: §5 economy layer — circuit breaker (endpoint+slot+
  model), dev2 phase ceilings (300 attempts / 1M known / 200k unknown upper
  bound, legacy counter NOT reset), exactly-once finalize, classified
  transport statuses, one-retry default; live 402 validation: veto with zero
  transport attempts. 7 offline tests + 16/16 boundaries unchanged.
- 4f978cdf: three user-reported economy fixes — runner dev2 phase wiring
  (budget_phase(); pilot never implicit), atomic single post-cooldown probe
  admission (PROBING claim via BEGIN IMMEDIATE, inherited cycles, transient
  release), in-flight RESERVED api rows in the unknown ceiling; 12/12
  offline tests; frozen negative-pilot identity d41f244f unchanged.
- 87182e5c + runs: §7.A closed with 0 new API (FactCG bank 6/6 + V2
  proposals replay SUCCEEDED 4/4, 15 archived answers re-served, 13
  journaled failures reproduced); §7.C closed on dev2 (48 shared-B mistral
  queries, 192/192 decisions, 53 attempts / 92381 logical / 91339 known
  tokens; verdict scoring in negative_review_pilot_v4/arm_scoring.json).

## Next in queue (assignment §7 order)

A. DONE 2026-10-02 (0 new API: FactCG 6/6, V2 replay 4/4; IR/CCG semantic
audit already covered by M2 census row) →
B. paired graph/atomization pilots (same cases, INVALID/missing explicit) →
C. DONE 2026-10-02 (frozen negative-routing B-run on dev2; arm_scoring.json;
temporal-calculation assistant check remains open within C scope) →
D. automatic Steps 2–4 + bounded CCG pilot → E. SelfCheck/RAG-Triad
completion → F. long-bank quality.

Sealed: NOT started; shortlist freeze + budget forecast required first.
Default service config R0 unchanged.
