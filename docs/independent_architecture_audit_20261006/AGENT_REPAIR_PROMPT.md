# Guardian — исправление контрактов, причин и устойчивости полного решения

## 0. Задание и самостоятельность

Ты работаешь как инженерная и исследовательская команда над Guardian-of-Truth. **Выполни исправления и измерь их эффект end-to-end.** Нужна переносимая система проверки текущего действия по переданным политикам и свидетельствам, с правильными причинами, хорошим бинарным F1 и воспроизводимой обработкой.

Сохрани полезные реализованные идеи. Самостоятельно меняй архитектуру, схемы, границы модулей, порядок стадий, retrieval и формулировки заданий модели, если измерения показывают необходимость. Для изменения укажи проблему, проверяемую гипотезу и сопоставимый контроль. Не добавляй сложный framework ради архитектурной красоты. Не останавливайся после плана, единичного теста, правильного JSON или возврата одной известной строки.

Работай до согласованного, запускаемого кандидата с тестами, полными прогонами и честным решением о default. Разрешено автономно использовать сохранённые ответы, тестовый сервер и переданные модели. До новых больших HTTP-фаз закончи дешёвые проверки. При недоступности ресурса продолжай независимые локальные задачи; не жди следующего сообщения пользователя.

**Обязательно используй субагентов для независимого анализа кода и логики/методологии.** Раздели implementation, code review и source/gold/causality review. Если платформа не предоставляет subagents, явно укажи это ограничение; self-review не называй независимым review. Проверяй замечания по коду и источникам, не по голосованию агентов.

## 1. Обязательные исходные материалы и история

Сначала прочитай эти файлы целиком и проверь их утверждения по сохранённым трассам:

```text
docs/independent_architecture_audit_20261006/REPORT.md
docs/independent_architecture_audit_20261006/CAUSE_RECONCILIATION.md
docs/independent_architecture_audit_20261006/CAUSE_RECONCILIATION_logic.md
docs/independent_architecture_audit_20261006/agent_code.md
docs/independent_architecture_audit_20261006/agent_logic.md
docs/independent_architecture_audit_20261006/agent_method.md
docs/independent_architecture_audit_20261006/agent_gain_source_check.md
docs/independent_architecture_audit_20261006/cause_followup_receipts.json
docs/independent_architecture_audit_20261006/raw_replay.json
```

На машине пользователя основной checkout аудита:

```text
C:\Users\Igor\Guardian-architecture-audit-20261006
```

Зафиксированные точки:

| Ref / SHA | Значение |
|---|---|
| `research/guardian-integrated-v1-20261005`, `6dfd72ab` | Исходная интеграция; historical default guard |
| `research/guardian-verification-v2-20261006`, `aed76d1f` | Admission v2 и V3; adopted default guard_adm2 |
| `research/guardian-proof-executor-v4-20261006`, `32ede180` | Frozen V4, external outputs и gold-v2 rescore |
| `research/independent-architecture-audit-20261006`, `9f2d5d40` | Независимый аудит и дополнение о причинах |

SHA — проверенные снимки, а не обещание текущего remote HEAD. Проверь `git status`, remote refs, историю новых коммитов и `AGENTS.md`. Сделай отдельную research ветку/worktree от согласованного снимка с доступными audit материалами. Не переключай рабочую ветку другого агента, не меняй production/main и не трогай чужой WIP. Audit checkout sparse: отсутствующий файл сначала ищи в Git tree/другом worktree; при необходимости расширь sparse selection. Не выдавай отсутствующий локально каталог за отсутствующую реализацию.

Прочитай также `docs/integrated_v1`, `docs/verification_v2`, `docs/verification_v4`, их freeze/amendments/runbooks. Исследования последовательны: результаты отдельных фаз нельзя складывать как независимые подтверждения.

## 2. Что известно и что нельзя переобъяснять

