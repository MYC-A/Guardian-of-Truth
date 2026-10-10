# Изолированная проверка vLLM с полным B2

## Решение после короткого native screen

Одинаковая synthetic работа8×256 output tokens: concurrency1 —70.320s,
29.124 output tok/s; concurrency8 —29.887s,68.525 tok/s. Наблюдаемый выигрыш2.353×.
Это batch wall с preflight/client costs, не isolated decode или доказательство
причины bottleneck. Сумма native intervals при concurrency8 перекрывается.

16 exact legacy reviewer requests, один rep каждого arm:

| Arm | Batch wall, s | Input/output tokens | Speedup vs base | Transport/admission failures |
|---|---:|---|---:|---|
| Base8 workers/8 slots |232.800|114290 /10928|1.000×|0 /0|
| Queue16 workers/8 slots |223.590|114290 /11025|1.041×|0 /0|
| ngram-mod8/8 |226.805|114290 /10865|1.026×|0 /0|

В обоих candidates2 reviewer decision flips и16 различий admitted payload;
причины не оценивались независимо. Это не binary F1 полного B2. Оба profiles
не достигли prereg10% screen gain; default не меняется и отдельные долгие full
B2 прогоны этих profiles пока не выполняются.

## Новый backend profile

- Engine vLLM0.19.1, отдельная venv; PyTorch2.10.0 по зависимости engine.
- Official `Qwen/Qwen3.8-27B-FP8`, revision
  `017b9c7af6b5689d5dd426a76e0bc077eb5ca20a`;66 indexed weight files,
  суммарно30866866928 bytes. Это другой quant profile, не те же Q8 GGUF bytes.
- Transformers первоначальная установка5.5.4; **до GPU** обязательный отдельный
  compatibility amendment до5.8.0 согласно recipe и config/tokenizer smoke.
- Скачивание8 workers + Xet range concurrency8, прямо HF→сервер; установка
  engine идёт параллельно. Setup root `/workspace/guardian/vllm_probe_20261010`.
  Не меняет прежнюю B2 venv/runtime. Setup timeout1800s.
- После download добавить pinned `video_preprocessor_config.json` (малый файл,
  не вошёл в первоначальный allow list), сохранить amended file protocol.
- Все weights должны совпасть с upstream LFS SHA256; все малые assets — с
  upstream Git blob identity. `scripts/qwen_vllm_verify_assets.py` выдаёт отдельный
  manifest. Старый download manifest не переписывается и не считается полной
  strict verification. Manifest SHA входит в backend/cache identity.

## Контракт запуска

`scripts/qwen_vllm_adapter.py` — отдельный opt-in research runner. Production CLI
сохраняет прежний default. Его `predict_one` принимает явные model/provider только
для нового profile и проверяет согласованность model с client и Layers.
Политики, prompts, schemas, stages, admission, token caps и output recovery B2
сохраняются. Нет compact pre-pass, нового threshold, oracle или silent clipping.
Labels исключаются из inference reader; scorer читает их только после outputs.

Новый profile имеет честный FP8/vLLM alias, exact request и sent-wire hashes,
explicit thinking-off/chat rendering flags, `/tokenize` preflight и проверку
согласования фактического prompt usage. Responses сохраняются до parsing;
no retries в adapter, singleflight только внутри свежего запуска.
Модельные повторные стадии B2 сохраняются — отсутствие transport retry их не
отключает. Technical/default0 flags учитываются отдельно от качества.

Первый GPU smoke: первые2 rows original order (выбор не по labels),1 worker,
8 slots, context32768,180s HTTP timeout,600s run cap,24 completion cap.
`--enforce-eager` сначала исключает долгую CUDA graph compilation из диагностики.
Prefix caching/chunked prefill явны; BF16 compute, auto KV без отдельного
снижения precision. Effective kernel/cache dtype требуется подтвердить log.
Никаких двух GPU servers одновременно.

При успешном smoke — **полный valid46**,8 workers/8 slots, тот же profile,
context32768 и B2 token limits;600s HTTP timeout как у исходного LocalClient,
1800s run cap,400 completion cap, новый output.
Сначала baseline B2 на новом backend, без lazyF. Не запускать полный набор,
если smoke технически не выполняется или завершается через default0.

Оценка: expected IDs46, TP/FP/FN/TN/F1, binary/cause/target changes, all stage
calls и usage, technical/null/default0, startup и whole wall отдельно. Исторический
Q8 B2 reference15TP/0FP/8FN,1743.834s — не contemporaneous new-native control.
vLLM+FP8 меняет два фактора и не позволяет приписать выигрыш одному engine.
При перспективном результате нужны matched controls/repeats; private performance
и готовность нового archive не объявляются по valid46.

Новый profile пока не adopted. Конкурсный ZIP не пересобирается до качества,
скорости, offline/fresh install и проверки веса+runtime archive size.

Источники: [vLLM model recipe](https://recipes.vllm.ai/Qwen/Qwen3.8-27B),
[pinned FP8 implementation](https://github.com/vllm-project/vllm/blob/v0.19.1/vllm/model_executor/layers/quantization/fp8.py),
[pinned OpenAI server](https://docs.vllm.ai/en/v0.19.1/serving/openai_compatible_server/).

## ???????? ? ?????????????? coordinator

249 targeted tests passed, 2 POSIX-only skipped ?? Windows. ??????????? code review
????????? cleanup workers ????? ?????????? leader ? ?????????????????? ???.
Full same-raw replay ????? plumbing: valid46 15TP/0FP/8FN, ??? ?????????
???????/??????; ? ????? backend ??? ???????? ???????????? receipts.

`scripts/qwen_vllm_launch_remote.py --source-sha <FULL_PUSHED_SHA>` ???????????
?? research ??????? ????? CPU/network setup. ?? ????????? ??????????? source SHA,
????????? assets, ?????? CPU/GPU smoke, ????? full valid46 ? scoring. ??????? cap6000s
???????? bounded dependency waits; full inference ????? ????????? cap1800s.
?????????/?????? ? ??????? wall times ??????????? ??? ??????? ?????? ? polling.
