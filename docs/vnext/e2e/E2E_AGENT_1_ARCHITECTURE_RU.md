# Guardian of Truth — E2E V1: полная архитектура системы

> Версия: E2E V1 (ветка `E2E-agent-1`, tip `cf1ab77` + настоящий документ).
> Этот документ — исчерпывающее описание архитектуры, всех модулей и краевых
> случаев end-to-end системы Guardian of Truth E2E V1. Технические первоисточники:
> `docs/vnext/e2e/E2E_V1_ARCHITECTURE.md`, `E2E_V1_SEMANTICS.md`,
> `E2E_V1_TRUST_BOUNDARIES.md`, `E2E_V1_BASELINE_AUDIT.md`,
> `E2E_V1_RESULTS.md`, `E2E_V1_FAILURE_AUDIT.md`, `E2E_V1_FINAL_DECISION.md`.

---

## 1. Назначение и философия системы

Guardian of Truth E2E V1 — система машинно-проверяемой верификации поведения
LLM-агента, работающего с инструментами (tool-calling agent). На вход подаётся
кейс: политика (normативный текст), источники пользователя (запрос), траектория
(история вызовов инструментов и результатов) и целевой ответ агента. Система
выносит один из четырёх вердиктов:

- `PROVED_ERROR` — доказано, что ответ нарушил нормы (политику/цель/факты);
- `PROVED_NO_ERROR` — доказано, что нарушений нет (требует замыкания семантического пространства);
- `UNRESOLVED` — доказательство невозможно (честный отказ, никогда не выдаётся за безопасность);
- `ERROR`/небинарные статусы конвертируются адаптером в бинарное решение продукта.

Философия (спека §3–§5, «LLM proposes / trusted code validates»):

1. **LLM только предлагает** — семантические решения (структура правил,
   фреймы целей, привязки смыслов к траектории, типизация клеймов).
2. **Детерминированный код валидирует и решает** — сборка ledger'а,
   компиляция программ, сведение (lowering) в обязательства, перебор миров,
   логический вывод, сертификаты.
3. **Каждый окончательный вердикт сопровождается сертификатом**,
   который независимый чекер перепроверяет полным пере-выводом.
4. **Gold никогда не входит ни в один вход системы** — золотые метки
   живут только в герметичном хранилище раннера и присоединяются к
   предсказаниям только после печати предсказаний (seal).
5. **Никакого post-hoc ремонта семантики**: невалидируемое предложение LLM
   отвергается (reject-only) или честно помечается UNKNOWN/UNRESOLVED.

Архитектурный принцип, подтверждённый экспериментально: LLM силён в
семантических решениях, но ненадёжен как канонический сериализатор; поэтому
эмиссия канонических форм (DSL, канонические ID) либо обёрнута в
детерминированный канонизатор с жёстким аудитом, либо отвергается.

---

## 2. Общая схема конвейера

```
                         ┌────────────────────────────────────────────────┐
                         │ E2ECaseSources (source_adapter_v1)             │
                         │ case_id, policy_text, atom_catalog,            │
                         │ user_sources, trajectory, target_response,     │
                         │ tool_schemas, T1-контракты, (опц.) замыкания   │
                         └───────────────┬────────────────────────────────┘
                                         │
   run_semantic_passes() — все arm-НЕзависимые LLM-проходы, 1 раз на кейс:
   ┌─────────────────────────────────────────────────────────────────────────┐
   │ 1. render_prompt/render_response → normalize → EvidenceLedger+LedgerIndex│
   │ 2. build_claim_graph (10 узких проходов по целевому ответу)              │
   │ 3. H0-фронтенд (замороженные задачи)  → H0Result (v3-программа)          │
   │ 4. GRS-фронтенд (grounder→B1→канонизатор+валидатор) → GRSResult          │
   │ 5. Goal-фронтенды (FIREWALL: только USER-источники):                     │
   │      Conservative → RuleFrameRaw[]                                       │
   │      RuleFrames   → RuleFrameRaw[]                                       │
   │      → E5 (детерминированный резолвер) → trusted assembler → контракты   │
   │ 6. semantic_binding PASS 2 (общий): атомы каталога + goal-пропозиции     │
   │      → BindingRecord (кандидаты привязок к инструментам/наблюдениям)     │
   └─────────────────────────────────────────────────────────────────────────┘
                                         │
   analyze_e2e_v1(arm) — детерминированная композиция, без LLM:
   ┌─────────────────────────────────────────────────────────────────────────┐
   │ A. Композиция оси POLICY: выбранные arm'ой фронтенды → readings;         │
   │    дедупликация поведенчески эквивалентных чтений; конфликты RETAIN      │
   │ B. Композиция оси GOAL: Conservative+RuleFrames контракты;               │
   │    эквивалентные obligation-поверхности дедуп, иначе RETAIN BOTH         │
   │ C. Lowering: policy_lowering_v1 + goal_lowering_v1                       │
   │    → E2EAxisChoice (обязательства ProofObligation + маркеры)             │
   │ D. Замыкание vs эмпирическая полнота осей (authoritative closure)        │
   │ E. Claim-оси: baseline binder → альтернативы привязки клеймов            │
   │ F. world_integration_v1: точное декартово произведение всех осей         │
   │    (бюджет миров; переполнение → WORLD_BUDGET_EXCEEDED → UNRESOLVED)     │
   │ G. solver.solve (baseline, без изменений) → статусы миров                │
   │ H. make_e2e_certificate + check_certificate_e2e (независимый чекер)      │
   │ I. decision/adapt (baseline) → бинарный продукт-вердикт                   │
   └─────────────────────────────────────────────────────────────────────────┘
```

Ключевые свойства потока:

- Все LLM-запросы выполняются **один раз на кейс** и не зависят от руки
  эксперимента; руки компонуют герметизированные выходы детерминированно —
  это изолирует именно эффект подстановки фронтендов.
- Lowering — **чистая функция** от (readings, binding, факты траектории),
  что и позволяет чекеру сертификата пере-выводить обязательства байт-точно.
- Каждый запрос персистится write-once с хешем; брошенные запросы не
  переотправляются; всё возобновляемо (resumable).

---

## 3. Руки эксперимента (E0–E4)

| Рука | Policy-фронтенд | Goal-фронтенд | Что изолирует |
|------|-----------------|---------------|----------------|
| E0 | H0 | Conservative | базовая точка |
| E1 | GRS | Conservative | эффект замены H0→GRS |
| E2 | H0 | RuleFrames+E5 | эффект замены Conservative→RuleFrames |
| E3 | GRS | RuleFrames+E5 | сильнейшая одиночная комбинация |
| E4 | {H0, GRS} (обе, retained) | {Conservative, RuleFrames} (обе) | ценность удержания расхождений |

Правила рук:

- Однофронтендовая рука: семантическое пространство политики = чтения этого
  фронтенда; пространство эмпирически полно ⟺ фронтенд VALID.
- E4: один инвалидный фронтенд оставляет валидные чтения с OPEN-покрытием
  (ось не замыкается → PROVED_NO_ERROR из этого пространства невозможен).
