# HISTORY_AUDIT.md — audit of prior research lines before F/S/V (three-architectures experiment)

Branch: `research/three-architectures-24gb-20260930` (from `zai/system-research-v2-20260930` @ `ab6f0335`).
Audit method: per-branch artifact verification in-repo (docs + per-case records + scorer outputs), not doc-only reading.
Every row: mechanism / key commits / dataset / model / metrics / limitations / status / what is new in F/S/V.

---

## 0. Verified status of the owner's preliminary claims

| # | Claim | Verdict | Actual numbers (source) |
|---|---|---|---|
| a | structural channel catches 12/23 errors without FP | **CONFIRMED** | TP12/FP0/FN11/TN23, P 1.000 R .5217 (`outputs/full21/control_repro_percase.csv`) |
| b | pgjudge finds 23/23 but many FP | **CONFIRMED** | TP23/FP16/FN0, R 1.0, F1 .7419 fresh (`outputs/big_researh/p_api/pgjudge/records.jsonl`); pre-reset FP14 (UNVERIFIED post-reset) |
| c | direct judge F1 ≈ 0.76–0.79 | **PARTIALLY** | direct Mistral .7547 (UNVERIFIED, records lost); granite 3.3 .7805 (verified); but fresh single Mistral arm M = .6984; gpt-oss-20b .7556 (n=39) |
| d | Granite always adds useful errors | **REFUTED as "always"** | 3.3 adds +8 unique TP in OR (.6857→.8889); **4.1 adds ZERO new errors to the OR** (`outputs/searh_23/gate41_or/summary.json`); on hotel granite adds 8–11 FP; 60k context .6061 |
| e | different judges don't err simultaneously | **PARTIALLY** | FN overlap = 0 for all 3 judge pairs (E5); but FP co-occur: blockrun∩codex 14 shared FP, codex∩pollinations 4 |
| f | refutation removes FP without losing TP | **PARTIALLY** | v3.1 public46 TP23/FP6/FN0 (in-sample, 0 TP lost); v4 hotel .9032 (in-sample); out-of-sample hotel: 0/12 FP removed; counter-examples: refute v1 killed 1 TP; v3.0 .9020 was an indexing bug (→.8846) |
| g | formalization and Clingo "don't work" | **CONFIRMED as applied negative** | solver itself 43/43 sound (bakeoff); on public46: 0 violations, 28/64 bound; feeding Clingo verdicts to judge HURTS (pglcljudge .7188 < pgjudge .7667). Blocker = NL premise observability, not the solver |
| h | decomposition and repair always useless | **CONFIRMED for tried setups** | one-shot B .5 vs decomposed A .286; B3 repair 0/5; critic −0.40 F1; S1-B/C/D atom F1 .095–.353 vs .621 one-shot; investigator steps 2/4/6: 0 FP removed. EXCEPTION: compile-failure→cross-model repair (V2) lifted sealed .700→.750 |
| i | majority of repeated votes necessarily improves | **REFUTED** | majority-of-3 different judges .7419 > each single; BUT majority-of-2 (AND) .6545/.619 WORSE than best member; no repeated-vote experiment ever existed; no majority ever beat OR .8889 |

---

## 1. big_researh (main results line)

- **Mechanism:** Stage I (S6 LangExtract, S8 Clingo, S9 NuExtract cards, P/Q arms) → Gate (Granite 4.1 vs 3.3) → Stage II deterministic router → Stage III adaptive verification agent with counter-hypothesis search. Frozen control contract: OR(structural Guardian, granite-3.3 groundedness) never tuned on public46.
- **Commits:** 8370b585 → 3e9a907b → ea9e7069 → d34d6dae → 1c6297f0 (final RESULTS.md).
- **Dataset:** public46 = valid.parquet, 46 rows (id,prompt,response), 23/23 gold, **PUBLIC_SEEN dev, not holdout**; gold joined post-hoc.
- **Models:** granite-guardian-3.3-8b (b3421eda, local, groundedness, 12k head-tail, temp 0), granite-guardian-4.1-8b (ab01ccca, BYOC), Mistral API ministral-14b-latest, NuExtract3-W4A16 local, LangExtract API, Clingo 5.8.2.
- **Metrics:** baseline OR TP20/FP2/FN3 **F1 .8889** (never beaten); granite 3.3 .7805; gate 4.1 .8095 (43/46 agree with 3.3); pgjudge R 1.0 F1 .7419; S9 cards-as-judge .2286–.3750 (negative); S5 graph-as-context .6032; router_v1 .7805 (labels=control; audit: "no tools were executed in v1"); agent_v1 .80 vs standalone (UNVERIFIED — traces lost).
- **Limitations:** 2026-09-23 server reset destroyed outputs (S6-API/S8/S9/P/Q/router/agent raw records) — marked UNVERIFIED; Stage II/III compared vs granite standalone, not the OR control; RESULTS.md S5 row contradicts audited per-case (TP5 vs TP19, same F1).
- **Status:** EXECUTED (pre-reset); pgjudge/gate41/Q re-run fresh in searh_23.

