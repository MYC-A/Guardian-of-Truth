# Experiment protocol (frozen before inference)

Freeze manifest: `outputs/multipacket_v1/FREEZE_v1.json` (sha `cd6c020f…`, commit `8883737c`). It holds SHA256 of every inference-relevant file (packer, multipacket modules, arms, gaps, call layer, runner, I4 interface, baseline cache, SYN-M1 inputs and gold), the prompt hashes and the pre-registered rules quoted below. No arm, prompt, packet rule or threshold changed after any result was seen. Later additions are separate versions (see the bottom of this file).

## Model and contract
- Reviewer: Mistral `ministral-14b-2512`, T=0, max_tokens 1700, strict `json_schema`. It is the same reviewer as the U2 study.
- Decision calls: the unchanged I4 decision-last schema and `admit` (target, norm-ID and evidence-actor checks).
- Continuation calls add one fixed addendum: LEDGER (D, G2, G4 final), ADJUDICATE (C1/CTRL conflicts) or OBLIGATION (G3 recheck). Ledger, reviews and findings travel as extra JSON fields, always labelled MODEL_HYPOTHESIS.
- G4 question answering uses its own small strict schema (`QAReply`): ESTABLISHED/REFUTED need cited source IDs, otherwise UNKNOWN.
- Reason judge: Ollama `gpt-oss:120b`, with the same judge prompt as evidence_packer_v2. Applied to TPs only. SAME or PARTIAL counts as reason-correct.
- Transport: retries only on 429/5xx/timeouts (logged). Failed transports are not cached and are retried on the next invocation. Every completed call is cached by sha256(request) + attempt index and never re-sent.

## Suites
- **valid46**: diagnostic only. It was used in all earlier design work. ref15 also served for oracle arms; unseen31 is "less seen", not untouched.
- **SYN-M1** (`outputs/multipacket_v1/suite_syn_m1/`): synthetic, not official hidden data, 46 cases.
  - 23 negatives: the label-0 valid rows, consistently re-identified.
  - 23 positives: an earlier assistant block of a valid row (history truncated before it), mutated by one universal operator. FACT_NUMBER: 6; CALL_ARG_ID: 17. 18 positives have prompts over 20k.
  - Gold is in a separate file that inference never reads.
  - Limits: positives cover only fabrication/contradiction errors (no missed obligations or exceptions); negatives are final turns while positives are mid-dialog turns; negatives share content with valid46.

## Arms
A = U2 20k; B = U2 48k; FULL. On valid46 all three reuse the frozen 3-run evidence_packer_v2 replies; request hashes were re-verified (138/138 identical).

| Arm | Calls beyond A | Definition |
|---|---|---|
| CTRL | ≤1 | matched-call control: A run k and A run k+1 on the same packet, plus the C1 aggregator |
| C1 | 1–2 | parallel: complementary U2 packet (A units excluded as primary units; last-user/last-assistant anchors shared), independent I4, structured aggregator |
| C2 | 2 | NORM inspector (stage A on a policy-heavy packet) → EVIDENCE decision (stage B on a history-heavy packet + norm sources cited by the inspector) |
| D1 | 1 | sequential: fixed complementary packet + ledger of A claims (+ the sources they cite) |
| D2 | 1 | sequential: packet ranked by A's open questions, norm interpretations, exception analysis and reason |
| D3 | 1–2 | D2 + third gap packet iff D2-final is UNKNOWN or differs from A |
| G2_S / G2_L | 1 | evidence sufficiency for the *proposed* claim: deterministic PRIORITY search for its norm conditions/exceptions, facts and bindings (4 hops/8000 chars or 8/16000) + ledger review |
| G3B / G3V | 1–2 | blinded / verdict-seeing obligation scan (stage A on the NORM packet); recheck iff A ≠ ERROR and the scan finds applicability YES & violated TRUE |
| G4_S / G4_L | 2–4 | recursive: A open questions + UNKNOWN scan assessments → PRIORITY search → QA answers with follow-ups (≤2 rounds, depth ≤1) → final review with ledger + research answers |
| ORACLE_E | 1 | DIAGNOSTIC: gold-referenced spans + targets/declarations + last user |
| ORACLE_R | 1 | DIAGNOSTIC: A first, then a 2nd packet = gold spans that A missed (D-style continuation) |

## Pre-registered rules (verbatim in the manifest)
- UNKNOWN → 0, and technical null → 0; both are reported separately.
- **Degenerate rule:** when the 20k packet is FULL_INPUT, or no new evidence is found, retrieval arms return A unchanged and make 0 calls.
- **D:** the primary result is the step-2 decision (the model integrates the ledger). The secondary "sticky" result is ERROR if any step said ERROR. C1/CTRL also report an "any_error" variant.
- **Selection for SYN-M1:** within each family (Parallel C1, C2 | Sequential D1, D2, D3 | Adaptive G2_S, G2_L, G3B, G3V, G4_S, G4_L), choose the arm with the highest (reason-correct TP − FP) on the valid46 pilot. Ties go to the arm with fewer mean calls. The "gap without recursion" slot is the best of G2/G3.
- **Success:** an arm beats A only if (1) its mean F1 is higher, (2) its reason-correct TP is not lower, and (3) a paired sign test gives p < 0.1. Otherwise the result is "not established".
- **Budget:** pilot ≤ ~900 reviewer calls; SYN-M1 final ≤ ~1500 calls.
