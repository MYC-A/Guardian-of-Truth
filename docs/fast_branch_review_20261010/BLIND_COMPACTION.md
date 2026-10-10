# Где сокращать blind pre-pass

Проверены текущий Hook2/B2 и полный сохранённый submission baseline46. Runtime и
готовый ZIP не менялись. Сеть заблокирована: 46 строк воспроизведены по точным
request hashes; binary, owner и accusation совпали с исходными ответами,
перепроецированными текущим submission finalizer. Это анализ затрат и формы
данных, а не новый эксперимент качества компактного prompt.

## Измерения

В этом baseline pre-pass сгенерировал **59 202 completion tokens**. Это другой
прогон, чем прежний local B2 с 66 401; их числа не следует смешивать.

- Все 46 ответов pre-pass распарсились. 32 переданы reviewer, 14 отброшены после
  генерации по 60 000-byte wire cap. На отброшенные ушли **20 032 tokens**.
- Для **7 из этих 14** нижняя граница injected request уже больше cap: исходный
  reviewer packet + неизменный addendum + весь neutral view + минимальный
  schema-valid analysis, в котором все обязательные массивы пусты. Эти 7 ответов
  стоили **10 701 tokens**. Их можно не генерировать, сохраняя тот же base-review
  fallback. Остальные 7 нельзя исключать этим доказательством: компактный ответ
  мог бы поместиться. Нельзя подменять нижнюю границу эвристическим резервом.
- Raw answers: 219 730 UTF-8 bytes; те же parsed values в minified JSON:
  191 750 bytes. Разница **12.7%** — оформление; это не измерение token savings.
  Reviewer уже получает minified analysis. Экономия генерации возникнет только
  при новой компактной wire/task инструкции, эффект которой надо проверить.
- Цитаты requirements: 34 473 bytes; `why`: 29 861; вместе **29.3% raw bytes**.
  Requirement paraphrases: 18 880; expected action strings: 31 577;
  uncertainties: 21 532. Эти разделы частично повторяют смысл друг друга, но
  автоматически считать весь их текст лишним нельзя.
- В 32 delivered views: 495 blind sources, из них 335 имеют text, точно равный
  одному из ordinary review sources. Дублированный source text: 208 896 из
  407 496 UTF-8 bytes (**51.3%**). Это измерение дублирования текста, не проверка
  равенства actor/order/scope или семантической роли. Нужна адресная связь.

Receipts: [baseline accounting](blind_baseline_budget.json),
[accounting with injection lower bounds](blind_baseline_lower_bound.json).
Script: [blind_prepass_offline_audit.py](../../scripts/blind_prepass_offline_audit.py).

## Предлагаемый порядок

1. **Не оплачивать заведомо недоставляемый pre-pass.** До вызова вычислить
   точную нижнюю границу тем же serializer. Если даже она выше cap, сохранить
   NOT_EXECUTED_UNDELIVERABLE и unchanged base reviewer. Не использовать IDs,
   gold, guessed response size или названия бизнес-инструментов. Это отдельная
   маленькая оптимизация; request equivalence проверяется по frozen receipts.
2. **Передавать совпадающие источники один раз.** Код связывает source spans,
   document, role, event и текст между blind/ordinary namespaces. Передавать
   alias map и только недостающие blind sources. При невозможности точного
   связывания сохранить отдельный source и gap. Не потерять chronology,
   not-read coverage и правило обычных final citations. Это сокращает reviewer
   prefill, а не само чтение истории pre-pass. Новый reviewer wire требует
   нового quality comparison, даже если содержание кажется тем же.
3. **Compact analysis вместо повторного пересказа.** Model выбирает выданные
   кодом source/leaf/norm-unit IDs, не копирует большие policy quotes. Сохранять
   краткие binding/conditions/exception hypotheses. Общие expected actions и
   uncertainties объединять с соответствующим requirement, оставляя отдельные
   нерешённые gaps. Норма с несколькими clauses требует адреса clause и
   родительского контекста; одного document ID недостаточно. Fuzzy Q2 не является
   точной source verification. Не заставлять модель считать символьные offsets.
4. **Ограничить задачу актуальным намерением из истории.** Просить выделить
   requirements для явно обсуждаемой задачи и глобальные ограничения, не
   перечислять все возможные будущие действия. Scope берётся из политики;
   user intent не отменяет global norms. Текущий response и его arguments
   остаются скрытыми, включая action-conditioned retrieval metadata.
5. **После этого сравнить компактный output budget.** 3400 — потолок, не среднее
   число сгенерированных tokens. Просто поставить 700 вместо 3400 в старой
   многословной схеме означает риск INVALID_JSON и потери pre-pass. Сначала
   уменьшить объём задачи/схемы, затем замерить completion length и долю
   delivered/failed analyses. Никаких молчаливых cuts и inferred verdicts.

Не удалять entity ownership, revisions, failed/stale receipts, conditions,
exceptions, alternative lawful actions и вычисления ради короткого JSON.
`why` может содержать единственное важное объяснение, почему условие выполнено.
Оставить короткую premises-based заметку вместо полного удаления.

## Важная логическая граница

Blind pass не знает текущего действия. Он не может превращать условную норму
«для изменения booking нужна confirmation» в безусловную обязательность для
любой следующей операции, включая lookup. Нужно разделять activation scope
нормы и состояние условий в истории. Сохранять «если next action обновляет
booking, confirmation обязательна; confirmation не найдена в прочитанной части».
Применимость именно к текущему действию устанавливает reviewer по исходным
источникам. Proposal, exact source support и code arithmetic не становятся
policy proof автоматически.

## Что можно обещать

Заведомо недоставляемые 7 pre-passes устраняют измеренную бесполезную работу;
их base reviewer requests могут остаться неизменными. Изменение очереди/KV-cache
и serving может всё равно изменить живые LLM outputs, поэтому same-wire replay
не заменяет GPU проверку. Source dedup/compact task потенциально уменьшают
затраты сильнее, но их эффект на quality и whole-script wall time **не измерен**.
Проценты bytes нельзя превращать в проценты latency; суммированные decode
timings параллельных calls нельзя считать временем полного прогона.

Для принятия: matched Qwen B2 controls, полный valid46 diagnostic и доступный
новый holdout; TP/FP/FN/F1, target/cause, generated-but-discarded work, invalid
responses, prompt/completion tokens и wall time с cold start отдельно. Server
выключен; новой live фазы нет. Текущий submission archive не заменять этим
исследовательским предложением.