## 2. searh_23/investigator-v2

- **Mechanism:** claim-level suspicion registry + 5 deterministic tools + independent EvidenceControllerV2 + fixed aggregation (0→1 only mechanical/formal SUPPORTED; 1→0 only ALL refuted + counter scanned); then FP-diagnostic refute layers v1/v3/v3.1/v4, typed-question layer, LettuceDetect, hotel transfer.
- **Commits:** 33cceca3 → 42543a90 → 685e4a8b → 7c058526 (FREEZE) → 18da6502 → cd8d0993 → fcf5a06c → 0a248f26 → 42763bab.
- **Dataset:** public46 (in-sample) + synthetic hotel v1 (20 cases)/v2 (28).
- **Metrics:** arms A .7419 / B .8889 / C .8889 (C 10× faster) / M .6984; **zero flips at steps 2/4 everywhere; B@6 = only flip, LOST a TP**; refute v3.1 TP23/FP6/FN0 .8846; v4 hotel .9032 R 1.0; TQ −2 FP public46 (in-sample), 0 on hotel.
- **Limitations:** in-sample everywhere; hotel synthetic single-author; a THIRD unseen domain = "the honest validation frontier" (FREEZE.md).
- **Status:** EXECUTED; C1/C2/C3 frozen at 7c058526.

## 3. Past ensembles / voting / aggregators (E5 + OR/AND tuning)

- **Mechanism:** E5 post-hoc OR/AND/majority/k-of-3 over all prediction sources on disk; full21 s3/s5 granite OR arms; fixed aggregators everywhere.
- **Metrics:** singles: blockrun .623, codex-mistral .7213, pollinations/gpt-oss-20b .7391 (n=39); **OR(blockrun,codex) .6866; AND(codex,pollinations) .7442; majority-3 .7419; majority-2 .6545/.619 (WORSE than best member)**; granite OR variants .6977–.8889. OR(structural,granite) .8889 unbeaten.
- **Limitations:** judge coverage incomplete (n=30–43/46, missing→0); post-hoc replay, no new inference; GOAL_STATUS bans repeat/repair loops and arbitrary weights (documented, not measured).
- **Status:** EXECUTED (cached-replay-style analysis).
- **NEW in V:** k=3/5 repeated verdicts with sampling; cross-family vote with Granite as a member; vote-level calibration; quorum/fallback rules. None of these ever existed.

## 4. Granite Guardian runs (transfer behavior)

- granite 3.3: .7805 public46; context ablation 6k .7391 / 12k .7805 / 24k .7692 / 60k .6061; think-mode .6341 (negative); evasiveness P 1.0 R .1739.
- granite 4.1: .8095 standalone; OR == OR 3.3 == .8889 (zero new errors — both 4.1 wins covered by structural).
- **Hotel transfer (new domain):** C1 v1 TP10/FP8/FN0 F1 .7143 — recall transfers (10/10), precision does NOT (8/10 compliant twins flagged); structural channel abstains 0/20 → C1 degenerates to granite-only. Hotel v2: granite TP14/FP11.
- **AgentHallu DEV 488:** granite groundedness F1 **.4043** (P .644, R .295) — honest negative; public46 not representative.
- **NEW in V/S:** Granite as ONE vote among several (not OR-channel), threshold adapter fixed on dev; cost-measured sequential load in 24 GB VRAM.

## 5. E2E-agent-1 / E2E-agent-2 (formal verifier line)

- **Mechanism:** certificate-gated all-world formal E2E: LLM frontends (policy H0/GRS, goal obligations, response claims) → binding → worlds (budget 4096) → solver + independent checker → PROVED_ERROR/PROVED_NO_ERROR/UNRESOLVED/INCONSISTENT with re-derivable certificates.
- **Commits:** agent-1 d51aac25/cf1ab776/ff40cbd8; agent-2 4d7fdfb3/4fa2212d/e7eb79c7/5e4bc39e…; final freeze **B4h-sound-v2 @ 315bee3**.
- **Datasets:** own synthetic corpora (69-case, 112-case holdout, 144-case dev); gold by construction.
- **Models:** BAI qwen3.8-flash (later quota-dead).
- **Metrics:** agent-2 dev B4h F1 .8780 (P 1.000, R .7826, FP 0); holdout112 .875; **but on real valid.parquet B4h = F1 .2308 (session A) → .516 (session B)**; C0 legacy Docker = .686.
- **Limitations:** synthetic self-authored; T1 contracts/state_contract research-only metadata; claim-typing nondeterminism at temp 0.
- **Status:** TERMINAL for V1; B4h-sound-v2 is the frozen formal baseline.

