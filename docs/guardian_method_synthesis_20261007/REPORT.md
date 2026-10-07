# Guardian: что соединять и какие пробелы закрывать

Дата: 2026-10-07. Отдельная ветка анализа `research/guardian-method-synthesis-20261007`.
Исследованный снимок первого круга: **a300bb0f20d17bd23c556d9f70aca9a65029687a**.
Ноль новых inference/API-вызовов. Работающий Lynx не перенастраивался.
Runtime, production/default, исходные labels и прежние результаты не менялись.

**Основной вывод:** имеет смысл соединить независимый разбор требований,
полный inventory текущих действий/claims и source-bound проверку кандидатов.
Сейчас между ними нет достаточно согласованного контракта. Добавление графа
или solver само по себе этот пробел не закрывает. Самые дешёвые следующие
эксперименты — доставка blind analysis, проверка claims в аргументах вызовов
и раздельное связывание policy/action/evidence. Объединение моделей имеет
измеренную комплементарность, но также измеренный риск FP.

## 1. Новый независимый offline пересчёт

[Скрипт](../../experiments/guardian_local_a100/method_synthesis.py) читает
Git blobs напрямую: имена сохранённых model directories содержат `:`, поэтому
их нельзя просто checkout на Windows. Проверяет исходные 46 уникальных IDs,
23/23 labels, дубликаты/чужие IDs. Артефакты имеют SHA256 в
[полном отчёте](offline_analysis_final.json). Для первичного технического
статуса используется существующий `score_local.classify_row`; это не новый
семантический judge. Непринятый evidence binding внутри parseable ответа
может остаться binary 0 — такой отказ выделен отдельно от transport/decode.

| Модель / рукав valid46 | TP / FP / FN / TN | Нет пригодного решения | F1 по пригодным решениям |
|---|---|---|---|
| Qwen A | 9 / 0 / 13 / 23 | 1 positive | .581 на 45 |
| Qwen B2 | 13 / 1 / 10 / 22 | 0 | .703 на 46 |
| GPT-OSS A | 9 / 2 / 14 / 21 | 0 | .529 на 46 |
| GPT-OSS B2 | 13 / 4 / 10 / 19 | 0 | .650 на 46 |
| Compass pointwise B2 | 6 / 0 / 17 / 23 | 0 | .414 на 46 |
| Ministral A, saved | 12 / 9 / 10 / 14 | 1 positive | .558 на 45 |
| Ministral B2, saved | 14 / 9 / 9 / 13 | 1 negative | .609 на 45 |
| Distill A | 6 / 0 / 8 / 18 | 14: 9 positive + 5 negative | .600 на 32 |
| Distill B2, остановленный | 4 / 0 / 6 / 14 | 12 technical + 10 missing | .571 на 24 |

**Поправка к исторической сводке:** Ministral AM `airline__44::t22` и B2
`banking_knowledge__task_033::t2` имеют INVALID_JSON / finish_reason=length.
Их записанные binary значения не являются пригодными решениями. Исторический
A .578 включал первое значение; B2 .609 численно совпадает, поскольку второе
было TN и TN не входит в F1. Но coverage было 45, а не 46. Старые отчёты
сохранены. Это пересчёт пригодности, а не изменение benchmark labels.

Для Distill условное .600 нельзя ставить рядом с полным .703 как сопоставимый
результат: все 14 AM отказов имеют length/INVALID_JSON. Диапазон F1 на полном
valid46 при всех возможных присвоениях этим отсутствующим решениям —
**.353–.789**. Это sensitivity bounds, а не предсказания. У Qwen A диапазон
**.563–.606**. Технические отказы не записываются как NO_ERROR.

A и M на этих valid46 имеют одинаковые бинарные решения. Это не доказывает
ненужность контрактных исправлений: строгие F/P в текущем профиле не получают
механическую authority, а набор может не упражнять исправленную границу.

### Blind-разбор: создано не значит доставлено

