# SEMANTIC PIPELINE — CURRENT INFORMATION FLOW (Phase 1)

Branch: `codex-update-run` @ `4639b46f2e6995ea7036aef73a01ebbc723c0e14`
Arm in production use for the competition view: **B4h** (`("h0_hist",)` policy frontends, `("conservative",)` goal frontends, `SEMANTICS_ARMS["B3"]`, `AdapterMode.COMPETITION`, `enable_t2=True`).
Scope of this document: exactly what text each semantic module of Guardian currently receives, what is structurally preserved, and what is never semantically interpreted. All statements cite code locations in `src/guardian_truth/`.

---

## 1. Raw input shape (competition row)

A competition row is `{id, prompt, response}` (firewalled view: `real_valid_v1.competition_view`). Real example (`airline__21::t7`, 28 037 prompt chars):

```
⟦SYSTEM⟧
<instructions> ... You are a customer service agent ... Always communicate
with the user in Russian ... </instructions>
<policy>
# Airline Agent Policy
... (English normative text, ~8 100 chars) ...
</policy>
[AVAILABLE TOOLS]
- book_reservation — Book a reservation.
    user_id: string! — The ID of the user ...
    ...
⟦USER⟧
Здравствуйте! Мне нужно срочно изменить ... (Russian)
⟦ASSISTANT · ход 1⟧
...text...
	→ TOOL_CALL search_one_way_flights: {...}
	← TOOL_RESPONSE search_one_way_flights: {...}
⟦USER⟧ ... (4 USER turns, 6 ASSISTANT turns, 10 TOOL_CALL/TOOL_RESPONSE pairs)
```

The target `response` is the final assistant turn (`⟦ASSISTANT · ход 7⟧ ...`), containing assistant text and/or attempted `→ TOOL_CALL` blocks.

**Language mix**: policy/instructions/catalog are English; user turns are Russian (this case). Multilingual retrieval is therefore not optional for USER/TOOL_RESULT content.

## 2. Structural parsing (regex — legitimate layer)

All structural boundaries are regex-based in `guardian_truth/parsing.py`:

| Regex | Purpose | Location |
|---|---|---|
| `MARKER` (`⟦header⟧`, `→ TOOL_CALL name:`, `← TOOL_RESPONSE`) | event boundaries, roles, call/result pairing | `parsing.py:10-14` |
| `_POLICY` `<policy>...</policy>` | policy span inside SYSTEM | `competition_adapter_v1.py:22` |
| `[AVAILABLE TOOLS]` + `TOOL` (`- name — ...`) | tool catalog entries | `parsing.py:15,105-148` |
| `FIELD` (`name: kind! [enum: a\|b]`, indentation) | argument grammar → schemas | `parsing.py:16-21` |
| `_TOOL_HEADER` | first-line tool description | `competition_adapter_v1.py:23` |

Structural parsing is **lossless w.r.t. text**: every event keeps its exact character span (`Source(document, start, end)`) and the full raw prompt is retained (`E2ECaseInput.raw_prompt`).

## 3. What each LLM-facing semantic module actually receives

The adapter (`competition_adapter_v1.adapt_competition_input`) produces `E2ECaseInput`:
`system_policy` = `<policy>...</policy>` span only (`_policy()`, `competition_adapter_v1.py:66-80`); `user_request` = **last** USER text event (`users[-1]`); `history=()` — earlier turns exist only inside `raw_prompt`; tool schemas from the catalog grammar.

`GuardianE2EV1.analyze_e2e_v1` (`core_v1.py:216-...`) then routes text to the five LLM-facing modules:

| # | Module (backend task name) | Text it receives | Code |
|---|---|---|---|
| 1 | Policy frontend `h0_hist` (C-ALR `PARSE_TASK`) | `{"policy_text": <policy span>, "atom_catalog": [...]}`. The atom catalog is **deterministic from case metadata** (`action:<tool>` for every catalog tool, `state:<field>` for state-contract/T1-write fields, two fixed distractors) — never derived from policy text. | `policy_historical_v1.py:129-146,361-376` |
| 2 | Goal frontend `goal_conservative_frames` | `{"user_request": <last USER turn>}` only (goal firewall). | `goal_conservative_v1.py:78-82`, `core_v1.py:486-508` |
| 3 | Claim extraction (multi-pass `claim_*`) | Response text spans only (`response_spans(response)`); the model sees `{span_id, text}` inventory items, never the prompt. | `claims.py:75-99`, `claim_adapter_v1.py:66` |
| 4 | T2 effect hypotheses `tool_conditional_effect_hypotheses` | Per call/result pair (including **history** pairs): `tool_identity`, tool schema, call arguments, result payload. `authoritative_docs` is always `None` on this path. | `tools.py:152-166`, `core_v1.py:228-241` |
| 5 | PASS-2 binding `operational_action_binding` | `hypothesis` (from frontends), `normative_source` = policy text + machine suffixes (`POLICY_ATOM_CATALOG=`, `POLICY_STATE_CONSTRAINTS=`, `EXPLICIT_ALLOWED_SCOPE=`), `tool_catalog` (names), `target_calls` (tool + arguments). | `grounding.py:69-...`, `core_v1.py:249-275` |

## 4. Answers to the Phase-1 questions