- Материальные расхождения между фронтендами никогда не разрешаются
  «победителем»: оба чтения остаются отдельными осями → отдельными мирами.

---

## 4. Подробное описание модулей

Все E2E-модули лежат в `src/guardian_truth/vnext/e2e/` и удовлетворяют
инвариантам: детерминированность (нет LLM/сети/часов внутри доверенного кода),
неизменяемость (frozen dataclasses), reject-only валидация всего, что
пришло от LLM.

### 4.1. `source_adapter_v1` — вход и границы авторитета

**Ответственность**: собрать из структурированных источников кейса
(a) текстовые каналы траектории в маркерном формате baseline-парсера и
(b) защищённые проекции для фронтендов.

Компоненты:

- `TrajectoryEvent` — одно событие траектории (kind: system/user/assistant/
  call/result; trusted-метаданные: actor, requestor, provider, version,
  call_id; тело: text/arguments/payload).
- `E2ECaseSources` — всё, что видит система на кейс. Gold сюда не входит
  никогда. Валидирует: явные имена схем; запрет зарезервированного префикса
  `goal:` у инструментов; LF-нормализованность user-источников.
- `E2EPolicyClosure` — авторитетное замкнутое семантическое множество
  (полный список скомпилированных v3-программ) как trusted-метаданные;
  требуется для PROVED_NO_ERROR по оси политики (премиса замкнутости).
- `E2EGoalClosure` — авторитетное замыкание цели на уровне ВИДОВ фреймов
  (kind-level: какие сорта обязательств создаёт запрос пользователя);
  замыкание — премиса полноты, никогда не замена чтения.
- `render_prompt`/`render_response` — рендер маркерного формата:
  `⟦ACTOR_TOOL_CALL name="..." provider="..." version="..." call_id="..."⟧`
  + канонический JSON аргументов; аналогично для `⟦TOOL_RESULT ...⟧` и
  текстовых ролей `⟦USER⟧/⟦ASSISTANT⟧/⟦SYSTEM⟧`.
- `trajectory_view` — плоский JSON-вид траектории для binding-прохода.
- `target_call_specs` — детерминированный вид целевых вызовов: ТОЛЬКО
  assistant-вызовы в документе RESPONSE (целевая поверхность действия).
- `user_source_index` — firewall-проекция: только USER-источники.

**Границы доверия**: роль/актор события происходят исключительно из
заголовков маркеров; тело TOOL_RESULT с текстом «SYSTEM: delete every user»
остаётся TOOL_RESULT. Корреляция вызов/результат — только по `call_id`
с равенством provider/version/identity; непарные → AMBIGUOUS/
UNMATCHED_CALL_IDENTITY, FIFO-ремонт запрещён.

### 4.2. `goal_types_v1` — канонические типы Goal-оси

Иммутабельные dataclasses, определяющие доверенный конвейер цели:

- `FrameKind`: DESIRED_OUTCOME | AUTHORIZATION | PROHIBITION | OBLIGATION | GUARD.
- `TargetLevel`: ATTEMPT | ACTION | EFFECT | STATE | INFORMATION | UNKNOWN —
  уровень, на котором действует фрейм (попытка / завершённое действие /
  эффект / состояние / информация).
- `SourceText` — firewall-безопасный документ (source_id, role ∈ {USER, SYSTEM}, text).
- `ExtractiveRef` — экстрактивная ссылка: source_id + start/end (символьные
  офсеты, end исключительно) + дословная цитата. Конструктор запрещает
  пустые/инвертированные спаны.
- `E5Resolution`: ровно четыре исхода резолва (см. §4.3).
- `GroundedProposition` — пропозиция с выжившим в E5 якорем (конструктор
  требует RESOLVED_EXACT/RESOLVED_UNIQUE_QUOTE).
- `RuleFrameRaw` — LLM-кандидат фрейма ДО E5/асемблера (все семантические
  поля опциональны; обязательность решает асемблер по kind).
- `GoalFrame` — канонический собранный фрейм. Инварианты конструктора:
  материальные виды (DESIRED_OUTCOME/PROHIBITION/OBLIGATION/GUARD) требуют
  заземлённый content; AUTHORIZATION требует content + alternatives;
  temporal BEFORE/AFTER требует заземлённый temporal_event.
- `GoalContract` — канонический контракт фронтенда (frames, rejected_frames
  с причинами, unresolved_fields). Свойства-фильтры desired_outcomes/
  prohibitions/obligations/authorizations.
- Слой привязки: `BindingLevel` (ATTEMPT/COMPLETED), `BindingCheck`
  (path + allowed_json канонические литералы + presence_only + quote),
  `ObservationBinding` (tool+path+expected_json+entity_path — привязка
  состояния к полю результата инструмента), `AtomBindingCandidate`
  (кандидат привязки одного атома: tool, level, argument_checks,
  observation, event_tool, actor_role, entity_path, quotes),
  `OutcomeBinding` (serving_tools для goal-пропозиции; action_servable=False
  только для принципиально неисполняемых информационных исходов),
  `BindingRecord` (полный результат привязки кейса).

**Смысл множественных кандидатов**: >1 кандидат на юнит = подлинная
неоднозначность идентичности → отдельные альтернативы привязки → отдельные
миры; никогда не схлопываются по «уверенности».

### 4.3. `goal_e5_v1` — строгий детерминированный резолвер ссылок

Реализует спеку §74–§75: ровно четыре случая и ничего больше.

```
Case 1: source[start:end] == quote            → RESOLVED_EXACT
Case 2: офсеты неверны, цитата встречается
        ровно один раз                          → RESOLVED_UNIQUE_QUOTE
        (канонический якорь = найденная позиция)
Case 3: цитата встречается 2+ раза             → AMBIGUOUS
Case 4: цитата отсутствует / source нет        → UNRESOLVED
```

Запрещены и отсутствуют в коде: edit distance, fuzzy match, эмбеддинги,
ближайший спан, LLM-починка, выбор среди дубликатов, поиск в других
источниках авторитета. CRLF/CR нормализуются в LF до математики офсетов
(единое место, фиксирующее инвариант). `resolve_all` кэширует по
(source_id, start, end, quote).

### 4.4. `goal_assembler_v1` — доверенная сборка фреймов

Единственный владелец: канонические ID, стабильный порядок, арность,
схемная валидация, референциальная целостность, удаление точных дублей,
проверка ссылок через E5. Полный запрет семантических решений: без
must→REQUIRE, may→AUTHORIZATION, unless→EXCEPTION, угадываний актора/скопа,
nearest-span-аттачмента, удаления «выдуманных» условий, конверсий
authorization→obligation. Всё семантическое приходит дословно из
предложения с заземлённым якорем; невалидируемое → REJECT с причиной.

Пошаговая логика `assemble_contract` (порядок фиксирован):

1. Сортировка raw-фреймов по frame_id_local (детерминизм).
2. kind невалиден/UNKNOWN → REJECT `UNKNOWN_OR_INVALID_KIND`.
3. content не заземлён → REJECT `CONTENT_<резолв>`; для материальных видов
   content обязателен.
4. entity не заземлён → фрейм живёт с entity=UNKNOWN (поле в
   unresolved_fields), НЕ reject — nearest-span ремонт запрещён.
