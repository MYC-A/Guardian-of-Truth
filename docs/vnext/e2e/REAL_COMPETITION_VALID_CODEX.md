# REAL_COMPETITION_VALID_CODEX — B4h-sound-v2 on the 46 public valid cases

Branch: `competition-real-valid-codex` (from frozen `315bee335a467476732b47e1e7f412097222cd3b`, branch `E2E-agent-2`).

Purpose: restore the real olympiad pipeline from the frozen E2E-agent-2 baseline, run it
on the public AI Journey 2026 Guardian development cases (`valid.parquet`, 46 rows),
fix only what is actually broken (one root cause per iteration, max 3 general iterations),
and prepare the ground for the next development cycle. This file is written AS WORK
PROGRESSES — sections below carry timestamps and commit SHAs of the moment they were
written. All quality numbers on `valid.parquet` are DEVELOPMENT RESULTS on viewed data,
never a generalization or hidden-test claim.

---

## Official competition contract

Verified against the official sources (fetched 2026-09-16, UTC):

- Rules PDF (primary): `https://gitverse.ru/api/repos/gitverse/AIJ/raw/branch/master/AIJourney2026-rules-ru.pdf` (32 pages, downloaded, full text extracted; Task 1 = section 3.7).
- Task page: `https://dsworks.ru/champ/aij26-guardian` (JS-rendered; static shell only — page title "Guardian of Truth — Разработка новых методов детекции галлюцинаций LLM-моделей" confirms the task; body text is client-rendered and was not retrievable; the rules PDF is treated as authoritative).
- Group page: `https://dsworks.ru/group/aij2026` (same JS shell).

### 1. Exact task statement (rules §3.7)

Build a guardrail that automatically detects a **contextual hallucination** in an LLM-agent
response. The guardrail works black-box: it sees only the input context text and the
response text — no weights, no internal states, no hidden reasoning. Binary classification
at the response level.

### 2. label = 0

No hallucination. Cosmetic/style differences that provably do not change the user-visible
result are NOT hallucinations: correct paraphrase/aggregation/filtering/sorting; rounding,
formatting, rewording without meaning change; imprecise wording inside internal reasoning
when the final result is correct; service fields not reaching the user.

### 3. label = 1

At least one hallucination of either mechanism:
- **contradiction** — the response contradicts the context (data, instruction, tool results) so the outcome becomes wrong (wrong number/date/value/name; reference to a non-existent entity/field/value; violation of a mandatory instruction rule that distorts the result);
- **unsupported** — a statement not derivable from the context (invented fact, number, reason, entity, condition) even if nothing directly contradicts it.

Disputed-case test from the rules: "Does this change the outcome or the data the user will
see?" — yes/potentially yes → hallucination.

### 4. Fields the solution actually receives

`id` (str), `prompt` (str), `response` (str). The public development set additionally has
`label` (int) and `explanation` (str); the hidden test is a CSV passed to
`scripts/predict.py --input <path_to_test.csv> --output <path_to_predictions.csv>`.

### 5. What is in `prompt`

The full context the agent saw before its answer: system instruction (rules + available
data/metadata), the user request, and previous tool invocations with their results. Rules
specify the transcript marker vocabulary `⟦SYSTEM⟧`, `⟦USER⟧`, `⟦ASSISTANT⟧`,
`⟦ASSISTANT_TOOL_CALL name="X"⟧`, `⟦USER_TOOL_CALL name="X"⟧`,
`⟦TOOL_RESULT name="X" requestor="assistant|user"⟧`.

