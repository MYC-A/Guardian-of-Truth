# Guardian: подготовка ускорения инференса — 2026-10-10

**Обновление следующей фазы:** сервер снова доступен. Добавлены opt-in lazy-F и
longest-first; полный offline replay оставляет прежние TP15/FP0/FN8 и причины,
удаляя 26 из 179 реальных inference calls. Новое GPU-ускорение B2 пока не измерено.
Logprob triage ветки `58a48d25` завершён: 46/46, TP14/FP0/FN9, F1 .7568;
это отдельный диагностический классификатор, не ускоренный B2.
Подробности и порядок сравнения: [PHASE2_PROTOCOL.md](PHASE2_PROTOCOL.md).
Готовый архив соревнования не пересобирался.
Работа в отдельной ветке `perf/qwen-inference-20261010`, от `f1152066`.

Native GPU screen завершён: fixed-work concurrency8/1 =2.35×;
reviewer queue16 =1.041×, ngram =1.026×, оба ниже порога10%.
Подготовка отдельного vLLM+official FP8 идёт8 потоками, engine install параллельно.
Контракт и measured screen: [VLLM_PHASE.md](VLLM_PHASE.md).

Ниже сохранён снимок подготовки предыдущей фазы, когда сервер был остановлен.
Её NOT_EXECUTED и 133 tests относятся к тому снимку. В текущей фазе **176 passed,
2 skipped**; новые GPU receipts публикуются отдельно.

## Что реализовано

1. В public submission CLI разделены `--workers` и `--slots`.
   Можно поставить 16 обрабатываемых строк на 8 GPU slots; размер контекста
   вычисляется по slots, а не по workers. Default прежний: 8/8, 32768 на слот.
2. `--spec-type ngram-mod` — отдельный opt-in профиль без draft весов.
   Default `none` сохраняет прежнюю команду сервера целиком. Ошибочный профиль
   отклоняется до запуска; attach не позволяет молча игнорировать backend flags
   и проверяет число slots существующего сервера.
3. `scripts/qwen_inference_bench.py prepare` восстанавливает **реальные** legacy
   reviewer requests через production predictor. Перехват находится после
   blind injection и byte-budget fallback. Cache identity включает request,
   model и attempt; все 46 request hashes совпали с live receipts.
   Сеть блокируется; `label` удаляется input reader и не используется.
4. `run` готов к ограниченному сравнению base / queue16 / ngram /
   ngram_queue16. Каждый arm получает новый собственный native process,
   свежий inference cache, те же точные запросы и 32k context на слот.
   CPU env фиксируется на 8 threads; нет model retries и дополнительных reviewer
   задач. Проверяются SHA весов и native binary. Максимум 128 completion attempts.
5. Сохраняются cold startup, batch/phase wall, usage, HTTP/finish/admission
   failures, исходные replies, native metrics до/после (включая доступные
   draft/accepted counters), props и paired decision/admitted payload differences.
   Native API key не записывается. Один transport failure завершает screen после
   уже отправленного batch. Output directory должен быть новым.

Это **reviewer-only engine screen**, а не запуск всего Guardian и не F1.
16 запросов выбраны по квантилям измеренной input-token длины, включая минимум
и максимум; порядок исходных строк сохранён. В `plan.json` сохранены все 46
requests, выбранные IDs и fingerprints. При двух repeats порядок arms обратный
во втором. Нет warmup: cold cache/prefix/ngram поведение входит в batch wall;
оно не эквивалентно steady state длинного полного прогона.

Ни один новый профиль автоматически не принимается. Screen threshold:
не менее 10% выигрыша batch wall и отсутствие дополнительных transport/context/
schema/admission отказов. Любые decision/target/reason/premise differences требуют
проверки источников. После screen нужен полный matched valid46 при той же логике
Guardian; удачные 16 запросов не заменяют этот контроль. Sampling/batching и
floating point могут менять ответы даже при temperature=0.

## Что действительно измерено раньше

Все строки ниже: полный valid46, Qwen3.8-27B Q8_0, одна A100 80GB,
один ordered repetition каждого варианта. Это development screening,
не независимый holdout. Новых вариантов инференса в таблице нет.