## 6. competition-real-input-audit / competition-real-valid-codex (REAL format)

- **Official input:** one text, two blocks: `<prompt>` = full agent context (system policy + tools catalog + user request + prior tool calls/results; markers ⟦SYSTEM⟧/⟦USER⟧/⟦ASSISTANT⟧, arrows `→ TOOL_CALL name: {json}` / `← TOOL_RESPONSE name: {json}` in actual parquet — official ⟦ASSISTANT_TOOL_CALL⟧ markers appear in 0/46), `<response>` = answer to check. Fields: id, prompt, response (+ label/explanation in dev parquet).
- **Official output:** CSV columns `id,label`. **ERROR = contradiction OR unsupported** (quoted definitions in docs/vnext/e2e/COMPETITION_REQUIREMENTS_AUDIT.md). Metric: response-level F1 (primary), P, R. Limits: 30 min runtime, <40 GB, **max 10 successful submissions, 3 final solutions**; network conservatively blocked; GPU A100 (task page) vs H100 (rules PDF) contradiction recorded.
- **T1 premise audit (46/46):** argument schemas/read-char/action-verbs available; freshness/exact writes/effect guarantees/failure-completion semantics 0/46 (G-class) — only manual-T1 could close them.
- **30-min gate:** ~0.055 rows/s live → ~98 rows max; external API NOT competition-ready.
- **Status:** audit complete; the actual Docker submission still runs legacy C0 (.686) — CRITICAL PACKAGING GAP (B4h not wired).

## 7. full-architecture-v1 / semantic-pipeline-v1

- Bakeoff: Clingo/s(CASP)/Drools 43/43 vs incumbent 27/43 → Clingo recommended. real46: N0 TP3/FP0; N5 TP4/FP2.
- semantic-pipeline: retrieval recall .648→1.000; adversarial NLI 8/8; final arms honest-low (A0/A1 TP2, precision 1.0); central finding: V1 lowering cannot consume NL conditions/comparisons/cardinalities.
- Status: implemented + smoke; not promoted.

## 8. codex/fast-followup-20260924

- 350 commits of falsifiable follow-ups on server; service-desk frozen suite (32+32 renamed); C1 AND v4-safe FP-gain traced to family H missing modal `must` — logically UNSOUND, not promotable; source-first parsers exact IR 0/10; staged policy tree V2 10/10 typed-field IR → 8/10 after span audit; Req2LTL/NL2Logic compare: strict full-IR **0/12 every arm**.
- Status: complete follow-up cycle; policy parsing remains open bottleneck.

## 9. Policy-Φ / GRS / formal core

- Policy-Φ native multi-hypothesis: accepted-candidate correctness 23.0% vs P1 53.7% → **NOT admitted** (overgenerates wrong alternatives).
- GRS: Stage A +17.86 pp with oracle inventory, but 3/6 preregistered gates failed → **REJECT_GRS_COMPOSITION**.
- Clingo on public46: 0 violations; as judge-context hurts (.7188 < .7667). Verdict: honest-negative filter on this benchmark; solver itself sound.

## 10. Step-1 working architecture / F5 / F6

- Step1 W1 (v10): dev P .958/R 1.000; F3 sealed .636/.778; F4 .750/.750 — "NOT yet production-ready".
- F5 sealed generalization: v10 **P .406/R .361** — overfit threshold crossed; oracleA (gold nodes + frozen stack) .800/.667 — **relation stack transfers, mention extraction does not**; modular strong-form refuted.
- F6 LLM-first: raw mistral mention coverage 1.000, 0 hallucinated quotes; **rawsan = best real sealed pipeline P .800/R .558/F1 .658**; NLP-first frontend refuted; LangExtract adds nothing; strict-grounding prompt B worse; selective escalation ≤3 pts. Verdict: raw LLM + frozen sanitation = validated direction.

## 11. Integration lines

