# Независимый аудит новых архитектур Guardian — 2026-10-06

**Вывод: идеи сохраняют потенциал, но нынешний V4 нельзя считать универсальным доказательным решением.** Есть воспроизводимые полезные изменения, реальные ошибки реализации и слишком широкие интерпретации метрик. Самая перспективная линия — вычислять проверяемые факты в коде, отдельно устанавливая их связь с действием и применимой политикой. Следующий шаг — исправление этих границ и сопоставимый эксперимент, а не добавление ещё одного общего reviewer.

Аудит основан на обновлённых remote refs и конкретном снимке `32ede180831948272a8f4a57fe80b55d17e5e6dd`. Новые результаты агента не принимались на веру: проверены код, история freeze/amendments, исходные входы, сохранённые ответы и независимые контрпримеры. Работа выполнена в отдельной ветке `research/independent-architecture-audit-20261006`; production, исходный gold и исторические outputs не менялись. Новых model/API/SSH вызовов нет.

## 1. Какие ветки изучены

| Ветка / снимок | Что добавляет | Оценка |
|---|---|---|
| `research/guardian-integrated-v1-20261005`, `6dfd72ab` | Единый SourceStore → guard → U2 → reviewer → relations/controller → итог; установочный и CLI путь | Полезная интеграционная основа. Always-on relations ухудшили результаты; gated вариант post-hoc. Полного парного Gemma46 нет. |
| `research/guardian-verification-v2-20261006`, `aed76d1f` | Admission v2, skeptical review, counterfactual, checklist, narrow verifier; затем V3 DF/CB/G_closed | Admission v2 — подтверждённое исправление технического отказа. DF — небольшой повторённый выигрыш на внутреннем LB3. Отдельные выводы о неработающих идеях слишком широки. |
| `research/guardian-proof-executor-v4-20261006`, `32ede180` | DF4, типизированный executor, Ems, all-target, matched control, external tau2 | Хорошее разделение предложений и вычислений, но сертификаты не проверяют всю семантическую цепочку. Внешний gold v1 ошибочен; v2 exploratory. |
| `backup/v4-wip-20261006`, `a864e58a` | Восстановленная промежуточная работа после rollback | Это backup, не отдельный подтверждённый кандидат. Финальный DF4 отличается последующей общей проверкой направления дат. |

Эти ветки образуют последовательную историю, а не четыре независимых подхода. Нельзя складывать их выигрыши как независимые подтверждения или объединять все модули без новых ablations.

## 2. Что воспроизведено

**472 строки, 903 заново построенных запроса:** из сохранённых `raw_content` восстановлено исполнение текущего frozen V4. Каждый запрос принимался только при точном совпадении `request_sha256`. На всех строках совпали решения **и тексты/адресаты обвинений** во всех arm projections.

Состав: valid46; LB1-long57; LB2-long47; LB3-long56 × 2; external70 × 3. Это replay исходных ответов, а не новые предсказания модели и не независимая аутентификация provider cache-key/attempt. Две исключённые v2 строки сохраняются в исходном external replay; v2 метрики считают явно только 68 размеченных строк.

- [Скрипт replay](../../scripts/independent_architecture_replay.py), [JSON результатов](raw_replay.json).
- Независимый V2/V3 анализ восстановил ещё 90 verifier request hashes, все совпали; оба исходных LB3 V3 прогона полностью воспроизведены.
- Выбранные существующие тесты: **102 passed, 2 skipped, 1 failed**. Ошибка — физический SHA frozen external файла после Windows LF→CRLF checkout. Оригинальные Git blobs совпадают с manifest; различие ровно в переводах строк. Это проблема переносимости артефактов, а не свидетельство изменения gold.
- На Windows обнаружено второе условие запуска: locale-dependent `read_text()` в research runner/scorers искажает UTF-8 маркеры при cp1251. В одном исходном external ходе число targets стало 1 вместо 5, policy исчезла. Replay выполнялся с `PYTHONUTF8=1`; это обход в аудите, не исправление исходного runner. Публичный integrated CLI уже читает UTF-8 явно.

Команда полного runtime replay:

```powershell
$env:PYTHONUTF8='1'
python scripts/independent_architecture_replay.py --output <НОВЫЙ_ПУТЬ_ОТЧЁТА.json>
```

Скрипт блокирует сеть и отказывается перезаписывать существующий отчёт. Старые scoring scripts не запускались в режиме report: они могут перезаписать исторические outputs.

## 3. Что действительно работает, а что ещё не доказано

### Admission v2 — оставить

Исправляет представление актёра tool-result по источнику, которым владеет код. На LB2: 17TP/1FP → 19TP/1FP, без новых запросов. Это полезное и переносимое исправление контракта; оно не подтверждает смысл самого обвинения. Базовый рекомендованный профиль остаётся `guard_adm2` в пределах измеренного формата.

