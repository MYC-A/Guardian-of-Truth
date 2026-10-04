# Исправления retrieval и multi-packet: результаты 2026-10-05

Технические дефекты исправлены и независимо проверены. **Прирост бинарного F1
с правильными причинами пока не подтверждён.** Малый парный прогон показывает,
что валидный JSON и восстановленные нормы сами по себе не обеспечивают верный
разбор текущего действия. У новых TP обнаружены ошибочные объяснения.

Ветка: `research/retrieval-corrections-v2-20261004`.
Код, исходные запросы и протокол зафиксированы **до API** в коммите
`8dfb7a0652c7a88a359fcfdd52ebbde2e96d363f`.
Production/main, `valid.parquet`, SYN gold и старые результаты не изменены.

## Что исправлено

- U2: текст непосредственно после heading/tag доступен поиску; governing
  первый абзац остаётся зависимостью дочерних правил, включая промежуточные теги.
  CATALOG ограничен своим событием, последующие SYSTEM сохраняются как POLICY.
  Обязательный последний USER-якорь нельзя ложно объявить прочитанным после exclude.
- `resolve` и global resolution: проверяются категории, автор, событие, kind,
  tool, parent, source ID, текст и хеш во всех массивах. FULL_INPUT включает
  **весь исходный каталог**, включая неиспользованные объявления, и все parsed
  event spans. Транспортные разделители парсера находятся вне этой гарантии.
- FC: детерминированные tie-breaks/суммы; квалифицированный result и полный
  paired call читаются атомарно; latest USER определяется по текстовому событию.
  Длинный USER читается целиком или получает явную failure. Whitespace-окна
  сохраняются; parent/receipt coverage сообщается явно. Недоказанная гарантия
  аппроксимации и неработающий второй feedback удалены.
- C1: независимый P2 сохраняет нормативный контекст в том же бюджете.
  C1/D пропускают этап без новых units; CTRL проверяет FULL до второго вызова;
  контроллер устраняет одинаковые вопросы до обработки; G4 останавливается
  по приращению текущего раунда.
- Отклонённый P2 не голосует как NO_ERROR: единственный валидный ответ
  сохраняется с явным fallback, owner и незавершённой composition. Raw decision,
  admitted decision, пропущенный/отклонённый этап и итог различаются.
  Старые baseline нельзя применять к изменившемуся request hash.
- Затраты включают завершённые отклонённые ответы. Дополнительно различаются
  cached/uncached вызовы и отсутствие returned usage. Старый transport теперь
  по умолчанию делает один вызов; новая фаза использует durable single-attempt
  ledger. Полное покрытие нормативного span считается по union, а не overlap;
  ambiguous повторный текст не выбирается произвольно. Numeric source coverage
  использует равенство Decimal, а не вхождение числа в сериализованные metadata.

Проверки: **150 тестов прошли**. Проверены 230 corrected U2 packets на всех
46 исходных строках при 20/40/48/80k и без лимита; budget failures/overruns — 0.
Детерминизм FC проверен на исходных 15 случаях при пяти hash seeds.
Новый frozen runner независимо проверен на incomplete/duplicate/changed-wire
inventory и offline replay без сети.

## Offline source coverage

Счётчик ниже — полные наборы **существующих 15 reference cases**, не F1.
Исходная FC нестабильна между hash seeds; здесь её baseline заранее фиксирован
на `PYTHONHASHSEED=0`. Required policy/history spans покрываются полностью по union.

| Бюджет source bytes | U2 OLD | U2 NEW | FC OLD | FC NEW |
|---|---:|---:|---:|---:|
| 20k | 8/15 | 9/15 | 3/15 | 3/15 |
| 40k | 11/15 | 12/15 | 8/15 | 6/15 |
| 48k | 13/15 | 13/15 | 10/15 | 9/15 |
| 80k | 14/15 | 14/15 | 12/15 | 12/15 |

FC потеряла нормы преимущественно из-за стоимости повторяемых window metadata
и порога перехода whole-policy → ranked-policy, а не непосредственно из-за
обязательной атомарности receipt. Например, banking_068 при 40k пересекает
whole-policy allowance всего на 3,35 bytes, после добавления 1890 bytes metadata.
Поля при этом вообще не передаются reviewer через `slim`.

Отдельный **offline prototype** удаляет три повторяемых поля из source records,
сохраняя packet-level parent/receipt diagnostics. Он восстанавливает FC coverage
с **3/6/9/12 до 4/8/10/12** полных наборов при 20/40/48/80k. На 120 пакетах
прошли проверки точного бюджета, исходных spans, полных qualified dependencies,
latest USER и честной parent coverage. Это research-only runtime patch,
**LLM F1 этого варианта не измерялся**; frozen arm и исходные результаты сохранены.
Подробности: [offline interpretation](OFFLINE_INTERPRETATION.md),
[probe script](../../scripts/coverage_metadata_probe.py).

## Парный Mistral-прогон

Одинаковые reviewer `ministral-14b-2512`, I4 prompt/schema/admission, temperature0;
одна генерация на запрос. Предварительно выбранные известные диагностические
примеры: по две положительные строки и одной отрицательной на механизм.
Никакие labels/gold/reference spans не передавались модели.

