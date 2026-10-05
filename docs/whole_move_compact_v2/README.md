# Общая проверка текущего хода: итоговый слой интеграции

Добавлен reusable [bridge.evaluate](../../experiments/whole_move_compact_v2/bridge.py):
он собирает исходный FULL packet, проверяет его через resolve, допускает ответ
baseline/compact reviewer и независимо проверяет **все текущие assistant calls**
по исходным объявлениям. Положительная required/type/enum находка даёт ERROR
даже при пропуске позднего вызова моделью. Underlying ответ/отказ сохраняется.

Runtime не содержит ID valid rows, словарей бизнес-инструментов, отраслевых
исключений или подстановок правил из gold. Имена и требования берутся из входа.
Поддерживаемая executable declaration grammar ограничена явными types/required/
enum и nesting. Неоднозначная/неподдержанная schema даёт GAP. Отсутствие tool
не обвиняет без явно заданной tool-universe closure; default — False.

## Проверенный прирост от generic mechanical guard

На тех же 6 исходных valid cases с теми же архивными FULL baseline ответами:

| Вариант | TP | FP | FN | TN | F1 |
|---|---:|---:|---:|---:|---:|
| BASELINE | 2 | 0 | 2 | 2 | 0.6667 |
| BASELINE + mechanical | 3 | 0 | 1 | 2 | 0.8571 |

Добавленный TP имеет исходное основание: 16 required fields отсутствуют в поздних
вызовах `airline__23::t10`. Это источник механически установленного нарушения
контракта аргументов, а не модельная догадка о consent. Два прежних baseline TP
сохраняют ошибочные объяснения; прирост не делает весь baseline source-correct.

Все 46 исходных строк проверены offline: 1 mechanical positive, 0 FP по gold;
остальные 45 не объявляются бизнес-корректными. Самостоятельный mechanical
classifier пропускает другие виды нарушений. В отдельных 12 старых наборах
предсказаний OR исправляет этот FN в 9 наборах; сильный U2_20k уже находил строку,
поэтому там прироста нет. Это не новый модельный F1 на46 и не скрытый тест.

Подтверждено **137 focused tests**, включая переименование инструментов/сущностей,
перестановку каталога, missing second call, source/actor corruption, исключения,
примитивные/nested types и сохранение ошибки модели при mechanical override.
Пример использования без HTTP:

```python
from experiments.whole_move_compact_v2.bridge import evaluate

result = evaluate(row, baseline_json_reply, interface="baseline")
```

Передавать надо ответ, соответствующий именно исходному row/request; транспортный
runner дополнительно проверяет wire/raw/model hashes. Буквальные цитаты и native
metadata, сформированные кодом, доказывают адресацию, не истинность интерпретации.

## Модельные фазы и сохранённые результаты

Богатая whole-move схема v1 не оправдалась: 6/6 real technical failures;
fresh12 F1 ухудшился 0.9231→0.8. [История и аудиты](../whole_move_v1/README.md)
сохранены, raw-ответы не переписывались.

Компактный v2 повторяет все 18 те же входы: 6 known real + 12 authored contrasts.
Новых baseline HTTP нет; точные ответы и hash-проверки переиспользуются.
Все 18 новых compact calls завершились: 101479 provider tokens, 0 retries,
0 transport failures и 0 неизвестных usage. Все ответы admitted: технические
ошибки копирования цитат устранены, но семантическое качество не улучшилось.
Это development follow-up,
joint schema+prompt change, не независимый hidden holdout.

| Cohort | Вариант | TP | FP | FN | TN | F1 | UNKNOWN | Technical |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| Known valid, 6 | BASELINE_CACHE | 2 | 0 | 2 | 2 | 0.6667 | 0 | 0 |
| Known valid, 6 | BASELINE + mechanical | 3 | 0 | 1 | 2 | 0.8571 | 0 | 0 |
| Known valid, 6 | COMPACT | 1 | 1 | 3 | 1 | 0.3333 | 3 | 0 |
| Known valid, 6 | COMPACT + mechanical | 1 | 1 | 3 | 1 | 0.3333 | 3 | 0 |
| Authored contrasts, 12 | BASELINE_CACHE | 6 | 1 | 0 | 5 | 0.9231 | 0 | 0 |
| Authored contrasts, 12 | BASELINE + mechanical | 6 | 1 | 0 | 5 | 0.9231 | 0 | 0 |
| Authored contrasts, 12 | COMPACT | 4 | 0 | 2 | 6 | 0.8000 | 6 | 0 |
| Authored contrasts, 12 | COMPACT + mechanical | 4 | 0 | 2 | 6 | 0.8000 | 6 | 0 |

UNKNOWN и технический отказ преобразуются в binary 0 с отдельным учётом.
Ни один исходный положительный cause не восстановлен новым reviewer на known6.
Его airline23 ERROR объясняется неверными условиями и инверсией FORBID polarity;
permissions FP содержит выдуманный текст, а retail FN сохраняет пропуск
взаимодействия двух операций над одной сущностью. Mechanical override в airline23
даёт правильное основание, но не меняет уже положительную COMPACT метку.

На authored contrasts исключение правильно снимает прежний FP; два новых FN
связаны с отсутствием повторной ссылки на собственный target внутри evidence,
несмотря на содержательные объяснения нарушения. Точный источник не доказывает
применимость нормы; обязательная повторная ссылка также не гарантирует её.
Замороженные admission/aggregation и raw не переписываются задним числом.

Рекомендованная интеграция этой работы — **существующий baseline + mechanical
guard**, с явным `interface="baseline"`. COMPACT и rich reviewer остаются
отрицательными исследовательскими результатами. Улучшение U2_20k от guard
не заявляется: в сохранённых предсказаниях эта строка уже была TP.

Обе новые модельные фазы вместе: **54 HTTP / 291102 provider tokens**.
[Аудит исходных случаев](VALID_CAUSE_AUDIT.md),
[аудит authored contrasts](FRESH_CAUSE_AUDIT.md),
[точные метрики](../../outputs/whole_move_compact_v2/model/summary.json).

Код до API: `e9eb4fb6`; frozen requests до API: `0c0c36a1`.
[Протокол](EXPERIMENT_PROTOCOL.md),
[baseline bridge replay](../../outputs/whole_move_compact_v2/baseline_bridge.json),
[code-only all46 diagnostic](../../outputs/whole_move_v1/all46_offline_summary.json).

Production, исходный valid/SYN gold и прежние frozen phases сохранены.