**SOURCE DISCREPANCY (recorded, not silently resolved):**
- SOURCE A (rules PDF §3.7 example): tool calls/results as separate bracket markers `⟦ASSISTANT_TOOL_CALL name="X"⟧` / `⟦TOOL_RESULT name="X" requestor="assistant"⟧`.
- SOURCE B (actual `valid.parquet`, all 46 rows): tool calls/results as indented arrow lines inside numbered assistant turns — `→ TOOL_CALL name: {json}` / `← TOOL_RESPONSE name: {json}` under `⟦ASSISTANT · ход N⟧` markers (N continues across the conversation; the response is `⟦ASSISTANT · ход N+1⟧` in 41/46 cases, the other 5 are first-turn cases).
- ASSUMPTION USED: the parser must accept BOTH transport spellings (the repository's `guardian_truth.parsing.MARKER` already accepts both); no assumption is made that the hidden test matches either one specifically.

### 6. What is in `response`

The agent answer to check: `⟦ASSISTANT · ход N⟧` blocks containing natural-language text
and/or `→ TOOL_CALL name: {json}` action lines. The rules explicitly say the substantive
content must be looked for in the text, in the tool-call type/name, AND in its arguments.
Census on the 46 cases: 23/46 responses contain tool calls (15×1, 5×2, 3×4 calls);
responses contain no `← TOOL_RESPONSE` lines.

### 7. Tool definitions / schemas / descriptions

PRESENT. Every one of the 46 SYSTEM blocks contains a `[AVAILABLE TOOLS]` catalog in a
text signature format (not JSON Schema): `- tool_name — description.` followed by
indented `argument: type! [enum: a|b] — description.` lines. 13–17 tools per case,
55 unique tool names across the corpus. Argument names, types, requiredness, enums and
per-argument descriptions are all explicit. Banking cases additionally expose a
discoverable-tools mechanism (`unlock_discoverable_agent_tool`, `call_discoverable_agent_tool`,
tools with entity-suffixed names like `get_all_user_accounts_by_user_id_3847`).

### 8. Tool calls / results in the data

PRESENT in prompts: 393 `→ TOOL_CALL` lines and 372 `← TOOL_RESPONSE` lines across the 46
prompts (some conversations end with an unanswered call — the response under check).
23/46 responses themselves contain tool calls.

### 9. Hidden test input format

CSV with `id`, `prompt`, `response` (rules §3.7 "Формат входных данных"; the parquet
`label`/`explanation` columns are development-only). The exact CSV quoting of huge
multi-line prompts is a packaging concern for the submission stage, not for research.

### 10. Submission format

Docker image (structure: `root/{README.md, pyproject.toml, model/, src/, scripts/predict.py}`),
platform runs `pip install .` then
`python scripts/predict.py --input <test.csv> --output <predictions.csv>`;
output = CSV with columns `id`, `label`.

### 11. Official metric

Response-level: **F1-score (primary ranking)**, Precision, Recall — computed against the
binary `label`.

### 12–15. Time / CPU / GPU / RAM / Docker limits

- Script runtime limit: 30 minutes.
- Hardware: 1× GPU NVIDIA H100.
- RAM: not separately specified in the rules.
- Solution size: strictly < 40 GB.

### 16–18. Network / external API / local LLM

- The rules state "Внешние запросы к интернету во время формирования метрики блокируются" explicitly for **Task 2** (Green Challenge). For Task 1 (Guardian) the rules do not state a network policy in the constraints block.
- ASSUMPTION USED (conservative): the final submission must be fully OFFLINE (no external LLM API at inference). The H100 provision and the 40 GB model directory strongly indicate local-model readiness. External APIs (Gemini/Mistral/ZAI) are therefore research-time tools only, never a submission dependency.

### 19. Submission count

Max 10 solutions per participant/team over the whole competition (only successful
submissions consume the limit); 3 final solutions are selected for the final table.

### 20. Other platform constraints

Period 25.08.2026–11.11.2026 (Task 1); proprietary technology requiring paid licenses is
forbidden; private sharing of solutions/ideas outside one team is forbidden.

---

## Repository state

Commands executed at the start (2026-09-16 ~18:40 UTC), clone via PAT, worktree at
`/home/z/my-project/guardian-of-truth`:

```
$ git status                  -> clean, on branch main (fresh clone)
$ git fetch origin E2E-agent-2
$ git ls-remote origin refs/heads/E2E-agent-2
   -> 315bee335a467476732b47e1e7f412097222cd3b  refs/heads/E2E-agent-2
$ git cat-file -t 315bee335a467476732b47e1e7f412097222cd3b -> commit
$ git log --oneline -8 315bee3
   315bee3 FINAL FREEZE B4h-sound-v2 (final pre-benchmark verification complete)
   ebf2bc4 Final pre-benchmark verification (B4h-sound-v1 -> B4h-sound-v2): REP-01 ...
   8c91701 FINAL FREEZE B4h-sound-v1 (pre-benchmark soundness audit complete)
   5e4bc39 Pre-benchmark soundness audit (B4h -> B4h-sound-v1): 10 formal soundness bugs ...
   e7eb79c E2E V1 cycle 3: causal false-certified-ERROR repair study (B0-B4) and freeze
   4b9141b E2E V1 full architecture document (RU) ...
   4fa2212 E2E V1 fresh holdout results ...
   4d7fdfb E2E V1: versioned multi-frontend architecture ...
```

Remote SHA of `E2E-agent-2` == local frozen commit == `315bee3` — verified identical.
Working branch created (frozen branch left untouched):

```
$ git checkout -b competition-real-valid-codex 315bee335a467476732b47e1e7f412097222cd3b
   -> Switched to a new branch 'competition-real-valid-codex'
```

## Frozen baseline

`315bee3` = **B4h-sound-v2**: frozen historical H0 policy frontend + Conservative Goal
frontend + cycle-3 B3 semantics (`conservative_state`, `alternative_groups`,
`inconsistent_status`, `claim_typing` all on) + soundness fixes SND-01..SND-11. Freeze
manifest quotes: "no known FORMAL_SOUNDNESS_BUG; production hardcoding 0; B0 byte
fidelity true on both corpora; e2e+soundness 96 passed / 0 xfail; baseline 1481 passed".
Research-corpus regression (dev32+holdout112, VIEWED development data): TP 49 FP 0 FN 20
TN 5, precision 1.000, recall 0.7101, F1 0.834, false-certified ERROR 0, false-certified
NO_ERROR 0, uncertified definitive 0. These numbers are on the SYNTHETIC research corpus,
not on `valid.parquet`.

## Execution path

The real B4h-sound-v2 execution path (found by code reading, not assumed):

```
scripts/run_soundness_regression.py            (offline replay runner, frozen caches)
scripts/evaluate_vnext_e2e_cycle3.py           (live runner, arm B4h)
  └─ guardian_truth.vnext.e2e.experiment_v1.load_corpus / registry_for
      └─ guardian_truth.vnext.e2e.core_v1.GuardianE2EV1(
             backend, registry=ContractRegistry(t1_contracts),
             arm=E2EArmConfig("B4h", ("h0_hist",), ("conservative",)),
             max_worlds=4096, adapter_mode=AUDIT, semantics=SEMANTICS_ARMS["B3"])
           .analyze_e2e_v1(E2ECaseInput)
```

Inside `analyze_e2e_v1` (core_v1.py):

1. `source_adapter_v1.build_source(case)` — composes `⟦SYSTEM⟧policy + ⟦USER⟧request +
   history events` and `response`, runs the deterministic marker transport
   (`guardian_truth.parsing.parse_events` — accepts BOTH `⟦HEADER⟧` and
   `→ TOOL_CALL name:` / `← TOOL_RESPONSE name:` spellings) into LedgerEvents;
   TEXT_VIEW/ACTION_VIEW projection of the target response.
2. `EvidenceLedger.from_events(history_complete=case.history_complete, ...)`.
3. T1: `tools.evaluate_t1(registry, call, result)` per matched call/result pair —
   uses `registry_for(case)` built from `case.t1_contracts` (research metadata);
   for tools with NO registry entry `tools.propose_t2(...)` asks the LLM
   (`tool_conditional_effect_hypotheses` task; proposals are non-trusted world axes).
4. `claim_adapter_v1.build_claims(response, backend, ledger, semantics)` — LLM claim
   extraction (`claim_*` tasks) over the response text; deterministic value anchoring,
   entity binding, time binding; claims become world axes.
5. PASS 1 policy: `policy_historical_v1.historical_readings(...)` — the frozen C-ALR H0
   protocol: LLM `PARSE_TASK` (one typed structure for the WHOLE policy) + one
   machine-validation `REPAIR_TASK`; atom catalog built deterministically from case
   metadata (`action:<tool>` per catalog tool, `state:<field>` per state-contract/T1-write
   field, 2 distractors); compiled by the frozen v3 compiler into `PolicyReading`s.
6. PASS 1 goal: `goal_conservative_v1.parse_conservative(user_request, backend)` — one
   bounded LLM pass over the USER source only (goal firewall).
7. PASS 2 lowering: `policy_lowering_v1.lower_reading(...)` and
   `goal_lowering_v1.lower_goal_contract(...)` — operational grounding of rules onto the
   trajectory (LLM `operational_action_binding` task), prerequisites, preservation.
8. Axes (policy readings × goal contracts × claims × T2 candidates) →
   `world_integration_v1.build_worlds` (exact Cartesian product, budget 4096) →
   `solve_e2e` per-world verdicts → all-world aggregation → CoreStatus.
9. `certificate_context_v1.make_e2e_certificate` + independent checker; invalid
   certificate → UNRESOLVED (conservative).
10. `adapters.adapt(...)` → ProductDecision (AUDIT: PROVED_ERROR→1, PROVED_NO_ERROR→0,
    else None+fallback; COMPETITION mode: INCONSISTENT→1, UNRESOLVED→0).

LLM dependency of the frozen line: the historical H0 frontend (`h0_hist`), the
conservative goal frontend, claim extraction, T2 proposals and operational binding all go
through `backend.propose(task, payload, schema)` (SemanticBackend protocol). The research
runs replayed persisted per-corpus caches; live calls used the BAI provider
(`qwen3.8-flash`) with `response_format_mode='none'` and JSON-extraction normalization.

**Cache dependency verdict (section 11 of the directive): CACHE_DEPENDENT_BASELINE.**
B0–B3 replay fully offline against persisted per-corpus LLM caches; B4h needed live calls
only for historical policy tasks. On `valid.parquet` (unseen policy texts) every cache key
is a guaranteed MISS, so any real run is COLD CACHE by construction.

LLM endpoint availability test (2026-09-16, from this environment):
- Gemini `gemini-3.6-flash`: HTTP 400 "User location is not supported for the API use" — region-blocked, unusable.
- Z.AI `GLM-4.7-Flash` (api.z.ai/api/paas/v4): key accepted but persistent HTTP 1302 "Rate limit reached" on every attempt — unusable.
- BAI `api.b.ai/v1`: rejects the provided z_ai key ("Invalid api_key format") — unusable.
- Mistral `ministral-14b-latest` (api.mistral.ai/v1): WORKS.

ASSUMPTION USED: live backend for the cold-cache competition runs = provider `mistral`,
model `ministral-14b-latest` (the only reachable endpoint). This is a DEVIATION from the
frozen BAI/qwen3.8-flash config, forced by endpoint availability, recorded here; it does
not change any pipeline semantics (the SemanticBackend protocol is provider-agnostic).
R0 replay on the research corpus stays byte-identical to the frozen caches regardless.

## The section-7 question: can B4h-sound-v2 be called as analyze(prompt, response)?

NO — not directly. `analyze_e2e_v1` consumes `E2ECaseInput`, which is a research-corpus
record with rich metadata. Dependency table:

| Input dependency | Needed? | Present in competition prompt? | Research-only? |
|---|---|---|---|
| `system_policy` | YES — policy axis input | YES — `⟦SYSTEM⟧` block (12.7K–27.5K chars incl. `[AVAILABLE TOOLS]`) | no (derivable) |
| `user_request` | YES — goal firewall input | YES — `⟦USER⟧` turns (1–25 per case, 84–6512 chars total) | no (derivable; multi-turn split is an adapter decision) |
| `history` (marker events) | YES — ledger/observations | YES — `⟦ASSISTANT · ход N⟧` turns with `→/←` lines | no (derivable) |
| `target_response` | YES | YES — `response` field | no (derivable) |
| `tool_metadata` (identities) | partial — identity binding | PARTIAL — tool names from `[AVAILABLE TOOLS]`; provider/version unknown | subset derivable |
| `tool_schemas` | partial — T2 hint | PARTIAL — text-signature catalog (research corpus passed name-only dicts) | subset derivable |
| `t1_contracts` | YES for trusted T1 effects | NO — must be authored per tool | RESEARCH-ONLY |
| `state_contract` | YES for preservation proofs | NO | RESEARCH-ONLY |
| `history_complete` + basis | YES for absence proofs / closure | NO — not stated in the input | RESEARCH-ONLY (assumption) |
| `authoritative_policy/goal_readings/behaviors` | oracle substitution only | NO | RESEARCH-ONLY (not used in non-oracle B4h) |
| LLM backend (live or cache) | YES — claims, goal, H0 policy, T2, binding | N/A | cache-dependent on research corpus; COLD on real data |

Consequences for a competition adapter: missing T1 → all tools fall to non-trusted T2
LLM proposals (world alternatives, never trusted effects); missing state_contract →
preservation rules lower to unresolved (sound abstention); history_complete=False →
absence proofs blocked (sound abstention); missing metadata → UNKNOWN, never invented.
This is exactly the "missing information → abstention" discipline required by the
directive.

## valid.parquet as-is (dataset study)

- 46 rows; columns `id, prompt, response, label, explanation`; dtypes object/int64.
- Label distribution: 23×`0`, 23×`1` (balanced).
- `prompt` length: min 13,634 / median 30,499 / max 233,104 chars.
- `response` length: min 51 / median 428 / max 2,339 chars.
- Domains (POST-HOC ONLY, never used in inference): 12 airline, 10 banking_knowledge, 10 retail, 12 telecom.
- Transcript census: 46 SYSTEM blocks (all with `[AVAILABLE TOOLS]`, 13–17 tools, 55 unique names); 267 USER turns; 403 numbered assistant turns; 393 `→ TOOL_CALL` + 372 `← TOOL_RESPONSE` lines in prompts; 23/46 responses contain 1–4 tool calls; response turn numbering continues the prompt numbering in 41/46 cases.
- 6 cases have zero prior tool calls (`airline__47::t1`, `airline__5::t1`, `banking_knowledge__task_033::t2`, `retail__108::t1`, `retail__14::t1`, `retail__78::t1`).
- All call-line JSON decodes cleanly; some `← TOOL_RESPONSE` payloads span multiple lines (multi-line JSON) — the transport parser handles them as body text of the result event.
- GOLD FIREWALL: the inference input object is exactly `{id, prompt, response}`; `label`/`explanation` join only at the post-seal scoring step.

Regression check for the firewall (label/id independence) is implemented in the adapter
runner (`scripts/run_real_valid.py --metamorphic-gold`): flipping the label and changing
the id with identical prompt+response must not change the prediction.

---

## Baseline run (no fixes)

2026-09-16, branch `competition-real-valid-codex` @ `315bee3` + the transport-only
competition adapter (uncommitted at run time; committed as the first commit of this
branch, see Git discipline). Runner: `scripts/run_real_valid.py` (mode R1/R2),
scoring post-seal: `scripts/score_real_valid.py`.

### R0 — frozen research mode (integrity check)

The frozen runner cannot consume raw parquet rows (`MISSING_COMPETITION_ADAPTER` at
runner level: it loads corpus JSONs with research metadata). After the transport-only
adapter, R0 on real cases coincides with R1 BY CONSTRUCTION: no research metadata
(t1_contracts, state_contract, authoritative rows, LLM caches) exists for the 46 public
valid cases. The frozen line itself was verified offline on the research corpora via
`scripts/run_soundness_regression.py` (dummy BAI key — the runner demands BAI
credentials even for pure cache replay, itself a recorded friction point):

- B0 byte-fidelity on dev32 and holdout112: TRUE (no divergences).
- B4h-sound-v2 replay: dev TP 11 FP 0 FN 4 TN 1 (P 1.000 R 0.733 F1 0.846), holdout
  TP 38 FP 0 FN 16 TN 4 (P 1.000 R 0.704 F1 0.826), combined TP 49 FP 0 FN 20 TN 5 —
  exactly the frozen freeze-manifest numbers; 0 cache misses.

Conclusion: the frozen pipeline is intact; its research-corpus numbers are real; it has
never been run on competition-shaped input before this cycle.

### Smoke diagnostics before the full run (recorded, NOT fixed pre-baseline)

- Mistral transport: the endpoint rejects the top-level `reasoning_effort` field
  (HTTP 400 code 3051) that the frozen BAI endpoint accepted; the runner applies a
  transport-level compatibility shim (drops that one field; task content unchanged).
- Single-shot frontend fragility on real-sized inputs (5 identical repeats per task,
  same payload, temperature 0): h0 PARSE on the 13.5K-char airline policy 4/5
  schema-valid; goal_conservative on a 686-char multi-turn user request 2/5
  schema-valid. The frozen protocol performs NO semantic retries (by design), so these
  failures are sticky per cache key.

### R1 — competition prompt only (live LLM, cold cache)

Backend: mistral / ministral-14b-latest (only reachable endpoint; deviation from the
frozen BAI/qwen3.8-flash config recorded above), `response_format_mode=none`,
max_output_tokens 2048, interval 1.0s, max_retries 2, 523 persisted cache entries.

Full 46-case run (chunked foreground; each case crash-safe, resume via progress JSONL):

| mode | TP | FP | FN | TN | Precision | Recall | F1 | statuses |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| R0≡R1 | 1 | 0 | 22 | 23 | 1.000 | 0.0435 | **0.0833** | 45 UNRESOLVED + 1 PROVED_ERROR |
| R2 (structural only) | 0 | 0 | 23 | 23 | — | 0.000 | 0.000 | 46 UNRESOLVED |

Predictions sealed before scoring: `outputs/vnext/real_valid/prediction_seals.json`
(SHA256 per CSV; R0 file carries the R0≡R1 provenance note). The single PROVED_ERROR
is a certified TRUE positive: `telecom__service_issue...overdue_bill_s::t15` — the
response calls `check_sim_status`/`check_network_status`, tools absent from
`[AVAILABLE TOOLS]`; the proof went through the goal contract + operational binding
(target calls vs catalog) with a valid certificate, needing NO T1 semantics at all.

Gold firewall regression (directive §9): id-independence PASS (4 sample cases rerun
with renamed ids, identical core statuses, full cache replay); input-hash integrity
PASS (progress records hash prompt/response only). Label never enters the inference
object by construction (`run_real_valid.load_rows` reads id/prompt/response columns
only).

### R2 — structural only

All 46 cases UNRESOLVED with zero LLM calls: the deterministic layers of the frozen
E2E architecture (marker transport, ledger, catalog, claims gating, world composition,
certificate) have ZERO standalone coverage on real competition input. Every verdict in
this architecture flows through at least one LLM-semantic frontend. (The repository's
older production detector line — scripts/predict.py with availability/schema/
provenance checks — is a different pipeline, not B4h-sound-v2.)

## Failure decomposition

Frontend availability across the 46 cases (R1):

| component:kind | cases | share |
|---|---:|---:|
| goal_conservative:SCHEMA | 18 | 39% |
| goal_conservative:TRANSPORT | 16 | 35% |
| policy_h0_hist:TRANSPORT | 2 | 4% |
| policy_h0_hist:SCHEMA | 1 | 2% |
| policy_h0_hist:COMPILE | 1 | 2% |
| (no frontend failure) | 11 | 24% |

Root-cause table (primitive per case, deterministic priority):

| Root cause | FP | FN | TN | TP | total |
|---|---:|---:|---:|---:|---:|
| GOAL_PARSE | 0 | 16 | 15 | 0 | 31 |
| CLAIM_PARSE | 0 | 4 | 5 | 0 | 9 |
| POLICY_PARSE | 0 | 2 | 2 | 0 | 4 |
| STATE_EVIDENCE | 0 | 0 | 1 | 0 | 1 |
| OTHER (the certified TP) | 0 | 0 | 0 | 1 | 1 |

Transport failure autopsy (cache records): 158 transport-ERROR proposals in the run,
156 of them `rate_limit` (Mistral 429 under sustained load with large payloads; the
ChatClient's 2 retries were insufficient), 2 `truncated`. 50 SUCCESS-but-schema-invalid
proposals. The goal SCHEMA failures were confirmed by direct replay to be wrong-output-
shape failures of a 14B model against the strict bounded CONSERVATIVE_SCHEMA (wrong
enum values like kind="INFORMATION", frame object returned unwrapped at top level,
missing required keys) — NOT semantic misreadings.

The 11 cases where both frontends succeeded still ended UNRESOLVED with primary
reason POLICY_AMBIGUOUS: the single-structure H0 reading of a 13–27K-char real policy
(one REQUIREMENT/PROHIBITION over a few atoms) plus one conservative goal contract is
semantically far too weak to close any world definitively (and correctly refuses to).

Dependency table (directive §22):

| Dependency | number of cases |
|---|---:|
| works without T1 (structural: catalog/schema/provenance) | 10/23 positives |
| needs prompt-derived tool semantics (schema/procedure rules) | 7/23 positives |
| needs observed-trajectory reasoning (provenance/fabrication) | 5/23 positives |
| needs manual/oracle T1 (freshness/effects/ownership) | 6/23 positives (deepest family only) |
| blocked by policy parse | 4/46 |
| blocked by claim parse | 9/46 (21 with ≥1 failed claim pass) |
| blocked by goal parse | 34/46 |
| blocked by missing current-state evidence | ≤11 (frontends-OK abstentions) |

## Premise coverage (post-hoc, gold explanations read AFTER sealing)

`outputs/vnext/real_valid/premise_coverage.csv` — per-case weakest sufficient proof
level for the 23 positives (directive §14 priority order):

| level | positives | T1/premise family |
|---|---:|---|
| INVALID_TOOL_NAME (2) | 5 | EXPLICIT_SCHEMA (the catalog is in the prompt) |
| UNSUPPORTED_ARGUMENT_PROVENANCE (4) | 3 | OBSERVED_TRAJECTORY |
| INVALID_ARGUMENT_SCHEMA (3) | 2 | EXPLICIT_SCHEMA |
| SYSTEM_PROCEDURE_VIOLATION (8) | 5 | EXPLICIT_SYSTEM_POLICY |
| FABRICATED_RESULT (10) | 1 | OBSERVED_TRAJECTORY |
| FABRICATED_ACTION (9) | 1 | OBSERVED_TRAJECTORY |
| STATE_EFFECT_REASONING (11) | 6 | MANUAL_ORACLE_ONLY beyond prompt text |

Key conclusion: **10/23 positives need NO T1 semantics at all** — they are provable
from the explicit tool catalog, the tool text schemas, or the observed trajectory
(catalog violations ×5, argument schema ×2, provenance ×3). The single baseline TP
came exactly from this family. 6/23 need deep state/effect/temporal reasoning where
trusted T1 is genuinely unavailable in competition mode (abstention is the sound
answer there today).

---

## Fix iterations

### ITERATION 1 — GOAL_PARSE robustness (root cause: goal frontend unavailable on 34/46 cases)

2026-09-16/17. Root cause evidence: 18 SCHEMA + 16 TRANSPORT goal frontend failures; direct
replay of failed calls showed wrong-output-shape failures of a 14B model against the
strict bounded CONSERVATIVE_SCHEMA (kind="INFORMATION" enum confusion, frame object
returned unwrapped, missing keys) and 156/158 transport errors were mistral rate-limit
429s that exhausted the 2 configured retries; additionally the transport boundary
DISCARDED the decoded content of schema-invalid completions (payload_json=None), so any
repair re-ask ran blind with the useless machine error "expected object, got NoneType".

Hypothesis: mirroring the frozen historical H0 frontend's single machine-validation
repair protocol onto the goal frontend (opt-in `allow_format_repair`, default OFF —
2/60 holdout goal cache entries are schema-invalid and an unconditional repair would
break B0 byte-fidelity there) + preserving decoded-but-invalid payload content at the
transport boundary + hardened transport retries (max_retries 5, interval 1.2s) makes
the goal axis available on real input and unlocks goal-plan violations.

Production change (minimal, general, mirrors an existing frozen mechanism):
- `goal_conservative_v1.py`: `GOAL_REPAIR_TASK`, deterministic `_first_schema_violation`
  diagnostic, opt-in one-shot repair in `parse_conservative` (a schema-valid-but-wrong
  answer is never retried).
- `core_v1.py`: `GuardianE2EV1(goal_format_repair=False)` constructor flag.
- `json_extract_backend_v1.py`: preserve the decoded-but-schema-invalid payload
  (transport form only; consumers still gate on schema_status).
- `scripts/run_real_valid.py`: repair enabled in competition mode, transport hardened.
- `scripts/prune_goal_cache.py`: surgical re-drive of exactly the 34 pre-fix goal
  first-attempts (their cached records had lost the content the repair protocol needs).

New tests: `tests/e2e/test_goal_conservative_repair.py` — 11 tests (single-call on
success, repair recovers enum/transport failures, repair failure recorded not retried,
default-off frozen behavior, quote-grounding gate still enforced, deterministic machine
error, payload-content preservation at the transport boundary).

Full 46-case rerun:

| | TP | FP | FN | TN | Precision | Recall | F1 | statuses |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| before | 1 | 0 | 22 | 23 | 1.000 | 0.0435 | 0.0833 | 45 UNRESOLVED + 1 PROVED_ERROR |
| after | 3 | 0 | 20 | 23 | 1.000 | 0.1304 | **0.2308** | 43 UNRESOLVED + 3 PROVED_ERROR |

Corrections: `airline__9::t6` (premature transfer while get_flight_status available),
`banking_knowledge__task_018::t6` (premature transfer, obvious retry untried) — both
UNRESOLVED→certified PROVED_ERROR, both gold=1 (goal-plan obligation violation path,
exactly the mechanism that produced the baseline TP). Regressions: 0. Goal frontend
availability: 12/46 → 34/46 cases. Soundness: all 3 definitive verdicts carry valid
certificates; 0 false-certified anything; frozen research replays byte-identical
(B0 byte-faithful both corpora, 0 cache misses, frozen metrics unchanged); e2e +
soundness suites 107 passed; gold firewall id-independence PASS. Decision: **KEEP**.

Data-quality finding (documented, NOT fixed — isolated 1/46, fixing it would be a
case-specific patch): `telecom__mms_issue...break_app_sms_p::t10` contains an
agent-voice turn wrapped in a `⟦USER⟧` marker ("Спасибо, Джон. Я нашёл ваш аккаунт…",
"*Примечание: Я вижу, что у меня есть инструменты для удалённой диагностики…"),
which pollutes the concatenated goal-firewall source for that case.
