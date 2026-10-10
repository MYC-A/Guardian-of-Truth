# Очередь, GPU utilisation и следующий inference screen

2026-10-10. Текущие frozen legacy/compact и queued N0/RF не изменялись.
Это анализ настроек и пассивный замер, не результат нового scheduling arm.

## Что уже делает код

`cli.py` использует ThreadPoolExecutor: несколько строк обрабатываются одновременно.
ModelServer получает `slots=workers`, а `-c=slots*context`, `-np=slots`.
Поэтому сейчас16 workers автоматически означают16 model slots и общий context524288
при32k/slot. Для отдельного опыта16workers/8slots нужно развести настройки.
Само увеличение workers здесь не сокращает per-slot context до16k.
Llama.cpp f498 continuous batching включён по умолчанию; это не новая capability.

## Фактический короткий замер

Во время compact rep1 сделано6 последовательных GET /metrics с промежутком5s
и nvidia-smi snapshot. Дополнительных completion requests не было; API key не
сохранялся и не печатался. Во всех6 точках requests_processing=8,
requests_deferred=0. Cumulative average busy slots/decode примерно7.956.
GPU snapshots:99%,80%,20%,100%,0%,79%.

В этом окне нехватка поданных запросов не объясняет провалы GPU percentage:
движок уже держит8 jobs. Это не full-run utilization trace и не доказательство,
какой CPU/kernel/grammar/phase bottleneck виноват. Metrics и GPU readings сняты
последовательно, не одновременно. Cumulative average не является средним лишь
за эти25 секунд; stage counters не заменяют поминутный GPU timeline.
Загрузка GPU показывает долю sample interval с исполняющимися kernels,
а не долю доступного ускорения или эффективность memory bandwidth.

Raw: `outputs/qwen_gpu_pilot_20261010/scheduler_sample_1791614994.json`.
Baseline179 calls/46 rows (~3.89), а не1.7. Максимальный actual reviewer input
baseline10629 tokens плюс1700 completion reserve =12329. Input context нельзя
снижать до8k. Для16k нужно проверить всю новую request matrix, включая auxiliaries.

## Следующие отдельные опыты после текущих полных прогонов

1. Раздельные CLI knobs workers/slots с defaults, сохраняющими текущий запуск.
   Сравнить8/8 и16/8 при unchanged model, prompts, caps,32k/slot.
   Измерять очередь, completed rows, timeouts, GPU samples и whole CLI wall.
   Если slots уже насыщены, одной очереди ожидаемый большой выигрыш не обоснован.
2. Затем12slots/16workers с тем же per-slot context, после measured VRAM preflight.
   Не уменьшать context молча. `kv-unified` не добавляет VRAM и не отменяет
   individual context/full aggregate-memory checks. Большая очередь увеличивает
   ожидание; текущий LocalClient timeout600s включает ожидание HTTP ответа.
3. Batch/ubatch и speculative ngram-mod — отдельные profiles; не менять несколько
   механизмов одновременно. Проверять реальные drafted/accepted counters,
   rollback/grammar, full outputs и recovery/default rates.
4. Matching MTP/DFlash по бюджету; Q4/vLLM — отдельный model/backend experiment.

Два Q8 servers на одной A100 требуют двух копий весов и KV/compute buffers;
один нынешний процесс использует около44GiB, два одинаковых могут превысить80GiB.
Один engine с большим batch лучше сохраняет общие weights; несколько servers не
выбраны первым шагом. Это выбор для этой конфигурации, не универсальный запрет.

Зависимые pre→review stages должны соблюдать порядок. Независимые строки уже
параллельны. Дополнительные независимые checkers можно ставить в общую bounded
очередь только после проверки зависимостей, mutable state/caches/call budgets;
async rewrite сам по себе не ускорит saturated GPU.

Изменение batch geometry может менять численные результаты и дальнейшие tokens
даже приtemperature0. Нельзя обещать отсутствие систематического вреда без
парных полных запусков: считать TP/FP/FN/F1, cause/target flips, output completeness,
default-zero/context/timeout rates, tokens и wall. N0 F1.686 другого агента не
matched reference для B2 legacy F1.78947. Alternate arm order, одинаковый warmup;
первые16 строк служат только speed screen, не quality acceptance.

## Primary documentation

- [Pinned server flags, continuous batching, KV and metrics](https://github.com/ggml-org/llama.cpp/blob/f498f864fbc0472004ee1c3616c1188c68eb157f/tools/server/README.md)
- [NVIDIA utilisation definition](https://docs.nvidia.com/deploy/nvidia-smi/index.html#utilization)
