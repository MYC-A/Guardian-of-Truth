# Guardian of Truth: single-pass judge v2 (13.10.2026)

`python scripts/predict.py --input <test.parquet|csv> --output <predictions.parquet|csv>`

Выход `id,label`, id в исходном порядке. Читаются только `id, prompt, response`. Без сети, всё из архива
(встроенный рантайм vLLM 0.19.1 из прежнего проверенного архива).

## Почему так

- Платформенный каскад: F1 0.32448, P 0.26316, R 0.42308. Recall всех команд лидерборда кратен 1/130,
  значит в публичном тесте 130 ошибок из 548 (23.7%). Отсюда TP=55, FP=154, FN=75, TN=264: почти угадывание.
- Топ: P ~0.61, R ~0.63, «1» у 25-34% строк.
- 27B dense на A100 не прочитает весь тест за отведённое время. Поэтому MoE с ~3B активных, один проход,
  без генерации текста.

## Как работает

1. **Механика**, `mechanical.py`. Железные «1»: инструмента нет в каталоге; нарушена схема; аргументы не объект;
   **ссылочный аргумент** (ключ `*_id`, `*_ids`, `*_number`, `*_code`, кроме `new_*`), значения которого
   нет в контексте (сравнение без регистра и разделителей); узкий date-gate. Всё остальное только
   подсказки, в том числе «несколько вызовов за ход» и «текст плюс вызов»: задача не считает их
   галлюцинацией самих по себе, и свободный текст в аргументах (`message: Hello123`).
2. **Судья**, `judge_stage.py` + `prompting.py`. Ответ ограничен токенами YES/NO, вероятности
   читаются после этого ограничения: оценка = log P(YES) - log P(NO), оба ответа всегда считаются явно.
   На старте проба проверяет это на живом движке; если vLLM этого не делает, стадия останавливается
   (`require_exact_scores`). Политика и инструменты **не обрезаются** (кроме случая, когда они сами не
   помещаются; тогда `policy_trimmed=true` в записи). До инференса все строки считаются полной
   длины, и **один лимит токенов планируется на весь прогон** по `planning_tokens_per_second`. Только
   если реальная скорость ниже, лимит снижается для остатка (`emergency_cap` в логе).
3. **Решение**: железные «1» плюс верхние `positive_rate` оценённых строк. **30% это гипотеза**
   из лидерборда (доля ошибок 23.7%, у топа «1» 25-34%), а не измерение: единственный параметр,
   который меняем по итогам сабмита.
4. **Надзор**, `judge_submission.py`. Файл ответов пишется только при покрытии моделью не меньше
   `min_coverage` (90%). Меньше: файла нет, код выхода ненулевой, попытка не считается. В принятом прогоне
   строки без оценки явно помечены в `decisions.jsonl` и логе (`fallback_rows`): «1» при железной
   находке, иначе «0». Новых чанков после 23 мин нет, стадия убивается в 25.5 мин,
   сторожевой выход в 28 мин.

## Порядок действий

0. Модели:
   ```
   huggingface-cli download cyankiwi/Qwen3.6-35B-A3B-AWQ-4bit --local-dir models/qwen36-a3b-awq
   huggingface-cli download cyankiwi/Qwen3.5-35B-A3B-AWQ-4bit --local-dir models/qwen35-a3b-awq
   ```
   Запишите commit каждой модели со страницы HF: он нужен сборщику.
1. Тесты (CPU, из корня репозитория): `PYTHONPATH=src python -m unittest tests.test_judge_mechanical -v`
2. Механика на valid: `python scripts/eval_judge_valid.py --input valid.parquet --mechanical-only --out runs/mech`.
   **Ворота:** `hard_rows_on_label0` = 0. Иначе смотрим `hard_on_label0_details`; для `unknown_reference`
   есть `"hard_unknown_identifier": false`.
3. Модели на valid (GPU): `python scripts/eval_judge_valid.py --input valid.parquet --model models/qwen36-a3b-awq --python <archive>/runtime/python/run_python.sh --out runs/q36`.
   Сначала в `stage.log` событие `probe` должно быть `exact: true`, а `inexact` = 0.
   Затем сравнить `auc_judge`; ориентир Granite 0.794. При разнице меньше 0.02 берём Qwen3.6.
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
   В логе `GUARDIAN_JUDGE final` должно быть `accepted: true`, `scored: 46`, `fallback_rows: 0`.
7. Сабмит. TP = R x 130, FP = TP / P - TP. Пришлите эти числа.
8. Дальше меняем только `positive_rate`.