- integration-research: v10 compatible_nodes accepted 4/8 dangerous same-action/different-object pairs → scope gate 8/8; sealed J graph suite W1 0/8 vs +scope-veto 8/8.
- integration-eval: scope veto no regression on F3/F4 (identical edges 10/10).
- system-integration-step1-4: F6 paired scope-veto RAWSAN .800/.558/.658 vs +veto .758/.581/.658 (default off); Step-2 compiler sealed 20/40 P 1.000; Step-3 response-only strict 1/21; Step-4 refusal sealed 8/8+8/8 (oracle inputs); unified runtime 37 trajectories: 27/37 exact, 11/11 ERROR caught, 0 false ERROR, 54% abstention.

## 12. zai/system-research-v2-20260930

- Full-auto sealed: universal Φ 10/20 (.50) exact 3-way, decided .25, acc decided .800, ERROR recall .40, **0 false ERROR**, UNKNOWN .75; error-existential 11/20.
- **Oracle decomposition: gold Step 1 alone lifts 10/20 → 17/20, ERROR recall .40 → 1.00** — Step 1 (automatic Policy Program acquisition) is the single dominant bottleneck; gold Steps 2/3/4 change nothing.
- Negatives: compositional parsing killed; CEGIS semantic falsifier found nothing to fix (value = compile-failure CEs + cross-model repair); wrong invariant broke a correct program (museum 4/4→1/4); prose contracts P/R .30; universal consensus suppresses correct Φ2 verdicts (archive 3 cases); sealed transfer gap 25 points.
- Simplest architecture (§20): raw policy+catalog → ONE strong LLM one-shot program → programmatic validation → bounded repair w/ cross-model fallback → second extractor as independent Φ → frozen proof runtime per Φ → universal consensus, escalate verdict-divergent (~15%).
- Cost: 336 API calls, ~403K tokens.

## 13. AgentHallu adapter & runs

- Adapter `benchmarks/agenthallu_v1/`: question-grouped split DEV 488 / LOCKED 205 (CC BY 4.0, rev 9ffe8bc); input.csv id,prompt,response; trajectory-level gold + first-error localization.
- Runs: zero-baseline F1 0; granite 3.3 groundedness DEV F1 .4043 (P .644 R .295) — honest negative; E6 blockrun in-flight ~30%, no completed numbers.
- Discipline: all tuning was on public46/valid.parquet (burned as external regression); AgentHallu DEV measured once with granite; LOCKED 205 never opened.
- **NEW requirement for F/S/V:** AgentHallu = external regression slice; distinguish trajectory label vs first-error step vs Guardian-compatible subset; previously-used examples = external regression only.

## 14. Past trainings

- **Exactly two small LoRA trainings exist, both event-identity cross-encoders, both FAILED:** BAAI/bge-reranker-base 3-way CE (r=8, α=16, 3 epochs, seed 20260928) — sealed TP0 FP0 FN32; binary CE 8 epochs — sealed TP0 FP2 FN32, 78 UNKNOWN. Both rejected; 8-shot Mistral identity judge beat both.
- No QLoRA, no full fine-tune, no unsupervised/axolotl/deepspeed anywhere. **A trained verifier B or trained aggregator has NEVER existed** — S5/S6/S7 and the T-line are genuinely new territory.

---

## The confirmed q_dispatch_vs_check defect (§3 directive)

**VERDICT: CONFIRMED** in `experiments/searh_23/system_research_v2/probe_tasks_2to5.py` (T4_QUESTIONS):

```python
{"id": "q_dispatch_vs_check",
 "policy": "A parcel may be dispatched only if its inspection passed. Checking inspection does not dispatch the parcel.",
 "question": "Does checking the inspection satisfy the dispatch condition?",
 "A": "yes - checking is the required evidence", "B": "no - only a passed inspection result satisfies it",
 "answer": "A"}
```

The gold `"A"` counts the mere act of checking as satisfying the dispatch condition, while the policy requires the inspection to have PASSED. The system's own authoritative artifacts for the same policy require the positive result (`parcel.inspection_passed` OBSERVED=true; depot.failed_gate world fact → ERROR). All 4 probed models answered B and were scored incorrect (`outputs/probe_task4.json`).
**Impact (bounded):** affects only the Task-4 role probe and the "contrastive resolver ≈ 6/8" figure (→ 7/8 corrected); model ranking unaffected (uniform −1); sealed full-auto metrics NOT contaminated (main system gold encodes the check RESULT correctly).
**Action per directive:** corrected version + diagnostic rescore saved alongside the original frozen version; historical numbers not silently overwritten (see `experiments/searh_23/system_research_v2/probe_task4_rescore/`).

---

## What is genuinely NEW in F/S/V (never tried anywhere in history)