### DF / DF4 — развивать, не выбрасывать

На первоначально отложенном внутреннем LB3 V3 добавил по два cause-correct TP в обоих прогонах, без новых FP; собственно DF добавил 1 и 2 TP. Это реальный ограниченный результат. Порог принятия всей V3 (≥3 в каждом прогоне) не достигнут.

| Набор / статус | База | Дополнение |
|---|---|---|
| valid46 r1, development | A: 15TP/3FP, F1 .732 | V3 и V4: тот же бинарный результат |
| LB3 r1, исходный V3 held-out внутри synthetic process | A: 23TP/7FP, F1 .793 | V3: 25TP/7FP, F1 .833 |
| LB3 r2, тот же внутренний контракт | A: 23TP/4FP, F1 .836 | V3: 25TP/4FP, F1 .877 |
| LB3 r2, последующий V4 development | A: 23TP/4FP, F1 .836 | V4: 27TP/5FP, F1 .900; уже не независимый holdout |

На CL3e и TL3e корректные oracle bindings позволяют неизменённому DF вычислить ошибку. Это подтверждает достижимость при правильной экстракции, **не** автоматический прирост F1. Семантическое сопоставление operands остаётся частью задачи.

### All-target — полезное покрытие; качество обвинений отдельно

Перечисление каждого current target исправляет структурную слепоту к остальным действиям. Но наличие строки с каждым ID не гарантирует проверку всех норм, правильное связывание evidence или правильную причину ERROR. Возвращённые кандидаты нужно хранить отдельно от target coverage.

### Counterfactual — проверена узкая реализация, а не идея целиком

На 3 из 4 остаточных LB2 FN необходимые вмешательства вообще не генерировались. Генератор делает ограниченные замены по истории и omissions; он не вычисляет новый срок/число ночей/сумму и не разрешает произвольные имена из prose. Удаление действия часто тривиально снимает нарушение и слабо проверяет причину. Отрицательный вывод относится к этому generator + original-status decision, а не ко всем причинным контрастам.

### Verifier — иногда полезен; Q2 нельзя считать точной цитатой

После исправления цитатного gate доля сохранённых правильных LB2 кандидатов выросла с 1/4 до 3/4. Но это post-hoc переоценка. Фильтрация всех A ERROR теряет TP; обязательная повторная проверка любых выводов не оправдана текущими данными.

## 4. Где формулировки результатов вводят в заблуждение

1. **Реальный FN BK3e описан неверно.** `docs/verification_v2/RESULTS.md:28` говорит, что E не перечислил нарушенное требование. В обоих исходных V3 прогонах E правильно записал `400+900=1300>1000` и VIOLATED. Gate затем удалил реконструированный JSON subset как не-дословную цитату. Отказ такого quote допустим; вывод об отсутствии способности — нет. Исправление: адресованные JSON leaves/несколько точных premises, а не ослабление смысловой проверки.
2. **«Later-call recall 9/9» — row recall, не проверка позднего действия.** `verification_v4/score.py` проверяет binary ERROR на строках с later gold target, но не совпадение обвиняемого target. Все новые later-row gains в external reps обвиняют t0, когда старый substantive gold target t1/t2/t3. Метрику нужно переименовать; отдельно считать target-correct и cause-correct recovery. Для нарушения всего хода допустим move-level target, но это другой контракт.
3. **Cause-correct менял определение.** Integrated scorer считает SAME+PARTIAL+GUARD; V2/V3/V4 — SAME+GUARD. Числа cc разных фаз без унификации несопоставимы. SAME проверяет модель той же семьи, видящая два текста, а не все исходные свидетельства. GUARD автоматически считается correct; такое решение тоже требует независимого premise/target аудита.
4. **«Format-only» не доказывает отсутствие содержательной ошибки.** В gold v2 substantive причины перечислены вручную для части строк. Независимое чтение обнаружило дополнительные возможные причины: выдуманный DOB в `ext_tel_004/047`, поздняя отмена другой резервации в `ext_air_061`. Нужна слепая adjudication. Автоматически менять labels или объявлять эти случаи новыми правильными TP нельзя.
5. **Нет доказательств скрытого выбора лучших успешных external ответов.** В rep3 92 записи на 70 IDs: 22 первых записи — 429, затем 200 с тем же A request hash. Last-write-wins соответствует transport resume. Но scorer обязан проверять законность retries и полное множество IDs, а не молча выбирать последнюю запись.

Подробности и independently checked evidence: [аудит логики](agent_logic.md), [аудит данных и метрик](agent_method.md).

## 5. Внешний tau2 эксперимент: что можно заключить