- Admission v2 восстановил часть правильных raw ответов без новых запросов. Сохрани это исправление.
- H5e, CL3e, BK3e имеют правильные причины в сохранённых V4. Не объявляй весь DF/Ems неработающим из внешнего AT wrong-cause наблюдения.
- G3e уже восстанавливался Q2/V3, но новый интерфейс V4 снова теряет правильное raw AT обвинение на evidence admission. Ems membership plan дополнительно ошибочен по роли/polarity.
- `ext_ret_022` r3: правильный Ems candidate теряется после двух INVALID_JSON/error verifier replies; финальным становится ложный AT candidate.
- `ext_ret_025` r3: все AT targets admitted, но выбирается только первый. У t3 есть поддержанное ядро missing cancellation reason, которое не проверяется отдельно.
- `ext_air_043` r1: narrow verifier теряет оба явных YES (h51/h53), имеющихся в основном packet. AT ошибся раньше; verifier затем не получает контрсвидетельства.
- Frozen external gold v1 ошибочно приравнял task success к compliance. Gold v2 post-hoc и неполон по acceptable causes; S у `ext_ret_041` противоречит видимым заказам/адресам. Не меняй старый gold.
- «Later-call recall9/9» считает ERROR на строке, а не правильный later target. «Почти всегда» неточно: revised external recall V4 =69.2%/71.2%/73.1%.
- Внешние 21 дополнительные winning причины и все внутренние model candidates — разные множества. Ложный winning reason может скрывать правильный candidate, удалённый обработкой.
- Старый cause judge сравнивает два текста, не видит источники. SAME/PARTIAL/DIFFERENT — соответствие аннотации, не самостоятельная истина обвинения. Integrated считает SAME+PARTIAL; V2/V4 — SAME. Определения метрик нужно унифицировать отдельной фазой.
- Существующий независимый replay:472 строки,903 exact request hashes, одинаковые decisions+accusations. Это воспроизводимость обработки прежних raw replies, не новое качество модели и не полная provider cache-key аутентификация.

IDs выше разрешены **только для анализа и regression fixtures**. Они не должны участвовать в runtime правилах, prompts, retrieval/routing или выборе результата.

## 3. Что здесь означает универсальность

Нужны общие механизмы, действующие по входной политике и свидетельствам, а не таблица ответов для домена. Явно определяй поддержанные форматы, операции и семантические контракты; за пределами них оставляй проверяемую неопределённость.

Запрещено:

- ветвиться по benchmark ID, gold, case suffix, домену или конкретному tool name ради нужного вердикта;
- закладывать требование consent/write/success/closed catalog по названию инструмента;
- внедрять неизменный «один call в ходе» без применимой переданной политики;
- считать любое Yes разрешением любой операции; подтверждение общего намерения — подтверждением всех аргументов;
- повышать structural admission, арифметику, цитату, model consensus или UNKNOWN до полного policy proof;
- ослаблять контроль polarity/identity/exceptions ради возврата TP;
- исправлять scoring/annotation только для улучшения метрик или отбирать удачный повтор;
- считать renamed IDs/новый домен с тем же автором и шаблоном независимым holdout.

Допустимы общие typed operations, грамматика declared input format, schema normalization и predicates, получающие **обоснованную связь с нормой из источника**. По имени инструмента можно адресовать его явную декларацию; смысл read/write/authorization должен следовать из декларации/политики и отдельно проверенного binding. Новая capability должна иметь позитивные, негативные и контрастные проверки через реальный parser.

## 4. Раздели пять контрактов

Названия/реализация свободны; следующие различия обязательны:

1. **Transport/decode/schema:** ответ получен, завершён, корректно разобран, типы и обязательные поля валидны. Каждый новый reply проходит локальную schema/Pydantic validation независимо от provider strict mode. Fenced JSON normalization допустима, если точна и записана. Не додумывай статус в truncated/error JSON.
2. **Source support:** каждая решающая premise адресована и действительно содержится в нужном исходном документе/event/JSON leaf. Это ещё не правильная роль premise.
3. **Semantic binding/applicability:** именно эта норма регулирует именно это действие; правильные actor/entity/field/unit/time, необходимые условия, exceptions, grouping и assertion scope. Модель может предложить связь, но её authority должна быть явной.
4. **Execution:** выбранное обоснованное выражение вычислено корректно; результат HOLDS/VIOLATED/UNRESOLVED относится к этому выражению. Правильная арифметика над чужими числами — не нарушение политики.
5. **Cause adjudication/final:** из поддержанных кандидатов выбран обоснованный binary result с правильной причиной/target или move scope; gaps/technical failures видимы. Проверка истинности причины отделена от её совпадения с gold.

В receipts различай хотя бы `schema_valid`, `source_supported`, `binding_status`, `applicability_status`, `closure_status`, `execution_status`, `verification_status`, `final_owner`. Можно выбрать более компактную эквивалентную схему. Не заполняй независимые неизвестные статусы одной булевой `code_proven`.

## 5. Конкретные слои для исправления

### 5.1 SourceStore, parser, I/O, order

Опорные файлы: `src/guardian_truth/parsing.py`, `types.py`, `source_search/store.py`, `evidence_packer/*`, `integrated/reviewer.py`; research runner/scorers.

