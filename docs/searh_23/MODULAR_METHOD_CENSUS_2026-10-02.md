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
| G1 old graph summary | PILOT_COMPLETE (paired 6-case set, 24/24 rows) | TP2/FP0/FN0/TN4 all four graph arms; pairwise decision agreement 6/6 | nothing for this bank; representation economy NOT measured (full prompt forwarded) | `mechanism_pilots.py` graph arms + `score_mechanism_arms.py` |
| G2 selected graph context | PILOT_COMPLETE (same paired set) | TP2/FP0/FN0/TN4 | same | same |
| G2-linear same facts linear text | PILOT_COMPLETE (same paired set) | TP2/FP0/FN0/TN4; shares information_sha256 with G2 within one provenance | same | same |
| G3 bounded read-only graph queries | PILOT_COMPLETE (same paired set) | TP2/FP0/FN0/TN4; ≤4 read-only queries (one legacy row: 0 queries) | same | same |
| M1 LLM→IR → Steps 2–4 | PILOT_COMPLETE (E2E dev, ordinary upstream, 4 cases) | equals archived C0 exactly: TP3/FP0/FN0/TN1, all transitions unchanged | larger bank if shortlisted | `system_v2_pilot.py` + `score_system_v2.py` |
| M2 CCG→semantics→inference | PILOT_COMPLETE (bounded, offline) | corrections 11/11 recovered (7 LEXICAL + 4 lexicalized); counterexamples 19/20 DISTINGUISHED, 0 INSENSITIVE; native Coq BLOCKED (not installed, no lossy bridge) | nothing for bounded scope | `ccg_bounds.py` |
| M3 formal channel + fallback w/ coverage | IMPLEMENTED (advisory shadow frozen) | formal coverage scored separately | verdict-level paired dev | formal shadow runner |
| A1 atomization + B | PILOT_COMPLETE (6/6 rows, honest negative) | atomizer INVALID 4/6 (tool-call targets), verifier MODEL_JUDGED 1/6; ADVISORY_ONLY never auto-promotes | different atomizer prompt would be a new arm | `mechanism_pilots.py` atomic + `score_mechanism_arms.py` |
| A2 MiniCheck (native port) | PILOT_COMPLETE (bank 15/15, acc .867) | fixed 6-claim bank 6/6 | nothing for dev bank | native adapters |
| A3 FactCG (native) | PILOT_COMPLETE (bank 15/15, acc .667; fixed 6-claim bank 6/6 scored) | new claims 0.5169 / 0.9272; paired-input layer unchanged | nothing for dev bank | native adapters |
| A4 atomic audit of Guardian explanation | IMPLEMENTED | — | dev measurement | modular profiles |
| U1 SelfCheck-NLI | PILOT_COMPLETE (bank 3/3, both modes separate) | agreement 1.0, frequency entropy 0; judge-NLI 0.003–0.164; reconstructed-target-NLI 0.58–0.84 (divergence vs surrogate generator, not truth); SEP not claimed | nothing for this bank | `selfcheck_bank.py` |
| U2 semantic uncertainty (SEP) | NOT_RUN | — | needs hidden states + trained probe (API cannot provide) | BLOCKED-by-design note in docs |
| T1 RAG-Triad (+coverage) | PILOT_COMPLETE (3-case bank, paired inputs) | raw/G2/G2-linear × target/explanation × 3 dims; target grounded 2–3/3, explanations score 0–2/3 (diagnostic, not proof) | nothing for this bank | `mechanism_pilots.py` triad + `triad_bank.py` |
| R1 negative-decision routing (strict/always/adaptive/random) | PILOT_COMPLETE (dev 48×4 arms, shared B) | baseline reproduces C0 (TP25/FP3/FN1/TN19 F1 .9259); always TP26/FP21/FN0 F1 .7123; adaptive AND random TP26/FP8/FN0 F1 .8667 from different sets (overlap = known FN only); known FN repaired by valid B verdict (review_additional_error); B flags additional error on 6/6 reviewed NO_ERROR per arm | honest negative: adaptive ≡ random at equal query fraction on dev; B precision on clean NO_ERROR governs | negative_review_pilot_v4 + score_negative_arms.py |
| Temporal-calculation assistant module (typed-ISO-relations) | PILOT_COMPLETE (18-case paired bank: full timezone bank + 10 new boundary cases) | offline ground-truth gate PASS 18/18 (arithmetic exact, spans verbatim, unzoned declined, ADVISORY_ONLY); paired B without/with advisory: 18/18 decisions UNCHANGED (TP6/FP12/FN0 both arms) — honest negative: no B verdict change from the arithmetic advisory; ::02 repaired by B in both arms | nothing for this bank | `temporal_assistant_pilot.py` + `score_temporal_arms.py` |
| Long-bank LLM quality (§7.F) | PILOT_COMPLETE (12-case pre-registered balanced subset) | TP5/FP0/FN1/TN6, F1 .909; exception family 4/4 errors caught at all positions; single FN = version-update family at begin; 12k in-limit OK; two-SYSTEM stress layout flagged | 12001+ stays operational UNKNOWN smoke (existing receipts) | `long_bank_pilot.py` + `score_long_bank.py` |
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

