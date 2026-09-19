# Guardian of Truth / AI Journey 2026 — MASTER HANDOFF

**Дата среза:** 19 сентября 2026 года. **Назначение:** передача проекта новому агенту без потери истории отрицательных экспериментов, параллельных веток, soundness-инвариантов, результатов и незавершённых задач. **Репозиторий:** https://github.com/MYC-A/Guardian-of-Truth. **Официальная задача:** https://dsworks.ru/champ/aij26-guardian.

> ВАЖНО О ПРОИСХОЖДЕНИИ. В этом документе различаются: **[GIT]** — найдено в публичном удалённом GitHub (коммит/файл/отчёт); **[LOG]** — предоставленный пользователем лог текущего агента, возможны незакоммиченные/игнорируемые артефакты; **[CHAT]** — обсуждение/предложение в доступном контексте прошлых бесед; **[PLAN]** — предлагаемое, но НЕ подтверждённое как реализованное/протестированное. Цифры на разных корпусах/моделях/коммитах НЕ сравниваются как общий рейтинг. Я не получил полный текст всех внешних shared-чатов: одна из ссылок на ChatGPT Share при попытке чтения была недоступна. Поэтому документ максимально подробен по доступным беседам, пользовательским файлам, GitHub и логам, но не претендует на буквальную расшифровку каждого сообщения каждого чата. Новому агенту надлежит дополнить его свежими локальными артефактами и исходными директивами.

## 0. Что надо знать в первые пять минут