| Модель B2 | Доставлено / 46 | Превышен byte cap при добавлении | Не разобран prepass |
|---|---:|---:|---:|
| Qwen | 30 | 14 | 2 |
| GPT-OSS | 31 | 8 | 7 |
| Compass | 36 | 10 | 0 |
| Ministral | 26 | 20 | 0 |

Все недоставленные reviewer requests в этих четырёх моделях имеют **тот же
cache key**, что соответствующий AM request: 16/15/10/20 соответственно.
Значит это действительно fallback к прежнему review, а не просто отсутствие
флага в логе. Не все недоставки вызваны контекстом: у Qwen 14 budget + 2 decode,
у GPT-OSS 8 budget + 7 decode. Эти причины нельзя смешивать.

Проверенный путь:
`guardian_semantic.variants.Hook.call()` →
`guardian_addons.variants2.Hook2.inject()` → добавление одновременно
`blind_analysis` **и полного `blind_analysis_sources`** к уже упакованному
review packet → измерение serialized UTF-8 body → fallback при >60 000 bytes.
Здесь дублируются пересекающиеся источники в двух namespaces. Их устранение
требует code-owned mapping исходных spans, а не удаления префикса `blind:`:
одинаковые локальные номера двух views могут обозначать разные фрагменты.

У Qwen 5 из 10 FN находятся среди недоставленных prepasses; другие 5 — среди
доставленных. У GPT-OSS — 2 и 8. Это **не** oracle ceiling и не доказательство,
что исправление доставки вернёт пять TP: группы различаются содержанием,
сложностью и длиной. Нужен новый парный ответ на изменённый wire.

На 45 общих пригодных Qwen A/B2 строках blind arm добавляет **3 TP и 1 FP**,
не теряя прежних ERROR. Ещё одна положительная строка (`airline__9::t6`)
получила пригодное B2 решение вместо AM truncation. Поэтому общее 9→13 TP
нельзя целиком описывать как четыре исправленных смысловых FN.

## 2. Где реально остаются ошибки

У Qwen B2 все **10 FN** имеют пустой `components` и пустой candidate pool.
Raw reviewer decisions: **9 NO_ERROR + 1 UNKNOWN**. Один NO_ERROR дополнительно
отклонён admission по evidence reference/actor. Здесь нет сохранённого raw
ERROR, которое достаточно «достать из парсера». У GPT-OSS B2 структура иная:
**7 FN без компонентов, 2 с компонентами без pool, 1 с pool без итогового ERROR**;
raw primary у четырёх из десяти FN был ERROR, отвергнутый admission.

### Состав вычисления — отдельная задача от арифметики

`airline__7::t6`: текущий tool call передаёт выражение
`402 + 306 + 308 + 16005`. Источник задаёт дату 2024-05-15; часть бронирований
содержит уже прошедшие flight dates. Требуется сумма предстоящих рейсов.
Модель подтверждает наличие сумм, но не проверяет допустимость каждого
слагаемого. Triggers: T_multi=false, T_calc=[], T_quant=false.

В коде `verification/df.py:trigger()` пропускает все targets, кроме `kind=text`;
`repair/df5.py:run()` тоже извлекает claims только из таких targets. Ems quant
trigger дополнительно требует количественную норму/подходящий аргумент.
Поэтому одиночное выражение внутри tool argument оказывается вне покрытия.
Простое вычисление 17021 арифметически правильно и **не исправляет ошибку**.
Нужны source-bound relation: requested set → eligibility of each item →
amount per eligible item → aggregation → submitted expression.

Расширять это следует через общие claims для material argument values,
strings с утверждениями, selectors/filters и identifiers. Не через специальный
`if tool == calculate` или поиск конкретного имени поля из этого примера.
Семантика поля берётся из декларации и контекста задачи; не каждый string
является утверждением, не каждое число — заявленная сумма.

### Правильная строка и raw ERROR не гарантируют правильную причину

Четыре GPT-OSS B2 FN с raw ERROR:

