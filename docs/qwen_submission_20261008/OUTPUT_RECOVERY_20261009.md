# Обработка отказов без изменения reviewer — 2026-10-09

Готовый архив: `A:\Guardian-submissions\guardian-qwen-b2-output-recovery.zip`.
Полный packaging receipt:`receipts/output_recovery_packaging_20261009.json`.
Source commit:`5711da67c3a5427a0f88005761d8d149a16a670f`.
Новый native runtime не компилировался; веса/бинарники прежние.

## Итоговый контракт

Пользователь явно выбрал полный binary output с fallback0. Новый протокол
`submission-output-recovery-1` реализован отдельно от строгого решения.
Промпт, schema с decision в конце, pre-analysis3400, reviewer1700, F-rules700,
источники, триггеры и порядок обычных проверок сохранены. Повторный reviewer
не добавляется. Вариант decision-first (`b5e52034`) отклонён и удалён из текущего
runtime; его архив `guardian-qwen-b2-decision-first.zip` **не использовать**.

Последовательность:

1. Обычный допустимый результат остаётся прежним, включая reason/owner.
2. Ошибка дополнительного DF/Ems/AT/verifier или слоя F/S/P записывается отдельно.
   Уже принятый primary и независимо поддержанные нарушения сохраняются;
   остальные независимые проверки продолжаются. На успешном пути запросы и
   ответы не меняются. Failed component не выдаёт candidate/certificate.
3. Для HTTP200+finish_reason=length можно добавить только одну завершающую `}`.
   Никакие значения/поля не додумываются; все прежние schema/reference checks
   должны снова пройти. Original raw остаётся в receipts.
4. Если strict result отсутствует, но полный JSON содержит top-level decision
   ERROR/NO_ERROR/UNKNOWN, используется его binary classification. Это
   `RAW_MODEL_DECISION`, **accusation=null**, cause NOT_VALIDATED. Decision внутри
   строки/вложенного объекта, duplicate keys, failed HTTP или finish_reason=error
   не принимаются. Неполный scalar/JSON не превращается в найденную метку.
5. Если пригодного решения нет, output0 с `DEFAULT_ZERO`, strict_binary=null,
   сохранённой technical_error и gaps. Это **не подтверждённый NO_ERROR**.

Изменяется обработка отказов и конечная binary projection для таких строк,
а не исходные правила политики. Полностью сохранить старое поведение на ошибках
и одновременно гарантировать per-row output невозможно: новая projection
явно разрешена пользователем, и её последствия считаются отдельно.

При исключении trigger helper используется уже полученный primary snapshot;
пропущенные следующие checks не объявляются выполненными. Policy-coverage gate
F/P проходит и после ошибок соседнего слоя: unread policy не становится proof.

Fallback покрывает неудачные строки **после чтения валидного input и запуска
runtime**. Ошибка входного файла, startup GPU/model, SIGKILL или невозможность
записи output остаются отдельными ошибками всего процесса. Абсолютной гарантии
завершения или правильного fallback0 нет.

## Сопоставимые проверки

| Кэш / full valid46 | Прежде, уже исправленная строгая обёртка | Сейчас | Новых HTTP |
|---|---|---|---|
| 8 slots,179 replies |14TP/0FP/9FN/23TN, F1 .7567568|То же|0|
| 16 slots,180 replies |14TP/1FP/9FN/22TN, F1 .7368421|То же|0|

Во всех92 строках совпали binary, owner и accusation; exact request/attempt/model/tag
checks совпали на179+180 сохранённых запросах. Никаких benchmark IDs, gold или
названий бизнес-инструментов для recovery/routing нет. Во всех этих сохранённых
строках новая raw/fallback projection не потребовалась: её частоту и качество
на реальном упавшем запуске эти данные не определяют.

Original archived wrappers had10/9 invalid rows из-за прежнего optional pre-pass
accounting. Их corrected projection уже существовала до этой работы; приведённые
F1 **не являются новым приростом**. Historical outputs и frozen gold сохранены.

Раздельные tests включают missing root close, wrong reference, rejected schema,
empty/truncated reply, failed completion, exceptions в компонентах, сохранение
подтверждённого кандидата и policy-closure gate, full output через public CLI,
а также совпадение live/replay двухступенчатой projection.
Итоговый выбранный набор: **146 passed,4 platform-specific skipped**.
В четырёх legacy CLI tests исправлен stub `lambda *a`→`lambda *a, **k`:
его отказ на уже существующем max_tokens воспроизведён и на старом runtime.
Assertions и runtime token limits не ослаблялись.

Независимый code reviewer `/root/archive_review` нашёл и проверил исправление
потери mechanical-positive при rec=None; проверил stage boundaries, transport
gate и независимость output classification от cause admission. Его selected
проверки:60 passed,2 POSIX skipped. Второй агент реализовал и проверил isolated
v5 stages; successful output/wire сравнивался с прежним режимом.

## Диагностика и ресурсы

В run.json: raw_model_recoveries, default_zero_fallbacks, root_close_recoveries.
В stdout: безопасные причины schema/reference/transport отказа, finish_reason,
raw content size/hash; raw text/полные source данные остаются в traces/calls.
Default0 может добавить FN. RAW_MODEL_DECISION может добавить FP; причина такого
предсказания не объявляется доказанной. Все строки участвуют в F1, без exclusions.

Новых модельных/GPU прогонов нет. Для нормального пути не добавлено HTTP calls;
CPU copying/validation/diagnostics даёт небольшой overhead. Продолжение других
проверок после исключения может выполнить работу, которую прежде бросали.
Архивная длительность46 строк29:05 и ограничение полного скрытого прогона
по-прежнему не превращаются в гарантию времени. Причина единственной реальной
платформенной невалидной строки неизвестна: её raw receipt в присланном логе нет.