1. Это **конкурсная бинарная классификация RESPONSE по PROMPT**, а не произвольный agent guardrail: 1 означает контекстно неверное/необоснованное утверждение ИЛИ действие, включая неверный tool/args, 0 — нет ошибки. Цель — F1 при реальном ограничении Docker, времени и локальных весов. PUBLIC `valid.parquet` содержит 46 уже просмотренных примеров (23 положительных/23 отрицательных) с `explanation`. Это development, не hidden, нельзя настраивать production по ID/объяснениям.
2. Исторически существовали **две несовпадающие линии**: старый production `main`/V5.3 (one-shot Groq + проверенные точные Python-правила) и лабораторный vNext/E2E (доказательства, UNKNOWN, миры, сертификаты). Позднее от E2E-agent-2 независимо ответвились две реальные конкурсные линии и две линии semantic pipeline. **Нет одной ветки, содержащей всё автоматически.**
3. **Самая важная soundness-находка:** `10 TP / 0 FP / F1=.606` у `codex-update-run` получено с неявным предположением, что `[AVAILABLE TOOLS]` является замкнутым набором, а все неописанные поля объекта запрещены. Аудит выявил, что эти предпосылки **не подтверждены источником** (есть discoverable tools и действия клиента вне каталога). Замороженная исправленная линия `4639b46` выдаёт `3 TP / 0 FP / F1=.230769`; результат `.606` НЕ считать строго доказательным/по умолчанию production. При этом сам конкурсный decision-layer может использовать недоказанный, но полезный статистический сигнал — с отдельной маркировкой, не подменяя proof-core.
4. **Новые движки уже проверены на нейтральных формальных входах:** Clingo, s(CASP), Drools — 43/43, incumbent 27/43; Clingo evidence на 52/52 синтетических оракульных примерах. Это **не означает** хороший E2E F1: доставка исходного NL-смысла в формальный контракт, полнота интерпретаций и final decision остаются отдельными вопросами.
5. **Новая Full Architecture V1 НЕ является finished winner.** В GitHub ветка `full-architecture-v1` на момент проверки заканчивается WIP-коммитом `923bb445...`: код/адаптеры SafePyramid, BARRED, FOLIO, ProofWriter есть, но значительная часть результатов находится только в логе агента/игнорируемых `outputs/full_architecture_v1/`; последний ContractNLI ещё не завершён. В логах N0=3 TP/0 FP; в коммите фаз A–E прямо указано N5=4 TP/**2 FP**, т.е. «сертификат валиден» НЕ равняется «правильно поняли естественный язык».
6. Пользователь **не рассчитывает на сильную/платную удалённую LLM в финальном решении**. Mistral/BAI/Groq/Gemini использовались в исследовательских экспериментах. Нужны локальные компактные модели, готовые специализированные детекторы, разные архитектуры и проверка финального офлайн Docker. Не просто нарастить NuExtract+GLiNER+Clingo.

## 1. Официальный конкурс и реальный вход

Источник: [аудит регламента от 16.09](https://github.com/MYC-A/Guardian-of-Truth/blob/competition-real-input-audit/docs/vnext/e2e/COMPETITION_REQUIREMENTS_AUDIT.md). Официальные [страница задачи](https://dsworks.ru/champ/aij26-guardian), [правила PDF](https://gitverse.ru/api/repos/gitverse/AIJ/raw/branch/master/AIJourney2026-rules-ru.pdf). Перепроверить действующую версию до отправки: документ фиксирует состояние на 16.09.

- Вход платформы: CSV с `id,prompt,response`; output CSV строго `id,label`. `response` включает текст ИЛИ новые tool calls с аргументами. `prompt` содержит SYSTEM (policy/instructions/catalog), USER, ASSISTANT, tool calls/results и историю; в реальных 46 разработческих кейсах используется стрелочный транспорт `→ TOOL_CALL ...` / `← TOOL_RESPONSE ...`, а официальный контракт описывает также маркеры `⟦ASSISTANT_TOOL_CALL ...⟧` и `⟦TOOL_RESULT ...⟧`. Различать CALL от RESULT и USER от ASSISTANT.
- Публичный `valid.parquet`: 46 строк, 23/23 классов; четыре доменные группы airline/banking_knowledge/retail/telecom; некоторые prompts до ~233k символов; target response бывает текстом и вызовами инструментов. Английские политики и русский диалог могут смешиваться. `label`/`explanation` не доступны inference.
- Официальный смысл ошибки: contradiction И unsupported по отношению к контексту, когда это влияет/может влиять на итог или данные пользователя. Правильные перефразирование/форматирование/округление — не ошибка сами по себе. Структурный дефект вызова может быть ошибкой, если нарушает реальный контракт; **формальные предпосылки о запрете лишних полей надо обосновывать отдельно**.
- По аудиту: `python scripts/predict.py --input ... --output ...`; Docker меньше 40 ГБ, скрипт 30 минут, лимит успешных сабмитов 10. Страница задачи указывала A100, PDF — H100; для локального бюджета безопаснее ориентироваться на A100 40 GB. Доступность внешней сети **для задачи 1 не установлена** (а не доказанно запрещена), значит рабочий финальный пакет нельзя делать API-зависимым без проверенного разрешения/реального теста.
- Никакие экспериментальные метрики на 46 dev-кейсах не являются leaderboard-результатом или прогнозом hidden.

## 2. Ветка за веткой: проверенная удалённая карта

На момент чтения GitHub **девять опубликованных веток**: `main`, `experiment/guardian-vnext-from-0199bf9`, `E2E-agent-1`, `E2E-agent-2`, `competition-real-input-audit`, `competition-real-valid-codex`, `codex-update-run`, `semantic-pipeline-v1`, `full-architecture-v1`. Ветка `core-engine-bakeoff-v1` встречается в логах/документе, но **НЕ показывается среди удалённых веток**; её коммит `bf972b0...` существует как предок `full-architecture-v1` и её файлы там сохранены. Локальные worktree, удалённые неотправленные коммиты, untracked и игнорируемые outputs могут отличаться — проверить на месте.

```text
main (afb7906, V5.3; отдельный legacy production)
   └─ experiment/guardian-vnext-from-0199bf9 (8b0d13c, vNext baseline)
        ├─ E2E-agent-1 (d790a23; frozen кандидат ff40cbd, A1)
        └─ E2E-agent-2 (315bee3; frozen B4h-sound-v2)
             ├─ competition-real-input-audit (67e81c7; реальный input/adapters, C0/C3)
             ├─ competition-real-valid-codex (300dc2e; FN audit, catalog axis, witness fix)
             ├─ codex-update-run (869a93a; конкурсный adapter, 2 fixes,
             │  затем soundness-correction 4639b46,
             │  затем эксперимент semantic_pipeline_v1 4e6d200)
             │   └─ core_engine_bakeoff_v1 COMMIT bf972b0 (ветку remote не нашли)
             │       └─ full-architecture-v1 (0c2bda7 → WIP 923bb445)
             └─ semantic-pipeline-v1 (0d8d804; отдельная альтернативная реализация
                src/guardian_truth/semantic_pipeline_v1, не предок full-architecture-v1)
```

**Важное уточнение DAG:** `semantic-pipeline-v1` и `competition-real-valid-codex` разошлись от `315bee3`; `codex-update-run` и `competition-real-valid-codex` тоже параллельные линии. `full-architecture-v1` происходит от `codex-update-run` через `4e6d200` и `bf972b0`, а **не** от одноимённой ветки `semantic-pipeline-v1`. Не пытаться cherry-pick целую ветку по созвучному названию. Точные отношения перед любым merge проверять через `git merge-base`, `git log --graph`, `git diff`.

### 2.1 `main` — старый production (HEAD `afb7906c3a3244fbc4196fe5cb2ea18ee86e0d96`)

[Ветка](https://github.com/MYC-A/Guardian-of-Truth/tree/main) · [README](https://github.com/MYC-A/Guardian-of-Truth/blob/main/README.md) · [V6](https://github.com/MYC-A/Guardian-of-Truth/blob/main/docs/V6_RESEARCH_CYCLE.md) · [V7](https://github.com/MYC-A/Guardian-of-Truth/blob/main/docs/V7_FORMAL_REASONING_CYCLE.md) · [V9](https://github.com/MYC-A/Guardian-of-Truth/blob/main/docs/V9_OUTER_SEMANTICS_CYCLE.md).

**Есть:** legacy `scripts/predict.py → cli → pipeline.Detector`, parser двух форматов, структурные tool/catalog/schema проверки, источники значений, граф наблюдений, точные date/action/policy prechecks, optional one-shot semantic backend, fallback и shadow формальные прототипы. Полный предсказательный путь здесь исторически реален; vNext не импортируется этим `predict.py` автоматически.

**Проверено (все числа на 46 viewed dev, НЕ на hidden):** автономная база `TP=6 FP=0 FN=17 TN=23 F1=.414`; 51 синтетический case `TP=12 FP=0 FN=3 TN=36 F1=.889` (механизм, не конкурсная оценка); Groq GPT-OSS-20B one-shot `14/5/9/18 F1=.6667`, 18 fallbacks, 40 logical calls/99 HTTP/143389 tokens, 1104 сек; V6 один exact action-cardinality precheck поднимает `.6667→.7273` (16/5/7/18); V7 точный date-gated-action добавляет 1 TP без FP `.7273→.7556` (17/5/6/18). Exact-only после V7: 12 TP/0 FP/11 FN/23 TN, F1≈.6857. [V7](https://github.com/MYC-A/Guardian-of-Truth/blob/main/docs/V7_FORMAL_REASONING_CYCLE.md).

**Отрицательные пробы:** structured UNKNOWN/recovery на 12 строках `.5455→.5000`, +1 FP, 0 исправленных FN (выключено по умолчанию); граф/RLM на 8 строках не запросил дополнительных источников; claim-gate strict vs relaxed на 46 одинаковый F1=.6667, relaxed +1 TP/+2 FP; минимальная декомпозиция extractor→verifier остановлена по coverage-gate (Groq/Gemini пропускали важные числа), `KEEP_ONE_SHOT`; narrow verifier на 16 проверках 12/16 correct, но лишь 4/8 реальных обвинений, не внедрён; Gemini неоднократно 429; FaiRR 2/4 schema/source-valid, LINC-like final relation 4/4, но перевод нестабилен 2/2, оба shadow; CEL не внедрён, потому что не решает NL→формальный смысл. [DECOMPOSITION_RESULT](https://github.com/MYC-A/Guardian-of-Truth/blob/main/docs/DECOMPOSITION_RESULT.md), [V7](https://github.com/MYC-A/Guardian-of-Truth/blob/main/docs/V7_FORMAL_REASONING_CYCLE.md).

**V9 outer semantics:** прототип `Phi_working ⊆ Phi_outer`, structural holes, explicit uncertainty, две SAT-проверки; 15/15 synthetic metamorphic, НО на 16 реальных правилах покрыто лишь 45/84 конструкционных признаков, 0/16 проходят gold-audit gate, strict 3/19 diagnostic, 0/3 confident-wrong. Translator НЕ принят в production; проблема `φ* ∉ Φ_outer` не решена. Отсутствие противоречия на ограниченном Φ не доказывает полноту естественного правила.

**Чего нет:** не считать `main` финальной новой архитектурой; нет внедрённого Clingo FullArch, нет подтверждённого end-to-end нейросимвольного улучшения hidden; `main` должен оставаться воспроизводимой исторической опорой.

### 2.2 `experiment/guardian-vnext-from-0199bf9` — фундамент vNext (`8b0d13c1147531f4513d084ed99dc7133bfdcc92`)

[Ветка](https://github.com/MYC-A/Guardian-of-Truth/tree/experiment/guardian-vnext-from-0199bf9) · [архитектура](https://github.com/MYC-A/Guardian-of-Truth/blob/experiment/guardian-vnext-from-0199bf9/docs/vnext/ARCHITECTURE.md) · [протокол](https://github.com/MYC-A/Guardian-of-Truth/blob/experiment/guardian-vnext-from-0199bf9/docs/vnext/BENCHMARK_PROTOCOL.md) · [PROGRESS](https://github.com/MYC-A/Guardian-of-Truth/blob/experiment/guardian-vnext-from-0199bf9/docs/vnext/PROGRESS.md).

**Идея:** Normalizer → append-only Evidence Ledger → separate Policy / Goal / target Claim frontends → T1 trusted contract + T2 untrusted effect proposal → indexed candidate binding → множество допустимых миров → four-valued solver → certificate/checker → adapter. Роли, call/result pairing, exact sources, actor/entity/time boundaries. Только trusted premises могут подтверждать effect/state/causality. UNKNOWN не равен FALSE. Не выбирать одну трактовку по confidence, не считать retrieval miss доказательством отсутствия.

**Проверки до E2E:** T1 16/16 применимых fixture cases и 2 NOT_APPLICABLE, false no-effect/causal=0; T2 18/18 transport/schema, known-true recall 1/4, restricted positive precision 1/8, 9 ambiguous + 9 unknown, ledger pollution=0 — не promoted как trusted эффект. Claim Graph 41 case, span F1=1 на 39 полностью аннотированных, но типизированный gain gate провален: object 9/36, predicate 16/36, actor 21/37; 410 запросов vs C2 41 и большая стоимость. Policy-Φ 104 case: 61/265 candidate behaviorally correct (23%), строгий all-candidate yield 2/104; больше кандидатов часто хуже при consensus; не принят. Goal v1/v2: оба 22/22 UNRESOLVED, v1 15/22 schema-valid; v2 176/190 schema-valid, 0 сертификатов. Binding/temporal source-backed v2: 34/34 typed truth и scoped binding, TRUE14/FALSE8/UNKNOWN12, 2/2 ambiguity preserved, API=0 — это контрольная typed задача, не E2E NL. Goal v3 extraction: см. отдельные docs в ветке; отдельные экспериментальные конфигурации отклонены по ошибочному связыванию обязательств и zero certificate, не считать готовой целью.

**Важное:** frozen vNext-корпуса и stage fixture-результаты зачастую содержали РУЧНЫЕ trusted T1/state/closure/authoritative fixtures; это НЕ факты, доступные из настоящего `prompt,response` конкурса. Ранние `blind/holdout` после просмотра стали development. Не сравнивать stage F1 с contest F1.

### 2.3 `E2E-agent-1` — E2E и scoped UNKNOWN

[Ветка](https://github.com/MYC-A/Guardian-of-Truth/tree/E2E-agent-1), tip `d790a23...`; **замороженный кандидат — не tip, а `ff40cbd897eaadafd2a8bb89578cad2cff49bd27`, arm A1**. [E2E результаты](https://github.com/MYC-A/Guardian-of-Truth/blob/E2E-agent-1/docs/vnext/e2e/E2E_V1_RESULTS.md), [repair report](https://github.com/MYC-A/Guardian-of-Truth/blob/E2E-agent-1/docs/vnext/e2e/E2E_AGENT1_REPAIR_RESULTS_RU.md).

**Есть:** E2ECaseInput, source adapter/TEXT vs ACTION view, H0 и refined GRS policy, Conservative/RuleFrames goal, T1/T2, claims, bindings, v3 DSL, exact Cartesian worlds, 4-valued consensus, independent certificates. 5 arms E0–E4. Исходный E0 на 69 конструированных dev: certified coverage=.246, ERROR recall=.188; retention E4 ухудшал coverage до .174.

**Исправление:** глобальные claim UNKNOWN маскировали независимый certified violation. A1 scoped UNKNOWN: сертифицированный FALSE в полной оси доминирует над посторонними неизвестностями, но NO_ERROR остаётся строгим. Dev 69 (32 ERROR, 24 NO_ERROR, 12 UNRESOLVED, 1 INCONSISTENT): A0 TP6 FP1 ERR-F1=.308 → A1 TP17 FP1 ERR-F1=.680, 11 исправлений/0 регрессий; false-certified NO_ERROR=0, но один **старый false ERROR** остался. A2 value anchoring, A3 catalog binding были реализованы как arms, дополнительного выигрыша в verdict не дали. 25 новых тестов, старые 45/45 E2E; full suite имела те же 10 прежних provider/seal failures. Frozen A1 config scoped_unknown=true, остальные два ремонта выключены.

**Нет:** единого независимого невиданного holdout для честного общего сравнения Agent-1 и Agent-2, его нельзя заменить собственным holdout любого из агентов. НЕ смешивать его 69-case ERR-F1 с 46-case contest F1.

### 2.4 `E2E-agent-2` — B4h-sound-v2 (`315bee335a467476732b47e1e7f412097222cd3b`)

[Ветка](https://github.com/MYC-A/Guardian-of-Truth/tree/E2E-agent-2) · [cycle3](https://github.com/MYC-A/Guardian-of-Truth/blob/E2E-agent-2/docs/vnext/e2e/E2E_V1_CYCLE3_RESULTS.md) · [soundness audit](https://github.com/MYC-A/Guardian-of-Truth/blob/E2E-agent-2/docs/vnext/e2e/PRE_BENCHMARK_SOUNDNESS_AUDIT.md).

**Есть:** H0 historical + Conservative goal + B3 semantic fixes, T1/claims/binding/worlds/certificates; B1 conservative state/temporal evidence, B2 alternative-actions OR-groups, B3 inconsistency/claim-typing, B4h historical H0 from Agent-1. Из 144 уже просмотренных dev+«holdout» (32+112): B0 TP53 FP10 → B4h TP54 FP0 F1=.878. Затем soundness-аудит нашёл SND-01..SND-11: неявная persistence, stale-state после попытки mutation, envelope status vs business state, entity scope, недоказанные enum↔flag и прочие. На B4h-sound-v2 144 просмотренных dev: TP49 FP0 FN20 TN5, P=1 R=.710 F1≈.834, false-certified ERROR=0/NO_ERROR=0, uncertified=0. Снижение coverage намеренно: источник не доказывает ownership поля. 46 soundness tests, E2E+soundness 96 passed; full baseline 1481 passed + 9 архивных ранее существовавших failures.

**Граница:** ручные T1 и trusted read/write/effect guarantees в research fixtures; никакой автоматической победы на конкурсном input. Frozen — не переписывать ради сравнения; делать отдельный потомок. Не путать «нет выявленного soundness bug в конкретной версии» с доказанным охватом всех неизвестных кейсов.

### 2.5 `competition-real-input-audit` (`67e81c7488d151de81ae5672aa4c7961decdf611`)

[Ветка](https://github.com/MYC-A/Guardian-of-Truth/tree/competition-real-input-audit) · [audit](https://github.com/MYC-A/Guardian-of-Truth/blob/competition-real-input-audit/docs/vnext/e2e/COMPETITION_REAL_INPUT_AUDIT.md) · [requirements](https://github.com/MYC-A/Guardian-of-Truth/blob/competition-real-input-audit/docs/vnext/e2e/COMPETITION_REQUIREMENTS_AUDIT.md).

**Есть:** strict raw competition adapter, sources with spans, gold firewall, 46-case premise audit, C0 legacy submission, C1 manual/oracle T1 ceiling protocol, C2 source-derived-only prototype, C3 no T1, case_audit.jsonl, packaging audit, `.dockerignore` whitelist. Реальная отправка через старый `predict.py` исполняет legacy Detector, НЕ B4h; попытка B4h на dict без адаптера дала 46/46 AttributeError. C0 legacy `--backend none` TP12 FP0 FN11 TN23 F1≈.686 (46 public); C2 1/46 smoke; C3 44/46 к моменту отчёта (10 PROVED_ERROR, 34 UNRESOLVED среди 44), C1/C2 не завершены из-за квот. Не считать C3 «10 TP на полном корпусе».

**Установлено:** prompt даёт catalog/schemas/observed calls/results, но не даёт авторитетные точные effects/writes/freshness/failure semantics. T2 семантические эффекты — не trusted. В документации оценивались 11/12 публичных паттернов как проверяемые из доступного входа, но это representability-analysis, не фактическое 11/12 recall. BAI qwen3.8-flash получил insufficient_user_quota, z-ai GLM имел throttling; внешняя LLM и десятки/сотни calls не гарантированно помещаются в 30 минут/офлайн Docker. Wheel-import dependency on `scripts.evaluate_vnext_c_alr_reimpl` отдельно зафиксирована.

### 2.6 `competition-real-valid-codex` (`300dc2edd20e631928b9997a8f581ab8659a75b2`)

[Ветка](https://github.com/MYC-A/Guardian-of-Truth/tree/competition-real-valid-codex) · [worklog](https://github.com/MYC-A/Guardian-of-Truth/blob/competition-real-valid-codex/docs/vnext/e2e/REAL_COMPETITION_VALID_CODEX.md) · [15 FN](https://github.com/MYC-A/Guardian-of-Truth/blob/competition-real-valid-codex/docs/vnext/e2e/REAL_VALID_FN_AUDIT.md) · [witness masking](https://github.com/MYC-A/Guardian-of-Truth/blob/competition-real-valid-codex/docs/vnext/e2e/WITNESS_MASKING_FIX.md).

**Есть:** другой raw adapter, goal repair, Session A/B independent repeat, catalog_conformance, REP-08 must-act abstention, исправление witness masking в `300dc2e`; отдельные артефакты Session A/B и FN audit. После воспроизводимого Mistral `ministral-14b-latest` 46 dev: TP8 FP0 FN15 TN23, F1=.5161 (38 unresolved); один telecom t7 был неправильно `UNRESOLVED` при уже доказанном catalog violation; fix `completion-invariant FALSE witness` поднял TP до 9, FP0, FN14 TN23, F1=.5625; 11 метаморфных тестов, e2e+soundness 137 passed, full 1618 passed + те же 9 archival. Это отдельная branch-specific цифра, **не merged в FullArch автоматом**.

**FN-аудит 15 до witness fix:** provenance значений/пар аргументов/повторного failed call — 6; missing multi-rule policy — 4; KB-as-policy не представлен — 1; claim typing/capability/fabricated action — 3; witness composition — 1. 15/15 признаны по человеческому анализу потенциально выводимыми из исходного prompt без oracle T1, но это не доказательство автоматической реализуемости всех 15. В `REAL_VALID_FN_AUDIT.md` typed argument-provenance был **предложенным следующим экспериментом, не внедрённым этой веткой**. После witness fix остаются 14 FN исходного canonical run.

**Критическая последующая поправка от другого аудита:** сама «tool вне AVAILABLE TOOLS ⇒ доказанный ERROR» опирается на неустановленное замыкание каталога; телекомуникационные «инструменты» могли быть действиями клиента, банковские discoverable инструменты могут вызываться в особом протоколе. Правильный источник ошибки может быть ACTOR / required wrapper / policy, а не голое отсутствие имени. При переносе witness fix сохранить его общее свойство FALSE-доминирования, но **не перетаскивать без обоснования его catalog premise**.

### 2.7 `codex-update-run` (`869a93a9417cbd73d00000070cdd352abcad15b8`) и его потомки

[Ветка](https://github.com/MYC-A/Guardian-of-Truth/tree/codex-update-run) · [worklog](https://github.com/MYC-A/Guardian-of-Truth/blob/codex-update-run/docs/vnext/e2e/REAL_COMPETITION_VALID_CODEX.md) · [closure audit](https://github.com/MYC-A/Guardian-of-Truth/blob/codex-update-run/docs/vnext/e2e/HIDDEN_ASSUMPTIONS_AUDIT.md).

**Есть:** strict competition adapter, B4h invocation, gold-only-postseal runners, `ministral-14b-latest` Mistral research run; исходные R0/R1/R2 на 46: TP2 FP0 FN21 TN23 F1=.16 (44 unresolved). Два изолированных KEEP-коммита: `92b5d26` (out-of-catalog 5 новых TP, итого TP7/F1=.4667) и `0dbacb5` (schema 3 новых TP, итого TP10/F1=.6061). Результаты запечатаны. Но **не останавливаться на этом выводе**.

**Скрытые предпосылки — самый ценный последующий аудит:** `4639b46f2e6995ea7036aef73a01ebbc723c0e14` — синтаксическая полнота parsing catalog ≠ closed universe; поле `additionalProperties=False`, автоматически добавленное к каждому объекту при парсинге текстовой схемы, не было явно декларировано. Среди прежних 10 TP 5 опирались на catalog closure, 2 — только на object closure, 1 — explicit required schema, 2 — policy. Конфигурации (одни и те же 46, zero live calls, реконструкция witnesses, НЕ fresh independent run): C0 обе closure ON: TP10 FP0 F1=.6061; C1 catalog OFF: TP5 F1=.3571; C2 object OFF: TP8 F1=.5161; C3 обе OFF: TP3 FP0 FN20 TN23 F1=.23077, 43 unresolved. Исправление гейтит closure по явным trusted premises, сохраняет required/type/enum при их прямом наличии. 20 новых adversarial/metamorphic тестов; E2E+soundness 138 passed, full 1620 passed + 9 старых failures; продакшн hardcoding scan: один `gold_label` в post-seal audit, не inference.

**Важно о кэше:** `fix2_final` LLM-cache не был закоммичен; сравнение C0-C3 сделано deterministic witness reconstruction + проверка инвариантности 62/62 LLM requests. Для повторения исходных live-сводок нужен локальный исторический cache или отдельный новый прогон с собственным названием и печатью, НЕ выдавать C0-таблицу за byte-identical replay live models.

**Отдельная ветка экспериментов `semantic_pipeline_v1` в этой линии:** собственный `experiments/semantic_pipeline_v1/`, сохранён в коммите `4e6d20072be86a42466a9490495600dfeb4b9dc6` — не путать с одноимённой удалённой `semantic-pipeline-v1`.

### 2.8 `semantic-pipeline-v1` — альтернативная самостоятельная реализация (`0d8d804d3f78a008fdfa1cc9e8db5dd1ee3ebdca`)

[Ветка](https://github.com/MYC-A/Guardian-of-Truth/tree/semantic-pipeline-v1) · [implementation docs](https://github.com/MYC-A/Guardian-of-Truth/blob/semantic-pipeline-v1/docs/vnext/e2e/SEMANTIC_PIPELINE_V1_IMPLEMENTATION.md) · [Colab](https://github.com/MYC-A/Guardian-of-Truth/blob/semantic-pipeline-v1/colab/README_SEMANTIC_PIPELINE_V1.md).

**Есть:** `src/guardian_truth/semantic_pipeline_v1/`: source timeline, BGE-M3 retrieval and binding, BGE reranker, NuExtract3-W4A16, `cross-encoder/nli-deberta-v3-base`, Mistral extractor/backend, RuleIR, Phi, conservative bridge to старому proof-core, cache/seal/lifecycle, runnable CLI, Colab script. GLiNER2.5 в изолированном Python sidecar (Transformers 4.x vs main 5.x); LangExtract 1.7 здесь optional diagnostic-only без настроенного provider, **не active extractor**. A0–A5 quality ablations; A6 GLiNER diagnostic-only; A7 LangExtract UNAVAILABLE; A8 combined diagnostic-only. В A2 без Mistral core intentionally `CORE_SEMANTIC_BACKEND_NOT_CONFIGURED` и UNRESOLVED: **это не полный автономный NuExtract-only Guardian**. Рекомендованный `A5` всё ещё требует remote Mistral в core, т.е. не подходит готовым финальным офлайн решением.

**Не установлено одними README/кодом:** реальный end-to-end GPU прогон на ModelScope всех 46 с моделью NuExtract3, улучшение contest F1, отсутствие невошедших фиксов параллельной competition-ветки. В переписке есть Colab/T4 smoke для deps/моделей и ModelScope A10 окружение (PyTorch 2.9.1+cu128, transformers 5.3.0, ошибка HybridCache у sentence-transformers), но **не смешивать проверку импортов и model-load с полноценным score всей архитектуры**. Main env пинит Transformers 5.16.1 / sentence-transformers 6.0.1 / compressed-tensors .15; Colab profile использовал Transformers 5.17.0. Указанный в docs путь `/mnt/data/guardian/...` привязан к чужому контейнеру и не является универсальным.

**Нет:** автоматического merge с `competition-real-valid-codex`/witness fix/closure fix, standalone local core, proof that GLiNER relation hypotheses losslessly lower into policy rules. Не считать эту ветку последней `full-architecture-v1`.

### 2.9 `codex-update-run` → `4e6d200` semantic_pipeline_v1 experiment (другая линия!)

[Отчёт](https://github.com/MYC-A/Guardian-of-Truth/blob/full-architecture-v1/docs/vnext/e2e/SEMANTIC_PIPELINE_V1.md) · [flow audit](https://github.com/MYC-A/Guardian-of-Truth/blob/full-architecture-v1/docs/vnext/e2e/SEMANTIC_PIPELINE_CURRENT_FLOW.md) · [коммит](https://github.com/MYC-A/Guardian-of-Truth/commit/4e6d20072be86a42466a9490495600dfeb4b9dc6).

**Есть в `experiments/semantic_pipeline_v1/`:** SourceTimeline с byte-exact spans и разбором `TOOL_RESPONSE [ERROR]`, union retrieval A deterministic/B lexical-local/C multilingual embeddings/D KB, Mistral RuleIR, локальный NuExtract-1.5-tiny и GLiNER2.5-small, Pydantic RuleIR, NLI DeBERTa-small, binder exact→embedding→rerank, Phi и thin adapter через старый compile_h0 в unchanged incumbent Core. Эксперимент запускался **на CPU 2 cores / 3.9 GiB RAM**, NuExtract3 4B признан недоступным в том окружении и заменён на NuExtract-1.5-tiny. LangExtract 1.7 проверен, но не использован как основной backend в том окружении.

**Измерено:** обязательные релевантные фрагменты: current role-usable 68/105=.648 → combined retrieval 105/105=1.0; embeddings-only .581, deterministic-only .705; 17 synthetic held-out, RuleIR union modality .882, condition .571, target .529, exception 1.0 на применимых подгруппах. NLI 8/8 семантических инверсий при среднем cosine~.866 (эмбеддинги не проверяют истинность). Binder 18/36 корректно bound, 0 wrong, 2 ambiguous, 16 UNKNOWN. Dev Phi mean~91 интерпретация/кейс; сложность/условия не обязательно lowerable. **E2E на свежем общем кэше:** A0 incumbent TP2 FP0 F1=.160, A1 retrieval incumbent TP2, A8 full pipeline TP1 FP0 FN22 TN23 F1=.0833; synthetic A8 0 TP/14 FN/3 TN. Значит **лучший retrieval ≠ хороший финальный классификатор**. Главный конкретный гэп: NL condition→ledger atom binding и отсутствие V1 lowering для comparisons/cardinality; также goal SCHEMA fragility 25/46 свежих входов. Full pipeline НЕ рекомендован к переносу как есть; рекомендованы timeline/error parser, union retrieval, NLI firewall и compositional IR как доноры. Full suite 1620 passed + 9 прежних.

### 2.10 `core-engine-bakeoff-v1` — удалённой ветки нет, но commit `bf972b0...` есть в истории FullArch

[Коммит](https://github.com/MYC-A/Guardian-of-Truth/commit/bf972b04655aedcfc0854860179414e08be94725) · [отчёт в full-architecture-v1](https://github.com/MYC-A/Guardian-of-Truth/blob/full-architecture-v1/docs/vnext/core_engine_bakeoff_v1/CORE_ENGINE_BAKEOFF_V1.md) · `experiments/core_engine_bakeoff_v1/`, `outputs/core_engine_bakeoff_v1/`.

**Есть:** NeutralCoreInput (факты/typed atoms/interpretations), 43 независимых формальных synthetic scenarios, 46 world-oracle, 58 primitive-oracle, Clingo, s(CASP) через SWI, Drools через Java/KIE, Soufflé provenance probe, performance scaling. На повторном прогоне 19.09: incumbent 27/43, worlds30/46, primitives47/58, 16 честных abstentions; Clingo/s(CASP)/Drools **каждый 43/43, worlds46/46, primitives58/58**, 0 unsound по oracle. Сравнивали уже формализованные входы; никакой движок не парсил английский. На 2-core CPU при 10k events Clingo ~0.39 сек vs current ~4.9 сек, s(CASP) ~10.76 сек; per-query process запуск дорог. Soufflé — только provenance probe, не full-core candidate. Временные performance numbers из отчёта и performance.json несколько отличаются из-за разных rerun; использовать один pinned файл на конкретном commit.

**Локальные проблемы:** SWI-Prolog без root установлен из deb в home и требует `make_library_index`; s(CASP) pack версия/индекс влияет на результаты. Drools jars локальные; абсолютные `/home/z` пути не переносятся. **Не сделано в bake-off:** реальный 46-case E2E replay; сознательно перенесён в `full-architecture-v1`.

### 2.11 `full-architecture-v1` — самое новое опубликованное направление

[Ветка](https://github.com/MYC-A/Guardian-of-Truth/tree/full-architecture-v1) · [Phase A inventory](https://github.com/MYC-A/Guardian-of-Truth/blob/full-architecture-v1/docs/vnext/full_architecture_v1/COMPONENT_INVENTORY.md) · [A–E commit](https://github.com/MYC-A/Guardian-of-Truth/commit/0c2bda7ec49a52ef851a8b5d45610b2c1d88659a) · [последний проверенный remote WIP](https://github.com/MYC-A/Guardian-of-Truth/commit/923bb445ab29399cd5e58a19a55941c1fdb9f6af).

**В GIT есть:** `experiments/full_architecture_v1/` с jsonschema parity probe, Invariant comparator, GLiNER2.5 typing probe, `evidence.lp`, `policy.lp`, Clingo backend, RuleIR→Neutral compiler, facts builder, certificate builder/checker, arms pipeline, `benchmarks/{real46,safepyramid,barred,folio,proofwriter}.py`; также доисторический semantic_pipeline experiment и bake-off как предки. В `pipeline.py` arms: N1 current frontend typing OFF + incumbent Core; N2 GLiNER typing ON + incumbent; N3 Clingo POLICY с incumbent evidence tval; N4 Clingo POLICY + Clingo EVIDENCE; N4-I N3 + Invariant comparator (не авторитетен); N5 N4 + certificate/checker. N0 отдельный incumbent baseline runner, НЕ arm в `pipeline.ARMS`.

**Phase A–E по коммиту `0c2bda7`:** jsonschema probe 580 synthetic/real/suite проверок, 0 совпадений verdict-диагностик с incumbent в поддерживаемом подмножестве, но 1 документированная N1 numeric divergence; Invariant 6 probe patterns; GLiNER2.5 успешно загружен, найденная типизация чувствительна к набору labels; split Clingo 43/43, 46/46 worlds, 58/58 primitives; RuleIR→Neutral поддерживает только представимые случаи, unverifiable остаётся marker; certificates 43/43 + tamper detection; evidence 52/52 Oracle и 10/10 metamorphic; N0 real46 TP3 FP0; **N5 real46 TP4 FP2** (точно из commit message!), поэтому формальная корректность генерации сертификатов не гарантирует правильное human-gold label. Сравнение N5 с N0 без остальных данных о протоколе/времени не считать окончательным.

**Phase F/G/H из ПОЛУЧЕННОГО ЛОГА АГЕНТА:** SafePyramid smoke 234 pairs TP0 FP11, unresolved~94%; main 466 pairs TP5 FP43 unresolved~86%. BARRED адаптер создан, `plan_verification` падал на newline в ASP value, в `923bb445` добавлен sanitizer; точные BARRED metrics в переданном логе НЕ указаны. FOLIO oracle-FOL→ASP: сообщено representability 27%, accuracy 45%, UNKNOWN-never-FALSE; ProofWriter OWA 500: representability 61%, accuracy 66%, UNKNOWN-never-FALSE. Ранее при первом FOLIO запуске была representability 17.5%, после правок — 27%, не смешивать. Про ContractNLI агент только начал проверять доступность — **нет подтверждённого результата**. `923bb445` опубликован как сохранение прерванной сессии и по сравнению с `0c2bda7` меняет лишь benchmark adapters + ASP sanitize; **outputs/full_architecture_v1 с указанными числами не входят в список изменённых закоммиченных файлов**. Получить локальные caches/predictions/metrics у текущего агента прежде чем считать replay возможным.

**Чего нет/не доказано:** не опубликован полный terminal отчёт FullArch N0–N5, не подтверждён полный независимый external benchmark suite, не реализован подтверждённый offline final Docker, не установлена готовность к hidden, не доказана полнота NL→RuleIR/Φ, не доказано, что опыт с уже просмотренными внешними датасетами является независимой валидацией. Не объявлять N5 победителем и не удалять прежний incumbent.

## 3. Общая архитектура и границы доверия

```text
RAW prompt/response (text + target tool calls)
  ├─ trusted STRUCTURE: exact event log, actor, calls/results, source spans,
  │  declared tool names/fields, original observed argument/result bytes
  │       ├─ structural checks (jsonschema only where schema premise explicit)
  │       └─ indexed complete timeline for counting/order/absence under closure
  └─ SEMANTIC PROPOSALS: retrieval → extractor(s) → compositional RuleIR
         → source/span validation + NLI/cross-check (NLI = signal, не proof)
         → candidate tool/entity/field binding, no arbitrary winner-picking
         → Phi (known options, unmodeled terms, completeness metadata)
         → NeutralCoreInput / ASP facts
                 ├─ evidence.lp (attempt/success/state/freshness/absence)
                 ├─ policy.lp (conditions/quantifiers/cardinality/world safety)
                 └─ Clingo answer sets / consensus
         → source-backed witness + independent checker
         → PROVED_ERROR | PROVED_NO_ERROR | UNRESOLVED | INCONSISTENT
                  ↓
       CONTEST DECISION LAYER (binary 0/1; probabilistic fallback possible,
       but never mislabeled as formal proof)
```

**Нельзя потерять:** USER_ACTION != ASSISTANT_ACTION; INTENT != COMPLETED; CALL_ATTEMPTED != ACTION_COMPLETED; FAILED_CALL != SUCCESS и != доказанный NO_EFFECT; CLAIM != OBSERVED_FACT; UNKNOWN != FALSE; NOT_FOUND != ABSENCE; old read != current state; later state != causal attribution; PERMISSION != OBLIGATION; alias != unique identity; tool name/description ≠ trusted effect. Совместная модель **может** классифицировать 1 на недоказанном вероятностном признаке в contest decision layer, но должна отдельно хранить core proof status и provenance. Даже `PROVED_ERROR` бывает false относительно исходного естественного правила, если фронтенд перевёл правило неверно или придумал closure premise; сертификат доказывает лишь результат относительно допущений, а не истинность формализации.

**Крупные измеренные failure points:** H0 получает policy span, но пропускает earlier USER/KB normative text и иногда служебные instructions; old parser теряет `TOOL_RESPONSE [ERROR]`; goal frontend видит лишь последний USER; full RuleIR→старый compiler не lowering NL conditions/count/comparisons; multiple Φ может сделать систему слишком осторожной; negative F1 после лучшего retrieval; 64-interp cap в FullArch, 91 mean candidates в другом experiment — это разные величины, не смешивать. В Clingo вводить только допустимо полные axes; даже cautious следствие не доказывает покрытие всех разумных естественных интерпретаций `φ*∈Φ`.

## 4. Не путать тесты и цифры: общий регистр

| Источник/версия | Данные/модель | Результат | Чего НЕ доказывает |
|---|---|---|---|
| `main` autonomous | public46, backend none | TP6 FP0 FN17 TN23 F1=.414 | hidden качество |
| V6 one-shot | public46 Groq GPT-OSS20B | TP14 FP5 F1=.6667 | хорошее качество объяснений: reason precision лишь 4/13–5/13 |
| V6 exact improvement | public46 | TP16 FP5 F1=.7273 | переносимость единого подтипа |
| V7 exact date | public46 | TP17 FP5 F1=.7556 | вероятность такого же результата hidden |
| V9 outer | 16 NL rules + 19 diagnosis | 15/15 synthetic, 45/84 feature, 0/16 gold gate, strict3/19 | полноту Φ для NL |
| vNext ClaimGraph | 41 fixtures | spans perfect на 39, type gain gate FAIL | accurate typed claims, E2E |
| vNext PolicyΦ | 104 fixtures | 61/265 candidate correct, strict2/104 | full policy completeness |
| vNext Goal v1/v2 | 22 fixtures | 22 UNRESOLVED, 0 cert | E2E obligations |
| vNext T1/T2 | 18 controlled | T1 16/16 applicable; T2 positive 1/8 restricted | trusted effects для произвольных реальных tools |
| vNext binding v2 | 34 controlled | 34/34 typed truth | NLP/competition gains |
| Agent-1 A1 | dev 69, BAI | TP17 FP1, ERR-F1=.680 | comparison with Agent-2 corpus |
| Agent-2 B4h-sound-v2 | viewed dev 144, BAI | TP49 FP0 FN20 TN5 F1≈.834 | contest F1 46 без oracle contracts |
| competition audit C0 legacy | public46 backend none | TP12 FP0 F1≈.686 | B4h pipeline |
| codex Session baseline | public46 Mistral | TP2 FP0 F1=.160 | F1 другой модели/версии |
| `competition-real-valid-codex` | public46 Mistral | TP8 FP0 F1=.516 → witness fix TP9 F1=.5625 | closure-premise soundness |
| `codex-update-run` fix2 | public46 Mistral + implicit closure | TP10 FP0 F1=.606 | строгость недоказанной closure |
| `codex-update-run` C3 | SAME public46 witness reconstruction, corrected | TP3 FP0 F1=.23077 | отдельный live full run, hidden |
| semantic_pipeline_v1 (`4e6d`) | public46 fresh cache | A0 TP2, A8 TP1 F1=.0833 | retrieval improvement ⇒ E2E gain |
| bake-off `bf972b0` | 43 neutral-formal synthetic | Clingo/s(CASP)/Drools 43/43; current27/43 | NL→logic fidelity |
| FullArch `0c2bda7` | public46 + synthetic | N0 TP3 FP0; N5 TP4 FP2; 52/52 evidence, 43/43 neutral | certificate-valid ⇒ gold-correct |
| FullArch external [LOG] | SafePyramid/FOLIO/ProofWriter | SP 466: TP5 FP43; FOLIO 27% representability 45% accuracy; PW 61%/66% | одинаковые задачи, published run, hidden |

**Примечание к отрицательным тестам:** SafePyramid и BARRED — policy+conversation, не тот же тип инструментальных траекторий; FOLIO oracle-FOL и ProofWriter шаблонный транслятор измеряют преимущественно адаптер/формальную выразимость, а не весь конкурсный Guardian. Количество abstention и denominator сообщать отдельно. Ни один «43/43» не является «43/43 на живых соревнованиях».

## 5. Что предлагается, а не сделано: новые архитектуры из пользовательских документов и чатов

[CHAT/PLAN] Прикреплённый документ с альтернативами предлагал **развести две задачи**, вместо того чтобы загонять всё в NuExtract→RuleIR→Clingo: (A) compliance/conformance вызовов и порядка действий, (B) grounding/faithfulness утверждений в итоговом тексте. Обсуждались независимые каналы и гибрид, причем пользователь НЕ имеет сильной LLM в конечной поставке. Это пока **архитектурные гипотезы, НЕ доказанные результаты/не автоматически существующие модули в FullArch**.

- **Policy/trace**: Declare/Declare4Py/PM4Py/ProM/RuM, finite LTLf/flloat/ltlf2dfa, data-aware counting/precedence/response/absence, возможно AgentLTL идеи. Проверять смысл временны́х правил на конечной/неполной истории и роль actor; для агрегатов читать **полный** event index, не top-k retrieval. Нельзя автоматически считать разное имя метода независимостью; `COUNT_DISTINCT BY K` с несколькими допустимыми ключами (method/channel/factor_class) и UNKNOWN, если source не закрепляет K.
- **Data/arithmetic/provenance**: Z3/CVC5/PySMT как отдельная альтернатива Clingo для сравнений, чисел и формальных значений. Считать именно source provenance и допустимые преобразования, не «значение встречается где-то в prompt». Entity scope и legitimacy transformations должны быть явными.
- **Claims**: MiniCheck/Bespoke-MiniCheck, LettuceDetect, Granite Guardian 3.x (возможная функция function-calling risk), AlignScore/SummaC/Lynx и др. Нельзя без тестов утверждать, что RAG-faithfulness detector ловит неправильный tool-call/policy; измерять отдельно claim-only и end-to-end, source pairing и long-context. Наличие исходников/весов и лицензии проверить.
- **Extraction**: NuExtract/GLiNER/Mistral/local small instruction LM; LangExtract — orchestration, а не модель; Outlines/XGrammar/llguidance/vLLM structured output, DSPy, Logic-LM self-refinement после компиляционных ошибок, lexical-residue check с точными source-span и `UNMODELED` (не жёсткое правило по списку слов). Извлечение двух разных интерпретаций не доказывает, что третья невозможна.
- **Формальные альтернативы/частичная информация:** Clingo cautious/brave, s(CASP) justification tree, OPA partial evaluation, Cedar, Scallop/ProbLog/PSL — только ablation после уточнения trust/semantics; вероятностный ответ и формальное доказательство нельзя смешивать.
- **Decision-layer как самостоятельная система:** текущий `UNRESOLVED→0` даёт высокий FN. Отдельный скорер на структурных признаках + scores компактных специализированных моделей / heuristic override; тренировку и калибровку на внешних/синтетических данных, **не на неоднократно просмотренных 46**. Проверить standalone detector A, formal B, hybrid C и router D, а не автоматически складывать всё в один «зоопарк».
- **Валидация/инструментирование:** независимые fault-injection пары, Hypothesis metamorphic, Langfuse/Phoenix/MLflow для трассировки, weak supervision Snorkel/Skweak при обоснованной разметке; внешние SafePyramid, BARRED, ToolSandbox, ToolEmu, ContractNLI, RAGTruth, HaluBench, τ-bench/τ², FOLIO, ProofWriter — задачи различаются, не выдавать метрику одной за конкурсную другую.

**Критика предложений, которую новый агент ОБЯЗАН учитывать:** `NLI entailment` не доказывает формальное совпадение source rule/IR; `confidence retrieval` не доказывает полноту top-k; «если хоть одна трактовка ERROR, ставим PROVED_ERROR» НЕ sound при допустимой другой трактовке OK (здесь граница competition probable label vs proof). Факт «две sms одинаковы» не доказывает отсутствие разных ресурсов/факторов без заданных атрибутов. `--enum-mode=cautious` доказывает лишь по полной формально представленной программе, не по всему NL. `unsat-core` Z3/justification s(CASP) не заменяет проверку правильности NL→facts и trusted contract. «Conformal calibration гарантирует хороший F1 на 46» — НЕ установлено; малый dataset делает статистические гарантии слабым местом. Генерация исполняемого Python-предиката моделью — отдельный высокий security/soundness risk, НЕ реализовано в FullArch. Запрещено обещать high hidden F1 по созданным в наших руках синтетическим правилам.

## 6. Что именно не реализовано в опубликованном состоянии / где искать

1. **FullArch standalone end-to-end без Mistral API:** N1–N5 читают frozen `outputs/vnext/semantic_pipeline_v1/phi.jsonl` из предыдущего Mistral CPU experiment; значит локальный Clingo после кэша не делает архитектуру готовой автономной к hidden data. Нужна реальная онлайн (локальная модель) генерация Phi для нового prompt/response в пределах 30 минут, или иная полностью локальная architecture.
2. **Основной готовый claim-faithfulness канал MiniCheck/LettuceDetect/Granite Guardian и калиброванный fallback** — в проверенном GitHub FullArch inventory/изменённых файлах отсутствуют. Это идеи/новая директива пользователя, не результаты. Перед установкой проверять веса, runtime, license и tests. Не выдавать вводимый score за certificate.
3. **Declare/LTLf и Z3 вместо/рядом с Clingo** — в текущем `experiments/full_architecture_v1/` нет подтверждённой реализации этих arms. Обсуждались, не запускались на тех же frozen NL входах в предоставленных логах.
4. **Полная внешняя оценка:** есть benchmark adapter files, но не все scores/seals/output published; BARRED numbers/ContractNLI run в данном контексте отсутствуют. Следующий агент должен сначала попросить/скопировать локальные `outputs/full_architecture_v1/` и зафиксировать SHA + модель/corpus/конфиг до новых запусков.
5. **Общий fresh holdout Agent-1 vs Agent-2** так и не подтверждён; B4h holdout112 уже viewed development, нельзя назвать его fresh common blind. FullArch/semantic external benchmarks тоже стали dev после раскрытия результатов.
6. **Финальная интеграция**: проверить, что реальный `scripts/predict.py`/Docker вызывает выбранный новый pipeline, а не legacy `Detector`. Никакой готовый research runner не является этим доказательством. Отдельно проверить `pip install .` vs `scripts.evaluate_vnext_c_alr_reimpl` wheel import и объявленные зависимости.
7. **Trusted closure**: отсутствие tool имени в source catalog и автоматический `additionalProperties=False` НЕ достаточно для формально строгого вывода. Если конкурсная интерпретация оценивает такое как 1, сделать это отдельно как конкурcный вероятностный/нормативно подтверждённый сигнал; не реанимировать старый non-source-backed proof.
8. **Новые сведения о состоянии** могут находиться в ещё не отправленной ветке `architecture-research-v1` или локальных worktrees. Нельзя утверждать, что её нет локально — подтверждено только, что опубликованных remote branches по проверке было девять.

## 7. Проверка безопасности перед стартом нового агента

**Никогда не переключай текущую ветку/сбрасывай изменения в рабочем каталоге, пока предыдущий агент работает.** Сначала выясни, выполняется ли предыдущий процесс, где его worktree, `.env`, venv/модели, локальные игнорируемые outputs и незакоммиченные файлы. Делай read-only inventory; новый worktree можно создать только после фиксации базы/отдельного диска и оценки ресурсов. `git status --porcelain=v1 -uall`, `git rev-parse HEAD`, `git branch -avv`, `git log --graph --decorate --all --oneline -n 100`, `git merge-base`, `git worktree list --porcelain`, `git ls-files outputs/...`, `git check-ignore -v`. Не удалять чужую директорию, не включать/переписывать `.env` в коммит, не публиковать API keys и private gold.

**Отдели два research environments:** старый CPU 2 cores/3.9 GiB (NuExtract tiny); отдельный ModelScope A10/Colab T4 (NuExtract3 4B/GLiNER2 sidecar, несовместимые Transformers). Локальные `/home/z/models`, `/mnt/data/guardian` могут отсутствовать в новом контейнере; кэши и модели не должны неявно подтягиваться по сети в финальном Docker.

## 8. Первоисточники по веткам и где искать артефакты

- `main`: `README.md`, `docs/V6_RESEARCH_CYCLE.md`, `docs/V7_FORMAL_REASONING_CYCLE.md`, `docs/V9_OUTER_SEMANTICS_CYCLE.md`, `docs/DECOMPOSITION_RESULT.md`, `docs/EXPERIMENT_LOG.md`.
- vNext baseline: `docs/vnext/ARCHITECTURE.md`, `BENCHMARK_PROTOCOL.md`, `POLICY_PHI_RESULTS.md`, `GOAL_PLAN_RESULTS.md`, `GOAL_V3_ISOLATION_V3_RESULTS.md`, `CLAIM_GRAPH_RESULTS.md`, `BINDING_TEMPORAL_RESULTS.md`, `TOOL_SEMANTICS_RESULTS.md`, `PROGRESS.md`, `contracts/vnext_requirements_v1.json`, `outputs/vnext/*_freeze/results/seal*`.
- Agent-1: `docs/vnext/e2e/E2E_V1_RESULTS.md`, `E2E_AGENT1_REPAIR_RESULTS_RU.md`, `E2E_AGENT_1_ARCHITECTURE_RU.md`, `outputs/vnext/e2e_agent1_repair_freeze.json`, `scripts/evaluate_e2e_agent1_repair.py`.
- Agent-2: `docs/vnext/e2e/E2E_V1_CYCLE3_RESULTS.md`, `E2E_V1_FINAL_DECISION.md`, `PRE_BENCHMARK_SOUNDNESS_AUDIT.md`, `scripts/run_soundness_regression.py`, `tests/e2e_soundness/*`.
- competition audit: `docs/vnext/e2e/COMPETITION_REAL_INPUT_AUDIT.md`, `COMPETITION_REQUIREMENTS_AUDIT.md`, `outputs/vnext/competition_valid/*`.
- competition-real-valid-codex: `docs/vnext/e2e/REAL_VALID_FN_AUDIT.md`, `WITNESS_MASKING_FIX.md`, `outputs/vnext/fn_audit/*`, `outputs/vnext/witness_masking_fix/*`, `tests/e2e/test_witness_masking.py`.
- codex-update-run: `docs/vnext/e2e/REAL_COMPETITION_VALID_CODEX.md`, `HIDDEN_ASSUMPTIONS_AUDIT.md`, `SEMANTIC_PIPELINE_CURRENT_FLOW.md`, `SEMANTIC_PIPELINE_V1.md`, `outputs/vnext/hidden_assumptions_audit/*`, `outputs/vnext/semantic_pipeline_v1/*`, `experiments/semantic_pipeline_v1/*`.
- semantic-pipeline-v1 (другая): `docs/vnext/e2e/SEMANTIC_PIPELINE_V1_IMPLEMENTATION.md`, `src/guardian_truth/semantic_pipeline_v1/*`, `scripts/run_semantic_pipeline_v1.py`, `colab/README_SEMANTIC_PIPELINE_V1.md`, `tests/semantic_pipeline_v1/*`.
- bake-off: `docs/vnext/core_engine_bakeoff_v1/CORE_ENGINE_BAKEOFF_V1.md`, `experiments/core_engine_bakeoff_v1/*`, `outputs/core_engine_bakeoff_v1/*` в full-architecture-v1.
- FullArch: `docs/vnext/full_architecture_v1/COMPONENT_INVENTORY.md`, `experiments/full_architecture_v1/{pipeline.py,policy/,evidence/,certificate/,probes/,synthetic/,benchmarks/}`, **локально** `outputs/full_architecture_v1/{real46,safepyramid,barred,folio,proofwriter,...}` (не установлено, что все артефакты опубликованы).
- История обсуждений (не исходный текст полностью): https://chatgpt.com/share/6aa981cc-138c-83eb-9a18-d6fabbdd90ee (архитектура/промпт), https://chatgpt.com/share/6aa64b61-07e4-83eb-82ed-36b88f7e6a98 (продолжение), https://chatgpt.com/share/6aad7a70-3504-83eb-bc1f-59c4a500c7b8 (новая архитектура; при моей попытке читать share был timeout). Если новый агент может получить экспорт — он должен прочесть его и явно обновить этот handoff, не реконструировать неувиденные реплики как факт.

## 9. Что новому агенту делать дальше — не реализуй старые ошибки заново

**Сначала только audit/inventory + восстановление артефактов текущего агента.** Закрепить Git head/worktree и `outputs/full_architecture_v1`, сверить `0c2bda7` vs `923bb445` и невошедшие изменения, записать N0..N5 по каждому кейсу, FP N5=2, зависимость от freeze Phi/API, SafePyramid/BARRED/FOLIO/ProofWriter/ContractNLI реальные denominators/seed/labels/score. Уточнить, какие статусы реально false certificates (проверка соответствует *формальным* предпосылкам) и где источник NL/formalization неправильный. Не чинить по gold до регистрации протокола.

**Потом независимые архитектуры, которые пользователь просил пробовать:** standalone MiniCheck/LettuceDetect/Granite Guardian (claim-only и complete contest input), отдельно channel для формальных policy и schema, Declare/LTLf на timing/count, Z3 на numeric/provenance; small local extraction без сильной LLM; упрощённый fallback/ensemble/router. Перед полным GPU запуском — tiny smoke, compatibility/licensing/VRAM/model size. Избегать «загрузили модель значит она покрывает все типы ошибок».

**Честные абляции:** baseline legacy `main` exact-only vs best archived one-shot vs corrected `codex-update-run` C3 vs FullArch N0/N5 *на одном и том же входе при одинаковом model/cache*, standalone detector, proof override + detector fallback, per-class routing, optional Declare/Z3. Отдельно, если есть законные source-backed guarantees закрытия catalog/object, сравнить ON/OFF на специально новых метаморфных примерах; иначе держать trusted closure OFF. Порог score и веса обучать на независимом train/calibration corpus, не подгонять 46 публичных кейсов и тем более не перебирать все сочетания на них ради максимума.

**Финал:** новый `scripts/predict.py` с офлайн весами/нетривиальным cold start, `pip install .`, вход CSV, вывод `id,label`, качественная лицензия, <40 ГБ, 30 минут, отдельный API-disabled run на чистом окружении, стабильные метрики/manifest, не переписывать существующий submission без решения пользователя.

---

## 10. Проверочный список вопросов, ответы на которые пока НЕ доказаны

- Все ли локальные результаты сессии H (особенно BARRED и N0..N5) дошли в remote? **Нет подтверждения; по git diff видно не все outputs.**
- Есть ли remote `architecture-research-v1` / `core-engine-bakeoff-v1`? **На проверенном списке девяти нет, локально может быть.**
- Вошёл ли `300dc2e` completion-invariant witness fix в `full-architecture-v1`? **Не считать вошедшим: линии расходились; перепроверить diff именно proof primitive.**
- Может ли FullArch по незнакомой строке работать только с локальными моделями и без precomputed `phi.jsonl`? **Не доказано и по pipeline зависит от frozen Phi.**
- Почему N5 4 TP 2 FP с проверенными сертификатами? **Требуется per-case source/IR/binding/trust audit; валидный сертификат не удостоверяет faithful NL interpretation.**
- Дают ли MiniCheck/Granite/LettuceDetect пользу для action/policy, а не только text claim? **Ещё не измерено в этой линии.**
- Есть ли sound универсальное правило `out-of-catalog = ERROR`? **Без explicit closure/actor/wrapper contract — нет.**
- Есть ли правильный способ доказать отсутствие нарушения при incomplete `Φ`? **Нет общего доказательства; partial/open world → UNRESOLVED в строгом слое.**
- Можно ли считать публичные 46 и просмотренные внешние наборы fresh validation? **Нет.**

**Это история исследований и карта текущего доказательного статуса, а не инструкция игнорировать существующие хорошие компоненты или механически добавлять все предложенные библиотеки.**