| Случай | Что видно в raw | Что нужно исправлять |
|---|---|---|
| banking task068 | Обнаружен placeholder account_id текущего t1, но фактом действия назван policy source q1 | Разделить policy citation и target/argument address; затем проверить отсутствие реального binding. Не принимать fabricated premise по существованию q1 |
| retail48 | Повторный lookup обвинён по предполагаемому требованию немедленного transfer после authentication failure; evidence тоже указывает q0 | Сначала source-based applicability/cause review. Совпадение строки с gold не делает такое объяснение правильным |
| telecom MMS/data_usage | В raw обвинён прошлый `can_send_mms`, хотя current target — `check_network_status` | Current-action localization и performer. Замена actor не исправит подмену действия |
| telecom MMS/APN | Есть ядро multiple calls / unavailable actions; policy/catalog источники размечены actor=assistant | Typed policy/catalog references и проверка каждой premise, отдельное согласование допустимой причины и target/move scope |

IDs служат только диагностикой. **Нельзя объявлять эти четыре случая четырьмя
достижимыми автоматическими TP от общего ослабления admission.** Часть raw
имеет неправильную причину/target. Модельное semantic repair — новая задача
и новый запрос, а не косметическая нормализация уже вычисленного ответа.

### Применимость, performer и закрытость

Единственный Qwen B2 FP (`banking task057`) требует найти KB-процедуру открытия
счёта **до** запроса данных для идентификации. В текущем действии агент пока
запрашивает данные и планирует проверить требования после верификации.
Это тот же класс риска, что прежнее превращение refund-only условия в запрет
lookup: норма действия переносится на подготовительный шаг. Старое regex
ошибочное enforcement исправлено в contract-safety, но **LLM тоже может
совершить такую семантическую ошибку**. Граф и точная цитата сами её не устранят.

Telecom misses показывают другое: документ может описывать действие клиента
на устройстве, а модель трактует это как доступный агенту API. Требуются
раздельные `mentioned capability`, `declared callable`, `performer`,
`delegated user instruction`, `attempt`, `success receipt`. Пустой поиск
по урезанному catalog не доказывает запрет; закрытость inventory должна иметь
явное основание. Само упоминание имени в policy не создаёт API capability.

## 3. Можно ли объединить модели

По **всем 46 пригодным B2 решениям** Qwen/GPT-OSS:

| Offline операция | TP / FP / FN / TN | F1 |
|---|---|---:|
| Qwen | 13 / 1 / 10 / 22 | .703 |
| GPT-OSS | 13 / 4 / 10 / 19 | .650 |
| OR | 18 / 5 / 5 / 18 | .783 |
| AND | 8 / 0 / 15 / 23 | .516 |

Каждая модель находит пять положительных строк, пропущенных другой. Но их FP
не пересекаются: OR добавляет Qwen пять TP **и четыре FP**. Это постфактум
анализ пересечений знакомого valid46, без нового inference/cause adjudication,
не новый accepted stack. Объединение Qwen+Compass B2 даёт 14/1/9/22, F1 .737:
один дополнительный TP, без нового FP на этом маленьком диагностическом наборе.
Это тоже не валидация Compass как универсального reviewer: его pointwise
профиль слабее на sanity dev, native pairwise роль отдельно не измерена.

Рациональная проверка: сохранять предложения обоих reviewers как кандидаты,
согласовывать каждую причину по источникам, затем агрегировать подтверждённые
причины. Сравнить с простым OR и с равным по затратам вторым вызовом той же
модели. Ни один из этих источников кандидатов не получает право решать через
majority vote, regex или совпадение case ID.

Lynx исследуется в **другой роли** — factual grounding document/question/
answer. Он может проверять поддержку фактической premise или material claim.
PASS не доказывает применимость нормы; FAIL не означает автоматически policy
violation. Для каждой candidate cause отдельно нужны action/policy binding,
exceptions и полнота поиска контрсвидетельств. Прежде чем включать фильтр,
измерить, сколько истинных причин он удаляет, особенно на русском input и
с negative/absence claims. Не использовать только pass/fail текущего ответа
как binary label Guardian.

### Дополнение: завершившийся Lynx, снимок 064b2152

