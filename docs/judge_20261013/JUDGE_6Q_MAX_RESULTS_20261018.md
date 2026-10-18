# 6q MAX: доступные оценки без глобального отката — 18.10.2026

## Полный архив

`guardian-judge-qwen36-awq-6q-max-20d3c110-20261018.zip`: веса + offline Linux runtime + scripts/predict.py.
Путь: `A:/Guardian-submissions/guardian-judge-qwen36-awq-6q-max-20d3c110-20261018.zip`.
Размер: 30,677,896,656 байт (30.678 GB), строго меньше 40 000 000 000 байт.
SHA256: `41b3f350e15e68fa5eed7e7aae5e004bcff203feed8e9bbe22da2815a50b9fbe`.
Код: [`20d3c110f3233b8d447f7380ac6abc0d04034b48`](https://github.com/MYC-A/Guardian-of-Truth/commit/20d3c110f3233b8d447f7380ac6abc0d04034b48).
Ветка публикации: judge-single-pass-20261013, без force-push/main.

Пользователь отверг потерю полезных дополнительных оценок при неполном покрытии.
Новый профиль явно отменяет глобальный completeness gate. Предложение использовать
только полностью завершённые вопросы также отвергнуто и НЕ входит в эту сборку.

## IMPLEMENTED

- `submission/JUDGE_6Q_MAX.json`: legacy, шесть прежних вопросов @on, review=off,
  aggregate=max_logit, chunk16, per_chunk. Один Qwen3.6 AWQ, exact one-token log-odds,
  T=1.0. Контекст/ответ/cap строки одинаковы, меняется только финальный вопрос.
- Для каждой строки применяется ОДНА функция: максимум доступных finite exact
  scores из overall/values/actions/tool_use/policy/refusal. Отрицательный ответ
  другого вопроса не уменьшает больший score. Нет полной матрицы — используются
  полученные элементы. Нет полного вопроса — полученные оценки отдельных строк
  всё равно используются. Missing/error/inexact/bounded не являются нулём или NO.
- Если доступен только overall, максимум равен overall. Если вообще нет точной
  оценки, остаётся технический/mechanical fallback с полным бинарным output.
  Отдельный глобальный fallback в overall для max_logit отсутствует.
- Сохраняются .30 quota, hard override и literal/duplicate id. Положительный
  model score не принуждает label=1: положительные метки выбираются по ранжированию.
- Primary durable перед extras, существующие deadline guards/row isolation,
  статусы и фактические prompt SHA. Уже записанные оценки сохраняются при позднем
  сбое. Дополнительные попытки при техническом отказе primary не добавлялись;
  существующий stage прежде всего обслуживает primary-scored строки.
- MAX требует exact scoring; reader исключает inexact primary и bounded extras,
  max повторно проверяет finite значения, отрицательный-only максимум остаётся
  отрицательным. ranked_rows/ranked_coverage/fallback/source отражают реальный
  рейтинг, отдельно от primary coverage. Eval использует тот же агрегатор.
- Старые production/strict mean_z/blind profiles сохранены. Никаких новых моделей,
  вопросов, LoRA, blind, shuffle, нормализатора, обучаемых весов или result cache.

## MEASURED — технические проверки

- [Linux CI](https://github.com/MYC-A/Guardian-of-Truth/actions/runs/39089149283): **244/244 passed, 0 skipped**, Python3.12,
  реальный pinned encoder, 33.753 с тестов (не model runtime).
- Windows существующий venv/реальный локальный encoder: 244 tests, 4 POSIX skipped,
  23.009 с. POSIX-проверки выполнены Linux CI.
- Qwen tokenizer, valid46 только для технических регрессий: 46 строк / 276 inputs,
  2 trimmed, question reserve 57, cap 49093,
  max фактических tokens 47999 при окне 49152.
  Input SHA256: `8e730cc999a6cf07c3f17f273300a17ce16539c5b6166885e74b41e93cfc47ba`. Метки не читались для выбора правила.
- Сквозной harness из конечного ZIP: реальный predict -> supervisor -> judge_stage
  -> exact scoring contract -> MAX -> Parquet. Только модель заменена fake-vLLM.
  10 primary + 50 extras на случай, четыре заранее заданных случая:
  * полные оценки: labels=[0, 0, 0, 0, 0, 0, 0, 1, 1, 1];
  * одна inexact extra: labels=[0, 0, 0, 0, 0, 0, 0, 1, 1, 1] — нет отката;
  * values доступен только одной строке, policy только двум, остальные extra
    недоступны: labels=[1, 1, 0, 0, 0, 0, 0, 0, 0, 1];
  * вообще нет exact extra: labels=[1, 1, 1, 0, 0, 0, 0, 0, 0, 0].
  Во всех случаях aggregate=max_logit. Sparse case меняет реальные выходные метки
  относительно primary-only, без требования полного вопроса/набора строк.
  Это искусственные scores для wiring, не F1/TP/FP качества модели.
- Проверены gold isolation, literal/duplicate id, Unicode внутри JSONL, чтение
  durable primary перед extras; отдельный engine-failure harness сохраняет output.
  Windows harness обходит Linux bootstrap и заменяет POSIX cleanup; исполнение
  bundled Linux runtime/GPU им не доказано.
- Все 52636 файлов ZIP сверены builder по size/SHA256/mode;
  независимая проверка полного SHA256, путей, дубликатов, manifest/config/README,
  исходников и import closure. 52224 runtime-файлов совпадают
  с закреплённым UP1 runtime; ELF x86_64, executable modes, private loader/offline,
  toolchain и dependency closure проверены.
- Qwen cyankiwi/Qwen3.6-35B-A3B-AWQ-4bit, revision
  00fcea2d3bcf5389b518d4fc082e5590e0ba4844. Все 21 файл сверены с pinned receipt,
  6 safetensors-шардов / 95 427 tensor index keys проверены. Весов не скачивали.
- Runtime metadata: {"vllm": "0.19.1", "torch": "2.10.0", "triton": "3.6.0", "transformers": "5.8.0", "flashinfer-python": "0.6.6", "flashinfer-cubin": "0.6.6", "pandas": "3.0.6", "pyarrow": "26.0.0", "jsonschema": "4.26.0", "pydantic": "2.14.0", "pyyaml": "6.0.3"}; Python3.12.3.

## EXPLORATORY / GPU_UNTESTED / NOT_EXECUTED

MAX — необученная эвристика. Разные вопросы имеют непроверенную калибровку.
Один ложноположительный высокий score может доминировать; больше доступных
вопросов означает больше возможностей получить экстремальную ошибку. Partial
coverage может зависеть от длины/порядка/дедлайна. Это риски качества, а не
доказательство, что максимум лучше mean_z или overall. Высокий YES — модельная
оценка, не подтверждённая источниками истина. tool_use не охватывает все пропуски.

GPU/независимые quality metrics/F1/AUC/AP/CI, реальная coverage/cache/VRAM и полный
1800-second timing НЕ ВЫПОЛНЕНЫ. Ранее в этой сессии два настроенных SSH endpoint
дали timeout/refused; повторные бесконечные подключения не выполнялись. Data
inventory/train/eval исходного research handoff не подменяется valid46: он не
выполнен в этом этапе упаковки. Наличие исходных данных не отрицается.
Если extras не успеют начаться или top-.30 останется тем же, платформенный балл
может совпасть с прошлым. Новый код устраняет потерю уже полученных сигналов,
но не гарантирует их появление или улучшение F1.

Stop1380/kill1530/watchdog1680 от predict сохранены;1800 снаружи включает старт.
Технический вердикт: VERIFIED_ARCHIVE. Качество/скорость: INSUFFICIENT_EVIDENCE.

## Воспроизведение и файлы

```bash
python scripts/predict.py --input INPUT.parquet --output OUTPUT.parquet
```

Из worktree `20d3c110f3233b8d447f7380ac6abc0d04034b48`:

```powershell
$env:PYTHONPATH='C:/Users/Igor/Guardian-judge-6q-max-20261018/src'
& 'A:/Guardian-submissions/cascade-build-20261011/u2-build-venv/Scripts/python.exe' scripts/build_judge_submission.py --source-zip A:/Guardian-submissions/guardian-judge-qwen36-awq-6540dc50UP1.zip --source-sha256 f54329f9c8fd7779fe31a66fdeca76f520de699c2969421355d29d45182c56c7 --model-dir A:/Guardian-weights/qwen36-awq --model-id cyankiwi/Qwen3.6-35B-A3B-AWQ-4bit --model-revision 00fcea2d3bcf5389b518d4fc082e5590e0ba4844 --judge-config submission/JUDGE_6Q_MAX.json --source-revision 20d3c110f3233b8d447f7380ac6abc0d04034b48 --output NEW_FULL_MAX.zip
& 'A:/Guardian-submissions/cascade-build-20261011/u2-build-venv/Scripts/python.exe' scripts/check_judge_6q_profile.py --config submission/JUDGE_6Q_MAX.json --model A:/Guardian-weights/qwen36-awq --input C:/Users/Igor/Guardian-judge-ci-v3-20261014/valid.parquet --out TOKENIZER_CHECK.json
```

Фактические local drivers: build_max_submission_20261018.py (дополнительная
сверка pinned весов), inspect_max_submission_20261018.py, max_archive_cpu_20261018.py
в A:/Guardian-submissions/cascade-build-20261011. Квитанции в sixq_max_receipts_20261018
и рядом с ZIP. Основной diff: decision.py/max_logit, judge_submission.py/readers/
effective ranking/coverage, eval_judge_valid.py, config/builder/checker/docs/tests.
Новый supervisor/движок scoring не создавался; runtime и production defaults не обновлялись.

По действующему разрешению удалить старые ZIP удалён заменяемый
guardian-judge-qwen36-awq-6q-meanz-e546cef9-20261018.zip; его квитанции сохранены.
Blind-eef11fc4, b758b199, исходный UP1 runtime и модельные веса сохранены.
Новый архив не отправлялся на платформу автоматически.

Квитанции: [CI](sixq_max_receipts_20261018/CI.json),
[проверка архива](sixq_max_receipts_20261018/ARCHIVE_INSPECTION.json),
[токенизатор](sixq_max_receipts_20261018/TOKENIZER.json),
[удаление заменённого ZIP](sixq_max_receipts_20261018/STORAGE_CLEANUP.json).