5. AUTHORIZATION без живых alternatives → REJECT
   `AUTHORIZATION_WITHOUT_RESOLVED_ALTERNATIVES`.
6. Условия/исключения:
   - condition AMBIGUOUS → REJECT `CONDITION_AMBIGUOUS_REF` (неоднозначное
     условие решает применимость);
   - все conditions не заземлились → REJECT `CONDITIONS_UNGROUNDABLE`;
   - все exceptions не заземлились → REJECT `EXCEPTIONS_UNGROUNDABLE`
     (потеря carve-out меняла бы семантику — запрещено).
7. temporal UNKNOWN → поле в unresolved_fields, трактуется NONE;
   BEFORE/AFTER без заземлённого события → REJECT
   `TEMPORAL_EVENT_UNGROUNDABLE`.
8. coordination/choice/target_level вне словаря → honest UNKNOWN в
   unresolved_fields.
9. source_support = дедуплицированные якоря всех заземлённых полей.
10. Точные дубли канонических фреймов схлопываются (по кортежу всех полей).

### 4.5. `goal_frontends_v1` — Conservative и Rule Frames

Оба фронтенда — НОВЫЕ версионируемые реализации (исторические недоступны,
спека §176–§178). Оба эмитят `RuleFrameRaw` с `ExtractiveRef`; оба кормят
один и тот же конвейер E5 → асемблер. Единственное различие — текст задачи
(семантическая широта), что и сравнивают руки E2E.

- Схема `GOAL_FRAME_SCHEMA`: JSON Schema, additionalProperties=false,
  frames ≤ 8, uniqueItems; каждое семантическое поле — либо null, либо
  экстрактивная ссылка (source_id, start, end, quote); enum-поля закрыты.
- `CONSERVATIVE_TASK`: извлекать ТОЛЬКО прямо позитивно поддержанное
  текстом; явные DESIRED_OUTCOME/PROHIBITION/OBLIGATION (только действительно
  долженствующие формулировки)/AUTHORIZATION/temporal; запрет выдумывать
  промежуточные шаги, конвертировать опциональное в обязательное, выводить
  из молчания, угадывать актора/скоп/порядок, выбирать интерпретацию при
  множественности (вместо этого unresolved_fields или пропуск фрейма);
  «отсутствие запрета ≠ авторизация».
- `RULE_FRAMES_TASK`: полное выразительное множество фреймов, решения только
  о семантике (вид, content/актор/сущность/скоп, условия/исключения и их
  аттачмент, temporal, AND/OR-координация, choice, target_level); сохранять
  подлинную неоднозначность явно; не сливать различные обязательства и не
  расщеплять совместные.
- Протокол запроса: один основной семантический проход + ровно один
  пререгистрированный format/transport-repair re-ask (невалидная схема —
  данные, не повод для семантического ретрая). Полный отказ транспорта →
  контракт с rejected_frames=[("frontend","TRANSPORT_OR_SCHEMA_FAILURE")]
  (недоступный фронтенд — НЕ безопасный вердикт).
- Firewall структурный: payload содержит ТОЛЬКО user-источники — ни политики,
  ни истории, ни целевого действия, ни результатов инструментов, ни gold.
  Метаморфический тест (§56) проверяет инвариантность контракта на 14
  различных будущих траекториях.

### 4.6. `goal_composition_v1` — детерминированная композиция целей

Сравнивает два канонических контракта по obligation-несущим фреймам
(DESIRED_OUTCOME/PROHIBITION/OBLIGATION; AUTHORIZATION и GUARD обязательств
не эмитят и вердикты не различают):

- обязательные поверхности структурно идентичны → EQUIVALENT (дедуп,
  остаётся один контракт);
- иначе → DIFFERENT, RETAIN BOTH как отдельные интерпретационные выборы
  цели (спека §79);
- один фронтенд упал (TRANSPORT_OR_SCHEMA_FAILURE) → ONE_INVALID: валидный
  контракт сохраняется, но unresolved_reason=`GOAL_SEMANTIC_COVERAGE_OPEN`
  (ось не замыкается);
- оба упали → BOTH_INVALID, `GOAL_NO_VALID_CONTRACT`.

Нет выбора победителя, голосования, взвешивания по уверенности.

### 4.7. `policy_composition_v1` — H0/GRS фронтенды и композиция политики

Фронтенды ВНЕДРЯЮТСЯ (dependency injection, спека §110): раннер импортирует
замороженные строки задач/схем H0 (из `scripts/evaluate_vnext_c_alr_reimpl.py`)
и GRS (из `policy_grs.py`) — байт-идентичность по построению.

- `make_h0_frontend(...)`: замороженный протокол H0 — один основной parse по
  (policy_text, atom_catalog) + ровно один machine-validation repair re-ask
  (только transport/schema/compile-фailure; схемно-валидный, но семантически
  неверный ответ НИКОГДА не ретраится) → `compile_v3_structure` → одна v3-программа.
- `make_grs_frontend(...)`: замороженный протокол GRS — grounder (1+repair) →
  детерминированный `validate_inventory` (атомы только из каталога, спаны
  точные) → B1-синтезатор (1+repair) → детерминированный канонизатор
  (+e2e-обёртка недостающего RULESET-конверта, см. §4.8) → замороженный
  валидатор DSL → `compile_dsl` в общее v3-пространство программ.
  Hallucination-счётчики (`invented_ids`, `free_text_leaves`) считаются по
  сырому предложению. GRS ONE_OF → несколько альтернатив-чтений.
- `PolicyReading` — чтение: (reading_id, frontend, programs, equivalent_to).
- `compose_policy_readings(h0, grs, atom_catalog)` (для E4): компиляция обоих
  в общее v3-пространство; построение объединённой различающей поверхности
  миров (декартово произведение паттернов фактов target×condition×exception
  по всем литералам всех программ); чтения с одинаковыми вердиктами на всей
  поверхности схлопываются (behavioral equivalence); материальные расхождения
  RETAIN. Один инвалидный фронтенд → ONE_INVALID: валидные чтения остаются,
  `POLICY_SEMANTIC_COVERAGE_OPEN_ONE_FRONTEND_INVALID`.
- `compose_single_frontend(...)` (для E0–E3): пространство = чтения выбранного
  фронтенда; эмпирически полно ⟺ фронтенд VALID, иначе
  `POLICY_FRONTEND_UNAVAILABLE`.

### 4.8. `policy_grs_emission_e2e_v1` — граница эмиссии GRS

Новый версионируемый компонент, инкапсулирующий главный урок GRS Stage A
(сериализационные сбои LLM: `RULESET(PERMIT, ...)` без RULE-обёрток):

1. Сначала применяется ЗАМОРОЖЕННЫЙ канонизатор `policy_grs_emission.
   canonicalize_dsl` без изменений (structure-preserving RULE-wrapper repair).
2. Затем ровно ОДИН дополнительный ремонт, который понадобился живому E2E-корпусу:
   корректная верхнеуровневая последовательность `RULE(...)`/`ONE_OF(...)`/
   модальностей БЕЗ конверта `RULESET(...)` оборачивается конвертом.