После основной фиксации анализа очередь завершилась и опубликовала результаты.
Native v3: **70/70 current-turn checks, 0 technical rows, 47 PASS / 23 FAIL**;
дополнительно 33 проверки сохранённых Distill accusations. У 10 строк отсутствует
Distill B2, что записано отдельным reviewer gap. На valid46 current turn получает
35 PASS / 11 FAIL; это не Guardian confusion matrix.
[Независимый подсчёт по raw rows](lynx_analysis.json) сохраняет commit, blob hash,
счётчики sets/arms и полноту document view.

Обнаружены два существенных ограничения адаптации:

1. **Все 46 document views valid46 неполны** (`complete_input=false`). FAIL
   может зависеть от отсутствующего источника. Гарантия отсутствия truncation
   уже сформированного request не означает полноту исходной истории в view.
2. Для accusations renderer использует **только original prompt** — тот же
   document, что для проверки current answer. Сам current response в document
   отсутствует. Но обвинение часто утверждает, какое действие/аргумент содержится
   в current response. У судьи нет этого независимого наблюдения, он видит его
   лишь внутри проверяемого обвинения. Такой контракт непригоден как полный
   source-based cause verifier; неподдержанную premise он может и отклонить,
   и повторить из самой accusation.

На valid46 сохранено 12 accusation checks (A7+B2 5), все относятся к строкам
с positive binary gold: 8 FAIL / 4 PASS. Это не доля истинных/ложных причин:
positive row не удостоверяет каждую accusation, часть исходных reviewer paths
технически непригодна, отрицательных gold строк с accusation здесь нет.
По этому опыту нельзя оценить FP rejection или принять фильтр Lynx.

Следующая версия accusation witness должна включать code-addressed current
action/argument как **наблюдение о тексте действия**, policy premises,
supporting и contradicting history, coverage gaps. Историю брать из общего
original index под проверяемые premises; neutral blind view сохранять для
предварительного разбора, не переиспользовать автоматически как verifier bundle.
Это изменение document/wire и новый эксперимент. Текущие raw ответы сохранены,
не переинтерпретированы как результаты исправленного адаптера.

## 4. Что перенести из уже проверенных методов

| Метод | Что действительно узнали | Полезная роль сейчас | Чего не считать доказанным |
|---|---|---|---|
| Neutral blind analysis | На малых авторских контрастах выигрывал у open extra-call; в текущем valid46 B2 меняет ошибки, но часто не доставляется | Независимый разбор требований/сущностей/ограничений до показа current move; несколько допустимых действий, не один invented ideal answer | Полноту извлечения, применимость всех норм и отсутствие рационализации финальным reviewer |
| Source IDs / addressed leaves | Реальные ошибки ролей, цитат, grouping и pairing воспроизводились; исправления нужны | Code-owned original spans, JSON pointers, occurrence IDs; разные policy/action/fact references | Правильную семантику по одному валидному адресу |
| QuoteLLM / точные цитаты | Address probe: inventory 2/31 vs 0/31, UNKNOWN37/37; принятые адреса могли иметь неправильную поддержку | Проверяемое извлечение фрагментов/многих leaves вместо переписывания объектов | Что quote selection доказывает scope, exception или identity; лицензия/decoder требуют отдельной проверки перед переносом кода |
| Claims / all-target | Выявлен структурный пробел одиночных аргументов и вложенных summary; полный список targets полезен, первый candidate может скрыть следующий | Inventory всех material claims/arguments и проверка каждого locally supported violation; явный UNCHECKED | Что список IDs означает полноту норм или правильные причины |
| Graph / memory | Прежний paired 6-case графовый опыт дал одинаковые решения всех arms; экономию представления не измерял. Адресный graph pipeline часто ломался до reasoning | Индекс entity/field/event/time, call-result, proposal-confirmation-revision, asserted/copied/derived, source provenance; retrieval противоположных фактов | Прирост F1 от формы графа, истинность model-generated edges, доказанную closure |
| DF / Ems / typed execution | H5e/CL3e/BK3e/TL3e имели правильные причины, G3e возвращался downstream repairs; общий evaluator поверх своей model formula не дал изменений | Общие операции над обоснованными operands, filter/group/aggregate; вычисления сохранять | Что арифметическая истина выбранной формулы равна policy proof; что текущий executor покрывает call arguments |
| Counterevidence / focused verifier | Сохранённые примеры теряли Yes далеко в истории, правильный candidate терялся при техническом отказе | Self-contained witness+counterwitness bundle из общего original index; technical gaps отдельно | Что cited+recent4 достаточно; что повторяющий модельный judge независим |
| Roundtrip / solver / Clingo | Stable wrong interpretation возможна; верный formal input решался лучше, но adapters/unknown exceptions блокировали вывод | Диагностика потерянных guards/AND/OR; optional executor с тем же IR после binding | Что замена solver улучшает NL grounding; что formal equivalence доказывает исходный смысл |