1. **V: k=3/5 repeated verdicts (sampling/self-consistency) from a single judge** — every historical verdict is one greedy temp-0 call; no resampling, no vote-level variance analysis.
2. **V: cross-family voting with Granite as one vote member** (not OR-channel); quorum/fallback/degraded-row accounting; predictions.csv + audit.jsonl written atomically from the start.
3. **S: trained LoRA verifier B and trained (logistic) aggregator** — the only trainings in history are the two failed identity CEs; all aggregators were fixed rules.
4. **F: joint typed-substitution sensitivity with small-form exhaustive enumeration and STABILITY_NOT_ESTABLISHED semantics** — mutations library applies only single-point mutations; refutation recall vs a specific accusation never measured on sealed data.
5. **Common evaluation substrate:** 100+ new cases / 20 families (10 dev / 10 sealed), hard pure-negative cases, gold NOT produced by the evaluated runtime, τ-bench/τ²-bench external regression (AgentHallu DEV already granite-measured once), rename invariance inside families, and a uniform cost model (calls/tokens/latency/VRAM) across F/S/V.

## Design constraints carried into F/S/V from this audit

- public46 is PUBLIC_SEEN (burned); hotel synthetic is single-author; a THIRD fresh unseen domain is the honest frontier → the new holdout must be fresh and family-disjoint.
- Zero false ERROR is a hard-won property of every frozen line — preserve it in V's fallback design (absence of votes must not become confident 0).
- Structural channel abstains out-of-domain (hotel 0/20) — structural "1" must require a reproducible basis, and abstention must be explicit.
- Judge FP overlap is real (up to 14 shared FP) — cross-family independence must be measured, not assumed; vireonix `auto` family unverifiable → never count it as an independent family.
- The Step-1 bottleneck dominates any architecture that needs full policy programs; F (per-turn requirement form) deliberately avoids it — that avoidance is itself the hypothesis.

---

# ЧАСТЬ 2 — Аудит для задания HYBRID SERVICE (2026-10-01)

Контекст: ветка `research/hybrid-service-20261001` (от `research/three-architectures-24gb-20260930` @ 4df13b97).
Метод: чтение кода + `git log --follow` + пересчёт закоммиченных outputs напрямую (не пересказ доков).
Формат строк: компонент → файл/коммит → реальное подключение → данные → модель/промпт → измерения → ограничение → статус RUN/SMOKE/NOT_RUN/BLOCKED + ORIGINAL/ADAPTED/NEW.

## 15. GE: механический граф свидетельств (плоские модули)

| Компонент | Файл/коммит | Подключение | Данные | Модель | Измерения | Ограничения | Статус |
|---|---|---|---|---|---|---|---|
| `guardian_truth.parsing` | `src/guardian_truth/parsing.py` @ 421f9616 (2026-09-05, не менялся) | **ЖИВОЙ КОРЬ**: `scripts/predict.py` → `cli.main` → `pipeline.Detector.review()`; ~60 импортёров | public46/valid.parquet | нет (детерм.) | E1 offline TP12/FP0 F1 .6857; graph-mode live 8 строк F1 .750 (gpt-oss-20b) | только 2 диалекта маркеров; не-JSON результаты не индексируются | RUN, ORIGINAL, live |
| `guardian_truth.provenance` | `src/guardian_truth/provenance.py` @ 421f9616 | **ЖИВОЙ**: `Detector.review()` строит граф при включённых семьях проверок; кормит `check_rules`/`analyze_plan`/`AnalysisContext` | те же | нет | через каналы-потребители; 23 юнит-теста | структурный only: нет семантических алиасов, статусов мира, авторизации (докстринг) | RUN, ORIGINAL, live |
| digest `g_graph` | `experiments/superz_fullcycle/g_graph.py` @ d0d3935b (single) | standalone; `graph_digest` импортирован ≥12 поздними скриптами (S5/S6/S7/P/Q) | public46 + E3a suspicions 94 | blockrun/pollinations (L7-каналы) | a4g F1 .5778 < A4 .6222; gjudge F1 .4 (n=29/46, 17 FAILED); combo a4gp .6154; **flash-G1 (ветка flash-20260921, 7e8b6cde, НЕ в этой ветке): digest верификатору F1 .6667 vs Base .6207, UNCERTAIN 12→1** | outputs g_graph не закоммичены в ветке (сохранились chain4-логи); judge-side — честный негатив, verifier-side — единственный позитив | RUN (логи), ADAPTED |
| S5 graph-as-context | `experiments/full21/s5_graph_granite.py` @ 2d6a35ba | standalone leaf | public46 46 | granite-3.3-8b groundedness, 12k бюджет | digest-only **F1 .6032 (21 FP!)**; graph_quotes .6977; plain_summary .5818; контроль .7805 | факт-ЛИСТ как контекст раздувает FP независимо от «графовости»; вывод: польза графа — на стороне верификатора | RUN, ADAPTED |