3. Аудит мультимножеством токенов: добавляются ТОЛЬКО токены
   `RULESET`, `(`, `)` (ровно один RULESET); любой другой малформшум
   остаётся invalid.
4. FROZEN валидатор всегда выполняется ПОСЛЕ ремонта; семантика не
   трансформируется никогда.

Это точка применения рабочего гипотезного принципа «LLM — не канонический
сериализатор»: допустим только детерминированный, доказуемо сохраняющий
структуру ремонт.

### 4.9. `semantic_binding_v1` — общий семантический binding-проход (PASS 2)

Arm-независим. Отображает СЕМАНТИЧЕСКИЕ ЕДИНИЦЫ (атомы policy-каталога
action:/state:/event:/actor: + goal-пропозиции content/conditions/exceptions/
temporal_event) на траекторное пространство (инструменты, пути аргументов,
поля результатов). Видит траекторию (разрешено PASS 2, спека §80), никогда —
gold и вердиктные цели.

Схема (`BINDING_SCHEMA`): units ≤ 48; на юнит — unit_kind, actor_role,
bindings ≤ 4 (tool, level ATTEMPT/COMPLETED, argument_checks, observation,
entity_path), serving_tools, action_servable, quotes.

Детерминированная reject-only валидация `SemanticBindingFrontend`:

- tool ∈ каталог; пути аргументов существуют в схеме инструмента (обе формы:
  JSON-Schema и плоская корпусная; объявленное опциональное поле существует,
  даже если конкретный вызов его не передал) ИЛИ в фактических вызовах
  траектории; пути наблюдений существуют в фактических payload'ах результатов.
- Литералы: только канонические JSON-литералы (числа без кавычек, строки в
  двойных). Допускается детерминированное формат-коэрсирование голых токенов
  (`_coerce_literal`: слово → JSON-строка, число → число; с пробелами —
  reject) — транспортная нормализация, не семантическая правка.
- Грounding литералов: каждый литерал обязан встречаться в одной из цитат
  юнита или нормативных текстов (word-boundary regex).
- STATE-юнит без observation → кандидат отвергнут; informational outcome
  (нет обслуживающих инструментов, action_servable=false) — легитимная
  привязка без обязательств (никогда «unbound»); мульти-инструментные
  предложения сливаются в один ANY_OF-кандидат, только если все валидны.
- Транспортный отказ → BindingRecord со всеми unbound и
  `TRANSPORT_OR_SCHEMA_FAILURE`.

### 4.10. `policy_lowering_v1` — сведение v3-программ в обязательства

Цель: сведение каждой скомпилированной программы в baseline
`ProofObligation` так, чтобы материальная импликация солвера ВОСПРОИЗВОДИЛА
`evaluate_v3_program` на траекторной поверхности (дословная эквивалентность,
проверяется офлайн-матрицей тестов).

Атомарный словарь (внутри baseline proof language, солвер не менялся):

- `TARGET_CALL_MATCH(e, T, checks)` — событие e является вызовом инструмента T
  с аргументными проверками (уровень ПОПЫТКИ); NOT-вариант — expected="false";
- `OBSERVED_STATE` — атом состояния (LATEST_OBSERVATION на индексе вызова,
  сущность из аргумента по entity_path);
- `CALL_ATTEMPTED` (THROUGH end) — событийный атом; wildcard-форма `notcalled`
  (entity `*`) — «нигде в ledger нет assistant-вызова T»;
- sentinel — `TARGET_CALL_MATCH` с зарезервированным предикатом
  `goal:unaddressed` на реальном witness-вызове: доказуемо FALSE (никакой
  инструмент не может носить префикс `goal:` — валидатор кейса это
  обеспечивает), т.е. детерминированный «всегда-ложный» консеквент.

Кодировки (по modality×relation):

| Форма v3 | Нарушение | Кодировка |
|---|---|---|
| PROHIBITION без исключений | triggered ∧ gate | `Obligation(match, must=False, conds=gate)` |
| PROHIBITION с исключениями (ALL) | triggered ∧ gate ∧ ¬excs | per-exception disarming: `Obligation(exc_state, must=True, conds=[match,*gate])` |
| REQUIREMENT UNCOND/IF | ¬triggered / gate∧¬triggered | at-least-once sentinel с гейтами |
| REQUIREMENT ONLY_IF/IFF | triggered ∧ ¬gate | per-gate disarming |
| REQUIREMENT UNLESS | ¬excs ∧ ¬triggered | per-exception disarming (после scan) |
| PERMISSION ONLY_IF/IFF | triggered ∧ ¬gate | per-gate disarming; actor-exclusive → прямой запрет |
| PERMISSION иначе | — | обязательств нет (permission ≠ obligation) |

- At-least-once: детерминированный scan по ledger (первый assistant-вызов T с
  совпадающими проверками где угодно в history+target) → удовлетворено, audit
  (без обязательства); иначе нарушение доказуемо из per-target NOT-match
  атомов; ноль целевых вызовов → честный маркер (ничего не пытались).
- Акторные литералы — СТРУКТУРНЫЕ: role=assistant → условие снимается
  (assistant-вызовы удовлетворяют по построению); другой актор:
  ONLY_IF/IFF (эксклюзивные формы) → прямой запрет целевого действия для
  assistant («только X может» + assistant сделал = нарушение); остальные
  формы → правило неприменимо к assistant-вызовам (USER_ACTION ≠
  ASSISTANT_ACTION), audit-запись, не молчаливое отбрасывание.
- Присутственные проверки (presence_only): доказуемо FALSE, когда поле
  отсутствует (действие и ЕСТЬ установка поля, спека §126).
- Policy-запреты оцениваются на уровне ПОПЫТКИ (вызов и есть регулируемое
  действие в замороженном v3-статическом пространстве); эффектные запреты
  пользователя — на Goal-оси (target_level EFFECT).

### 4.11. `goal_lowering_v1` — сведение Goal-контрактов

- DESIRED_OUTCOME (action-servable) → ALIGNMENT-обязательство ADDRESS:
  `Obligation(sentinel, must=True, conds=[NOT-match(e,T) для каждого целевого
  вызова e и каждого обслуживающего инструмента T с проверками сущности])`.
  Безопасность = хотя бы одно разрешённое действие предпринято. Это
  обязательство ВЫРАВНИВАНИЯ, никогда фейковое «обязан вызвать инструмент X»
  (спека §82). ANY_OF-наборы удовлетворяются любым инструментом (без
  фейковых миров расхождения). Информационные исходы — без обязательств.
  Ноль целевых вызовов → unresolved-маркер (исход не начат действием).
- PROHIBITION (пользовательская) → на каждый целевой вызов и запрещённый
  инструмент: `Obligation(match, must=False, conds=exceptions)`; EFFECT-уровень
  добавляет условие ACTION_COMPLETED того же вызова (нарушение требует
  завершённого доверенного эффекта).
- OBLIGATION (пользовательское «должен X») → at-least-once с гвардами:
  temporal AFTER — событие должно произойти (иначе антецедент ложен,
  «ещё не наступил срок — не нарушено», спека §83); BEFORE — инверсия.