1. **Does the policy frontend receive the entire SYSTEM block?** No. It receives only the `<policy>...</policy>` span (last match) of the single SYSTEM event. The `<instructions>` block, the `[AVAILABLE TOOLS]` catalog and any other SYSTEM text are never policy input. (Fallback when no `<policy>` tags: text before `[AVAILABLE TOOLS]`, `competition_adapter_v1.py:73-80`.)
2. **Does it receive history?** No. `E2ECaseInput.history=()` for the competition adapter; the policy frontend payload is policy text + atom catalog. History reaches only the T2 module (as call/result payloads) and deterministic claim binding.
3. **Does it receive tool results?** No — not the policy frontend and not the goal frontend. Tool results reach (a) the T2 effect-hypothesis module as raw `arguments`/`result` payloads, and (b) the deterministic `LedgerIndex` used for claim entity/time grounding.
4. **Can normative text inside a KB/tool result ever become policy input?** No, structurally impossible today: the policy source is exclusively the SYSTEM `<policy>` span. A KB document inside a `← TOOL_RESPONSE` may contain rules ("passengers with X may do Y"), but the architecture classifies it as evidence, never as policy. It can only influence a verdict through T2 *effect hypotheses* about the observed call, never as a normative reading.
5. **Which information is selected by regex/parser rules?** Policy span (`_POLICY`), tool catalog and argument schemas (`TOOL`/`FIELD`), tool descriptions (`_TOOL_HEADER`, first line only), event structure (`MARKER`), user request (`users[-1]` — a positional, not regex, choice).
6. **Which information is preserved but later ignored?**
   - Full raw prompt incl. every history turn: preserved (`raw_prompt`, ledger events) but its semantic content is **never** sent to any policy/goal LLM module; history is used only deterministically (claim binding, T1/T2 pairing, world timeline).
   - Tool descriptions (first line + full text): extracted into `tool_declarations` and the premise inventory (`real_valid_v1.premise_rows`) but never shown to the policy frontend or binding LLM.
   - Earlier USER turns and ASSISTANT history text: parsed into events, never claim-extracted (claims are response-only).
   - Argument field descriptions inside the catalog (`" — The ID of the user..."`): parsed as part of `FieldSpec` spans but discarded from schema objects (only kind/required/enum survive).
7. **Which information is truly discarded?** No text is deleted from storage; what is *semantically* discarded: (a) SYSTEM text outside `<policy>` (instructions, catalog — catalog goes to the schema path only), (b) the meaning of all non-final USER/ASSISTANT/history turns for policy and goal interpretation, (c) normative content of tool results/KB documents (never promotable to policy), (d) tool description semantics for the binding stage.

## 5. Structural parsing vs semantic filtering (the key distinction)

Current Guardian satisfies the requirement "regex is acceptable for structural parsing": all regexes above are structural.

However, the **semantic relevance decision is hard-wired by module routing, not by content**: relevance is decided *a priori* by source type (SYSTEM-policy → policy module; last-USER → goal module; response → claims; call/result → T2). Consequences (development-data observations, `outputs/vnext/real_valid/`):

- A policy-like rule located in a `← TOOL_RESPONSE` KB document can never be interpreted as policy → related FN class.
- Conditions stated by the user in an *earlier* turn (not the last) are invisible to the goal frontend → goal SCHEMA failures on multi-turn cases (audited: telecom t7 family).
- The policy frontend must compress an ~8 k-char policy into ONE flat structure (H0) with a max-6 clause budget per bucket; long policies lose conditions that have no room in the atom catalog (the audited `degenerate_gated_program` abstention path).

## 6. Frozen-cache discipline note for this experiment

The fix2-final frozen cache (`outputs/vnext/real_valid/llm_cache__mistral__...json`, `input_sha256 de8ed525...`) was **never committed** (verified: no `llm_cache*` files in `outputs/vnext/real_valid/`). Current HEAD does not ship a Mistral cache; any replay of the incumbent baseline requires either a live resumable cache or the sealed per-run artifacts (`metrics__fix2_final.json`, `R*_predictions__fix2_final.csv`). The semantic pipeline experiment therefore runs its own fresh cache file under `outputs/vnext/semantic_pipeline_v1/` and never touches sealed artifacts.

## 7. Baseline metrics recorded before any change (Phase 0 freeze)

| Configuration | TP | FP | FN | TN | Precision | Recall | F1 | Source |
|---|---|---|---|---|---|---|---|---|
| HEAD production defaults (premises gated OFF: `tool_universe_closed=False`, `object_fields_closed=False`) | 3 | 0 | 20 | 23 | 1.0 | 0.1304 | 0.2308 | `closure_ablation.json` C3 (post-audit commit `4639b46`) |
| fix2-final sealed run (closure premises ON) | 10 | 0 | 13 | 23 | 1.0 | 0.4348 | 0.6061 | `metrics__fix2_final.json` (sealed artifact) |

The experiment baseline for all deltas in `SEMANTIC_PIPELINE_V1.md` is the **HEAD production defaults** row (soundness-corrected). The fix2 row is shown for reference only; the semantic-pipeline experiment must not re-enable the gated closure premises.

Mistral backend in use: provider `mistral`, model `ministral-14b-latest`, `api_key_env mistral_api_key`, `max_output_tokens 4096`, `reasoning_effort none` (per `run_config__fix2_final.json`).