## 16. Φ: формальная линия (RuleIR → солверы)

| Компонент | Файл/коммит | Подключение | Данные | Модель | Измерения | Ограничения | Статус |
|---|---|---|---|---|---|---|---|
| `semantic_pipeline_v1` (rule_ir.py) | 20 модулей @ 243cc8a0→831f6680 (2026-09-17..20) | библиотека экспериментов; НЕ в cli.py | dev46+17 synth | Mistral API + NuExtract-1.5-tiny + GLiNER + NLI | fragment recall .648→1.000 (union); Φ-кандидатов NLI-veto 28%; binding 18/36 BOUND; финальные Guardian-arms A0/A8 F1 .160/.083, synth 0/17 | lowering не умеет NL-условия/сравнения/кардинальность → UNRESOLVED | RUN, ORIGINAL, standalone |
| `p_precond_api` (P-line) | `experiments/big_researh/p_precond_api.py` @ d34d6dae→a74a37ef | standalone; pgjudge-выход → investigator-v2 | public46 | Mistral ministral-14b | extract 46/46→43 OK, 112 карт, 88 grounded; **pjudge F1 .7018; pgjudge R 1.0 F1 .7419** (fresh, 7c058526); pgljudge/pglcljudge .7458/.7188 — UNVERIFIED (журналы потеряны в ресете); +L/+C монотонно ухудшают | карты-как-контекст судьи теряют нюансы; пред-ресет числа UNVERIFIED | RUN (частично UNVERIFIED), ADAPTED |
| `q_discriminator` (Q-line) | `experiments/big_researh/q_discriminator.py` @ d34d6dae; v2 `searh_23/q_discriminator_v2.py` @ 42543a90 | standalone | public46 + S6/S9 каналы | Mistral | v2: 3434 расхождения, 12 deep, **verified 5/12, downstream flips 0**; v1 (3332/12/5/1) — UNVERIFIED | Q не срабатывает, когда оба канала пусты; перекрытие coarse | RUN, ORIGINAL |
| S8 Clingo verify | `experiments/big_researh/s8_clingo_verify.py` @ ea9e7069 | standalone; карты → RuleIR → B1-B4 → ASP | fresh карты P-line | нет (детерм.) | 112 карт, 88 grounded, 44 bound, **0 violated, 60 unknown** (49 applicability_unknown + 16 unobservable); контроль не изменён | премис-обсервабельность = блокер; B1-B4 покрывают 4 формы | RUN, ADAPTED |
| `full_architecture_v1` | pipeline.py+facts_builder+certificate @ 0c2bda7e→655f495f (2026-09-18..19) | standalone; никогда не промоутен | real46 + синтетика | Mistral (замороженные Φ) | bakeoff 43/43 sound, brave/cautious EQUIV; сертификаты 43/43 tamper-detected; **N5 real46 sound-lowered TP3/FP0 F1 .2308** (после строгого lowering); N0 incumbent TP3/FP0 | per-case outputs НЕ закоммичены; замороженная Φ-зависимость | RUN (артефакты частично утеряны), ORIGINAL |
| Формальные frontends A/B/C/D/E | `policy_architecture_abcd_v{1,2}.py` + 4 доки (REQ2LTL/NL2LOGIC, SOURCE_POLICY, STAGED_TREE, SOURCE_FIRST) @ 2026-09-26..27 | standalone | 10-12 политик (authored) | Mistral | **exact IR 0/12 и 0/10 ВСЕХ рук**; C OnionL/Req2LTL 0/19; D NL2Logic 1/19; E source-first 2/22, verifier принимает 17/18 собственных ошибок; staged B лучший (но не готов) | binding действие↔условие не решён ни одним frontend-классом | RUN, ORIGINAL/ADAPTED |

## 17. Census формальных движков (запускались/нет)

