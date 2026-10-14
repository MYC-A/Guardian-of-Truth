# Guardian of Truth: single-pass judge v3 (14.10.2026)

`python scripts/predict.py --input <test.parquet|csv> --output <predictions.parquet|csv>`

Выход `id,label`, id в исходном порядке. Читаются только `id, prompt, response`. Без сети, всё из архива
(встроенный рантайм vLLM 0.19.1 из прежнего проверенного архива). Почему именно так и что дальше: [STRATEGY.md](STRATEGY.md).

## Что изменилось в v3 (замечания ревью)

1. **Проверка ссылок теперь подсказка.** Аргумент `*_id/_ids/_number/_code`, значения которого нет в контексте,
   больше не ставит «1»: имя поля не отличает ссылку на существующую сущность от создания новой
   (`create_coupon code=SUMMER99`). Судья видит подсказку с обоими прочтениями. Жёсткий режим остался для экспериментов:
   `"hard_unknown_identifier": true`.
2. **Политика не теряется, если помещается.** Фиксированного резерва в 3000 символов под диалог больше нет.
   Порядок уступок: диалог (до нуля, дольше всего живут конец и строки с id из ответа) -> подсказки ->
   проверяемый ответ (голова + хвост, не меньше 4000 символов) -> и только потом сама политика
   (`policy_trimmed=true`). Раньше при превышении резался весь промпт целиком. Заодно исправлено: при
   нулевом бюджете `rest[-0:]` возвращал весь диалог; обрезка по первой новой строке могла съесть короткий
   хвост целиком.
3. **Ответ есть всегда.** Сразу после механики пишется базовый файл (железные находки -> 1, остальное 0),
   дальше он переписывается по мере прихода оценок. Низкое покрытие больше не блокирует файл: в логе
   событие `JUDGE_COVERAGE_LOW` и `coverage_low=true` в `final`. Стадия, которая не стартовала или упала,
   оставляет механический ответ (`stage_error` в логе). Код выхода 0. Старый ключ `min_coverage`
   читается как `coverage_warning`.

## Как работает

1. **Механика**, `mechanical.py`. Железные «1»: инструмента нет в полном каталоге; нарушена схема;
   аргументы не объект; узкий date-gate. Всё остальное подсказки судье.
2. **Судья**, `judge_stage.py` + `prompting.py`. Один проход, ответ ограничен токенами YES/NO,
   оценка = log P(YES) - log P(NO) после ограничения. Проба на старте проверяет точность (`require_exact_scores`).
   Один лимит токенов планируется на весь прогон; `emergency_cap` только при нехватке скорости.
3. **Решение**: железные «1» плюс верхние `positive_rate` оценённых строк. 30% это гипотеза из
   лидерборда, а не измерение. Правило для F1: строку выгодно помечать «1», когда P(ошибка) > F1/2.
4. **Надзор**, `judge_submission.py`. Файл с первых секунд; строки без оценки явно помечены
   в `decisions.jsonl` (`hard` / `model` / `fallback_zero`). Новых чанков после 23 мин нет, стадия убивается
   в 25.5 мин, сторожевой выход в 28 мин.

## Порядок действий

0. Модели:
   ```
   huggingface-cli download cyankiwi/Qwen3.6-35B-A3B-AWQ-4bit --local-dir models/qwen36-a3b-awq
   huggingface-cli download cyankiwi/Qwen3.5-35B-A3B-AWQ-4bit --local-dir models/qwen35-a3b-awq
   ```
   Запишите commit каждой модели со страницы HF: он нужен сборщику.
1. Тесты (CPU, из корня): `PYTHONPATH=src python -m unittest tests.test_judge_mechanical -v`
2. Механика на valid: `python scripts/eval_judge_valid.py --input valid.parquet --mechanical-only --out runs/mech`.
   **Ворота:** `hard_rows_on_label0` = 0; иначе смотрим `hard_on_label0_details`. На 46 строках это
   необходимое, но не достаточное условие (см. STRATEGY.md).
3. Модели на valid (GPU): `python scripts/eval_judge_valid.py --input valid.parquet --model models/qwen36-a3b-awq --python <archive>/runtime/python/run_python.sh --out runs/q36`.
   В `stage.log` событие `probe` должно быть `exact: true`, `inexact` = 0. Сравнивать `auc_judge`.
4. Скорость: `... --timing-rows 560 --seconds 1380 --out runs/timing`.
   Из `stage_done.tokens_per_second` впишите ~90% в `planning_tokens_per_second` и повторите замер.
   **Ворота:** `scored` = 560, `stage_done.emergency_caps` = 0, `policy_trimmed` = 0, `total_wall_seconds` < 1400.
5. Сборка ZIP:
   ```
   python scripts/build_judge_submission.py --source-zip <full.zip> --source-sha256 <sha> \
       --model-dir models/qwen36-a3b-awq --model-id cyankiwi/Qwen3.6-35B-A3B-AWQ-4bit \
       --model-revision <commit> --output judge-q36.zip
   ```
6. Сквозная проверка архива: распаковать, `pip install .`, `python scripts/predict.py --input valid.parquet --output /tmp/p.parquet`.
   В `GUARDIAN_JUDGE final`: `coverage_low: false`, `scored: 46`, `fallback_rows: 0`, `stage_error: null`.
   Если `coverage_low: true`, файл всё равно есть, но сабмитить такой архив нельзя: сначала причина.
7. Сабмит. TP = R x 130, FP = TP / P - TP. Пришлите эти числа и строку `final` из лога.
8. Дальше меняем только `positive_rate`.