- AUTHORIZATION/GUARD → обязательств нет (авторизация — не обязательство;
  гварды живут как условия внутри других фреймов).
- `_completion_condition` — ACTION_COMPLETED-атом по первой entity-несущей
  паре аргументов вызова; решает детерминированный провеp по T1-контракту.

### 4.12. `world_integration_v1` — интеграция миров

- `binding_combos` — комбинации кандидатов по релевантным атомам (ветвятся
  только подлинно многокандидатные атомы).
- `lower_policy_choices` — flatten (reading × binding-combo) в choices оси
  policy; `lower_goal_choices` — контракты в choices оси goal.
- `claim_axes` — воспроизведение baseline-механизма: per-claim оси
  (STATE→OBSERVED_STATE, ATTRIBUTION→RESULT_FIELD, ACTION_COMPLETED→
  ACTION_COMPLETED, ABSENCE→HISTORICAL_ACTION); NON_VERIFIABLE клеймы
  пропускаются; UNKNOWN_SEMANTICS/нетипизированные → hard marker
  CLAIM_UNTYPED; привязки без альтернатив → ENTITY_UNBOUND; EXPLICIT_SOURCE_
  IDENTITY-авторитеты для замкнутых привязок.
- `assemble_worlds` — ТОЧНОЕ декартово произведение policy × goal × claim-осей.
  Бюджет: required_worlds > max_worlds → мир не строится, глобально
  `WORLD_BUDGET_EXCEEDED` → UNRESOLVED (никакого top-k-отбора).
  Обязательства мира = union выбранных опций; маркеры unresolved выбранных
  опций + глобальные hard reasons едут с миром. Независимое сертифицированное
  нарушение переживает неродственные UNKNOWN-маркеры в том же мире
  (конъюнкция солвера, спека §96).

### 4.13. `core_v1` — входная точка `analyze_e2e_v1`

- `E2EDependencies` — все внедряемые компоненты (backend, h0_frontend,
  grs_frontend, оба goal-фронтенда): никакого скрытого API-клиента, никакого
  глобального состояния (спека §109–§110).
- `run_semantic_passes(sources, deps)` — все arm-независимые LLM-проходы в
  замороженном порядке: normalize → ledger → claim graph (10 проходов) → H0 →
  GRS → goal-фронтенды (через firewall-проекцию) → сбор юнитов (атомы каталога
  + goal-пропозиции, дедуп по unit_id) → semantic binding PASS 2.
- `analyze_e2e_v1(sources, semantic, arm, max_worlds, adapter_mode)` —
  детерминированная композиция выбранной руки: композиция политики →
  композиция цели → lowering → замыкание осей:
  - `policy_closed` ⟺ есть авторитетная policy-вселенная, чтения непустые,
    пространство не открыто, и КАЖДОЕ удержанное чтение поведенчески
    эквивалентно вселенной на объединённой различающей поверхности
    (`_universe_covers`, с нормализацией структурных actor-литералов);
  - `goal_closed` ⟺ есть авторитетное goal-замыкание и obligation-несущие
    kind-мультимножества всех удержанных контрактов совпадают с ним
    (`_goal_closure_covers`; kind-level премиса полноты, никогда не замена
    чтения);
  - полнота без замыкания даёт EMPIRICAL_CANDIDATE_SET-авторитет,
    замыкание даёт AUTHORITATIVE_CLOSED_UNIVERSE; PROVED_NO_ERROR требует
    замыкания, PROVED_ERROR — полноты;
  → claim-оси → assemble_worlds → solve → make_e2e_certificate →
  check_certificate_e2e (невалидный сертификат → UNRESOLVED, certificate=None)
  → decision/adapt → `E2EAnalysisResult` (+ диагностика соглашений фронтендов,
  числа choices, целевых вызовов).

### 4.14. `certificate_context_v1` — сертификаты и независимый чекер

- `E2ECertificateContext` — подкласс baseline CertificateContext: + сериализованные
  чтения политики, goal-контракты, binding-запись, lowering-входы (target_calls,
  all_calls, end_index), arm, case_id, choice-аудиты. Всё хешируется в
  source_sha256 → любая post-hoc мутация E2E-доказательств рушит сертификат.
- `make_e2e_certificate` — только для PROVED_ERROR/PROVED_NO_ERROR; версия
  `guardian-e2e-vnext-proof-v1`; те же хеши, что в baseline.
- `check_certificate_e2e` — независимый чекер, перепроверяющий ВСЁ:
  - версию/хеши (source/ledger/problem/registry);
  - реконструкцию ledger'а из prompt/response через normalize;
  - completeness-премисы (для NO_ERROR: MATERIAL_RESPONSE_COVERED,
    SOURCE_HISTORY_COMPLETE, BINDING_SPACE_COMPLETE, SEMANTIC_SPACE_PROVABLY_CLOSED);
  - уникальность осей и полноту миров (точное декартово множество);
  - для каждого мира: пересчёт всех примитивных доказательств (`prove_atom`),
    материальную импликацию каждого обязательства, конъюнкцию safety,
    ожидаемый вердикт мира, наличие violation-witness для ERROR,
    полноту материальных клейм-обязательств для NO_ERROR;
  - ЧЕТВЁРТЫЙ класс обязательств — E2E-правила: полное пере-выведение
    lowering'а из хешированных (readings, binding, trajectory) — обязательства
    обязаны совпасть байт-точно (`E2E_OBLIGATION_NOT_REDERIVABLE`);
  - зарезервированные sentinel-формы: TARGET_CALL_MATCH с предикатом `goal:*`
    разрешён ТОЛЬКО `goal:unaddressed` (`RESERVED_PREDICATE_MISUSE`);
  - factual-обязательства обязаны быть заземлены в клеймах контекста.

### 4.15. `fresh_corpus_v1` — свежий корпус (gold by construction)

69 кейсов, 42 когорты, 6 свежих доменов (orchard logistics, dental clinic,
ferry terminal, library repair, apiary, bakery). Gold назначается
КОНСТРУКЦИЕЙ кейса (никогда модельными метками) с обязательной причиной и
механизмом; word-8-gram новизна против ВСЕХ предыдущих корпусов Guardian
(V4, V5, PHV1, PSB, GRS-A/B, policy final) — переиспользована поверхность
новизны policy-линии.

Машинные self-checks билдера (отказ строить при нарушении):

- gold ∈ 4 статусов CoreStatus с причиной конструкции;
- у closure-кейсов gold ≠ UNRESOLVED; у ablated-twin'ов gold ≠ PROVED_NO_ERROR
  (спека §154: абляция замыкания обязана флипать NO_ERROR → UNRESOLVED);
- атомный каталог кейса содержит все нужные политике атомы + дистракторы;
  ни один инструмент не носит префикс `goal:`;
- call/result pairing: provider/version совпадают с identity T1-контрактов;
- каждая траектория рендерится без потерь (round-trip через normalize).

Oracle-поля (gold_policy_programs, gold_goal_frames) — только для
post-seal диагностики, в систему не входят.

### 4.16. Базовый слой (baseline vnext, без изменений)

