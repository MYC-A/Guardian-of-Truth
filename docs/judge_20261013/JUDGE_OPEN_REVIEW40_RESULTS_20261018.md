# Open review + MAX .40 — результат сборки 18.10.2026

## Артефакт

Полное решение: `guardian-judge-qwen36-awq-open-review40-max-34fb1c75-20261018.zip` — веса, offline Linux runtime и predict.py.
Размер: 30,677,902,087 байт, строго меньше 40 000 000 000.
SHA256: `b26fc6c7f92b9a0390289c815f0432c23a1c72d41fef4005538bbb82fc87b54d`.
Код: [`34fb1c750ceec4799f611b6d941c1dafef7ee829`](https://github.com/MYC-A/Guardian-of-Truth/commit/34fb1c750ceec4799f611b6d941c1dafef7ee829).
Ветка: judge-single-pass-20261013, без force-push и без изменения main.

## IMPLEMENTED

Профиль submission/JUDGE_OPEN_REVIEW40.json: open / answer_audit / per_chunk /
max_exact / positive_rate=.40. В каждой порции: durable overall → короткий
разбор текущего ответа с фактами, правилами, исключениями и counterevidence →
валидация структуры/ссылок → exact final с исходником и MODEL_HYPOTHESIS.
Одна загрузка Qwen/vLLM, три основных вызова на строку, если review допускает бюджет.
Ошибки и существующие технические повторы могут добавить запросы.

Пользователь отверг замену/глобальный откат полезных оценок и потребовал MAX как
в 6q. Для каждой строки: максимум доступных finite exact overall/final log-odds.
Низкий final не уменьшает overall, низкий overall не стирает final. Один missing,
inexact или duplicate final не отменяет результаты других строк. Final-only
строка также участвует. Недостающая оценка не считается нулём или модельным NO.
Hard override и учёт квоты среди scored rows сохранены. Если обеих оценок нет,
сохраняется существующий явный технический/mechanical бинарный fallback.

Это не шесть вопросов и не blind: предварительный разбор видит текущий response.
Сырые overall/final не усредняются; percentile replacement не входит в код.
MAX не может исправить высокий overall FP понижением его score, хотя изменение
рейтинга других строк может изменить итоговую метку. Сопоставимость шкал промптов
не измерена; один завышенный score может доминировать.

Review идёт между primary-порциями с резервом на оставшиеся primary; отложенные
порции могут выполняться после primary. Admission использует actual input token
counts и reserved output tokens, наблюдённые tokens/wall отдельных стадий; до
измерений действует явно эвристический prior3x primary wall с поправкой на длину.
APC не считается бесплатным. Это не доказательство прохождения GPU deadline.

Вход audit/final строится из saved actual primary context с проверкой SHA, без
baseline score/gold. До подготовки primary зарезервированы 2048 токенов. Notes
не вытесняют исходник: при превышении allowance/cap они исключаются с причиной.
Адреса относятся к фактически показанному user input; цитаты извлекаются кодом.
Валидная ссылка не доказывает entity binding или применимость нормы.

Generation384, T0, top_p1, seed0, thinking off, без YES/NO restriction. Scoring1token
T1/seed0, прежние answer_ids/answer_score/exact probe. Invalid/truncated audit
не доставляется; final может оценить источник без notes, что отдельно отмечается.
Сохраняются raw/parsed status, delivery, exactness, input/token SHA, tokens/wall,
доступность cache counters, final_scores/review_wins и действительный источник рейтинга.

Qwen cyankiwi/Qwen3.6-35B-A3B-AWQ-4bit, revision
00fcea2d3bcf5389b518d4fc082e5590e0ba4844; прежний runtime Python3.12.3,
vLLM0.19.1/Torch2.10.0+cu128/Triton3.6.0/Transformers5.8.0. Окно49152,
seq64, batchedtokens16384, memory.90, APC/chunked-prefill, chunk16.
Stop1380/kill1530/watchdog1680 от predict, внешний лимит1800 не изменены.
Нет result cache, server, новых моделей/весов/LoRA или переключения production defaults.

## MEASURED — техническая проверка

- [Linux CI](https://github.com/MYC-A/Guardian-of-Truth/actions/runs/39101111396): **254/254, 0 skips**, 29.223с тестов,
  Python3.12, настоящий pinned encoder. Это не время работы модели.
- Windows существующий venv/настоящий encoder: 254 tests, 250 passed, 4 POSIX skips,
  22.616с. Все POSIX-проверки прошли Linux CI.
- Реальный Qwen tokenizer, valid46 только техническая регрессия: 46 строк,
  primary cap=47096; audit max=47225, generation reserve384;
  final без notes max=46459; trimmed=2,
  policy_trimmed=0, response_trimmed=0.
  Input SHA `8e730cc999a6cf07c3f17f273300a17ce16539c5b6166885e74b41e93cfc47ba`. Gold не использован для выбора кандидата.
- Полный ZIP: 52637 членов, проверены каждый размер/SHA/права;
  независимый повторный SHA256 всего ZIP совпал. 52224 runtime
  members идентичны UP1 source (source ZIP SHA f54329f9c8fd7779fe31a66fdeca76f520de699c2969421355d29d45182c56c7).
  Сохранены ELF x86_64/private loader/offline flags/права исполнения; проверены
  import closure без research-зависимостей и точные config/code/README из pinned commit.
- Все21 файла модели проверены по закреплённому download manifest, все6 safetensors
  шардов и95427 tensor-index keys. Новые веса не загружались.
- Извлечённый predict → supervisor → stage → MAX .40 → Parquet, fake model only:
  полные final=20/20; low-final не подавляет overall;
  partial=1/20 использует единственный final;
  no-final сохраняет overall; bad-notes доставляет0 notes, но final scores остаются
  явно отдельно; primary_error допускает final-only строку. Во всех случаях
  aggregate=max_exact_overall_final, полный id/label output, literal/duplicate IDs,
  Unicode LF-only и gold isolation. Bootstrap/POSIX transport заменены только
  для Windows harness. Fake scores не являются F1, реальной delivery или GPU скоростью.

## EXPLORATORY / GPU_UNTESTED / NOT_EXECUTED

Прежний 6q MAX .30: пользователь сообщил F1 .45578 / P .40854 / R .51538;
это не результат нового кандидата. Платформенные логи недоступны, фактические
coverage/trim/cache/runtime предыдущей отправки неизвестны. Одинаковый старый
балл не доказал ни бесполезность blind, ни конкретную причину fallback.

Новый вариант одновременно меняет review, расписание, агрегацию и квоту.
Платформенная разница не изолирует вклад каждого. Независимый quality-run,
инвентаризация/разбиение новых данных, grouped CI, AUC/AP, фактические F1/P/R,
notes delivery/truncation, peak VRAM, cache counters и whole-pipeline GPU timing
для этого кандидата NOT_EXECUTED. Данные не объявляются отсутствующими.
Настроенные GPU SSH ранее дали timeout/refused; новых бесконечных попыток нет.
CPU/CI/ZIP-проверка не доказывает конкурсную готовность, throughput или gain.
Вердикт качества: **INSUFFICIENT_EVIDENCE**. Статус: **GPU_UNTESTED**.

## Воспроизведение

Закрепить PYTHONPATH на src активной копии и checkout полного CODE SHA выше.
Linux CPU CI команда сохранена в .github/workflows/judge-transcript-checks.yml.

```powershell
$env:PYTHONPATH='C:\Users\Igor\Guardian-judge-open-review40-20261018\src;C:\Users\Igor\Guardian-judge-open-review40-20261018'
$py='A:\Guardian-submissions\cascade-build-20261011\u2-build-venv\Scripts\python.exe'
& $py scripts/check_open_review_tokens.py --model A:/Guardian-weights/qwen36-awq --input C:/Users/Igor/Guardian-judge-ci-v3-20261014/valid.parquet --out OPEN40_TOKENIZER.json
& $py A:/Guardian-submissions/cascade-build-20261011/build_open40_submission_20261018.py
& $py scripts/verify_open_review_archive.py --archive A:/Guardian-submissions/guardian-judge-qwen36-awq-open-review40-max-34fb1c75-20261018.zip --source-runtime A:/Guardian-submissions/guardian-judge-qwen36-awq-6540dc50UP1.zip --commit 34fb1c750ceec4799f611b6d941c1dafef7ee829 --out OPEN40_ARCHIVE_INSPECTION.json
```

Portable builder CLI (предварительно проверить локальные веса по pinned manifest):

```bash
python scripts/build_judge_submission.py --source-zip /data/guardian-judge-qwen36-awq-6540dc50UP1.zip --source-sha256 f54329f9c8fd7779fe31a66fdeca76f520de699c2969421355d29d45182c56c7 --model-dir /data/qwen36-awq --model-id cyankiwi/Qwen3.6-35B-A3B-AWQ-4bit --model-revision 00fcea2d3bcf5389b518d4fc082e5590e0ba4844 --judge-config submission/JUDGE_OPEN_REVIEW40.json --context-mode legacy --source-revision 34fb1c750ceec4799f611b6d941c1dafef7ee829 --output /data/open-review40.zip
```

Реальный GPU quality-run, не доказательство конкурсного времени (явный extended deadline):

```bash
PYTHONPATH=src:. python scripts/eval_judge_valid.py --input /data/task_separated.parquet --out /data/open40-quality --model /data/qwen36-awq --config submission/JUDGE_OPEN_REVIEW40.json --seconds 7200
```

Конкурсный запуск из распакованного ZIP со штатными дедлайнами:

```bash
./runtime/python/run_python.sh scripts/predict.py --input /data/input.parquet --output /data/output.parquet --work-dir /data/open40-work
```

## Файлы и хранение

Runtime: answer_review.py, blind_review.py, review_stage.py, judge_stage.py,
judge_submission.py, eval_judge_valid.py, builder; opt-in config/README/protocol;
10 новых тестов, расширенный build test/CI; tokenizer/CPU/ZIP verification scripts.
Квитанции лежат в open_review40_receipts_20261018 и рядом с архивом.
Самостоятельной отправки на платформу не было.

По прежнему указанию удалить старые ZIP удалён устаревший u2dense-b758b199
(31,152,076,184 байт), контрольная сумма/квитанции сохранены. Лучший 6q MAX
20d3c110, blind-eef11fc4, UP1 source и веса сохранены.
