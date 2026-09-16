# COMPETITION REAL-INPUT AUDIT — Guardian B4h-sound-v2 vs AI Journey Guardian (Первая Задача)

Дата: 2026-09-16 (цикл competition-real-input-audit, от frozen `315bee3` = B4h-sound-v2)
Статус арм: C0 COMPLETE (sealed+scored) · C3 44/46 · C2/C1 protocol defined, execution throttled by research-LLM quota (см. §20-21)
Параллельные документы: `COMPETITION_REQUIREMENTS_AUDIT.md` (официальные условия, дословно), `outputs/vnext/competition_valid/*` (machine-readable артефакты)

## 0. Главный вопрос цикла

> Работает ли B4h-sound-v2 в реальных условиях олимпиады, если убрать hand-authored/oracle T1 metadata и разрешить использовать ТОЛЬКО информацию, реально присутствующую в prompt: SYSTEM policy, tool names, tool descriptions, tool schemas, arguments, conversation history, TOOL_CALL, TOOL_RESULT, candidate response?

Короткий ответ (развёрнут — по разделам):

1. **B4h-sound-v2 не подключён к текущему Docker-submission** —submission исполняет legacy `pipeline.Detector` (§3, CRITICAL PACKAGING/INTEGRATION GAP).
2. **Gold firewall достижим и верифицирован**: вывод зависит только от (id, prompt, response); инвариантность к label/explanation/id доказана тестами (§5).
3. **Реальный транспорт распарсен без oracle-метаданных**: каталог [AVAILABLE TOOLS] → типизированные схемы с source-span grounding; история и ответ — byte-exact (§4).
4. **Предпосылки T1**: аргументные схемы, read-характер инструментов и action-глаголы доступны из prompt (A/B классы); freshness, точные writes, effect guarantees, failure/completion semantics в prompt ОТСУТСТВУЮТ (§8/§9) — единственные семейства, где недостижим доказательный эффект-水平的 вердикт без oracle T1.
5. **12 публичных паттернов ошибок: 11 доказуемы из competition input** самым слабым достаточным proof-ом (invocation → schema → policy → claims); только точные effect/freshness state-proof требуют недоступных предпосылок (§10). Untrusted T2 сохраняет soundness: никогда не даёт definitive из недоверенных гипотез.
6. **Submission НЕ competition-ready в текущем виде**: зависимость от внешних LLM API (BAI мёртв по квоте; любой внешний API неконкурентоспособен при заблокированной сети) + превышение 30-минутного лимита на живых вызовах (§12-§14). «Research architecture works» ≠ «submission can execute it».

## 1. Метод и дисциплина

- valid.parquet = DEVELOPMENT/DIAGNOSTIC данные (не fresh holdout): никаких повторных просмотров ошибки, правил под кейсы, перезапусков ради F1. Все прогоны — без label в inference path (firewall + тесты), scoring — только post-seal (SHA256 манифест `prediction_seals.json`).
- Изменения frozen proof semantics: НЕТ (audit branch; новые модули adapter/runner не трогают vnext/e2e proof-ядро; единственное исключение — packaging-only фиксы .dockerignore).
- Домены (airline/banking_knowledge/retail/telecom) — только POST-HOC анализ; в production-коде нет ни одного `if domain ==` (§15: скан = 0 findings).

## 2. Официальные условия (кратко; дословно — в COMPETITION_REQUIREMENTS_AUDIT.md)

Вход: `<prompt>`/`<response>` текст; вход платформы — CSV; выход — CSV `id,label`; метрика Response F1; лимиты: 30 минут, <40 ГБ, 10 сабмитов; GPU: страница A100 vs правила PDF H100 — противоречие зафиксировано, локально консервативно A100; сеть для Первой Задачи не указана → консервативно считаем заблокированной.

## 3. §4 Execution-path audit — CRITICAL PACKAGING/INTEGRATION GAP

Фактический call graph текущего submission:

```
Dockerfile ENTRYPOINT python scripts/predict.py
  → guardian_truth.cli.main()                (src/guardian_truth/cli.py)
    → read_rows (CSV/JSONL/parquet)          — ок для платформы
    → detector_from_args → Detector(...)     (src/guardian_truth/pipeline.py — LEGACY)
    → per row: detector.review(prompt, response)
        → parse_events / parse_catalog / check_calls / check_turn_structure /
          check_date_gated_actions / build_graph / check_rules / analyze_plan /
          run_semantic (только при --backend != none)
    → decide(review, threshold, unknown_label)
  → CSV id,label
```