Источники истории:
[method census](../searh_23/MODULAR_METHOD_CENSUS_2026-10-02.md),
[oracle/scope audit](../searh_23/MODULAR_ORACLE_AND_SCOPE_AUDIT_2026-10-02.md),
[graph/quote review](../searh_23/RESEARCH_METHODS_REVIEW_2026-10-04.md),
[cause reconciliation](../independent_architecture_audit_20261006/CAUSE_RECONCILIATION.md),
[semantic](../guardian_semantic/REPORT.md), [add-ons](../guardian_addons/REPORT.md),
[independent new-branch audit](../new_branches_review_20261007/REPORT.md),
[contract repair](../contract_fix_20261007/REPORT.md).
Числа старых разных наборов не складываются с текущими local model results.

## 5. Компактная архитектура кандидата

```mermaid
flowchart TD
  S[Original sources + parser + complete target inventory] --> I[Addressed facts and optional graph index]
  S --> B[Move-independent requirements and state hypotheses]
  I --> C[Material claims and argument bindings]
  B --> C
  C --> P[Candidate pool per requirement and target]
  I --> W[Witness and counterwitness retrieval]
  P --> W
  W --> V[Source support + applicability + execution]
  V --> F[Supported causes, unresolved gaps, explicit binary projection]
```

Один SourceStore и стабильные original addresses; разные views лишь выбирают
источники, не переопределяют их смысл. Код выдаёт структурные edges: spans,
JSON parent/occurrence, source role, native event order. Entity aliases,
governed action, intent, copy/derived relation, exception applicability —
семантические hypotheses со своими основаниями. Их нельзя объединять
булевым `code_proven` с правильностью арифметики.

Minimal candidate contract: target/argument or assertion address; requirement
address; modality/scope/guards/exceptions; premise addresses; entity/field/unit/
time bindings; execution operator; support/binding/applicability/closure statuses;
counterevidence searched/not-read; verification status; final owner.
Несколько кандидатных причин сохраняются. Дополнительное обвинение не должно
проходить только потому, что бинарный label другой причины уже ERROR.

Граф можно добавить за этим интерфейсом без нового общего ontology/compiler.
Сначала идентичные facts в linear table и graph; сравнивать их retrieval и
покрытие при одинаковом бюджете. Если facts/edges меняются между arms,
приписывать эффект графовой форме нельзя.

## 6. Короткий порядок следующих экспериментов

Это **предложение следующей фазы**, не уже выполненные улучшения. Новых больших
прогонов в рамках анализа не запущено.