Изначальный gold v1 смешал task success/action matching с compliance. Независимо подтверждено: 19 прежних NO_ERROR нарушают явные правила формата; ещё две строки исключены как неопределённые. Агент правильно отозвал первоначальный REJECT и сохранил исходную фазу. Gold v2: 68 строк, 52 ERROR/16 NO_ERROR, построен **после просмотра результатов**; strict-v2 тоже наследует этот отбор. Это diagnostic, не blinded доказательство переноса.

| Rep | A F1 (TP/FP) | V4 F1 (TP/FP) | A + oracle отношения формата F1 (TP/FP) |
|---|---|---|---|
| 1 | .707 (29/1) | .809 (36/1) | .848 (39/1) |
| 2 | .738 (31/1) | .822 (37/1) | .872 (41/1) |
| 3 | .723 (30/1) | .835 (38/1) | .872 (41/1) |

Последний столбец — наш **дешёвый oracle diagnostic**, не новое универсальное решение. В коде проверены события production parser и два уже установленных policy отношения: максимум один tool call в ходе; отсутствие одновременного prose+call. Ограниченное распознавание именно этих английских фраз служит явным oracle contract, не общим NL compiler. Нет правил по имени инструмента или ID строки.

Уникальных format-positive строк 30 (F1:21, F2:11, есть пересечение); 19 имеют только размеченную format причину. Диагностическая добавка исправляет **10/10/11 FN** базы, без новых FP. Это показывает недоиспользованный потенциал точных policy-bound структурных отношений. Не доказывает, что их автоматическое извлечение будет столь же точным на новых политиках, exceptions и форматах.

External набор не запускает DF и не содержит подходящих compositional proof примеров. По нему нельзя отклонять DF, business-day расчёты или многопредпосылочный executor. Нельзя и объявлять их перенос подтверждённым. Замороженный конкурсный valid46 остаётся development диагностикой; архивный OR Granite F1 .8889 — иной стек, а R0 .9714 на sealed160 вообще другой набор.

## 6. Конкретные дефекты, которые нужно исправить

| Приоритет / слой | Воспроизведённая проблема | Универсальное направление исправления |
|---|---|---|
| P0, enforcement | `code_proven` означает правильную арифметику над LLM-selected листьями. Чужой адрес/игнорируемое исключение становятся ERROR; V3m/V4_mechanical обходят даже REFUTED | Разделить leaf support, role/entity/field/time/unit binding, applicability/exceptions/closure и expression truth. Не повышать arithmetic fact до policy proof; mechanical bypass только при полной цепочке |
| P0, цитаты | Q2 принимает цитату с удалённым NOT; это проходит и leaf/verifier admission | Точные source addresses и безопасная нормализация оформления. Polarity, quantities, operators, entities, guards и exceptions сохранять; fuzzy поиск допустим как поиск кандидата, а не certificate |
| P0, aggregation | Один amount600 с двумя цитатами суммируется как1200 | Code-issued leaf identity `(event, JSON pointer, occurrence)`; grouping и completeness. Равные суммы разных событий нельзя просто дедуплицировать по value |
| P1, DF | Случайное совпадение текущего числа с любым tool result отключает derivation; чужой age30 скрывает subtotal10+tax10 → current30 | NOT_DERIVED только по подтверждённой связи copy/field/entity/unit/time; сохранять competing hypotheses, не глобальный value match |
| P1, assertion scope | «I reject the incorrect claim 2+2=5 EUR» становится strict code violation | Разделять утверждение ассистента, цитату, отрицание, пример и условный контекст. До верификации scope сохранять hypothesis |
| P1, consent | BK-1 и BK-10 совпадают; Thank you сбрасывает уже подтверждённое предложение; yes с уточняющим вопросом проходит | Активные proposal/revision/confirmation события, точные action/entity/argument tuples и chronology. Aliases — отдельные подтверждённые отношения |
| P1, source closure | «Complete only for read operations; other writes allowed» превращает отсутствующий разрешённый write в mechanical ERROR | Явный bounded closure contract с областью/условиями; source cooccurrence не доказательство замкнутости |
| P1, candidate pool | AT/Ems/DF выбирают первый candidate; после его REFUTED остальные не проверяются. Неявные slices ограничивают targets/claims | Хранить весь admitted candidate pool; bounded queue с явными unchecked gaps; не терять доказанный другой candidate из-за первого |
| P1, вычисления | ADD/SUB/MUL с правым0 выполняют также DIV и получают ошибку; datetime теряет seconds/offset; 10000≈10001 | Выполнять только выбранный оператор. Full-precision timezone-aware timestamps; Decimal и явный rounding/tolerance contract для money/counts |
| P1, воспроизводимость | Windows cp1251 ломает входы; CRLF ломает frozen SHA; scorer молча допускает missing IDs/retries | Explicit UTF-8 I/O; LF attributes frozen paths; проверка оригинальных Git bytes и всего ожидаемого множества строк, отдельный retry ledger |