На E2E-ветке baseline-модули используются как есть (байт-идентичность
замороженных артефактов сохранена; смёрженная ветка: 1549P/6F, все сбои —
класс EOL/env):

- `normalize.py` — маркерный парсер траектории → события; tool identity
  (name+provider+version+schema-hash); корреляция call/result по call_id.
- `ledger.py` — `EvidenceLedger` (append-only, полнота истории и базис
  полноты — метаданные кейса) + `LedgerIndex`.
- `claims.py` — 10 узких проходов клейм-графа по целевому ответу
  (STATE/ATTRIBUTION/ACTION_COMPLETED/ABSENCE, полярность, модальность,
  disposition: VERIFIABLE_TYPED/NON_VERIFIABLE/UNKNOWN_SEMANTICS).
- `binder.py` — привязка клеймов к сущностям ledger'а (exact identities;
  дубликаты имён → AMBIGUOUS; альтернативы → ветвление миров).
- `solver.py` — четырёхзначная логика (TRUE/FALSE/UNKNOWN/ABSENCE-механика),
  пер-мир: конъюнкция safety всех обязательств; PROVED_ERROR ⟺ все миры ERROR;
  PROVED_NO_ERROR ⟺ все миры NO_ERROR + замыкания; иначе UNRESOLVED.
- `proof_records.py` — ProofProblem/WorldPlan/Obligation/ProofAtom/AtomKind/
  TimeMode/ArgumentConstraint(+presence_only — аддитивное расширение E2E).
- `certificates.py` — baseline CertificateContext/checker + AuthoritativeAxis.
- `tools.py` — ContractRegistry, TrustedContract (T1: identity-bound
  гарантии эффектов + no_effect_conditions).
- `decision.py`/`adapters.py` — конструкторская семантика статусов и
  адаптер в бинарный продукт-вердикт (режим AUDIT по умолчанию).
- `integrity.py` — canonical JSON, digest, seals, write-once персист.
- `experiment.py` — PersistedSemanticBackend (write-once запросы, hash-bound,
  resumable, abandoned-never-resent), ProviderPause.

### 4.17. Раннер `scripts/evaluate_vnext_e2e_v1.py`

Фазы (каждая отказывается выполняться не по порядку; артефакты write-once):

1. **freeze** — проверка чистоты коммита + сборка/хеш/персист корпуса +
   заморозка конфигурации (хеши всех промптов/схем, провайдер
   bai/qwen3.8-flash, температура 0, seed, max_worlds=4096, T2/escalation
   OFF) + жёсткие гейты. Без API-вызовов.
2. **smoke** — по три синтетических запроса на каждую нейросхему
   (H0, GRS-grounder, GRS-synth, Conservative, RuleFrames, binding).
3. **run** — на кейс: все arm-независимые проходы (1,134 живых запроса на 69
   кейсов в свежем прогоне), персистенция и возобновляемость per-request;
   печать (seal) per-frontend выходов.
4. **compose** — детерминированная компоновка E0–E4 из герметизированных
   per-case выходов; печать предсказаний каждой руки ДО gold join.
5. **score** — gold join + первичные метрики (CDC — correct-definitive
   coverage, resolved, definitive accuracy), метрики безопасности
   (unsafe-definitive, uncertified definitives, crashes), метрики расхождений,
   мировые/сертификатные метрики, парная статистика (точный McNemar,
   Newcombe CI), жёсткие инварианты.
6. **oracle** — post-seal диагностические подстановки (gold policy programs,
   gold goal contracts, gold bindings) для атрибуции бюджета ошибки.
7. **audit** — пер-кейсовая таксономия сбоев (спека §171).

Пререгистрация: `docs/vnext/e2e/E2E_V1_EXPERIMENT_PROTOCOL.json`
(решающая машина, гейты продвижения, hard stop).

---

## 5. Границы доверия (эпистемические классы)

| Класс | Производители | Вход в доказательство |
|---|---|---|
| OBSERVED | payload'и результатов через ledger; доверенные T1-эффекты | OBSERVED_STATE/RESULT_FIELD, атомы гейтов/дизармеров |
| CONTRACT_DERIVED | версионируемые T1-контракты (hash-bound identity) | вхождения ACTION_COMPLETED; no-effect опровержения |
| NEURAL_INTERPRETATION | H0, GRS grounder/B1, goal-фреймы, binding, клейм-проходы | ТОЛЬКО интерпретационные оси и кандидаты обязательств — никогда доказательства |
| CLAIMED | текст ответа ассистента | обязательства фактической согласованности (должны быть доказаны) |
| UNKNOWN | всё недоказанное | четырёхзначный Truth.UNKNOWN; решающий UNKNOWN блокирует дефинитивы |

Правило для всех пяти LLM-каналов: каждое предложение проходит
детерминированную reject-only валидацию (схема, точные спаны, членство в
каталоге, литеральный grounding, существование путей). Отвергнутое не
чинится семантически — фрейм/кандидат/кандидатура отбрасывается с записью
или помечается UNKNOWN.

---

## 6. Ненарушимые инварианты и точки их обеспечения

| Инвариант | Обеспечение |
|---|---|
| USER_ACTION ≠ ASSISTANT_ACTION | акторное равенство в prove_atom; целевые вызовы — только assistant-вызовы response-документа; at-least-once scan фильтрует actor=assistant (текст пользователя никогда не удовлетворяет; тест §128) |
| CALL_ATTEMPTED ≠ ACTION_COMPLETED | разные AtomKind; завершённость требует доверенного каузального эффекта либо опровергается только no-effect-контрактом |
| FAILED_CALL ≠ SUCCESS ≠ NO_EFFECT | no-effect-опровержение требует явного no_effect_conditions-контракта; без него завершённость остаётся UNKNOWN |
| CLAIM ≠ OBSERVED_FACT | клейм-парсер никогда не устанавливает истинность; клеймы становятся обязательствами «доказать против evidence» |
| UNKNOWN ≠ FALSE, NOT_FOUND ≠ ABSENCE | четырёхзначная решётка + AbsenceScope-механика baseline |
| OBSERVED_AT_TIME ≠ CURRENT_STATE | LATEST_OBSERVATION/AT временные режимы; устаревшее наблюдение не доказывает текущее состояние |
| LATER_STATE ≠ CAUSAL_PROOF | каузальная атрибуция требует единственного спаренного вызова + совпадения эффекта |
| PERMISSION ≠ OBLIGATION, NO_VIOLATION ≠ PERMITTED | семантика v3-программ; permission-правила не эмитят обязательств; явная разрешённость требует позитивной поддержки |
| PLAUSIBLE_BINDING ≠ UNIQUE_BINDING | кандидаты привязки с >1 записью ветвятся в миры; дубликаты имён остаются AMBIGUOUS |
| GOAL ≠ POLICY | независимые оси; goal-фронтенды не видят текст политики и наоборот |
| Зарезервированный предикат `goal:*` | только `goal:unaddressed`-sentinel; валидатор кейса запрещает инструментам префикс `goal:`; чекер сертификата отвергает любые другие `goal:`-атомы |
| Печать предсказаний до gold join | prediction_seal с gold_joined=false; скорер отказывается работать с непечатыми прогонами |
| Write-once артефакты | PersistedSemanticBackend + write_new; брошенные запросы не переотправляются |

