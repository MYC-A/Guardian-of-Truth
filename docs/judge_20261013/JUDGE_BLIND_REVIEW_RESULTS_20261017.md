# Blind review: исправление пакета и CPU-проверка — 17.10.2026

Итог инженерной проверки: найденные блокирующие дефекты исправлены, доступные
CPU-проверки проходят. Итог качества/конкурсной готовности: INSUFFICIENT_EVIDENCE.
GPU F1, скорость, APC и полный конкурсный runtime этим результатом не подтверждены.

Base: 6f0e990ef8d851cba52c6c34e80f5e66a2e48901,
ветка происхождения judge-single-pass-20261013. Локальная рабочая ветка исправлений:
fix/blind-review-package-20261017. Полный source commit указан в PACKAGE_MANIFEST.json
выпускаемого пакета. Исходный пакет v2: SHA256
5ca6ab5c4ef343789c5bf908455a180321b802c94aeaba14cbf012a619f03d5c.

## IMPLEMENTED

- Opt-in A/off, B/none, C/open, D/blind, одна загрузка модели, текущий exact scoring.
- Все primary durable до review. Ошибка prepass/final сохраняет primary.
- Сохранение фактических primary inputs в run-local spool с offsets вместо больших
  строк в RAM, fsync и проверкой run/input/position/row/model-input/token SHA.
- Final использует сохранённый первичный input, включая реальное сокращение/cap/hints.
  Повторной сборки/сокращения ради notes нет. Notes не помещаются → DROPPED_SIZE;
  checklist не помещается → явная ошибка строки и global primary fallback.
- Ошибки malformed sample, parse_notes, answer_score и non-finite score изолированы
  по строкам. Invalid/inexact не подменяются модельным NO.
- Исправлены бесконечное разбиение >400 ролевых блоков, обработка omission units,
  выбор effective рейтинга eval и чтение review/Unicode LF-only в analysis.
- Primary/final и диагностические метрики разделены. AP и наблюдаемая F1/P/R/confusion
  при production .30, paired grouped ΔF1 и ΔAUC CI; автоматический promote отключён
  до проверки независимости, покрытия, notes delivery и runtime. Старое допущение
  prevalence 130/548 не используется для новых метрик. In-sample threshold opt-in.
- Хэши реальных контекстов контролируются внутри строки и между arms. Несовпадение
  блокирует matched-анализ. Отсутствие хэшей явно отмечается в coverage.
- Дубли final не принимаются за однозначную оценку. Неполный final → primary для
  всего набора. Literal/duplicate id и полный бинарный Parquet output сохраняются.
- Исправлены ожидания старых tests и проверки упаковки; workflow расширен новыми
  тестами, прежние encoder/CPU-проверки сохранены.
- Пакет снабжён точным patch, полными изменёнными исходниками, base/source SHA,
  SHA256-манифестом и installer с предварительными проверками без перезаписи чужой работы.

Production JUDGE_CONFIG.json, hard-правила и вопросы judge-6q не изменены.

## MEASURED — только CPU/проводка

Windows Python 3.13.7; существующий локальный multilingual MiniLM encoder с закреплённой
revision e8f8c211226b894fcb81acc59f3b34ba3efd5f42. Библиотеки вслепую не обновлялись.

Полный набор на момент запуска: 233 tests, 229 passed, 4 skipped, 0 failures/errors,
43.57 секунд. После добавления ещё одной регрессии final/base mismatch она отдельно
прошла: суммарно 234 различных tests, 230 passed, 4 skipped. Повторные запуски одних
тестов не учитываются как новые проверки. Все пять real-encoder tests выполнены.

Четыре skips требуют POSIX process groups: существующие supervisor/process cleanup
и refresh проверки. На Windows новый integration test исполняет реальные supervisor,
stage, preparation, readers, writer и Parquet, но заменяет process transport и vLLM.
Это не доказательство Linux cleanup или GPU-производительности.

Дополнительный аудит сравнил A/off с исходным judge_stage из base-коммита:
последовательность model inputs совпала на той же фикстуре. A/B/C/D прошли настоящий
stage на трёх строках; D/C выдали по 3 prepass и 3 exact final, B — 3 final.
Проверены gold isolation, malformed outputs, сохранение primary и global fallback.
Все числа fake-vLLM — технические фикстуры, не метрики качества Qwen.

Runtime import closure включает blind_review.py и review_stage.py. Минимальные fixture
ZIP tests проверяют их присутствие в архиве. Существующий конкурсный ZIP не менялся.

Машинный receipt и команда: BLIND_REVIEW_CPU_TESTS_20261017.json и
README_BLIND_REVIEW.md. В пакете также сохраняются полный лог и дополнительный audit.

## EXPLORATORY / GPU_UNTESTED / NOT_EXECUTED

Это исправление инженерного пакета, а не выполненный quality-эксперимент.
Новые quality-результаты не просматривались и не использовались для выбора промптов.
GPU pilot, три полных повтора A/B/C/D, production timing и измерение cache counters
NOT_EXECUTED. F1/AP/AUC/TP/FP/FN/TN для реальной Qwen не приводятся.
Данные не объявляются отсутствующими: их inventory, provenance, дедупликация, группы,
split manifests и независимость в этом исправлении не выполнялись. valid46 не использован
для обучения/выбора. При просмотренных данных будущий прогон помечается EXPLORATORY.
Linux CI не запускался; приложен полный workflow diff с реальным encoder.

Выдача этого ZIP означает проверенный пакет кода для дальнейшего эксперимента.
Она не означает ACCEPT нового алгоритма или готовность конкурсного сабмита.