Доказательно: `vnext` не импортируется ни одним модулем этого пути (grep: 0 ссылок в top-level guardian_truth). **Docker-submission НЕ исполняет B4h-sound-v2.** Любой результат legacy Detector нельзя выдавать за результат B4h-sound-v2.

Дополнительные packaging-находки (§22):
- **Wheel-gap**: `python -m build` собирает wheel, но `guardian_truth.vnext.e2e` не импортируется из установленного wheel — `policy_historical_v1.py` импортирует `scripts.evaluate_vnext_c_alr_reimpl` (frozen исторический H0 источник). В Docker это маскируется `COPY scripts ./scripts` + `WORKDIR /app`. Устранено на audit-ветке whitelist-ом .dockerignore (в image входят ровно `predict.py`, `predict_e2e_competition.py`, `evaluate_vnext_c_alr_reimpl.py` — последний stdlib-only, 0 hardcoding findings).
- Docker в песочнице недоступен (`docker: command not found`) — §23 competition-like run помечен NOT_EXECUTABLE локально; Dockerfile audited статически (non-root USER 65534 ✓, pip install . ✓, ENTRYPOINT ✓).

## 4. §5-§7 Adapter, firewall, реальный envelope

**Реальный транспорт valid.parquet** (46/46 кейсов; официальный `⟦ASSISTANT_TOOL_CALL⟧`-маркер в 0/46 — dev-файл использует стрелочный транспорт):

| Компонент | Формат |
|---|---|
| SYSTEM | `<instructions>` + `<policy>` + `[AVAILABLE TOOLS]` DSL (`- name — desc`, `field: type! [enum: …]`) |
| Повороты | `⟦USER⟧`, `⟦ASSISTANT⟧`, `⟦ASSISTANT · ход N⟧` |
| Вызовы | tab-индентированные `→ TOOL_CALL name: {json}` / `← TOOL_RESPONSE name: {json}` внутри хода |

Envelope: 46 кейсов; домены 12/11/11/12; label 23/23; prompt 13.6K–233K chars (mean 42.6K); response 51–2339 (mean 519); ходов 2–52; tool-вызовов в истории 0–43 (mean 8.5); **в 23/46 ответах сами содержатся tool-вызовы** (проверяемое действие = часть ответа); tools с числовыми суффиксами (`close_debit_card_4721`), discoverable-паттерн (`unlock_discoverable_agent_tool` → `call_discoverable_agent_tool`), banking KB-инструменты (`KB_search_dense`, `grep`).

**Adapter** (`competition_adapter_v1.py`): парсит оба транспорта (реальный стрелочный + официально документированный маркер + `<prompt>/<response>`-теги) в `E2ECaseInput` с нулевыми oracle-полями:
- `system_policy` = весь SYSTEM-блок byte-exact (instructions + policy + каталог) — фронтенды видят ровно то, что видел агент;
- `user_request` = все USER-ходы (накопленное намерение; решения по дизайну задокументированы);
- `history` = ASSISTANT-ходы, перемаркированные `⟦ASSISTANT⟧` (тела byte-exact; стрелочные вызовы парсятся нативным legacy-парсером);
- `tool_schemas`/`tool_metadata` = из каталога DSL с digest-identity (канонические плейсхолдеры provider/version, т.к. промпт их не содержит);
- `history_complete=True` (black-box определение: промпт = весь контекст агента).

**Gold Firewall (§6)** — верифицирован тестами (`tests/e2e_competition/test_gold_firewall.py`, 5/5 PASS):
- физическое удаление всех колонок кроме id/prompt/response до inference;
- инверсия label/explanation → предсказания byte-identical;
- переименование id → предсказания byte-identical;
- упавший кейс = UNRESOLVED → label 0 (никогда не сфабрикованный вердикт).

## 5. §8-§9 T1 premise origin audit

Классификация происхождения предпосылок, которые T1-слой хотел бы получить (по всем 46 кейсам; таблица `t1_oracle_advantage.json`):

| Premise family | Needed | Available in prompt | Manual-only |
|---|---:|---:|---:|
| argument schema (поля/типы/enum) | 46 | **46 (A_EXPLICIT_SCHEMA)** | 0 |
| read-характер инструмента | 46 | **46 (B_EXPLICIT_TOOL_DESCRIPTION)** | 0 |
| action-глагол (дескрипшн-глагол действия) | 46 | **46 (B)** | 0 |
| freshness (fresh authoritative read) | 46 | **0 (G_NOT_AVAILABLE)** | 46 |
| точные writes (entity.field пути) | 46 | **0 (F_AMBIGUOUS/G)** | 46 |
| effect guarantee | 46 | **0 (G)** | 46 |
| result path ownership / failure / completion semantics | 46 | **0 (G)** | 46 |