- Explicit UTF-8 чтение/запись; LF для byte-frozen text artifacts через атрибуты. Оригинальные Git bytes и source fingerprints проверять без пересоздания старых manifest.
- Хранить оригинальные spans, стабильные code-owned IDs, полный inventory current calls/prose и status receipts. Metadata/mutable views не должны менять backing input незаметно для hash.
- Разделять source document/phase и локальный event ordinal. Проверить, не провоцируют ли h31/event31 и t0/event0 неверный общий порядок; при необходимости дать явное history-before-current отношение/global order. Эффект такого представления измерить, не объявлять заранее причиной всех ошибок.
- Валидировать payload types, nullable/required, duplicate keys, arrays и repeated occurrences. Решение по ambiguous framing — явный gap, не выдуманная роль.
- Структурный parser поддерживает объявленные формы входа. Новые формы подключать адаптерами к общему inventory, сохраняя original source и потери преобразования. Не пытайся regex решить произвольную NL применимость.

### 5.2 Точное evidence admission без семантического ослабления

Опорные файлы: `verification/common.py`, `proof.py`, `admission.py`, `alltarget.py`, `ems.py`, `verifier.py`.

- Q2 fuzzy matching с удалённым NOT не может служить certificate. Presentation-only normalization не меняет смысл; поиск похожего текста может искать candidate source, но decisive premise проверяется точно.
- Перейти на стабильные addressed leaves: document/source/event + JSON pointer/occurrence либо exact text span. Модель выбирает из выданных кодом адресов; код возвращает typed значение.
- JSON subset нельзя принимать поиском независимых scalars по всему тексту. Поля должны принадлежать одному нужному объекту; tuple associations, array membership/order и вложенность сохраняются. Не склеивать customer A, field B и exception C в один факт.
- Переформатированный JSON object с пропущенными нерелевантными полями может быть поддержан через точные addressed leaves, сохранив одинакового parent. Не требовать буквального совпадения всего сериализованного объекта, если контракт на leaves доказан.
- Для negative membership/absence адресовать полное применимое множество и его closure; отсутствие в retrieved subset не доказывает отсутствие во всём источнике.
- Admission v2 actor normalization сохранить, при смене схемы дать versioned migration. Источник authoritative по actor; нормализация не превращает assistant assertion в user/tool evidence.

### 5.3 Proof executor, grouping, applicability

Опорные файлы: `verification/proof.py`, `ems.py`, `df.py`, `df4.py`, `derived.py`, `calc.py`, `v3.py`, `v4.py`.

- Исправить eager evaluation ADD/SUB/MUL вместе с DIV; zero и division error — отдельные тесты.
- Сохранить секунды, offsets, timezone и precision; money/counts — typed Decimal/integer с явным rounding/tolerance. Business-day calendar и yearless date assumptions должны быть доступны и указаны; неизвестный calendar не угадывать.
- Дедуплицировать aggregation по атомарному fact/event/JSON path, а не по quote string/value. Два разных equal-value transfers — два события; две цитаты одного amount — один leaf.
- Привязывать operands к regulated target, entity, field, unit, operation и as-of state; учитывать receipt success и supersession. LATEST из model-selected неполного списка не доказывает реальное latest.
- Proof plan должен однозначно выражать compliance predicate или violation predicate; orientation едина и проверяема. Для G3e нужен current requested value и полное certified set, правильный MEMBER_OF compliance contract. Не заставлять отсутствующее boxing быть значением чужой цитаты.
- Applicability, guards и exceptions проверять отдельно от expression. Model SATISFIED vs code VIOLATED — binding disagreement с диагностикой, а не молчаливый NO_ERROR.
- Mechanical bypass допустим только при полном source/binding/applicability certificate. Arithmetic-only candidate не должен обходить семантическое REFUTED. Само REFUTED остаётся модельной оценкой, не автоматической истиной; конфликт разрешать явно.

### 5.4 DF и ownership утверждения

- Сохранить operation-specific code extraction и вычисления, давшие правильные DF результаты H5e/CL3e/TL3e; правильное Ems aggregation в BK3e сохранять и проверять отдельно.
- Удалить global accidental copy suppression: совпадение30 с age другого пользователя не снимает проверку invoice total30. NOT_DERIVED требует связи копирования по entity/field/unit/time/meaning либо остаётся hypothesis.
- Различать собственное утверждение ассистента, цитату, отвергнутое утверждение, пример и условный расчёт. `I reject the incorrect claim2+2=5` не превращать в mechanical violation.
- Typed roles/claimed value из source, не из заранее вычисленного моделью ответа. Проверить даты, counts, range semantics, inclusive/exclusive counting, literal constants в выражениях.
- Не скрывать ограничения first10 claims/другие slices. Сохранять coverage и unchecked items; performance cap — явный контракт.