Все counterexamples — offline admission/boundary probes, не оценки частоты ошибок живой модели. Они опровергают универсальность текущего certificate, но не отменяют измеренные корректные cases.

Детальные code references и входы: [agent_code.md](agent_code.md), [agent_logic.md](agent_logic.md); рядом находятся исполняемые probes и JSON результаты.

## 7. Рекомендуемая архитектура

Собирать компактную согласованную систему, оставив сложные модули opt-in до измерения пользы:

1. **Source/input:** неизменяемые UTF-8 оригиналы, explicit framing/actor/inventory; полный список current targets; статус успешности receipt и input completeness отдельно.
2. **Evidence/facts:** code-issued source/leaf IDs, typed values и JSON pointers; entity/field/unit/time/event/status. Observation — свидетельство содержимого, не автоматически текущее состояние мира. Retrieval хранит not-read gaps.
3. **Policy/binding:** source-addressed requirements с action scope, necessary preconditions, exceptions, grouping keys, timing и closure assumptions. Модель предлагает связи; admission доказывает только их заявленный уровень. Exact quote сама по себе не доказывает применимость.
4. **Focused checkers:** arithmetic/calendar и structural predicates в коде; DF/confirmation/all-target предлагают candidates. Ems исполняет выражение после отдельного binding check. Каждый статус различает supported fact, model hypothesis и unresolved premise.
5. **Candidate adjudication:** проверять обязательные premises, сохранять несколько причин/targets; независимое модельное уточнение только для unresolved семантики. Base A ERROR и дополнительные кандидаты учитываются раздельно, чтобы OR не скрывал базовые FP.
6. **Final contract:** violation, world-state unknown, missing evidence и technical failure различаются внутри; explicit binary projection с подсчётом вызванных FN. NO_ERROR не означает доказанный ALLOW.

Не требуется сперва внедрять большой ontology/compiler/planner. Достаточно enforceable контрактов для уже измеренных операций и возможность явно отказаться от неподдержанного binding. Архитектуру разрешено менять, но причина изменения и paired результаты должны быть видимы.

## 8. Следующие эксперименты по порядку

1. **До новых HTTP:** зафиксировать этот аудит; исправить чистые вычислительные/I/O ошибки отдельно; добавить контрпримеры на границы. Не редактировать старую gold/freeze фазу задним числом.
2. **Replay прежних raw ответов:** полные valid46 и LB1/2/3; раздельные ablations leaf addressing, duplicate grouping, copy suppression, assertion gate, confirmation state, candidate pool. Для каждого изменения — TP/FP/FN, true candidates lost/recovered, UNKNOWN/technical null, reasons/target, requests/cost. Oracle не считать автоматическим улучшением.
3. **Oracle ceiling на реальных FN:** дать правильные policy relations/operands, не менять вычислители; отдельно измерить binding attainable gains и ошибки downstream. Проверить BK3e, CL3e, TL3e и реальные valid46 misses. Успешная JSON экстракция не заменяет бинарную метрику.
4. **Автоматический grounding:** только после oracle; сравнить extraction contracts по операциям против общего proof plan. All-target сравнить с обычным review при одинаковом лимите output tokens и фактическом расходе; сейчас одинаковое число calls не равно одинаковому token ceiling (AT2200 vs CTRL1700).
5. **Новый blind holdout:** новые policy-compliance annotations, полные alternative causes и target/move scope, минимум независимая adjudication до просмотра model outputs. Разделять tasks/trajectories/domains; включить хорошие/плохие пары с exceptions, другой сущностью, stale/failed results, quotes/negation, несколькими equal-value событиями, prose/date/computation. Ещё один внутренний синтетический набор той же формы не независимая внешняя валидация.
6. **Полная фаза моделей:** Mistral и Gemma baseline46/integrated46 с отдельными сопоставимыми receipts и >=3 repetitions нового holdout. Gemma quota failure — NOT_EXECUTED, не ноль качества и не замена другим семейством. Останавливать provider на повторяющемся quota/rate-limit сигнале; не повторять сотни бесполезных 429.
7. **Принятие:** по заранее заданным бинарным и cause/target критериям, FP risk и cost. Сначала opt-in кандидат; default менять только по сопоставимому доказательству. Регулярные commit+push в research ветку, production merge отдельным reviewable шагом.

**На сегодня:** сохранять integration/admission основу, развивать source-bound DF и полный target inventory, сузить смысл proof labels, исправить downstream потери и оценку причин. Отрицательные verdicts не дают оснований выбрасывать DF/counterfactual/verification идеи; положительные binary scores не дают оснований считать готовым универсальный Guardian.
