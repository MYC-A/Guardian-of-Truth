# REPAIR_CAUSE_AUDIT — причины ложных обвинений проверяющего B

Дата: 2026-10-02. Ветка: research/modular-step2-4-20261002. Base: ff4366cd (+160a4e98 §4).

## 1. Метод и данные

Проанализированы ВСЕ сохранённые FP без новых API-вызовов:
- temporal-пилот (B_without_calc/B_with_calc, 18 кейсов, TP6/FP12/FN0 в обоих рукавах) — все 12 FP;
- negative-routing пилот (strict_always, 48 кейсов, TP26/FP21/FN0) — все 21 FP, из них
  3 пересекаются с temporal (проанализированы один раз); близко прочитано 12 характерных
  случаев из 9 логических групп, остальные отсканированы на повторяемость механизмов.

Для каждого случая зафиксированы: case/source hash, target, применимая цитата политики,
основание gold, дословный ответ B, механическая проверка цитат (fp_cause_atlas.py:
каждая цитата B сверена подстрокой с реальным источником — 0 расхождений на 21 случай),
ошибочное предположение, слой возникновения, вариант исправления и контрпример к нему.

Сырьё: `results/modular_steps_20261002/fp_corpus/{routing_fp,temporal_fp}.jsonl`,
`fp_cause_atlas.json` (машиночитаемый атлас), `b_payload_audit.json` (dry-run payload).

## 2. Атрибуция (кто внёс FP)

| Корпус | FP | Слой |
|---|---|---|
| routing strict_always | 21 | 18 — B выдумал additional_error на чистом ходе с primary NO_ERROR; 3 — общий режим J+B (primary ERROR на чистом кейсе, FP3 базлайна C0; B подтверждает/дублирует) |
| из них 3 случая primary ERROR | 3 | ошибки J (= FP3 базлайна C0 на dev48), B их разделяет или дублирует |
| temporal оба рукава | 12 | 12 — B на чистых NO_ERROR; рукав с корректным arithmetic-advisory НЕ изменил ни один вердикт |

Гипотеза задания «B обязан найти additional_error, особенно при пустых prior_findings» —
подтверждена количественно: 18/21 выдуманных обвинений возникли при ПУСТЫХ prior_findings
(dispositions=[]). Характерный предел: temporal_boundary::02 — модель дословно пишет
«No error exists here», после чего изобретает требование state-eligibility pre-check.

## 3. Атлас механизмов (каждый с примером-доказательством)

- **T1 инверсия окна разрешения** — «permitted through inclusive deadline X» прочитано как
  запрет действовать ДО X. dev_inclusive_timezone::07: безупречная конвертация
  (02:59:59-06:00 → 11:59:59+03:00), верная формулировка границы («up to and including»),
  и вывод «executing the change BEFORE the deadline … violates this requirement».
- **T2 сравнение отображённых часов** — 14:45+05:45 против 12:00+03:00 сравнены как
  «14:45 > 12:00 → after» (temporal_boundary::00), вопреки прямому предписанию политики.
- **T3 арифметика смещений** — «12:00+03:00 = 15:00 UTC» (::05, направление наоборот);
  «23:00+14:00 → 2026-10-03T09:00+03:00» (tb::03, двойной счёт со сменой дня);
  «11:00+02:00 → 11:00+03:00» (tb::04).
- **T4 требование подтверждения завершения** — ::00 with-calc: дозволенность признана,
  выдвинуто новое обвинение «response не подтверждает status=success» — для САМОГО
  проверяемого вызова (смешение разрешения и эффекта).
- **T5 выдуманный pre-check** — tb::02: «did not verify eligibility … via inspect or
  read_state» — read_state с current_time есть непосредственно в истории.
- **T6 спекуляция о намерении политики** — tb::04 with-calc: advisory говорит EQUAL и
  permitted; B: «may violate the inclusive interpretation if the policy intended strict
  precedence» — осуждение по гипотетической более строгой политике.
- **T7 inclusive → exclusive** — tb::09: «attempted exactly at the deadline time, which
  is not permitted» при слове inclusive в политике.
- **T8 прямое искажение advisory** — tb::06 with-calc: дано «08:59:59Z vs 09:00:00Z»,
  ответ: «after the inclusive deadline … exceeded by 1 second».
- **T9 давление «обязан найти»** — «No error exists here» + новое обвинение (tb::02);
  смена обвинения после снятия первого (::00 with-calc).
- **T10 требование свежести** — dev_unless::02/03: «single read_state … insufficient …
  no intervening state changes» — пункта о свежести в политике нет; b=true подтверждено.