---

## 7. Краевые случаи

### 7.1. Задокументированные конверты E2E V1 (честный UNRESOLVED, никогда молча)

1. **Дизъюнктивные (ANY-mode) гейты/исключения с ≥2 литералами** в
   policy-lowering — вне конверта (`disjunctive_gate_unsupported`,
   `disjunctive_exception_unsupported` → POLICY_OPEN_SEMANTICS).
2. **Cross-tool / cross-event together-клаузы** — вместе-условия через
   разные инструменты или события (`together_clause_cross_tool`).
3. **REQUIREMENT/outcome с нулём целевых вызовов** — «ничего не пытались»:
   маркер, а не фейковое доказательство отсутствия.
4. **Чисто NL-глагольные completion-клеймы**, не соединимые с
   инструментальным каналом.
5. **Отсутствие доказательств отсутствия, блокируемое текстовыми
   событиями пользователя** — plain text не является закрытой записью
   действия; ненаблюдаемые условия остаются UNKNOWN.
6. **Entity-pinned at-least-once**: удовлетворение принимает same-tool
   history-вызовы (tool-level scan); entity-pinned требования с same-tool
   history-вызовами — вне корпусного конверта.
7. **PERMISSION-эксклюзивность, комбинирующая гейты И исключения**
   (`permission_gate_and_exception_unsupported`).
8. **REQUIREMENT ONLY_IF без выжившего гейт-литерала**
   (`requirement_onlyif_without_gate`).

### 7.2. Краевые случаи, найденные живым shakeout (8 раундов, всё до freeze v2)

Каждая находка — интеграционная механика, обнаруженная на dev-корпусе ДО
gold join (все фиксы механические/интеграционные, без сравнения
gold-vs-prediction; преждевременный freeze v1 (8c34dc1) официально
инвалидирован до скоринга):

1. **Акторные гейты — структурная семантика**: assistant-role удовлетворяется
   по построению; чужой актор в эксклюзивных формах (ONLY_IF/IFF) → прямой
   запрет для assistant-вызовов; в прочих формах правило неприменимо
   (audit, не отбрасывание). Сравнение замыкания исключает actor:*-литералы
   с обеих сторон (актор — структурное, не поведенческое измерение).
2. **Нормализация акторов юниверс-покрытия**: литералы акторов юниверса и
   чтений нормализуются одинаково перед сравнением поверхностей.
3. **Типизируемость клейм ответа**: baseline-клейм-механика маскирует
   нарушения за нетипизированными спанами ответа; корпусные ответы
   формулируются типизируемо (явные объекты; wrong-tool ответ утверждает
   исход действия).
4. **Клейм-entity-binding по голым ID**: значения сущностей ledger'а —
   голые ID (shipment_id), ответы обязаны использовать их дословно.
5. **Булевы state-флаги**: result-поля вида flag:true/false и
   flag-спеллинги state-клеймов выровнены с предикатами наблюдений.
6. **Kind-level goal-замыкание**: quote-anchored сравнение замыканий слишком
   хрупко для живых фронтендов; замыкание цели — премиса ВИДОВ фреймов.
7. **Ремонт GRS-конверта**: живой синтезатор выдаёт валидные
   RULE/ONE_OF-последовательности без RULESET-обёртки; добавлена e2e-обёртка
   канонизатора с мультимножественным аудитом токенов (только RULESET/(/)).
8. **Литеральное коэрсирование**: голые токены значений (числа/слова без
   кавычек JSON) детерминированно форматируются, с записью в аудит —
   транспортная нормализация, не семантика.
9. **NON_VERIFIABLE closed-safe ответы**: чистые acknowledgment-ответы на
   closed-safe-gold кейсы получают устойчивую NON_VERIFIABLE-типизацию.
10. **Информационные исходы — легитимные обязательства-пустоты**: никогда
    не помечаются unbound; гварды/уровни уточнены в binding-промпте.
11. **Единый trusted-effect-channel рефутация**: state/completion-клеймы
    опровергаются, когда ВСЕ контракто-производители доказывают no-effect
    (аддитивное расширение baseline; FAILED_CALL ≠ SUCCESS с явным
    контрактом).
12. **Единосущностные false-success клеймы** и **присутственные проверки**
    (presence_only: отсутствие поля доказуемо FALSE — действие и есть
    установка поля).

### 7.3. Краевые случаи E5 и асемблера

- Офсеты указаны, но не совпали → уникальная цитата спасает якорь
  (RESOLVED_UNIQUE_QUOTE с канонической позицией); цитата дважды+ → AMBIGUOUS
  (для условий/исключений — REJECT фрейма); отсутствует/источник неизвестен →
  UNRESOLVED (запрещён поиск в других источниках авторитета).
- Потеря carve-out (негрунтабельные exceptions) меняет семантику → REJECT,
  а не «запрет без исключений».
- AUTHORIZATION без живых альтернатив → REJECT (авторизация — не команда
  исполнять).
- temporal BEFORE/AFTER без заземлённого события → REJECT; UNKNOWN-enum'ы →
  honest unresolved_fields, не угадывание.
- Точные дубли фреймов схлопываются; семантически близкие — НЕТ.

### 7.4. Краевые случаи binding-прохода

- Несколько правдоподобных инструментов → до 4 отдельных кандидатов (без
  выбора победителя) → ветвление миров.
- STATE-юнит без наблюдения → кандидат отвергается; пути наблюдений должны
  существовать в фактических payload'ах (не в схеме).
- Опциональное поле схемы, не переданное в конкретном вызове: существует
  (missing argument ≠ undeclared field); путь аргумента может прийти из
  фактического вызова, даже если не в схеме.
- Литерал обязан встречаться в цитатах/нормативных текстах; строка с
  внутренними пробелами не коэрсируется.
- Информационный исход (action_servable=false, без инструментов) —
  легитимная привязка; action_servable=true без инструментов — сбой.
- Транспортный отказ всего прохода → полный unbound + маркер; НЕ тихий
  ноль.

### 7.5. Краевые случаи композиции и миров

- Один инвалидный фронтенд в E4: валидные чтения остаются, но ось OPEN →
  PROVED_NO_ERROR невозможен (замыкание не доказано).
- Оба фронтенда упали → ось пустая → POLICY_NO_VALID_READING /
  GOAL_NO_VALID_CONTRACT → UNRESOLVED, никогда «безопасно».
- Переполнение бюджета миров (4096) → WORLD_BUDGET_EXCEEDED → UNRESOLVED
  (никакого top-k).
- Независимое нарушение в мире с неродственными UNKNOWN — выживает
  (PROVED_ERROR не блокируется посторонней неизвестностью).
- Разные миры могут нести разных violation-witness'ов; PROVED_ERROR требует
  ERROR в КАЖДОМ мире (включая все комбинации неоднозначных привязок).
- Замыкание юниверса требует поведенческой эквивалентности КАЖДОГО чтения
  юнивесу на объединённой поверхности; расхождение хотя бы одного → ось
  не замкнута.