### 5.5 Confirmation и closure

Опорные файлы: `verification/confirm.py`, `v3.py`, `integrated/declarations.py`, policy adapters.

- Состояние active proposal → scoped user confirmation → revisions/revocation → execution. Нейтральное Thank you не сбрасывает подтверждение.
- Exact canonical identifiers; BK-1 != BK-10. Names/aliases связывать отдельными evidence-backed отношениями. Аргументы multi-item действия — tuples, а не независимые наборы разрешённых значений.
- Yes с вопросом, условием, новым значением, частичным согласием или отказом не считать универсальным разрешением. Существующее подтверждение нескольких явно перечисленных действий может покрывать batch; не требовать новое Yes на каждое без policy основания.
- Смысл confirmation requirement получать из применимой нормы, с polarity/conditions/exceptions. `does not require confirmation` не превращать в доказанную обязательность.
- Catalog closure нельзя доказывать совместным наличием слов complete/tools. «Complete only for reads; other writes allowed» не запрещает остальные writes. Без подтверждённой scope/closure — gap.

### 5.6 Candidate pool и общий итог

Опорные файлы: `alltarget.py`, `ems.py`, `df4.py`, `confirm.py`, `v4.py` и общий pipeline.

- Каждый checker возвращает коллекцию candidates и requirement/target coverage. Сохранять все raw assessments, причины admission/rejection и source references.
- Проверять allowed IDs, уникальность и соответствие возвращённых obligations/bindings исходным requirements/claims/targets. Валидный JSON с неполным массивом не означает complete coverage; пропуски явно UNCHECKED. Неполная проверка других действий не должна отменять отдельно обоснованное нарушение с полным локальным certificate, но не позволяет сертифицировать NO_ERROR по всему ходу.
- Не терять последующий правильный candidate, если первый REFUTED/INVALID_JSON/UNRESOLVED. При явном budget cap оставшиеся — UNCHECKED, без предположения об их качестве.
- Отделить logical aggregation (ERROR если есть обоснованное нарушение) от selection объяснения пользователю. Несколько допустимых причин не обязаны иметь одинаковый текст. Неподдержанные обвинения не примешивать к supported причине.
- Допустимы per-action, batch/aggregate и move-level нарушения. Их target scope не смешивать; t0 не становится «пойманным t3» из row-level ERROR.
- Если нужно сохранить A ERROR для historical baseline, сделай отдельный режим/arm. OR сохраняет исходные FP и причины; no TP lost не доказательство правильности всех модулей. Изменение политики доверия A измерять отдельным контролем.
- Явно разделить нарушение обязательного процесса, неизвестное состояние мира и недостаток свидетельств. При доказанно полном журнале отсутствие обязательной успешной проверки **до** действия для **той же** сущности может быть процедурным нарушением; при неполном input/search это не доказанная absence. Проверка другой сущности не выполняет обязательное требование. Для UNKNOWN/technical null зафиксировать binary projection до оценки и считать его FN последствия.

### 5.7 Verifier и source completeness

- Текущий cited sources + recent4 теряет нужное контрсвидетельство. Для проверки ищи также опровергающие facts, applicable proposal/confirmation, exceptions, latest state, failed receipts и entity chain.
- Используй весь original index для адресного поиска; отдавай bounded self-contained witness bundle. Число последних events не заменяет смысловую closure проверку.
- Отсутствие confirmation во входном subset не даёт SUPPORTED absence claim. Различай complete input, complete policy coverage и complete search for this premise.
- Каждую decisive premise проверять отдельно, допускается несколько точных source pieces. Реконструированное предложение/объект без точных associations не доказательство.
- Сериализацию verifier исправлять универсально: компактный typed verdict/references, bounded analysis, controlled schema/retry protocol, finish_reason и decoding telemetry. Если меняешь decision-first/last, schema или task, это новая версия wire/arm. Truncated/error reply без полного valid contract — technical failure, не inferred SUPPORTED.
- При technical failure сохранять исходный correct candidate и статус NOT_VERIFIED для возможного bounded повторного шага; не подменять его неподдержанным обвинением. Выбор другой independently verified причины допустим и трассируется.

### 5.8 Проверка причины и gold

Сделай общий cause validation contract с тремя отдельными задачами:

1. **Истинность accusation по source:** action/target/move, применимая норма, обязательные premises, exceptions, порядок и evidence. Judge должен видеть source bundle и отмеченные coverage gaps, не только reason+gold text.
2. **Соответствие acceptable gold causes:** может быть несколько причин; поддержанная новая причина, которой нет в gold, — отдельная категория с adjudication. DIFFERENT не равно FALSE.
3. **Binary task:** label0/1 под исходным явным контрактом. Cause quality и целевой action localization считаются дополнительно, не меняют benchmark labels молча.

Раздели `supported_correct_core`, `supported_core_with_unsupported_extra`, `unsupported`, `unresolved`, `technical_unjudged`, `alternative_supported_cause`, `gold_conflict`. Exact wording не обязательна; correctness core и лишние утверждения оцениваются отдельно. Не считай GUARD автоматически cause-correct только потому, что строка положительна: проверь premise/rule/target.

Для нового gold: source-based annotation до model predictions, acceptable causes и move/target scope, explicit completeness assumptions, независимая adjudication спорных случаев. Одно семейство модели, согласие двух model judges или совпадение с их собственным gold не является независимой валидацией. Disagreement не выбрасывать из denominator; технические judge failures отражать отдельно и в sensitivity bounds.

Старые ext_tau2 v1/v2, valid46 и LB1/2/3 — diagnostic/development. Новый gold audit на прежних входах сохранить отдельной версией с before/after и основаниями; не выдавать эту версию за blind holdout. Для окончательного test нужны новые непроверенные источники/задачи с независимой разметкой.

## 6. Устойчивость: что исправлять и измерять

Нельзя обещать битово одинаковые LLM ответы при temperature0. **Детерминированная обработка одного и того же raw должна быть одинаковой.** Model variability, serialization failure, source selection drift и gold/judge disagreement должны измеряться раздельно.

Обязательные проверки:

- fixed raw replay: exact input/config/version/request hash → одинаковые parsed claims, admitted facts, candidates, statuses, итог и reason ownership;
- стабильный порядок множества sources/targets/candidates, deterministic IDs/serialization; разные hash seeds, независимые процессы, fresh install и resume;
- порядок нерелевантных полей/форматирование JSON не меняет semantic associations; порядок событий сохраняется, нельзя сортировкой переписать chronology;
- Windows/Linux: UTF-8, LF hashes, timezone/locale, Decimal/calendar contracts;
- cache keyed по provider/endpoint/actual model/request/attempt/adapter version; конфликтующие successful replies одного key не замалчивать;
- validated retries только по объявленному протоколу, полный expected ID set, no duplicate successful result selection, единый durable budget по процессам;
- >=3 frozen inference repetitions для baseline и candidate на одном полном наборе, одинаковые бюджеты/inputs/settings внутри сравнения; не выбирать лучший повтор;
- per-case binary flips, cause-core flips, target flips, variance F1/TP/FP/FN, unknown/technical failure rates. Несколько разных supported причин одной строки — не обязательно instability;
- повторный judge variance отдельно от reviewer variance. Новый ensemble/vote/calibration — отдельная измеряемая гипотеза, не способ скрыть неустойчивый одиночный arm.

Снижение колебаний не должно достигаться переводом всех трудных случаев в UNKNOWN→0. Измеряй появившиеся FN, selective coverage и false accusations. Выбирай устойчивость вместе с качеством и cost, а не саму по себе.

## 7. Порядок работы и полные прогоны

### P0 — зафиксировать baseline и протокол

До изменений runtime запиши branch/HEAD, environment и fingerprints источников/caches/gold. Проверь существующие failing tests: известный Windows LF/CRLF freeze failure не объявлять semantic tampering. Отдельно запусти замороженный independent replay и сохрани новый receipt. Исходные docs/gold/outputs не перезаписывать.

Формы источников и runner paths:

```text
valid.parquet                                      #46 исходных строк,23/23
outputs/verification_v2/lockbox/{long,short}/        #LB1:57; short/long те же cases
outputs/verification_v2/lockbox2/long/               #LB2:47
outputs/verification_v2/lockbox3/long/               #LB3:56, две V3/V4 reps
outputs/verification_v2/runs/<set>/rep*.jsonl
outputs/verification_v2/judge/verdicts.jsonl
outputs/verification_v2/cache/                      #raw provider caches, наличие проверить
outputs/verification_v4/external/{tau2,tau2v2,tau2v2_strict}/
outputs/verification_v4/reports/
outputs/integrated_v1/phase_valid46/                 #если отсутствует, искать в Git/server
scripts/independent_architecture_replay.py
docs/independent_architecture_audit_20261006/*probes.py
```

