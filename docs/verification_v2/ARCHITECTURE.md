# Verification v2 — what was built

Package `guardian_truth.verification` (research; the public default remains `integrated.review` with
the `guard` profile).

| module | role | authority |
|---|---|---|
| `admission.py` | admission v2 for the frozen I4 reply: evidence that cites a TOOL RESULT may carry actor `assistant`/`system`/`unknown` (normalised to the packet role, recorded as `actor_normalised`); every other v1 check unchanged. Request unchanged → replayable from cache. | code |
| `variants.py` | code-built single-element counterfactual variants of the current move: ARG (same-type value observed earlier: same key > same JSON object neighbourhood > user text; policy numbers on a line naming the argument), OMIT_CALL, PROSE_VALUE, OMIT_SENTENCE. ≤10 variants, ≤5 omissions, ≤3 alternatives per leaf; IDs stay in the same ID family. | code (generation only; never decides) |
| `probe.py` | counterfactual/contrastive probe: same U2 packet + original move + variants; strict JSON schema with source-ID enums; original status last. Candidate = admitted VIOLATING original with policy + evidence IDs. | MODEL_HYPOTHESIS → candidate |
| `second.py` | control arm B: frozen I4 reviewer + a generic skeptical re-review addendum (no new signal). | MODEL_HYPOTHESIS → candidate |
| `verifier.py` | narrow source-bound verifier: one candidate, cited policy + 2 nearest policy chunks, cited evidence, last 4 events, current move; SUPPORTED/REFUTED/UNRESOLVED with verbatim quotes checked by code (unverified SUPPORTED → UNRESOLVED). | MODEL_HYPOTHESIS, quote-checked |
| `calc.py` | deterministic CALCULATIONS table: every ISO date/datetime in the move and history vs the policy's stated "current time" (calendar days, hours, weekday, age in full years); safe `expr = result` arithmetic checker (AST, + − × ÷ only); numeric comparison parser (diagnostic). Does not say which value matters. | code |
| `checklist.py` | mechanism E (amendment 2): E1 verdict-free requirement extraction per target with policy quotes checked by code (exact / stitched list items / near-verbatim ≥0.9); E2 per-requirement check with the CALCULATIONS table; VIOLATED needs a verified evidence quote, a wrong `expr = result` → UNRESOLVED. Candidate = first admitted VIOLATED item. | MODEL_HYPOTHESIS → candidate |
| `pipeline.py` | `run_row`: A (guard profile, admission v1 pinned, frozen) → admission-v2 replay → on escalation set (A ≠ ERROR) B, C and/or E (+ verifier on each candidate); on A model-owned ERROR the verifier (shadow Av). Asserts the packet is byte-identical to A's. | — |
| `arms.py` | arm projections A, A_adm2, B, Bv, C, D, E, Ev, Av, Av_strict and primed arms B′, Bv′, C′, D′, E′, Ev′ (same candidates on the A_adm2 base) from one record (arms share the A call). | — |
| `integrated/pipeline.py` | new opt-in profile `guard_adm2` = `guard` + `admission='v2'` (same request bytes; only the admission of the reply differs). | — |

Mechanisms propose **candidates**, they do not vote on verdicts (summary §8.1). The guard remains the
only code-proven ERROR. No mechanism certifies NO_ERROR.
