# Повторная проверка NO_ERROR: что подготовлено и измерено

Ветка `research/modular-step2-4-20261002`. Продолжение
[oracle и source-scope аудита](MODULAR_ORACLE_AND_SCOPE_AUDIT_2026-10-02.md).

## Фиксированное правило

Дополнительная B проверяет первичный NO_ERROR, если есть хотя бы один
следующий source-признак:

1. Ответ инструмента нельзя однозначно связать с предшествующим вызовом.
2. У того же явно заданного tool/entity/path наблюдаются разные значения.
3. Policy содержит aware-ISO время и предшествующий result — aware-ISO время.

Это признаки для **проверки**, а не нарушения. Последовательное изменение
состояния может быть правильным; две даты могут относиться к разным условиям.
Код не решает эту семантику и не угадывает timezone.

Отдельный интерфейс sampled uncertainty принимает ровно3 valid same-input
judge-семпла: agreement<1 либо native judge-explanation contradiction≥0.5.
Target-reconstruction NLI не подставляется вместо judge NLI. Неполный банк,
другой source hash и отсутствие score дают UNAVAILABLE, не high confidence.
Новых семплов не генерировали; uncertainty-маршрутизация ещё не измерена.

Все пять признаков сохраняются отдельно для ablation. Объединение не
объявляется голосованием независимых моделей. Политики/домены/tool names/
case IDs не определяют ветвление алгоритма. Протокол записан до replay,
но **после просмотра dev-FN** — это подготовка на dev, не unseen победа.

## Реальный replay отбора

Router получил исходные dev-входы и уже сохранённые primary J, без gold.
Scorer позже отдельно прочитал только dev gold.

| Показатель | Source-adaptive | Случайный, та же доля |
|---|---:|---:|
| Первичных NO_ERROR | 19 | 19 |
| Дополнительных проверок | 6 | 6 |
| Выбран известных пропусков J | 1 | 1 |
| Выбрано авторских clean-входов | 5 | 5 |

Оба отбора включили `dev_inclusive_timezone::02`. Seed1729 и выбор по
content hash заморожены до scoring, не меняются из-за этого результата.
Дополнительная доля6/19=31.6%. Это не исправление FN: **B для этого
сравнения ещё не выполнялась**. На одном dev-пропуске преимущества над
случайным отбором не видно. Возникающие FP, UNKNOWN, latency и cost ещё
нужно измерить. Равная доля запросов не означает равного числа токенов.

## Следующий парный прогон готов

`negative_review_pilot.py` подготовил один frozen набор48 исходных dev
входов и четыре arms:

- `strict_positive`: source-bound-v2 B для ERROR/UNKNOWN;
- `strict_always`: та же B для всех;
- `strict_source_adaptive`: та же B дополнительно по source-признакам;
- `strict_matched_random`: та же B дополнительно для случайных6 NO_ERROR.

Это изоляция **routing**: все arms используют один и тот же сохранённый
primary J и один общий новый ответ B на идентичный query/input. Ответ B
журналируется до агрегации; получившие его arms ссылаются на общий record.
Семпл не выдаётся за четыре независимых голоса. Для29 positive первичных
ответов исходный helper восстановил все29 исходных findings.

Всего максимум48 уникальных B-запросов до technical reasks, максимум96
API attempts при одной reask на каждый. Shared actual ledger и cache
остаются обязательными. Per-arm cost для самостоятельного исполнения
показывается отдельно от реально единожды затраченного shared cost.
Стоимость старой первичной генерации не выдаётся за cold latency нового
сервиса; её повторное исполнение здесь не нужно для изоляции routing.

При INVALID B reviewed-arm получает UNKNOWN/degraded. Неотправленный
NO_ERROR сохраняет первичную модельную оценку; полнота его проверки не
сертифицируется. Sealed/default R0 не меняются. Этот frozen48 всё ещё
имеет исходный перекос Boolean-вариантов `a=false`.

Подготовка без inference:

```powershell
python experiments/searh_23/modular_steps_20261002/negative_review_pilot.py --root outputs/searh_23/modular_steps_20261002
```

Запуск на сервере из изолированного checkout после подтверждения отдельного
dev-бюджета:

```bash
/workspace/guardian/modular_venv/bin/python experiments/searh_23/modular_steps_20261002/negative_review_pilot.py --run
```

Runner не расширяет cap и не переключается на heldout-фазу. Он проверяет
hash primary archive/input/code/model, поддерживает resume shared-B и
per-arm journal, сохраняет BUDGET_STOP. Актуальный frozen manifest —
`negative_review_pilot_v4/selection.json`: source config входит в code hash;
полный raw B сохраняется до ограничений старого adapter. Первые две
подготовки не выполняли inference и были заменены до первого запроса.
V3 достиг BUDGET_STOP до обращения к провайдеру (done0/192), сохранив ledger
218 attempts/699667 tokens/pending0. Сравнение manifest между Windows и
Linux дополнительно нашло CRLF/LF различие в code fingerprint. V4
нормализует только Python newlines и JSON config; prompt/history/target
остаются отдельными неизменными exact hashes. V3 receipts сохранены.
Сырой результат и scorer остаются
раздельными. Алгоритм frozen не меняется после нового gold scoring.

## Проверки

16 regression-проверок прошли локально. Новые проверки удостоверяют:
missing/wrong-input/incomplete uncertainty не является уверенностью;
random-отбор сохраняет число и не зависит от ID или порядка строк;
INVALID дополнительная B не возвращает уверенный NO_ERROR; changing
payloads вызывают review без автоматического обвинения.

Сервисный профиль `modular-negative-adaptive-v1` подключён в экспериментальный
wrapper: strict R0 → source-only дополнительная B для первичного NO_ERROR.
Он пока не выбран победителем; готовность кода не означает quality gain.
API cap699667/700000 остаётся прежним, новый B-прогон не помещается.
Дополнительный dev-бюджет500000 токенов/150 attempts запрошен, ответа нет.