Следствия:
- Всё argument/invocation/availability-семейство доказуемо из prompt (A/B).
- Описания дают только глагол действия («Update the flight information of a reservation») — НЕ точные typed writes; превращение глагола в `writes=[reservation.flights]` = LLM-интерпретация, которая по §9 НЕ становится trusted T1. Правило соблюдено: в C2 такие факты идут ТОЛЬКО через untrusted T2 (`UNTRUSTED_T2_SEMANTIC_PROPOSAL`, EffectStatus.POSSIBLE_EFFECT — никогда не definitive).
- freshness/writes/effect/failure/completion — отсутствуют в промпте ВООБЩЕ: только manual T1 (C1-потолок) или architecture V2 (source-grounded typed representation из описаний с явным provenance-уровнем) могли бы их дать.

## 6. §10-§11 Prompt-derived contract mode (C2)

C2 доверяет только source-backed фактам:
- схемы аргументов — детерминированный парсинг DSL с точными спанами (каждый атом: source document/start/end/exact quote/extraction type/trust level);
- политики/процедуры — через frozen h0_hist policy lowering (LLM-фронтенд видит весь SYSTEM-текст; его обязательства — стандартный путь архитектуры);
- текстовые утверждения — claim adapter с grounding-ом в историю;
- эффекты неизведанных инструментов — ТОЛЬКО untrusted T2 гипотезы (grounded в фактических аргументах/результатах), возможные эффекты, никогда не trusted.

Никакого восстановления полного T1: применяется приоритет слабейшего достаточного proof (invocation → schema → user-intent → procedural policy → argument provenance → factual claim → call/result mismatch → эффекты последними).

## 7. §12-§14 Четыре руки: протокол и статус

| Рука | Конфигурация | Статус | Примечание |
|---|---|---|---|
| C0 | текущий competition build = legacy Detector, `--backend none` (реальность Docker-запуска) | **COMPLETE, sealed, scored** | TP=12 FP=0 FN=11 TN=23; P=1.000 R=0.522 **F1=0.686**; telecom 6/6 TP (availability-механика); FN — семантические кейсы |
| C1 | B4h-sound-v2 + manual/oracle T1 (7 инструментов, механическая конвертация) | протокол готов; после C2 (reuse кеша) | диагностический потолок, НЕ competition-realistic; конвертация строго механическая, непереводимое — UNMAPPED (§13-дисциплина) |
| C2 | B4h-sound-v2 + prompt-derived only (ГЛАВНАЯ) | 1/46 smoke; исполнение throttled квотой research-LLM (§20) | smoke: pipeline работает end-to-end (16 живых вызовов, policy/goal/claims все SUCCESS) |
| C3 | B4h-sound-v2 + NO T1 semantics (T2 off, empty registry) | **44/46** | lower-bound ablation |

Prediction seal (§14): `prediction_seals.json` — SHA256 каждой predictions-CSV + run report + UTC; scoring-скрипт отказывается работать без печати. C0 sealed до открытия gold (дисциплина соблюдена; scoring post-seal).

C3-наблюдения (44 кейса, до seal/scoring финальной версии): PROVED_ERROR достигается на invocation/schema/policy-кейсах (airline__21::t7 багаж; airline__23::t10 схема payment_methods; telecom unavailable-tool кейсы), UNRESOLVED доминирует в lower-bound (ожидаемо). Полные числа — после завершения прогона и seal.

## 8. §15-§16 Per-case audit

`outputs/vnext/competition_valid/case_audit.jsonl` — 46 записей: input SHA256/размеры, tool_environment (каталог со схемами и описаниями, числа вызовов/результатов истории), candidate (вызовы ответа), required_semantics, premises (A-H классификация со спанами), arms-блок (статусы по всем рукам), proof-блок (C2: core_status, сертификат, unknown reasons, missing premises). Gold-блок — только в --with-gold режиме post-seal.