| Порядок | Эксперимент | Контроль | Что измерить / условие полезности |
|---|---|---|---|
| 0 | Завершить текущий native Lynx grounding; разобрать disagreement по sources | Его clean/error smoke + существующие reviewer accusations, gaps отдельно | Usable outputs; удалённые истинные причины; factual support отдельно от policy correctness |
| 1 | Общий source-address mapping и доставка компактного blind анализа без повторной полной копии sources | Текущий B2; тот же компактный packet без analysis; open prepass при равном бюджете | 46/46 delivery либо явные gaps, TP/FP/FN, unknown/technical, exact wire bytes + actual tokenizer/reserved completion; исправление доставки не объявлять semantic gain заранее |
| 2 | Material claims в prose **и tool arguments**, несколько eligible-set/identity/scope hypotheses | Та же база + одинаковый extra-call budget обычного review | Сколько реальных FN дают candidate; верна ли причина; lawful literals/opaque strings/quoted text не становятся обвинениями |
| 3 | Typed policy/action/fact refs + bounded repair конкретной ошибки binding | Неизменённая admission; только deterministic source-owned metadata normalization отдельно | True candidates recovered/lost, false source associations rejected, wrong current target не проходит; новый repair response не заменять старым |
| 4 | Oracle source-bound relations на всех реальных остаточных FN, с отдельной adjudication спорных causes | Неизменный executor/final, автоматические bindings | Что исправимо правильным binding, где не хватает downstream operation; oracle не включать в automatic F1 |
| 5 | Graph retrieval vs linear retrieval **тех же facts/edges**; witness+counterwitness | Равные фактические input/output tokens и calls, включая retrieval cost | Entity/latest/consent/exception coverage, причины и F1; graph только если показал добавочную пользу |
| 6 | Candidate merge двух reviewers + source-based adjudication | Лучший одиночный arm, OR и same-family extra-call | Сохранить дополнительные TP без неподдержанных FP; cost и false-cause rate, затем новый holdout |

Не запускать всю матрицу для всех моделей. После Lynx выбрать один основной
reviewer из действительного quality/coverage профиля; для начала Qwen B2 —
кандидат с меньшим FP в имеющемся полном valid46, GPT-OSS — источник другого
набора candidates для ограниченного сравнения. Протокол первого круга неясно
задаёт A-vs-B2 primary ranking; это диагностическое предложение, а не
ретроспективно объявленный preregistered winner.

Сначала offline packet-size и addressed-claim probes, затем один парный полный
valid46 и прежние contrast/dev controls. Изменённый wire требует новых responses.
При положительном эффекте — frozen candidate, полные matched repetitions и
новый task-separated source-adjudicated holdout. Valid46 давно development;
старые tau2 gold/holdout версии имеют описанные post-hoc ограничения.

Нужные контрасты: другое поле с тем же числом; два равных платежа разных events;
past/future на границе времени; failed/stale receipt; lookup vs execution;
user device action vs callable API; exception; explicit retry; новый/generated
ID; цитата/отрицание/условное обещание; несколько candidates, первый ложный.
Контрасты проходят реальный parser и public entry point, без runtime правил по
benchmark ID/tool name. Regex пригоден для кандидатов синтаксических claims,
но не устанавливает нормативную применимость.

## 7. Ограничения и воспроизведение

Новый анализ — один аудитор, без независимого semantic/gold review. Labels
не менялись. Истинность всех новых объединённых обвинений не размечалась.
Оставшиеся общие Qwen/GPT FN включают gold-sensitive случаи: banking task018
требует не предоставленной Latin transliteration при запрете transliteration;
retail48 называет повтор lookup ошибкой, хотя пользователь повторно подтверждает
данные и просит поискать. Нельзя добавлять общий запрет retry или выдумывать
Latin argument ради binary TP. Их нужно adjudicate отдельно, сохранив official
binary metric. Анализ overlap не измеряет pipeline с новым verification.

```powershell
$env:PYTHONPATH='src;.'
$env:PYTHONDONTWRITEBYTECODE='1'
python -X utf8 -m experiments.guardian_local_a100.method_synthesis `
  --commit a300bb0f20d17bd23c556d9f70aca9a65029687a `
  --output <НОВЫЙ_ПУТЬ.json>
python -X utf8 -m pytest -q tests/test_local_a100_method_synthesis.py tests/test_local_a100_continuation.py
```

Проверено: **21 passed** (4 accounting tests + 17 continuation/native-contract
tests). Это проверки инструмента анализа/очереди, не новая оценка всего runtime.
Повторное создание отчёта должно дать идентичный JSON; существующий путь
скрипт перезаписывать отказывается. Идущий server job продолжает свою ветку;
отдельная analysis branch предотвращает конфликт с его автоматическим push.