| Сравнение | n | OLD TP/FP/FN/TN | NEW TP/FP/FN/TN | OLD → NEW F1 | Technical null OLD → NEW |
|---|---:|---|---|---:|---:|
| U2, original valid rows | 3 | 1/0/1/1 | 2/0/0/1 | 0,667 → 1,000 | 1 → 0 |
| FC, original valid rows | 3 | 1/0/1/1 | 0/0/2/1 | 0,667 → 0,000 | 1 → 0 |
| C1 P2, synthetic stage only | 3 | 0/0/2/1 | 1/0/1/1 | 0,000 → 0,667 | 3 → 0 |

UNKNOWN и technical null проецируются в binary0 с отдельным учётом.
Здесь **нет нового F1 на всех 46 строках** и нет измерения итогового C1 pipeline.
Выбор по известным labels и source deltas условный; это не независимый holdout,
не исследование обобщения и не статистически надёжный ranking механизмов.

Все **18 запросов** завершились, использовано **84909 provider tokens** из
лимита 130000; HTTP failures, retries и unknown usage — **0**. Все пять
technical null возникли на content/provenance admission, а не в transport.
Raw requests/replies и ledger сохранены. Offline replay воспроизвёл 18 решений
с **0 новых HTTP**; live budget сохранён отдельно от replay accounting.

## Почему нельзя объявить семантическое улучшение

Независимый разбор исходных политик, текущих targets и cited evidence выявил:

- U2, airline9: оба ERROR требуют отсутствующее в политике повторное немедленное
  подтверждение, хотя непосредственное предыдущее USER-сообщение уже подтверждает
  отмену. Gold-cause — преждевременная эскалация без доступной проверки статуса —
  не восстановлена: оба пакета не читают нужное объявление/receipt.
- U2, telecom positive: OLD raw ERROR распознаёт запрещённый undeclared tool,
  но отклонён из-за неверного actor в citation. NEW ERROR проходит admission,
  однако объясняет нарушение выдуманным ограничением MMS-диагностики.
  Добавленный binary TP — **admission recovery с регрессией причины**.
- FC, airline23: schema `book_reservation` с обязательными payment_id/amount
  доступна обоим пакетам. OLD ERROR обвиняет в отсутствии подтверждения отмены;
  NEW корректно замечает подтверждение, но игнорирует три malformed booking calls.
  Падение F1 отражает отсутствие исходного gold-cause и неполный разбор всего move.
- FC, retail27: оба NO_ERROR рассматривают первый target и пропускают вторую
  несовместимую операцию return/exchange того же order. OLD дополнительно
  использует receipt другого order — одинаковый actor не доказывает identity.
- C1, bank positive: NEW ERROR требует повторной verification, прямо вопреки
  прочитанному правилу once-per-conversation. Ни сравнение mutated user ID,
  ни decisive identity receipt не восстановлены. Это **TP с source-refuted причиной**.
- C1, airline positive: decisive calculate receipt1581.0 отсутствует в обоих P2;
  NEW повторяет mutated1787 как достоверную сумму и даёт NO_ERROR.

В отрицательных примерах восстановленные permission/authentication нормы
улучшают обоснование NO_ERROR. Но **ни один дополнительный TP в этом прогоне
не демонстрирует source-supported recovery исходной причины**.
Полные аудиты: [original valid causes](VALID_CAUSE_AUDIT.md),
[C1 stage causes](C1_CAUSE_AUDIT.md).

## Что делать следующим

Сохранить исправления provenance/guards/accounting как исследовательский слой.
Сначала проверить без нового большого бюджета whole-current-move oracle:
перечень всех current targets, generic declaration/schema obligations, scope,
identity и точные required receipts. Эти реальные FN уже показывают, что reviewer
пропускает дополнительные targets и подменяет governing conditions, даже когда
нужные нормы доступны. Только затем оценивать автоматическое сопоставление ролей
или атомарные отношения. Компактную metadata-репрезентацию тестировать отдельной
фазой; переносить в production по данному трёхстрочному F1 нельзя.

## Артефакты и воспроизводимость

- [Замороженный протокол](EXPERIMENT_PROTOCOL.md) и
  [machine-readable protocol](../../outputs/retrieval_corrections_v2/protocol.json).
- [Matched requests](../../outputs/retrieval_corrections_v2/jobs.json),
  [decisions](../../outputs/retrieval_corrections_v2/model/decisions.json),
  [binary summary](../../outputs/retrieval_corrections_v2/model/summary.json),
  [durable ledger](../../outputs/retrieval_corrections_v2/model/ledger.json).
- [Historical sidecar](../../outputs/retrieval_corrections_v2/historical_audit.json):
  552 сохранённые U2 решения, 64 повторявшихся transport runs, 686 записанных
  transport attempts; исходные compact artifacts не позволяют восстановить
  статусы/полную стоимость неуспешных повторов и judge. C1 SYN имеет 17
  NORM_REFERENCE_INVALID в каждом из трёх runs, хотя terminal null только1/0/0.
- [Offline replay](../../outputs/retrieval_corrections_v2/offline_replay.json) и
  [compact-metadata probe](../../outputs/retrieval_corrections_v2/metadata_probe.json).

Дополнительные документы/probe не меняют frozen code hashes. API runner
`verify()` и offline cache replay сохраняют исходный протокол. LF attributes
для новой фазы защищают byte-level raw hashes при Windows/Linux checkout.
