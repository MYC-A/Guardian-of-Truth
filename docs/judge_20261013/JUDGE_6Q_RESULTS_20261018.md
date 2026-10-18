# Полная 6q mean_z сборка — 18.10.2026

## Артефакт

Собран полный ZIP решения: `guardian-judge-qwen36-awq-6q-meanz-e546cef9-20261018.zip` — веса Qwen + offline Linux runtime + predict.py.
Локальный путь: `A:/Guardian-submissions/guardian-judge-qwen36-awq-6q-meanz-e546cef9-20261018.zip`.
Размер: 30,677,896,014 байт (30.678 GB), строго меньше 40 000 000 000 байт.
SHA256: `276f5cc069a232cbc335751cc21d8af501a6123a3b8b9029a926ff46fb263fdd`.
Код архива: [`e546cef9aa5908c3cadbb7fbd636a860e588a240`](https://github.com/MYC-A/Guardian-of-Truth/commit/e546cef9aa5908c3cadbb7fbd636a860e588a240).
Публикация: [judge-single-pass-20261013](https://github.com/MYC-A/Guardian-of-Truth/tree/judge-single-pass-20261013), без force-push/main.

Это новый 6q-профиль с реально выбранным агрегатором, а не collection-only профиль с aggregate=primary.
Предыдущая blind-сборка сохранена. Неизменный балл прошлой платформенной попытки сообщён пользователем;
логи/построчные решения отсутствуют. Глобальный overall fallback остаётся гипотезой причины.

## IMPLEMENTED

- Opt-in `submission/JUDGE_6Q_SUBMISSION.json`: legacy, review=off, шесть текущих вопросов @on,
  aggregate=mean_z и все шесть aggregate_keys; chunk=16, extras_schedule=per_chunk.
- Один построенный контекст/ответ/cap для всех вопросов строки; меняется финальный вопрос.
  Один scoring-токен, T=1.0, exact finite log P(YES)-log P(NO), один загруженный vllm.LLM.
- mean_z: стандартизация каждого вопроса по всем primary-оценённым строкам входа,
  population std (нулевая заменяется 1), равное среднее шести z-scores. Gold не используется.
  Никаких новых вопросов, обученных коэффициентов, blind, OR, shuffle или result cache.
- Primary durable до extras; фактический SHA256 и статус exact/inexact/missing/error каждого extra сохранён.
  Ошибка разбора одного extra не уничтожает primary/остальные extra; регрессия воспроизведена тестом.
- Сохранены .30, hard override, полный бинарный output и literal/duplicate id.
  Production defaults репозитория не переключены; упаковщик выбирает профиль явно и пишет provenance.
- `primary(aggregate_incomplete)` сохранён глобально: если любой primary-scored строке не хватает
  хотя бы одного точного ключа, весь рейтинг возвращается к overall. Строки без primary имеют прежний
  технический fallback. Разные шкалы по строкам не смешиваются.

## MEASURED — технические проверки

- [Linux CI](https://github.com/MYC-A/Guardian-of-Truth/actions/runs/39086700152), реальный pinned encoder, Python 3.12:
  **237/237 passed, 0 skipped**, тестовое время 33.432 с (не время inference).
- Локальный Windows стенд с существующим venv/энкодером: 237 тестов, 4 POSIX-only skipped,
  47.124 с. Изначальный запуск из другого Python без нужного окружения не использован как доказательство;
  повтор выполнен в существующем u2-build-venv с реальным локальным энкодером.
- Настоящий Qwen tokenizer на valid46: 46 строк, 2 trimmed,
  резерв вопроса 57 токенов, cap 49093, max фактического input 47999
  при окне 49152. Все 276 вариантов помещаются. Это техническая регрессия, не выбор
  агрегатора/порога и не качество. Input SHA256: `8e730cc999a6cf07c3f17f273300a17ce16539c5b6166885e74b41e93cfc47ba`.
- Независимый harness из КОДА КОНЕЧНОГО ZIP: настоящий predict -> supervisor -> judge_stage ->
  scoring contract -> mean_z -> бинарный Parquet. Только модель заменена fake-vLLM.
  Полный случай: 10 primary + 50 extras, aggregate=mean_z, labels=[0, 0, 0, 0, 0, 0, 0, 1, 1, 1].
  Одна inexact extra: aggregate=primary(aggregate_incomplete), lacking=1,
  labels=[1, 1, 1, 0, 0, 0, 0, 0, 0, 0]. Проверены gold isolation, Unicode LF-only, duplicate/literal id,
  чтение durable primary перед extras. Это искусственные оценки для проверки wiring, НЕ TP/FP/F1.
- Отдельный harness отказа модели сохраняет полный output из четырёх строк.
  Windows harness обходит Linux bootstrap и подменяет POSIX process cleanup;
  исполнение самого bundled Linux Python/GPU этим не доказано. POSIX-регрессии прошли Linux CI.
- Все 52636 файлов конечного ZIP сверены builder по size/SHA256/mode.
  Независимо проверены полный ZIP SHA256, paths/duplicates/manifest/config и runtime import closure.
  52224 runtime-файлов совпадают с закреплённым исходным архивом;
  ELF x86_64, executable bits, private loader/offline flags, toolchain/dependency closure проверены.
- Модель cyankiwi/Qwen3.6-35B-A3B-AWQ-4bit, revision
  00fcea2d3bcf5389b518d4fc082e5590e0ba4844: все 21 файл сверен с pinned download receipt,
  6 safetensors-шардов и 95 427 tensor/index keys проверены. Новые веса не скачивались.
- Runtime metadata: {"vllm": "0.19.1", "torch": "2.10.0", "triton": "3.6.0", "transformers": "5.8.0", "flashinfer-python": "0.6.6", "flashinfer-cubin": "0.6.6", "pandas": "3.0.6", "pyarrow": "26.0.0", "jsonschema": "4.26.0", "pydantic": "2.14.0", "pyyaml": "6.0.3"}; bundled Python 3.12.3.

## EXPLORATORY / GPU_UNTESTED / NOT_EXECUTED

mean_z — заранее зафиксированная необученная эвристика. Полезность шести вопросов НЕ измерена;
возможны разбавление сильного overall и усиление слабых/коррелирующих сигналов. tool_use проверяет
сделанные вызовы, а не все пропуски обязанностей. Изменение меток на реальных данных не гарантировано.
Даже исправная полная 6q-оценка может выбрать тот же top-.30; при incomplete снова сработает overall.

Две ограниченные попытки настроенного SSH: guardian-vast-new timeout, guardian-vast refused.
GPU pilot, реальная exact coverage, cache counters/VRAM/скорость, grouped quality comparison,
F1/AUC/AP/P/R/confusion/CI и полный 1800-секундный timing НЕ ВЫПОЛНЕНЫ.
Data inventory/train/eval эксперимент исходного исследовательского handoff не подменяется
техническим valid46; он остаётся невыполненным в этом этапе упаковки. Данные не объявляются отсутствующими.

Сроки сохранены: stop new work 1380, kill stage 1530, watchdog 1680 с от predict.py;
1800 с снаружи включают холодный старт/установку. Наличие prefix cache не доказывает завершение extras.
Вердикт упаковки: **VERIFIED_ARCHIVE**. Вердикт качества/скорости: **INSUFFICIENT_EVIDENCE**.

## Воспроизведение

Из распакованного корня архива:

```bash
python scripts/predict.py --input INPUT.parquet --output OUTPUT.parquet
```

Сборка из worktree кода `e546cef9aa5908c3cadbb7fbd636a860e588a240` (пути к существующим весам/runtime заменить при необходимости):

```powershell
$env:PYTHONPATH='C:/Users/Igor/Guardian-judge-6q-20261018/src'
& 'A:/Guardian-submissions/cascade-build-20261011/u2-build-venv/Scripts/python.exe' scripts/build_judge_submission.py --source-zip A:/Guardian-submissions/guardian-judge-qwen36-awq-6540dc50UP1.zip --source-sha256 f54329f9c8fd7779fe31a66fdeca76f520de699c2969421355d29d45182c56c7 --model-dir A:/Guardian-weights/qwen36-awq --model-id cyankiwi/Qwen3.6-35B-A3B-AWQ-4bit --model-revision 00fcea2d3bcf5389b518d4fc082e5590e0ba4844 --judge-config submission/JUDGE_6Q_SUBMISSION.json --source-revision e546cef9aa5908c3cadbb7fbd636a860e588a240 --output NEW_FULL_6Q.zip
& 'A:/Guardian-submissions/cascade-build-20261011/u2-build-venv/Scripts/python.exe' scripts/check_judge_6q_profile.py --model A:/Guardian-weights/qwen36-awq --input C:/Users/Igor/Guardian-judge-ci-v3-20261014/valid.parquet --out TOKENIZER_CHECK.json
```

Фактический build-driver дополнительно проверяет identity/download receipt/все веса/индекс:
`A:/Guardian-submissions/cascade-build-20261011/build_6q_submission_20261018.py`.
Независимый inspector: `inspect_6q_submission_20261018.py`, harness: `sixq_archive_cpu_20261018.py`.
Исходный UP1 runtime архив SHA256 проверен перед копированием, его байты не менялись.
Полные SHA/config/tokenizer/CI/inspection квитанции находятся рядом с ZIP и в sixq_receipts_20261018.

Квитанции: [CI](sixq_receipts_20261018/CI.json),
[проверка архива](sixq_receipts_20261018/ARCHIVE_INSPECTION.json),
[реальный токенизатор](sixq_receipts_20261018/TOKENIZER.json),
[очистка места](sixq_receipts_20261018/STORAGE_CLEANUP.json).

По явному разрешению пользователя удалён только старый ZIP
`guardian-judge-qwen36-awq-u2dense-58dfeb01.zip` (31 152 068 851 байт), заменённый b758b199.
Сохранены b758b199, blind-eef11fc4, исходный UP1 runtime ZIP и существующие веса.
Удаление зафиксировано в JUDGE_6Q_STORAGE_CLEANUP_20261018.json.