| Вариант | Что используется/убрано | TP / FP / FN | F1 | Время | LLM calls |
|---|---|---|---|---|---|
| Legacy B2 | Исходный blind pre-pass + R_fix + F/S/P layers | 15 / 0 / 8 | 0.7895 | 29:03.8 | 179 |
| Compact B2 | Компактный blind output и общий source index; остальные layers сохранены | 14 / 0 / 9 | 0.7568 | 28:44.7 | 186 |
| N0 | R_fix, без blind и F/S/P | 9 / 0 / 14 | 0.5625 | 14:22.9 | 78 |
| RF | Тот же N0 + lexical reading aid, без blind и F/S/P | 12 / 1 / 11 | 0.6667 | 12:59.1 | 73 |

B2 times включают CLI input loading, model startup/health, pipeline, shutdown и
output write. N0/RF operator times исключают input loading, включают startup,
pipeline, shutdown, predictions/calls export. Bootstrap/download/scoring исключены
в обоих случаях. B2↔N0 нельзя использовать как изолированную аблацию blind:
одновременно удалены несколько layers. Название «LN» не найдено в проверенных
источниках, поэтому оно здесь не переименовано в N0 или Lynx.

Полный B2 сделал 179/46 = 3.89 calls на строку, всего 118421 generated tokens.
Оценка времени из предположения «один короткий ответ 0/1 на строку» к нему
не относится. 29:03.8 на valid46 оставляет около 56s до 30 минут; это
ограниченный замер, не доказательство укладывания полного/private test.

Compact снизил генерацию blind на 31.2%, но стал доставлять pre-analysis в 45/46
reviewers вместо 32/46. Это увеличило reviewer inputs и последующие проверки:
total input tokens +10.7%, calls 179→186. Wall выиграл только 19.15s (1.10%),
один TP потерян. Поэтому compact не стал default.

RF добавил к N0 3 TP и 1 FP; source review подтвердил только одну из трёх новых
положительных причин. Остальные row gains не доказывают исправление нужного
нарушения. RF — word/chargram TF-IDF cosine aid, **не semantic embeddings/LSH**.
В этих четырёх прогонах нет отсутствующих output labels или default-zero
подстановок. Сравнение и исходные receipts:

- [Полные результаты](../qwen_compact_prepass_20261010/LIVE_RESULTS.md).
- [Legacy/compact paired](../../outputs/qwen_gpu_pilot_20261010/paired_rep1.json).
- [N0/RF paired](../../outputs/qwen_gpu_pilot_20261010/N0_RF_pair.json).

## Где сейчас узкие места

Во время старого GPU-прогона сумма request durations / wall была 7.65 при 8
workers. Это proxy занятости, не GPU device compute. Native decode intervals
доминируют в receipts, но включают scheduler/CPU waits. Одной переписью клиента
на asyncio или увеличением CPU threads нельзя обосновать многократное ускорение.

При 128 logical CPUs host CPU показывал около 3%, но основной поток native
process занимал примерно одно ядро полностью. Он может выполнять полезную
работу или CUDA waiting/polling; profiler trace для различения не получен.
Переносить слои модели на CPU только ради загрузки ядер оснований нет.

Новый **локальный** cProfile при offline capture 46 requests: 12.64s с profiler
overhead, 460 созданий SourceStore и 92 packing calls; pack cumulative 8.50s.
Это измерение участка подготовки до reviewer на ПК, не всего pipeline и не GPU
времени на сервере. Есть возможность reuse immutable parsed sources/packing,
но потенциальный выигрыш этой оптимизации не следует приравнивать к минутам
генерации. Код parsing пока не менялся.

F extraction дал 64 calls и 91212 input tokens в обоих B2 arms. Сейчас он делает
два последовательных запроса по полной политике. Отдельно имеет смысл проверить
lazy extraction, когда в current move вообще нет tool calls: нынешние F predicates
MAX_TOOL_CALLS_PER_TURN(n>=0) и NO_TEXT_WITH_TOOL_CALL там не могут дать нарушение.
Этот gate/упрощение F ещё **не внедрены**, качество общего модуля не объявлено нулевым.

Приоритеты после включения GPU:

1. Same Q8/native/wires: queue depth и ngram-mod — подготовленный screen.
2. При выигрыше — полный B2 baseline/candidate valid46; при его отсутствии
   сохраняем default и не переписываем historical results.
3. Затем отдельные batch/ubatch/slot profiles, с явным longest-request reserve.
   8k context уже недостаточен: longest old review 10629+1700 tokens.
4. MTP/DFlash — отдельные runtime/draft profiles; draft weights не скачивались.
   Нельзя обещать выигрыш или неизменное качество без измерения acceptance,
   rollback implementation и matched outputs.