Классификация ошибок C2 по primitive cause (§16) — после завершения C2: категории POLICY_PARSE/GOAL_PARSE/CLAIM_PARSE/TOOL_SPEC_PARSE/TOOL_BINDING/ENTITY_BINDING/ARGUMENT_PROVENANCE/MISSING_TOOL_SEMANTICS/STATE_EVIDENCE/TEMPORAL/EFFECT_SEMANTICS/CERTIFICATE/WORLD_EXPLOSION/PACKAGING/TRANSPORT/GOLD_AMBIGUITY/OTHER.

## 9. §17 T1 oracle-advantage (главная таблица цикла)

См. §5 выше + `t1_oracle_advantage.json`. Главный ответ:

**Доля текущих definitive-вердиктов, зависящих от информации, недоступной во входе олимпиады:**
- C0 (legacy): definitives (mechanical violations) опираются ТОЛЬКО на prompt-факты (availability/schema механика) → **0%**;
- C2/C3 (без manual T1): по построению все definitives опираются только на prompt-доступные предпосылки → **0%** (риск не dependency, а COVERAGE: недоступные семейства остаются UNKNOWN/UNRESOLVED, снижая recall, но не создавая ложных definitive);
- Единственное, что мог бы добавить manual T1 — effect/freshness-семейство (46/46 кейсов имеют инструменты с G-class effect-предпосылками): C1 измерит этот потолок.
- Архитектурно значимо: unavailable-предпосылки в B4h-sound-v2 ПО КОНСТРУКЦИИ не создают ложных вердиктов — они создают UNKNOWN (sound by design); oracle-преимущество = recall-разрыв, не precision-разрыв.

## 10. §18-§19 Реальные семейства кейсов и паттерны

Домены (post-hoc): airline (booking/refunds/компенсации; подтверждение перед мутацией; багажные allowance), banking_knowledge (KB-поиск; 2-of-4 верификация; discoverable tools; эскалация), retail (возврат/обмен XOR; аргументная provenance; идентификация по name+zip), telecom (device-диагностика НЕ в каталоге; contract_end_date исключения; reset-последовательности).

12 публичных паттернов (§19, `pattern_provenability.json`): **11 PROVABLE_FROM_COMPETITION_INPUT** (invocation-level, schema, procedural policy, user-intent/escalation, argument provenance, fabricated completion, call/result mismatch, stale state по датам, policy exceptions, computed allowances, attempted-effect claims), **1 REQUIRES_UNAVAILABLE_PREMISE** (точные committed-effect/freshness state proofs). Отдельный риск CURRENT_REPRESENTATION_GAP: «identical failed retry» паттерн не имеет выделенного шаблона обязательства в frozen фронтендах (ловится policy/goal lowering-ом лишь частично).

## 11. §20-§21 Cold start, network/model realism

- **Холодный запуск обязателен и реализуем**: контентно-адресованный кеш (`{ARM}_proposal_cache.json`) делает прогоны детерминированно воспроизводимыми; каждый прогон с пустым кешем = все proposals живые вызовы. Замер: C3 (44 кейса) = **418 unique proposals**; p50 latency/вызов ≈ 2-15s (glm-4-plus); per-case elapsed p50=13.5s, mean=18.5s, p95=40.9s, max=95.6s.
- **BAI (замороженный провайдер qwen3.8-flash) НЕДОСТУПЕН**: аккаунт `insufficient_user_quota: balance=0` — живые прогоны B4h невозможны на нём в принципе; это независимая от правил олимпиады блокировка research-инфраструктуры.
- **Подмена для диагностики**: локальный OpenAI-compatible прокси → z-ai GLM (glm-4-plus; research-инструмент, НЕ часть submission; внешний API). Квота z-ai: ~30 вызовов/burst, ~200/час устойчиво — этого хватило на C0/C3 и частично C2, но throttling удлиняет цикл.
- **Network realism (§21) вывод**: при консервативном прочтении (сеть заблокирована на формировании метрики) submission с внешними вызовами = NOT COMPETITION READY. Разделение подтверждено эмпирически: «research architecture works» (pipeline живой, кешируемый, верифицируемый) vs «submission can execute it» (нет: без сети формальный движок деградирует до offline- MISS — все фронтенды TRANSPORT_ERROR → UNRESOLVED → label 0; механический слой legacy-Detector при этом продолжает работать, см. C0).
- Вывод по модели для V2 submission: нужен локальный LLM в образе (<40 ГБ) или полностью офлайн-движок; 30-минутный лимит при ~2-15s/вызов и ~9 proposals/кейс в среднем означает необходимость радикального сокращения вызовов (batching/каскад: invocation/schema-механика первой, LLM только для оставшихся).

## 12. §22-§25 Build, Docker, ресурсы, 30-мин gate