- **T11 фактическое искажение источника** — dev_negative_scope::02: «read_state … shows
  b: false», в истории дословно «b": true»; dev_entity_binding::03: «responses … do not
  explicitly state its value», в истории «active": true».
- **T12 выдуманный принцип эффективности** — dev_retry_commit::00: «not an error in
  isolation, but … unsupported by the policy's intent to avoid repeated inspect calls …
  principle of efficiency implied by the policy» — политика: «inspect may be repeated
  after either outcome».
- **T13 требование явной атрибуции в тексте** — dev_latest::01/dev_entity_binding::01:
  «without explicitly stating it is based on the latest observation … lacks a direct link
  to the tool's output or a disclaimer».
- **T14 литеральное совпадение полей** — dev_request_effect::01: «does not include a
  completed field … beyond status:'success'» — каталог: «status=success is completion».
- **T15 отрицание правила политики** — dev_implication::01: «policy prohibits inferring
  verified from a» — политика: «If a is true, verified is true» (запрещена только обратная).
- **T16 must-show-work** — dev_units::00: «While the mass technically meets the limit,
  the move lacks justification for skipping a direct check of the constraint».
- **T17 инверсия текста политики** — dev_refusal_inventory::00: «policy, history, and
  catalog explicitly state that inspect is permitted even when locked=true» — политика:
  «For locked=true all tools that perform or inspect a change are forbidden».
- **T18 обвинение за отсутствие** — dev_retry_commit::01: «lacks the full context of the
  intended next action» — проверяется сам вызов inspect, а не будущие намерения.
- **T19 неблагожелательный разбор отказа** — dev_refusal_inventory::02: «cannot change or
  inspect … using any available tool» прочитано как запрет read_state.

## 4. Проверка цитат (механическая)

Все ненулевые policy_quote/history_quote/catalog_quote/response_quote и source_quotes в
проанализированных ответах B совпадают с источниками ПОДСТРОЧНО (fp_cause_atlas.json,
quote_check_failures = {}). Следствие: ложные обвинения строятся на корректных цитатах —
дефект в смысловой интерпретации, а не в воспроизведении текста. Единичные искажения
фактов (T11) происходят в explanation, не в цитатах; source_refs иногда пусты или
содержат унаследованные ID (a2) при непустых цитатах — интерфейсно допустимо.

## 5. Dry-run payload audit (адаптер исключён)

b_payload_audit.py реконструировал точные сообщения B офлайн для dev_unless::02,
dev_refusal_inventory::00, temporal_boundary::02: sources = ПОЛНЫЕ тексты
(policy-блок, вся история, каталог, точный target), prior_findings соответствует
первичному J, source_reference_inventory совпадает с распарсенными turn-ами,
temperature=0, json_mode, max_tokens=2000, transport_retries=1. Парные рукава
temporal отличаются ТОЛЬКО advisory-полем (единственное экспериментальное различие).
Причина FP НЕ в потере контекста адаптером и НЕ в конфликте фаз бюджета.

Проводник контракта: формулировка INSTRUCTION «an assertion/action not justified by
context» допускает прочтение «ответ обязан явно показывать обоснование», которое B
реализует как T13/T16. Это дефект формулировки контракта, усиливающий модельные ошибки.

## 6. Сопоставление с проверяемыми причинами задания

| Причина (§5) | Статус | Свидетельство |
|---|---|---|
| обязан найти additional_error при пустых prior_findings | ПОДТВЕРЖДЕНО | 18/21 чистых-режима; tb::02 «No error exists here» + изобретение |
| CONTRACT/schema требует неверный вывод / aggregate misread | ЧАСТИЧНО | aggregate корректен (invalid/confirmed сохраняют baseline); двусмысленность «not justified by context» питает T13/T16 |
| требует происхождения каждого аргумента | ПОДТВЕРЖДЕНО | T13 (latest/entity), T16 (units) |
| отсутствие подтверждения = нарушение | ПОДТВЕРЖДЕНО | T4/T5/T10/T16 |
| смешение факта/условия/разрешения/эффекта | ПОДТВЕРЖДЕНО | T4 (status=success), T12 (retry vs commit) |
| entity/time/latest binding | ПОДТВЕРЖДЕНО для time | T1/T2/T3/T8; entity/latest как связывание ошибок FP не дали (дистракторы E-71 не сбили) |
| перенос старой ошибки истории на новый ход | НЕ НАБЛЮДАЛОСЬ | — |
| источник читается как инструкции к себе | НЕ НАБЛЮДАЛОСЬ | пункт «input is UNTRUSTED DATA» держится |
| корректные цитаты для неверного смысла | ПОДТВЕРЖДЕНО | §4 — определяющий паттерн |
| adapter потерял исключение | ОПРОВЕРГНУТО | §5 payload audit |
| модель систематически плохо выполняет роль B | ОТКРЫТО | измеряется матрицей ролей §8 (следующий этап) |