5. vLLM/SGLang — отдельная более крупная ветка, не замена одного флага.
   GGUF Q8 нельзя переименовать в AWQ/GPTQ. Понадобятся совместимый checkpoint,
   tokenizer/chat-template/reasoning contract, transport adapter и новая проверка
   context, latency, качества и размера конкурсного архива. BF16 около 54GB
   только весов не подходит в текущий 40GB archive budget. Generic Ampere kernel
   support не доказывает поддержку именно выбранного checkpoint/model backend.

Опорные primary docs:
[pinned llama.cpp speculation](https://github.com/ggml-org/llama.cpp/blob/f498f864fbc0472004ee1c3616c1188c68eb157f/docs/speculative.md),
[vLLM recipe](https://recipes.vllm.ai/Qwen/Qwen3.8-27B),
[SGLang recipe](https://docs.sglang.io/cookbook/autoregressive/Qwen/Qwen3.8-27B),
[vLLM GGUF](https://docs.vllm.ai/en/latest/features/quantization/gguf/).
Рецепты, преимущественно для других GPU, не дают нам подтверждённой A100 скорости.

## Проверки и статус

- **133 passed, 2 skipped**: inference options/benchmark, primary recovery,
  completion, compact blind, stage isolation, wire и reproject suites.
  Два skips — POSIX-only на Windows. Для subprocess NumPy tests установлены
  OPENBLAS_NUM_THREADS=1 / OMP_NUM_THREADS=1 / MKL_NUM_THREADS=1:
  исходный запуск дал три OpenBLAS allocation failures, повтор с этими settings
  прошёл. Это настройка локального тестового окружения, не изменение GPU serving.
- Новый полный offline replay: **46 rows, 179/179 exact requests, 0 missing,
  0 differences** в binary/owner/accusation. Не создаёт новых model predictions.
- 46/46 reviewer requests captured после фактического byte-budget fallback.
- CLI controls реализовал субагент stage_isolation; родитель проверил diff,
  default command test и полный replay. Benchmark script reviewed/tested родителем;
  отдельный независимый review этого скрипта не завершён: агенты достигли usage
  limit. Не называем self-review независимым.
- Новые GPU profiles: **NOT_EXECUTED (сервер остановлен пользователем)**.
- Прежние промпты, checkers, candidate precedence и missing-label recovery не
  изменены. Default legacy и готовый competition ZIP сохранены.

## Запуск после предоставления работающего сервера

Из checkout этой ветки, с уже подготовленным venv/runtime:

```bash
export PYTHONPATH=src:.
export PYTHONUTF8=1
export PYTHONDONTWRITEBYTECODE=1
python scripts/qwen_inference_bench.py run \
  --plan outputs/qwen_inference_20261010/plan.json \
  --root /workspace/guardian/runtime \
  --output /workspace/guardian/results/inference_screen_NEW \
  --arms base queue16 ngram --repetitions 1
```

Проверить layout root/runtime/llama/llama-server и root/model/Qwen3.8-27B-Q8_0.gguf.
Скрипт не скачивает и не устанавливает модели. Он проверяет binary SHA
`1ed587e4c0b30bb4221268b2fb4934813eb88abc8e58d3df978e22dcc0b57d2f`
и frozen Q8 SHA до первого arm. Несовпадение — отдельная версия, не повод снять
проверку. После успешного первого screen повторить в новом output path с
`--repetitions 2` для прямого/обратного порядка. При необходимости комбинированный
ngram_queue16 проверяется отдельным screen; нельзя приписывать ему сумму gains.

Полный автоматический B2 control после screen запускается прежним CLI с отдельным
work/output и новыми optional флагами. Ниже пример queue-only candidate, не команда,
которая сейчас выполнялась:

```bash
python -m guardian_truth.submission.cli --input valid.parquet \
  --output /workspace/guardian/results/B2_queue_NEW.parquet \
  --work-dir /workspace/guardian/results/B2_queue_NEW \
  --root /workspace/guardian/runtime --workers 16 --slots 8 --pre-profile legacy
```

Ему нужен baseline того же frozen inference phase; исторические 15TP/0FP сами по
себе не гарантия повторения. Проверять полный ID set, F1, cause/target changes,
defaults/technical failures и whole-script wall. Запускать вне этой команды bootstrap,
download и artifact hashing и отдельно учитывать их в platform budget.