| Движок | Статус | Где/что измерено |
|---|---|---|
| **Clingo 5.8.2** (in-process) | **RUN, многократно** | bakeoff 43/43/58/0-unsound; scaling 0.01-0.9s; S8; Q minimal-check; H-solver CP-SAT-согласие 28/28, срезал 0/38 рёбер; Declare-BMC 13/13/13 + цикл UNSAT |
| **s(CASP) 1.1.4** (SWI 9.2.9) | RUN | 43/43, 46/46, 58/58; ~2.2-35.8s/query; 6 engine findings F1-F6 |
| **Drools 10.2.0** | RUN | 43/43, 46/46, 58/58 |
| **Soufflé** | SMOKE (probe) | рекурсивный Datalog + provenance explain 0.02s |
| **Z3 / CVC5 / PySMT** | **NOT_RUN** (ни одного `import z3` в репо; только будущее-обсуждение в handoff) | — |
| **LPS** | **NOT_FOUND** (0 упоминаний) | — |
| **Logical English / LE2** | **NOT_FOUND** (0 упоминаний) | — |
| **LogicLLaMA** | **NOT_FOUND** (0 упоминаний) | — |
| **Logic-LM** | NOT_RUN (1 строка будущего-обсуждения) | — |
| **LINC** | RUN как внутренний «LINC-like» ограниченный переводчик (V7 arm D): 4/4 валидных, перевод нестабилен 0/2 → shadow_only | `src/guardian_truth/formal_reasoning.py` @ e7d8b4ed |
| **NL2Logic / Req2LTL** | RUN (минимальные репродукции): 1/19 и 0/19 директив, 0/12 exact IR | policy_architecture_abcd |
| **NuExtract** | RUN: NuExtract-1.5-tiny modality .412; NuExtract3-W4A16 S9 46/46 карт (judge-абляции с картами .2286-.375 — негатив) | — |

## 18. Census внешних checkers (MiniCheck и пр.)

| Checker | Статус | Факты |
|---|---|---|
| **MiniCheck** | **NOT_RUN, DEFER** (EXPERIMENT_MATRIX.md:20 «Pending… DEFER until Granite tool-call smoke»); адаптера и outputs НЕТ | единственные упоминания — 4 manual-хендофа + матрица |
| **FactCG** | **NOT_FOUND** — 0 упоминаний в репо | — |
| **RefChecker** | NOT_RUN, cited-only (implementation_strategy.md:27, цитата arXiv 2405.14486) | — |
| **LettuceDetect** | **RUN, bounded-negative**: `ld_locator.py` @ 42763bab; public46 42 спана/12 кейсов, **найдено 0 пропущенных ошибок**, +1 FP на сьют; qwen-2b генеративная версия unusable (спаны битые) | не промоутен |
| **Jev** | RUN в ФОРМЕ только (TypeSafe Jev API НЕ использовался): TQ-слой public46 in-sample F1 .920 0-TP-lost; hotel перенос 0 изменений | «формой» — ministral |
| **ShieldAgent** | **NOT_FOUND** (0 упоминаний) | — |
| **Amazon Automated Reasoning** | NOT_RUN, design-review-only (GOAL_PLAN_V3 доки; Goal v2 22/22 UNRESOLVED) | — |
| **S4L→Prolog** | **NOT_FOUND** | — |
| **Granite Guardian 4.1 BYOC** | SMOKE: F1 .8095 vs 3.3 .7805 на общем протоколе; **OR-добавка 0** (все 4.1-хиты покрыты structural); как JSON-3rd-checker отклонён (нативный `<score>` yes/no) | доступен локально на инстансе (16G, rev ab01ccca) |

## 19. Integration/system-линии (2026-09-30)

| Компонент | Файл/коммит | Подключение | Измерения | Ограничения | Статус |
|---|---|---|---|---|---|
| `integration/` proof runtime | 12 файлов @ 2ac1c0a0→6194168d | standalone + 47 тестов; **НЕ в live-detector** | 37 траекторий: **27/37 exact, 11/11 ERROR, 0 false ERROR, 54% UNKNOWN**; ablations: no_reachability теряет refusal, first_prior даёт false ERROR, no_claim_evidence 17→13 | oracle-границы (ручные программы); Step-3 binding прячет 4 кейса в UNKNOWN | RUN (SMOKE-масштаб), NEW |
| `system_research_v2` | suite+arms @ 869feac1→ab6f0335 | standalone | sealed: universal Φ 10/20, err-exist 11/20; **gold_S1 17/20 (ERROR recall 1.0)** — Step-1 = доминирующий блокер; Step-3 sealed P 1.000 R .458; Step-4 4/4; 336 вызовов ~403K токенов | 6 открытых дефектов доверия (§21) | RUN, NEW |
| `run_f6_graph` (scope-veto) | @ f664f3fb | paired replay | base .800/.558/.658 vs +veto .758/.581/.658 → default OFF | негатив-идентификация veto, без F1-выигрыша | RUN, ADAPTED |
| `llm_first_f6` | 24 py @ 3345bb97→57b7dfc3 | standalone; rawsan → Step-1 кандидат | см. §10 выше; rename: codestral 6/6, mistral 1/6; CF 2/6 | Granite-экстрактор BLOCKED (gateway 503 ~4h) → F7 | RUN, NEW |

## 20. Micrograph-сертификаты (bounded-грамматики, детерминистические)