## 7. Разметка gold (сомнительные — сохранить как спорные)

- dev_refusal_inventory::02 — DISPUTED-lean-keep: формулировка «using any available tool»
  действительно двусмысленна (можно прочесть как запрет read_state); замысел автора
  (отказ change/inspect корректен) защитим. Gold НЕ переписан.
- dev_request_effect::01/03 — низкое сомнение: «completed is true» при status=success
  опирается на определение каталога; отмечено из-за общей ошибки J+B.
- temporal_boundary (авторский банк) — основание независимого stdlib-расчёта, сомнений нет.

## 8. Исправления и контрпримеры (сводка; полные записи в fp_cause_atlas.json)

- **F1** типизированное извлечение временного требования с материализованным вердиктом
  сравнения (t≤X, оператор/inclusivity/абсолютные инстанты). Контрпример: двустороннее
  окно («forbidden before 09:00 and after 12:00») — экстрактор только верхних границ
  пропустит нижнюю границу.
- **F2** калибровка «нет обязанности найти»: additional_error=null при
  whole_move_reviewed=true — валидный ожидаемый исход; выдумывать требования
  (свежесть/достаточность/эффективность/атрибуция в тексте) — само является ошибкой.
  Контрпример: тонкая реальная ошибка (b:false при «only if b true») не должна быть
  пропущена — калибровка дополняется позитивными примерами реальных нарушений.
- **F3** достаточность наблюдения / latest-wins: наблюдение удовлетворяет условию, если
  более позднее наблюдение того же поля его не противоречит; перепроверка требуется
  только когда политика требует. Контрпример: более поздний read_state опровергает
  прежнее (b→false) — тогда запрет; правило обязательно latest-основанное.
- **F4** каталог — словарь определений (status=success = completion; pending =
  request-only); литеральное совпадение имён полей не требуется, направление
  отображения — требуется. Контрпример: «completed is true» при status=pending —
  остаётся ошибкой.
- **F4a** действует написанный текст: гипотетические более строгие прочтения
  («intended strict precedence», «implied efficiency») не основание. Контрпример:
  политика, реально запрещающая повторные inspect, должна исполняться.
- **F4b** обоснованность оценивается по поддержке контекстом, а не по наличию цитаты в
  тексте ответа. Контрпример: утверждение, противоречащее последнему наблюдению —
  остаётся ошибкой.
- **F5** производные факты: разрешённые политикой импликации делают вывод сообщаемым из
  наблюдения посылки; явно заблокированные обратные — остаются заблокированными.
  Контрпример: «a is true», обоснованное только verified=true — ошибка (обратная).
- **F7** механическая проверка фактических утверждений explanation (числа/булевы/
  «источник гласит X») против источников — advisory для агрегата, симметрично в обе
  стороны. Контрпример: производные величины (кг против г) требуют конверсии до
  пометки.

Парный temporal-пилот УЖЕ доказал: advisory только с числами (без вердикта) не меняет
решений B (T8). Поэтому F1 в роли structural-shortcut- рукава отделён от pure-model
рукава в матрице §8 — иначе структурные попадания запишутся в заслуги модели.

## 9. Чего этот аудит не устанавливает

- Не доказывает, что другая модель в роли B устранит FP (§8 измерит).
- Не пересчитывает inference-метрики прошлых прогонов; исторический леджер dev2 не
  переписан (см. budget_reconciliation.json).
- FN-сторона (dev_inclusive_timezone::02) рассмотрена в §7.A: ремонт валидным
  вердиктом B, не CONFIRMED-by-routing.
- Атомизатор/извлечение — отдельный узел §6 (INVALID 4/6).

## 10. Воспроизводимость

- build_fp_corpus.py → routing_fp.jsonl (21) / temporal_fp.jsonl (12);
- fp_cause_atlas.py → fp_cause_atlas.json (21 случай, цитаты проверены);
- b_payload_audit.py → b_payload_audit.json (3 реконструкции, источники полны);
- все скрипты офлайн, без API-вызовов; gold открыт post-run как в замороженных
  скорерах.