## Session deltas (2026-10-02, §7 B–F continuation, pin 8b2bdf11)

- §7.B graph arms completed on dev2 (resume, 18 new rows): 24/24 paired
  rows, all four arms TP2/FP0/FN0/TN4 with 6/6 pairwise agreement;
  INVALID B preserved on two legacy rows (dev_latest::00 G2-linear/G3);
  analysis in mechanism_paired_analysis.json. Atomic path completed 6/6:
  honest negative (atomizer INVALID 4/6, verifier MODEL_JUDGED 1/6).
- §7.C tail closed: temporal-calculation assistant module checked as a
  separate module on the full timezone bank + 10 new author boundary
  cases (minute/extreme offsets, fractional seconds, cross-day, unzoned
  literal, latest-of-two clocks). Offline ground-truth gate PASS 18/18;
  paired B without/with the advisory: 18/18 decisions unchanged — honest
  negative (arithmetic advisory adds no verdict value to this B); module
  never decides scope/IDs/admissibility. Attempt-1 primary-reuse bug
  archived and recovered under versioned recovery.
- §7.D closed: M1 automatic SystemV2 Steps2-4 E2E on 4 cases with the
  ordinary upstream equals archived C0 exactly (TP3/TN1, all transitions
  unchanged); M2 bounded CCG: 11/11 failed sentences recovered (7 pure
  LEXICAL + 4 lexicalized rewrites), 19/20 minimal counterexamples
  DISTINGUISHED (formula changed), 0 INSENSITIVE, native Coq BLOCKED and
  no lossy bridge attempted.
- §7.E closed: SelfCheck bank 3/3 (judge and reconstructed-target modes
  separate; agreement 1.0, entropy 0; judge-NLI 0.003–0.164; target-NLI
  0.58–0.84 = divergence vs surrogate generator, not truth; SEP not
  claimed). RAG-Triad completed on the 3-case bank (raw/G2/G2-linear ×
  target/explanation; author template adapter, not native provider).
- §7.F closed: 12-case pre-registered balanced long-bank subset through
  the unchanged C0 service: TP5/FP0/FN1/TN6 F1 .909; exception family
  4/4 at all positions; single FN version/begin; 12001+ remains
  operational UNKNOWN smoke; two-SYSTEM stress layout flagged in every
  row.
- Environment note: tiktoken 0.14.0 added to the main venv (transformers
  5.16.1 still cannot load the DeBERTa spm tokenizer); SelfCheck-NLI runs
  under modular_venv (transformers 4.57.6) as the earlier recovery did.

## Next in queue (assignment §7 order)

A. DONE 2026-10-02 → B. DONE 2026-10-02 (graph 24/24 + atomic 6/6) →
C. DONE 2026-10-02 (negative-routing arms + temporal-calculation module
check) → D. DONE 2026-10-02 (automatic Steps 2–4 E2E + bounded CCG) →
E. DONE 2026-10-02 (SelfCheck bank + RAG-Triad bank) → F. DONE 2026-10-02
(long-bank LLM quality subset). §7 queue complete.

Sealed: NOT started; shortlist freeze + budget forecast required first
(assignment §9: new dev coverage of remaining Boolean branches, dataset/gold
versioning, UNKNOWN binary mapping, shortlist of ~4–6 systems, then a new
protocol for any sealed run).
Default service config R0 unchanged.