- **Build**: wheel собирается (guardian_truth-0.2.0); 103 packaging-relevant теста PASS (cli + e2e_soundness + e2e_competition + e2e); импорт vnext.e2e из wheel — GAP (см. §3), из репо-корня — OK.
- **Docker**: недоступен в песочнице — статический аудит только: python:3.11-slim, non-root, pip install ".[data]", ENTRYPOINT scripts/predict.py; .dockerignore whitelist (см. §3/§15).
- **Ресурсы (§24)**: C3-замеры — 418 unique proposals, ~580K входных символов LLM, ~200K prompt-токенов / ~43K completion-токенов на 44 кейса; peak RSS python-процесса < 1 ГБ; GPU не используется (формальный движок CPU-bound).
- **30-минутный gate (§25)**: при идеализированном холодном прогоне (без rate-limit) C3-подобная нагрузка ≈ 46 × 18.5s ≈ **14.2 мин** — в пределах; НО: (а) это glm-4-plus latency; (б) реальный submission обязан быть offline/локальной моделью, чья latency/throughput неизвестна; (в) при внешнем API с rate-limit ~200/час — 418 proposals ≈ >2 часов = НЕпроходимо; (г) число строк приватного теста неизвестно — не экстраполируем. rows/sec на C3 ≈ 46/840s ≈ 0.055 rows/s живого прогона → 30-мин бюджет ≈ ~98 rows максимум при этой архитектуре и latency.

## 13. §26 Cold-build scan

`scan_hardcoding.py`: 270 production-файлов; **src/guardian_truth + predict*.py = 0 findings**; 76 findings — только в benchmark/research-скриптах (в т.ч. freeze_v4_claim_set.py с case-ids и gold) — все исключены из image whitelist-ом .dockerignore. В образе: predict.py, predict_e2e_competition.py, evaluate_vnext_c_alr_reimpl.py (frozen-зависимость, stdlib-only, 0 findings), src/, pyproject.toml. valid.parquet/outputs/tests/docs/env — исключены.

## 14. §27 Proof status vs competition label (не путать)

- CoreStatus (PROVED_ERROR/PROVED_NO_ERROR/UNRESOLVED/INCONSISTENT) — доказательный статус формального движка; competition label — бинарный продукт-маппинг (COMPETITION mode: ERROR→1, NO_ERROR→0, INCONSISTENT→1, UNRESOLVED→0).
- UNRESOLVED→0 НЕ является «proof of correctness» — это fallback (used_fallback=true в audit); метрика F1 платит за это recall-ом, но звуковая семантика (никаких ложных definitive) сохранена.
- INCONSISTENT→1 — продукт-решение (trusted evidence конфликтует; консервативно помечаем «есть галлюцинация»): в audit всегда виден core_status, чтобы не путать маппинг с доказательством.
- Метрика — НЕ критерий принятия архитектурных решений (§0 цикла): никакой тюнинг под valid.parquet не производился и не будет.

## 15. Вердикты цикла

| Вопрос | Ответ |
|---|---|
| Docker исполняет B4h-sound-v2? | **НЕТ** — legacy Detector (CRITICAL GAP; исправлено протоколом predict_e2e_competition.py, не влито в frozen) |
| B4h-sound-v2 работает на реальном входе без oracle T1? | **ДА как research-архитектура** (smoke C2 end-to-end; C3 44/46); submission-исполнение — НЕТ (сеть/модель/30-мин) |
| Можно ли получить T1 из prompt? | Частично: schema/read/action-verb — да (A/B); freshness/writes/effects/failure/completion — НЕТ (G) |
| Зависят ли definitive от недоступной информации? | C0/C2/C3: **0%** (по построению sound: недоступное → UNKNOWN, не ложный definitive) |
| Публичные паттерны покрываемы? | 11/12 из входа; 1 (точные effect-state proofs) требует недоступных предпосылок |
| Production hardcoding | **0** (src + entrypoints) |
| Готовность к сабмиту | **NOT READY**: (1) packaging gap; (2) внешняя LLM-зависимость; (3) 30-мин лимит при живых вызовах; (4) wheel-import gap. Путь к готовности описан в §11-12. |

Следующие шаги (не в этом цикле): завершить C2/C1 прогоны (квота research-LLM), §16 primitive-cause разбор всех C2 ошибок, отдельный V2-прототип offline-submission (локальная модель или чисто механический каскад + выборочный LLM), Docker-сборка на машине с docker.