На Windows исходный replay запускается с `PYTHONUTF8=1`; production repair обязан убрать необходимость такого обхода для собственного I/O. Используй **новый** output path:

```powershell
$env:PYTHONUTF8='1'
python scripts/independent_architecture_replay.py --output docs\universal_repair\phase0_raw_replay.json
```

Сначала создай `docs/universal_repair` либо выбери существующий parent; скрипт также умеет создавать parent и отказывается перезаписывать файл. Изменённый runtime может перестать иметь exact old request hits — это ожидаемая новая версия, не повод снять assertions. Сохрани baseline replay в отдельном worktree/commit, а amended scorer/runner направь в **новую фазу**, не в historical report directories.

Не запускай старые `score report`, `rescore_v2 report`, builders или runners поверх frozen outputs. Offline flag транспорта сам по себе не запрещает runner писать файлы. Read-only replay требует и network tripwire, и контроля output paths.

### P1 — чистые фиксы и общие контракты

Небольшими reviewable коммитами: I/O/вычисления → exact leaves/grouping → proof authority/binding → candidate pool → verifier witnesses/serialization → consent/closure/assertion scope → unified cause/scoring. Порядок можно менять по зависимости и доказанной выгоде; объясни решение.

Добавляй meaningful regression/property/contrast tests на воспроизведённые дефекты, а не тесты, зеркалящие реализацию. Проверяй через production parser и public entry point. Каждому известному кейсу сопоставь новые контрасты: другое имя/ID/объект, другой exception, равные amounts из разных событий, failed receipt, later update, quoted/negated claim, revision consent, lawful read/write. Следи за zero/null/empty list, timezone, token boundary и multiple candidates.

### P2 — полный offline replay и раздельные ablations

**Обязателен полный valid46**, без выбора удачных6/24 строк. Пересчитай все имеющиеся сопоставимые repetitions, а также LB1/2/3 и внешний архив отдельно по frozen gold versions. Проверяй ровно ожидаемые IDs и labels. Полный subset-контроль нужен для каждого заявленного общего исправления.

Разделяй:

- unchanged-wire re-admission прежних raw replies;
- changed admission/execution с прежними proposals;
- oracle relations/leaves/causes, предоставленные диагностикой;
- новые automatic grounding/reviewer/verifier outputs;
- новые cause annotations/judge policy.

Changed verifier input требует нового ответа; прежний SUPPORTED нельзя переносить на другой witness bundle. Проверка нового t3 требует нового verifier либо честного NOT_EXECUTED. Не генерируй hypothetical prediction по gold и не записывай oracle gain как автоматический.

Сделай минимум controls: A guard_adm2 unchanged; fixes-only; candidate-pool-only; witness-closure-only; focused DF/binding; combined candidate. Сократи матрицу, если аблации независимы и доказательства достаточны, но сохраняй измерение вклада каждого существенного изменения. Не объединяй сразу всё так, чтобы источник прироста нельзя было установить.

### P3 — oracle ceiling на реальных misses

Для полного диагностического набора misses дай правильные source-bound relations/операнды при неизменном executor и final contracts. Измерь какие FN исправимы и где причина потери: retrieval, claim extraction, applicability, role/entity/time binding, execution, source admission, verifier, candidate selection, binary projection.

Затем автоматизируй самые полезные отношения и сравни с oracle ceiling на тех же строках. Эти диагностические IDs не подаются в runtime. Для сниженного числа новых HTTP сначала используй existing replies, но не подменяй ими отсутствующие ответы новой задачи.

### P4 — frozen live comparison и новый holdout

Только после offline checks заморозь candidate code, schemas/prompts/budgets, expected IDs, model versions и acceptance criteria. Проведи **Mistral и Gemma: baseline46 и candidate46**, сопоставимые полные repetitions. Минимум3 для анализа устойчивости; partial/blocked family — отдельный NOT_EXECUTED вывод, не полноценное сравнение.

Если baseline wire не менялся, compatible cached replies допустимы при exact cache identity; missing calls выполнить. Контекст измерить actual tokenizer/provider limit и reserved completion. Не обрезать длинный ввод молча. Если весь input не помещается, explicit bounded evidence view с gaps либо model-family-appropriate context profile, frozen до результатов.

Новый holdout должен реально упражнять DF/calendar/aggregation/identity/consent и отрицательные контрасты, иметь явные procedural полноту и policy scope, минимум25 positives и достаточные negatives/eligible examples для каждого заявленного механизма. Иначе verdict соответствующего механизма INSUFFICIENT EVIDENCE. Split по underlying tasks/trajectories/templates, не по отдельным сообщениям того же task. Аннотация policy compliance по видимому input, а не reward/task oracle.

