# Платформенный отказ и новый контракт основного ответа — 2026-10-09

## Подтверждённый отказ

Пользовательский лог SHA256 `99b27abcc4c52b22510035b1a65e93df87252de5a67db4ad6080583dfe62100b` показывает
46/46 обработанных строк, CLI elapsed 1744.70 s (29:04.70), затем `INCOMPLETE_PREDICTIONS`
для одного ID. Runtime действительно выполнял inference. Это application abort, а не доказанное
убийство по timeout. Подробных calls/traces из `/tmp` платформа в этот лог не включила.
Нельзя установить, был ли отказ INVALID_JSON, schema/reference admission, context или transport.
Оценить F1 по этому логу нельзя: файл предсказаний не записан.

Исходный ZIP `guardian-qwen-b2-rebuilt.zip` и его receipts сохраняются неизменными.
Новый кандидат находится в ветке `fix/qwen-primary-recovery-20261009`.

## Контракт кандидата

Default public CLI теперь `--primary-contract decision-first`, **без** `--retry-primary`.
В reviewer schema решение идёт первым; инструкция явно просит этот порядок.
Blind pre-analysis, R_fix и дополнительные слои сохраняются. Это новый wire,
не byte-identical прежний B2 и не доказанное улучшение качества/скорости.

Если обычный итог уже допустим, он сохраняется. В частности, отдельно найденное
нарушение не отменяется из-за отказа основного reviewer.
Если основной итог технически отсутствует, принимается только полностью записанное
первое top-level `decision` из **HTTP200 + finish_reason=length** неполного JSON.
Значения: ERROR→1, NO_ERROR→0, UNKNOWN→0 (явная историческая binary projection).
Keyword search не используется. Незавершённое значение, вложенное решение, уже
закрытый объект, некорректный prefix и завершённый повтор ключа отвергаются.

Такой результат — **PARTIAL_MODEL_DECISION**, `accusation=null`,
`source_support_status=NOT_VALIDATED`, `explanation_status=INCOMPLETE`.
Он не становится admitted cause или certificate. Raw receipt и технические gaps
сохраняются. Полное допустимое JSON продолжает проходить прежнее admission.

Пустой ответ, невалидный полный JSON и отсутствующее поле не превращаются в 0.
При таком неустранимом отказе default по-прежнему не выдаёт фиктивный полный файл.
Абсолютной гарантии завершения или правильной классификации нет.

## Опциональный recovery

`--retry-primary` разрешает один повтор только после отсутствующего final decision,
когда остальные checkers тоже не дали допустимый результат. Повтор не выполняет
pre-analysis или остальные слои снова. Сохраняется тот же packet; инструкция
уточняет serialization/source IDs. Для length output cap1700→3400.
Attempt+1000 и фактический request hash записываются отдельно.
Лимит4 дополнительных запросов на процесс защищён lock; каждый ограничен120s
включая tokenizer preflight. Фиксированные budget/context failures и HTTP4xx
не повторяются. Этот режим выключен, учитывая приоритет времени пользователя.

В stdout теперь есть компактная диагностика отказов/восстановлений без raw text.
Содержательное решение/причина не восстанавливаются по обрывкам explanation.

## Проверки и пределы

- 71 tests passed, 2 POSIX lifecycle tests skipped на Windows.
- Полные исторические raw replays:46 строк/179 запросов и46/180, 0 mismatches
  по binary, owner, accusation; 0 network calls. Replay сохраняет explicit reason-last control.
  Новый replay поддерживает отдельный decision-first contract, но для него нужны новые receipts.
- Новый decision-first wire проверен через public CLI с simulated local replies,
  Parquet output и контрастами parser. Это не живой GPU эксперимент.
- Параллельный независимый code reviewer проверяет prefix/admission/contracts;
  его замечания и итог сохраняются отдельно.
- Source/gold/benchmark IDs не используются для routing или runtime verdict.
- Windows refreeze inventory теперь использует POSIX separators.

Нельзя заявить, что этот patch исправит именно единственный платформенный case:
его raw reply отсутствует. Нельзя обещать30min: прежний запуск46 уже занял29:05,
а длительность полного скрытого набора неизвестна. Изменение порядка генерации
может менять качество; нужен полный GPU comparison, а не перенос old cache replies
на изменённый request. Цель patch — восстановление уже завершённого решения
без нового model call при оборванном explanation.

В архив не входят данные valid46, cache, judge/gold или операторские скрипты.
Native runtime и оригинальные веса остаются прежними; повторная компиляция CI не нужна.
