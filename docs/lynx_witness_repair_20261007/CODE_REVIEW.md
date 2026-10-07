# Независимый code review

Отдельный агент `lynx_witness_review` проверил witness builder, lifecycle и
scorer, без SSH/API/model calls. Это независимый code review, **не** независимая
разметка датасета или причины. Основной автор проверил замечания по коду.

До запуска e6632db4 исправлены:

- returned CONTEXT_NOT_FIT/TECHNICAL_UNJUDGED теперь отражаются в row status;
- length-limited completion не даёт verdict;
- freeze хранит hashes импортируемых renderer/loader/classifier;
- lexical score суммирует sorted tokens, чтобы hash seed не менял floating ties;
- ожидаемые candidates и UNCHECKED check slots создаются до вызовов, поэтому
  исключение не удаляет denominator и уже полученные checks.

Ревью подтвердило: current response присутствует только в accusation document;
turn document не содержит собственный answer; actual tokenizer preflight
сохраняет answer целиком; labels/benchmark metadata не входят в модельный input.
Независимо запущены24 теста, пройдены. Автор дополнительно запустил28 тестов
до live фазы, включая4 tests инструмента предыдущего offline анализа.

После старта e6632db4 выявлены и исправлены локально, без изменения wire:

- resume завершённой inference должен повторять publication, если прежний push
  не удался; done-файл сам по себе не доказывает публикацию;
- scorer не должен превращать отсутствующий Qwen primary binary в0; сначала
  проверяется пригодность primary и явно обрабатывается None;
- score receipt получает hashes scorer/runs/reviewer records/gold и явные
  precision/recall. Frozen original score сохраняется, reviewed re-score будет
  отдельным файлом с проверкой неизменности исходных чисел на этих входах.

Добавлен regression test для None→0; локально **29 passed**. Эти дополнительные
правки не изменяют witness selector, native prompt, model/settings, порядок
запросов или acceptance threshold. Их не выдаём за улучшение model quality.
# Отдельный v5 question-only review

Независимый агент проверил точное сохранение DOCUMENT/ANSWER/settings, source address последнего USER, отсутствие gold в запросе, tokenizer preflight, все46 IDs и technical denominators. Блокирующих дефектов не найдено; по замечанию добавлены hashes scoring helpers и binary gold hash. Сводный локальный запуск новых и связанных тестов:31 passed. Это code review, не независимая разметка причин и не model quality validation.