На новом holdout >=3 primary reps, независимое source/gold review, второй model family по доступности. Если доступна только одна семья, не объявляй межмодельный перенос. Acceptance thresholds для F1/FP/cause/target/stability/cost выбери и обоснуй **до** inference; после просмотра не снижать. Внесённый позже fix — отдельный post-hoc arm с новым holdout для окончательного вывода.

## 8. Метрики и доказательства

Для каждого set/model/rep/arm публикуй:

- rows/expected IDs, TP/FP/FN/TN, precision/recall/binary F1;
- paired gains/losses по rows, FP added/removed; доверительные интервалы/разброс с учётом task clusters, без псевдонезависимых short/long и repetitions;
- supported cause core, unsupported additions, alternative true causes, unresolved/gold conflict, unjudged;
- target-correct vs row-correct recall, aggregate/move-level scope отдельно;
- raw detected → source admitted → binding valid → computed → verified → final, с причинами потерь на каждой стадии;
- candidate survival/false candidate rejection, coverage/unchecked targets, source-closure status;
- UNKNOWN, missing evidence, failed transport, INVALID_JSON/schema rejection и их вклад в FN;
- per-case flips и диапазон качества по repetitions, same-raw determinism;
- фактические calls/input+output tokens/latency/usage missing, отдельно deployed arm и controls/shadow/judge. Одинаковые calls не означают одинаковый token budget.

Для ключевых регрессий запиши исходный source, raw reply, exact source addresses, schema/version/request hash, processing decisions и final cause. Не выводи credentials. Per-case объяснение исправления должно быть причинным: какое общее правило изменилось и какая цепочка восстановилась.

Архивные references: OR Guardian+Granite valid46 F1.8889 — другой стек; R0 F1.9714 — sealed160, другой набор. Это контекст, не headline baseline для непарного сравнения. Current V4 valid46 r1 A=15TP/3FP F1.732; V4 тот же результат. External v2 F1.809/.822/.835 — post-hoc. Oracle format overlay .848/.872/.872 — ограниченная диагностическая проверка, не universal compiler.

## 9. Сервер, модели, credentials и бюджет

Ресурсы переданы пользователем; наличие пути не обещает текущую доступность. Исторический SSH alias:

```sshconfig
Host new
    HostName 178.223.71.173
    Port 16389
    User root
    IdentityFile ~/.ssh/vast_me
    IdentitiesOnly yes
```

Проверь существующий `ssh -G new`; один bounded BatchMode/ConnectTimeout10 preflight. Не переписывай key/config/known_hosts и не отключай host-key check. При отказе/timeout переходи к локальным задачам. Исторические серверные пути проверить:

```text
/workspace/guardian/repos/
/workspace/guardian/venv/
/workspace/guardian/models/
/workspace/guardian/secrets/mistral.env
/workspace/guardian/secrets/api_keys.env
/workspace/guardian/results/ta_llm_cache/
/workspace/guardian/results/modular_steps_20261002/
```

| Provider | Base URL | Model / credential |
|---|---|---|
| Mistral | `https://api.mistral.ai/v1` | Historical `ministral-14b-2512`; `MISTRAL_API_KEY` |
| Ollama Cloud | `https://ollama.com/v1` | `gemma4:31b`; `OLLAMA_API_KEY` |
| AI Horde | `https://oai.aihorde.net/v1` | `google/gemma-4-31b`; public anonymous key `0000000000` |
| Ukisai, optional | `https://ukisai.com/api/swift/v1` | `swift`, placeholder `none`; actual family проверить |
| Vireonix, optional | `https://vireonix.ai/v1` | `auto`, placeholder `unused`; unknown actual identity не independent-family evidence |

Gemma через Ollama/AI Horde — одно семейство, разные serving profiles. `latest` aliases freeze по actual identity. Optional user candidates: gpt-oss20b/120b, nemotron3nano30b/super/ultra; не заменять ими Gemma молча. Heretic/RP quantized model — отдельная гипотеза, не тот же baseline.

Credentials находятся в env/server secrets и PRIVATE handoff. Готовая private версия этого задания:

```text
C:\Users\Igor\Documents\PROMPT_GUARDIAN_UNIVERSAL_REPAIR_2026-10-06_PRIVATE.md
```