| Компонент | Механизм | Измерения | Ограничения | Статус |
|---|---|---|---|---|
| `micrograph_certificate_v1` + replay | 3 regex-anchored bullet-паттерна (PRECONDITION/LATEST/AFTER_SUCCESS), tool-роли из описаний, всякое покрытие OPEN→UNKNOWN; seal+replay | **48/48 на 4 сьютах (repair, repair_renamed, parcel_v1, parcel_v1_renamed), 0 FP**; baseline raw-mistral на том же parcel: TP6/FP2 → micrograph убрал 2 FP | authored; 3 false-SAFE контрпримера найдены независимым аудитом и закрыты (b4087062); перенос формулировок: coverage 0 (36 UNKNOWN) на 3 парафраз-сьютах | RUN, ORIGINAL |
| Level-F endpoint certificate (E1/E3/E3W) | экстрактор обязан дать a_anchor/b_anchor как точные спаны + верификатор Q1-Q5 + детерминированный verify_certificate; E3W = AMR-witness veto | юниты 22: E1 1/22 (6 false-SUPPORTED) → **E3 11/22, 0 false-SUPPORTED, 9 UNKNOWN**; E3W ≡ E3 (AMR veto 0 срабатываний); Track B FULL_GOLD+E3 P .565/R .565; sealed F2: real frontend 0/8, 18 extra; rename 15/15 | real-frontend + E3 коллапсирует; «Step 1 не готов к интеграции» | RUN, ORIGINAL |

## 21. Открытые дефекты доверия V2-линии + archive-баг (найдены этим аудитом, НЕ документированы ранее)

1. **archive `(D∧S)∨P` vs `D∧(S∨P)` — ПОДТВЕРЖДЁН В КОДЕ, НЕ ДОКУМЕНТИРОВАН**: `v2_domains_sealed.py:594-609` `archive_programs()` кодирует gate как `{"unless": {base: D∧S, exception: P}}` = (D∧S)∨P, тогда как текст политики («Publishing is allowed with only the declassification when public interest» → public interest отменяет ТОЛЬКО sign-off) читается как **D∧(S∨P)**. Различающий угол **D=false, P=true** не покрыт ни одним из 4 archive-кейсов — потому self-verification 40/40 прошла. Протокол §5.2 задания: регрессия на всех 8 комбинациях D/S/P + чтение vs публикация, gold НЕ из archive_programs.
2. conveyor 4 → C4 нормализации НЕТ (claims quarry → `literal_entity_value_or_scope_unbound` → UNKNOWN); `_transit_goal` вручную делает split("passenger ") — только для transit gold.
3. Boolean-наблюдения → `_literal_value` пропускает bool («polarity requires licensed interpretation») → STATE_CLAIM о boolean-чтении непривязываем.
4. Модельные контракты штампуются `DOC_EXPLICIT` (`steps_2to4.enriched_case` + `contracts.acquire_documented`), EXECUTED-прочтения check-инструментов не закрыты контрастивом.
5. `quote_ok=false` — декоративный флаг (`apply_contrastive` применяет re-strength/rename независимо).
6. `candidate_actions_exhaustive: True` захардкожен при пустых valid_calls → CLOSED «no capability» неотличим от провала извлечения.
7. S1-E repair-loop (tool recall .60→.80, atom F1 .700→.750) НЕ подключён в `system_eval.auto_programs` — full-auto 10/20 не включает repair-выигрыши.
8. Документировано и ИСПРАВЛЕНО только q_dispatch_vs_check (cb14bc88, frozen-копия сохранена, история не перезаписана).

## 22. Гибриды УЖЕ БЫЛИ (§2 задания — «не объявляй граф+LLM новым изобретением»)

- `p_precond_api`: pjudge (карты) → pgjudge (+graph digest) → pgljudge (+langextract) → pglcljudge (+clingo) — полный каскад «текст + карточки → граф → извлечение → Clingo» измерен на public46 (см. §16).
- `g_graph`: a4g/gjudge — влияние механического графа на верификатор и на первого судью отдельно (§15).
- full_architecture_v1 N1-N5: frontend-типизация × Clingo POLICY × Clingo EVIDENCE × сертификат+checker (§16).
- system_research_v2: Φ1×Φ2 консенсус + оракул-декомпозиция по шагам (§19).
- Вывод для нового эксперимента: «граф без Φ» (GE/GP→судья), «Φ без графа», «граф+Φ» — все три клетки центрального квадрата имеют исторические аналоги, но ни одна не была прогнана в едином harness на свежих данных с одинаковым судёйским промптом — это и есть новая ось.