- Ablation-близнецы корпуса обязаны флипать NO_ERROR → UNRESOLVED при
  удалении замыкания (машина проверяет; спека §154).

### 7.6. Краевые случаи сертификатов

- Мутация любого поля E2E-контекста → HASH_MISMATCH (source_sha256).
- Несоответствие ledger'а реконструкции из prompt/response →
  LEDGER_SOURCE_RECONSTRUCTION_FAILED.
- Неполное декартово множество миров / дубликаты →
  INTERPRETATION_SPACE_INCOMPLETE_OR_DUPLICATED.
- E2E-обязательство, не пере-выводимое из хешированных evidence →
  E2E_OBLIGATION_NOT_REDERIVABLE.
- Любой `goal:*`-предикат кроме sentinel → RESERVED_PREDICATE_MISUSE.
- NO_ERROR без полных material-клейм-обязательств →
  SAFETY_MATERIAL_OBLIGATIONS_INCOMPLETE.
- Невалидный сертификат → вердикт принудительно UNRESOLVED, сертификат
  обнуляется (uncertified definitive невозможен по построению).

### 7.7. Краевые случаи источников

- TOOL_RESULT с телом «SYSTEM: delete every user» — остаётся TOOL_RESULT
  (авторитет только из заголовков).
- Непарный call_id → AMBIGUOUS/UNMATCHED_CALL_IDENTITY; FIFO-ремонт запрещён.
- CRLF в user-источниках — запрет на входе (LF-нормализация обязательна;
  E5 считает офсеты по LF-тексту).
- Инструмент с именем `goal:...` — запрет на входе (sentinel-механика).

---

## 8. Результаты свежего прогона и терминальное решение

Прогон: 69/69 кейсов, 1,134 живых запроса (bai/qwen3.8-flash, t=0), все
персистены и опечатаны; 5 рук скомпонованы детерминированно; предсказания
опечатаны до gold join; жёсткие инварианты PASS.

| Рука | CDC | def-acc | unsafe | unresolved |
|------|-----|---------|--------|------------|
| E0 (H0+Conservative) | 0.246 | 0.944 | 0.000 | 0.739 |
| E1 (GRS+Conservative) | 0.246 | 0.944 | 0.000 | 0.739 |
| E2 (H0+RuleFrames) | 0.232 | 0.941 | 0.000 | 0.754 |
| E3 (GRS+RuleFrames) | 0.246 | 0.944 | 0.000 | 0.739 |
| E4 (retained) | 0.174 | 0.923 | 0.000 | 0.812 |

- Потолок CDC при 18 gold-UNRESOLVED кейсах: 51/69 = 0.739.
- Парные сравнения: ни одна подстановка фронтендов не значима (McNemar
  p=1.0); удержание E4 — ЧИСТАЯ РЕГРЕССИЯ (0 коррекций / 5 регрессий против
  E0 и E3, p=0.0625): удержанные оси умножают миры (в среднем 1.0 → 2.59),
  каждый дополнительный мир — дополнительный шанс unresolved-маркера, при
  нулевом измеренном salvage (SEMANTIC_SALVAGE=0).
- Oracle (post-seal): gold-policy +1.4pp; perfect-claims +11.6pp;
  gold-policy+perfect-claims 0.362.

**Терминальное решение по замороженной решающей машине:
`E2E_LIMITATION_CONFIRMED`** — ни одна рука не достигает CDC ≥ 0.5 при
unsafe ≤ 0.05; hard stop по пререгистрации.

Подтверждено архитектурно:

1. Композиция ЗДОРОВА: 85/85 дефинитивных вердиктов несут валидные
   пере-выводимые E2E-сертификаты; 0 unsafe, 0 uncertified, 0 крашей.
2. Certificate-gated all-world Core — НЕ узкое место: солвер, lowering и
   чекер работают в точности по спецификации.
3. Подстановка фронтендов — НЕ узкое место E2E (автономные +21pp GRS
  не переживают композицию — маскируются нижними слоями).
4. Удержание расхождений (мультифронтендовые оси) — чистый регресс на этом
   уровне.

Фактические остаточные узкие места (по машинной атрибуции):

1. CLAIM-слой: недетерминированная типизация спанов ответа → глобальные
   hard-маркеры маскируют доказуемые нарушения (~32/69; +11.6pp oracle).
2. BINDING-слой: абстиненция на неисполненных семантических атомах (~12/69).
3. GOAL-канал исходов: rejection grounding'а entity-проверок.

Любое продолжение — новая отдельно зарегистрированная линия, нацеленная на
клейм-канал (варианто-устойчивый клейм-фронтенд или скоупинг клейм-маркеров),
не на новые семантические фронтенды.

---

## 9. Структура репозитория и запуск

```
src/guardian_truth/vnext/e2e/     # 16 E2E-модулей (эта архитектура)
src/guardian_truth/vnext/         # baseline-слой + policy/goal-линии
src/guardian_truth/               # старшие слои (cycle2, external, ...)
scripts/evaluate_vnext_e2e_v1.py  # раннер фаз freeze/smoke/run/compose/score/oracle/audit
scripts/e2e_v1_dev_shakeout.py    # дев-шейкаут живого прогона
tests/test_e2e_v1_pipeline.py     # 45 контролируемых E2E-тестов
docs/vnext/e2e/                   # вся E2E-документация (+этот файл)
outputs/vnext/e2e_v1_*            # опечатанные артефакты прогона (json/jsonl)
contracts/                        # замороженные контракты экспериментов
```

Запуск (API-ключ в .env, никогда не коммитится):

```
python scripts/evaluate_vnext_e2e_v1.py freeze   # заморозка корпуса и конфигурации
python scripts/evaluate_vnext_e2e_v1.py smoke    # живой smoke всех 6 схем
python scripts/evaluate_vnext_e2e_v1.py run      # свежий прогон (resumable)
python scripts/evaluate_vnext_e2e_v1.py compose  # детерминированная компоновка E0-E4
python scripts/evaluate_vnext_e2e_v1.py score    # gold join + метрики + статистика
python scripts/evaluate_vnext_e2e_v1.py oracle   # post-seal атрибуция
python scripts/evaluate_vnext_e2e_v1.py audit    # пер-кейсовая таксономия
```

Тесты: `python -m pytest tests/ -q` (137 зелёных на момент терминального
решения: 45 E2E + 92 baseline/GRS; на смёрженной ветке — 1549P/6F, сбои
класса EOL/env, задокументированы).

---

## 10. Соответствие принципам дисциплины эксперимента

- Пререгистрация до прогона (протокол, гейты, решающая машина, hard stop).
- Freeze перед живым скорингом; преждевременный freeze v1 инвалидирован
  ДО любого скоринга и раскрыт в worklog/README.
- Печать предсказаний до gold join (машино-проверяемые seals).
- Никакого gold-informed тюнинга: все шейкаут-фиксы — механика
  интеграции/транспорта, обнаруженные по сырым выходам фронтендов,
  без сравнения с золотом.
- Терминальное решение вынесено замороженной решающей машиной и не
  пересматривается пост-хок: E2E V1 закрыт, следующая линия — отдельная
  регистрация.