Резервный credential source: `C:\Users\Igor\Documents\PROMPT_GUARDIAN_FULL_INTEGRATION_PRIVATE_2026-10-05.md`, раздел `PRIVATE CREDENTIALS PROVIDED BY USER`. Его прежний план — история, текущая задача задаётся этим новым промптом. Локальные пути не существуют автоматически на сервере. Не печатать/коммитить literal API/private keys. Два альтернативных SSH blocks не означают необходимость двух ключей. Unspecified token не привязывать к провайдеру по догадке.

Один ограниченный discovery/smoke на provider profile, явные timeout и max_retries=0 для preflight. Quota402/429/auth unavailable — остановить этот profile и записать BLOCKED/NOT_EXECUTED; не делать сотни попыток. Одиночный transient retry допускается только в preregistered bounded protocol с ledger; повторяющийся лимит — не сигнал ждать постоянным polling.

До первой live фазы вычисли бюджет полного matrix, mechanism/judge calls и retries, установи durable cumulative attempts/token/cost caps по всем процессам. Пилотный cap18/36 calls не подходит для baseline46+candidate46, тем более repetitions. Предусмотри время/контекст для полных наборов, не скрывай технические exclusions. Budget amendments фиксировать до дополнительных calls с причиной; никаких silent unlimited retries. Пока calls идут, делай независимые задачи, не постоянные status checks. Уже скачанные модели/cache использовать раньше новых downloads; дополнительные установки — isolated pinned environment после disk/VRAM/license/context checks.

## 10. Review, публикация и критерий завершения

Сохраняй отдельные неизменяемые phases и reviewable commits. Пример структуры (можно уточнить):

```text
docs/universal_repair/
  REPOSITORY_AUDIT.md
  CONTRACTS_AND_ARCHITECTURE.md
  FIX_MATRIX.md
  PROTOCOL.md
  RESULTS.md
  STABILITY.md
  CAUSE_AND_GOLD_AUDIT.md
  INDEPENDENT_REVIEW.md
  RUNBOOK.md
  FINAL_DECISION.md
outputs/universal_repair/<frozen-phase>/
  manifest, inputs refs, raw receipts, attempts ledger,
  per-stage traces, predictions, score and cause reports
```

Code reviewer проверяет implementation/exceptions/boundaries/cache/retry and candidate aggregation. Logic reviewer отдельно проверяет источники/применимость/gold/causality/обобщение и соблюдение freeze. Оба должны иметь доступ к raw источникам и приводить воспроизводимые findings. Unit pass и мнение reviewer не заменяют paired полный эксперимент.

Commit+push после protocol freeze, каждого законченного general fix, wiring, полного replay/model phase и review. Добавляй конкретные проверенные paths, не `git add .`. Не публикуй секреты, venv, temporary locks или огромные unrelated archives. После push проверь clean status, локальный SHA и remote read-back `git ls-remote origin refs/heads/<branch>`. При сетевой ошибке сохрани локальный commit и продолжай доступную работу; опубликованным результат называй после подтверждения.

Работа считается законченной, когда:

1. Реальный public entry point соединяет source, facts, bindings, focused checkers, candidate pool, verification и итог с согласованными versioned contracts.
2. Все перечисленные defects воспроизведены и исправлены общим механизмом либо имеют измеренное честное ограничение; полезные прежние findings проверены на регрессии.
3. Same-raw обработка детерминирована; полные valid46 и доступные архивы replayable, исключения/отказы не спрятаны.
4. Автоматическое end-to-end качество, причины, target scope, variance и cost сравниваются на полном matched эксперименте; oracle и post-hoc результаты отделены.
5. Новая blind проверка проведена по наличию ресурсов либо явно указано, какие внешние действия NOT_EXECUTED и почему. Нельзя назвать такую фазу complete validation или universal deployment.
6. Полезный measured candidate выбран, неподдержанные модули shadow/off; при отсутствии сопоставимого улучшения лучшие repairs сохранены отдельно, default не меняется ради красивого результата.
7. Код/артефакты/отчёт опубликованы в research ветке, независимый review учтён, fresh install/runbook работает. Production merge — отдельный reviewable шаг.

В финальном ответе дай реальные before/after TP/FP/FN/F1, correct causes и сохранённые регрессии, range по repeats, что стало переносимым, какие assumptions остаются, что не выполнено, где лежат код/receipts и pushed SHA. **Не объявляй победу по одному oracle случаю, валидному JSON или исчезновению FP за счёт UNKNOWN/FN.**

Продолжай самостоятельно, включая полные необходимые проверки. Цель — полезный устойчивый Guardian с объяснимыми причинами и честным охватом.
