# Где ускорять Guardian: code, CPU, serving backend

2026-10-10. Runtime8911b35f, Q8 file/source pinned, frozen phase не изменялась.
Independent code audit — отдельный субагент stage_isolation; source/causes —
archive_review. Новые inference profiles из этого документа NOT_EXECUTED.

## Измеренные ограничения

Legacy179 calls,1743.83s; compact186 calls,1724.68s. Полная paired таблица и
quality caveats: [LIVE_RESULTS.md](LIVE_RESULTS.md). Compact opt-in, default прежний.

| Request timing, суммы перекрываются между8workers | legacy | compact |
|---|---|---|
| Total client request seconds | 13336.80 | 13018.69 |
| Native predicted duration seconds | 12352.87 | 11962.86 |
| Native prompt duration seconds | 809.10 | 873.72 |
| Client minus native timing residual seconds | 174.83 | 182.11 |
| Summed request duration / CLI wall | 7.65 | 7.55 |

Это request occupancy proxy, не GPU device compute time. Decode interval
включает scheduler/sampling/CPU/CUDA waits и задержки от других requests;
суммы нельзя складывать в wall. Однако генерация доминирует, а типичная
занятость requests близка к8. Все receipts имеют native timings.
Residual около1.3% request duration включает token preflight/HTTP/JSON/queue,
не является isolated tokenizer/CPU measurement. Массовая перепись наasyncio
не имеет доказанного потенциала убрать минуты при уже насыщенных slots.

Два пассивных10-second CPU окна работающего model server:
128 logical CPUs/affinity128; host busy2.90%/2.96%; native process100.78%/101.54%
в шкале100%=одно ядро. Main thread99.98%/99.75%; остальные почти свободны.
Processing slots8→7; cumulative busy/decode~7.96. GPU snapshots100%/69%.
Низкий aggregate CPU скрывает полностью занятый main thread. Это не доказанный
CPU bottleneck: поток может выполнять CUDA waiting/polling. Perf есть, но
perf_event_paranoid4; Nsight Systems отсутствует. Profiler trace/permissions
не получены; kernel settings не менялись. Нулевая cgroup metadata означает
недоступный путь, не доказанно unlimited quota.
Raw: `outputs/qwen_gpu_pilot_20261010/cpu_window_1791616205.json`.

Не переносить часть layers на CPU лишь ради загрузки128 ядер: это новая
CPU/GPU split с PCIe/state costs, её полезность не показана. Не увеличивать
threadpool до128 без теста; native current log подтверждает8 CPU threads.

## Code opportunities и границы

| Механизм | Обоснование / ограничения | Приоритет |
|---|---|---|
| Lazy F extraction | `turnrules.check` поддерживает лишь max-tool-count и prose+call, оба невозможны при0 current assistant calls. Пропуск model extraction для этого checker выводится из capability, не имени tools/домена | Высокий, отдельная fixes-only ablation |
| Policy-level singleflight | Shared Layers cache check/set безlock; exact LocalClient cache уже защищает одинаковые request+attempt, поэтому большой inference win не доказан | Контракт/детерминизм |
| Компактнее semantic pre output | Первое уменьшениеoutput31% не помогло достаточно: downstream work растёт, scope/catalog distinctions теряются | Высокий, после исправления semantic boundary |
| Lossless addressed sources | Blind view и selected unit texts частично дублируют policy. Не alias неподтверждённые role/event; inverse должен сохранить исходный content/context | Средний |
| Разделить workers/slots | Сейчас повышение workers увеличивает slots и KV. Queue16workers/8slots изолирует scheduling; occupied8slots ограничивают потенциал | Дешёвый screen |
| Независимые stage tasks | DF/Ems/AT и Layers идут последовательно. Shared bounded dispatcher может сокращать tail; общий token work остаётся. Нельзя менять verifier premises или precedence по arrival order | Средний |
| Immutable parser/index reuse | Сейчас input parse/SourceStore/packet собираются несколько раз. CPU saving возможен, доминирование не показано | Низкий |
| Exact tokenizer-count cache | Сейчас preflightHTTP на каждый новый completion. Key=model/tokenizer/chat-template/full-wire; reserve каждыйраз проверяется отдельно | Низкий, preflight не удалять |
| Global wall deadline | Нынешний completion timeout600s не ограничивает весь pipeline. Нужен reserve на output и явно отмеченные skipped optional calls | Надёжность; может увеличить FN |

F был64calls/91212 input tokens,0 mechanical F winners наvalid46. Это не основание
выключить F на всех inputs. Lazy0-call gate математически сохраняет доступные
проверки текущей capability; расширение capabilities требует пересмотра gate.
Для empty candidate-lines нужен отдельный source-coverage анализ, не общий
автоматический пропуск arbitrary policies. Нельзя экономить путём UNKNOWN→0 и
считать это улучшением качества. Existing guarded recovery сохраняется.

Есть выключенный CB global monkeypatch hazard в `repair/v5.py:316`; default
with_cb=False. Он не объясняет current timings, но до параллельного CB нужен fix.
Independence extraction следует сохранять: два proposal attempts F не превращать
в одно без новой версии wire/ablation. Вход/outputs/gold исторических фаз неизменны.

## Native serving и speculative

Continuous batching ужеdefault. Explicit FA показал82.06→83.95 synthetic aggregate
TPS,2.3%, и не прошёл threshold10%; это4requests×256tokens, не full-valid speed.
Вернуться кbatch/ubatch/12slots на real mixed load; не менять все сразу.
8k context непригоден: текущий longest reviewer10629+1700reserve=12329.
16k candidate допустим только после actual tokenizer-check всех stages/rows.
KV unified не отменяет individual/full memory bounds; VRAM в80GB не бесплатна.

Prefix reuse measured native cache_n: pre4388/review712 legacy,
pre2717/review445 compact; F примерно50k cached tokens. Есть reuse, но main
pipeline gain мал. Общий system prefix не означает закэшированные разные history/
policies/pre analyses. Hybrid recurrent checkpoints требуют их собственных правил.

После текущих full arms: fixed Q8 base vs ngram-mod, затем matching MTP/DFlash
при бюджете. Нужны actual draft/accepted counters, grammar/rollback, failures,
call/wall/quality flips. CPU draft/lookup может использовать свободные CPU
ресурсы без offload основного target, но speed/acceptance пока не измерены.
Exact target sampler verification не обещает побитово одинаковых GPU results.
Q4 и quantized KV — другие numerics, отдельное сравнение качества.

## vLLM / SGLang

GGUF header независимо прочитан с уже скачанного локального файла, только
10.94MBmetadata: general.architecture=qwen35, general.name=Qwen3.8-27B,
64blocks, context262144, embed5120,24heads/4KVheads; quant Q8_0.
Семейство использует hybrid full/linear attention. Оба проекта публикуют
recipe именно Qwen3.8-27B; основные speed numbers там наBlackwell/Hopper/Ascend,
не доказательство ускорения нанашей A100sm80.

| Backend hypothesis | Плюс | Что нужно проверить |
|---|---|---|
| llama.cpp pinned Q8 | Exact existing weights/runtime; небольшой standalone package | Native sampling/CUDA/grammar trace, batching и speculative |
| vLLM existing GGUF | Можно пытаться сохранить weightfile | GGUF в официальной документации experimental/under-optimized и требуетplugin; architecture/quant/feature support не гарантированы |
| vLLM native BF16 | Supported model path, chunked prefill/cache/graphs; сильный batched serving candidate | Другие numerics и checkpoint revision; примерно54GBтолько27B weights, плюсstate/KV/graphs; новая environment/package |
| vLLM native INT8/AWQ/GPTQ | Ampere имеет поддержанные quant kernel families | Нужен actual compatible Qwen3.8 checkpoint, полный model-specific smoke; Q8_0 нельзя просто переименовать вAWQ/GPTQ |
| SGLang native BF16/quant | Qwen-specific hybrid-state/cache/spec recipe | A100-compatible kernels, state/KV precision и peakVRAM; полноценный adapter/packaging |

FP8/FP4 Blackwell tutorial не копировать без hardware/kernel verification:
A100 не имеет Hopper/Blackwell native FP8/FP4 tensor path. Возможные weight-only
fallbacks проверять отдельно, не обещатьhardware speed. Generic quant support
не доказывает конкретную model+quant combination. Requantization изQ8 не возвращает
original BF16 checkpoint; нужны original pinned weights/tokenizer/config.

Для migration не достаточно поменять base URL: нынешний client требует llama
`/v1/chat/completions/input_tokens`, `/props`, exact n_ctx/alias и свой process
lifecycle. Adapter должен сохранить actual chat template, thinking disabled,
schema/grammar +localvalidation, reserved completion, finish_reason, cancellation,
model identity, raw usage/native timing и explicit failure/recovery. Одинаковый
OpenAI-shaped API не доказывает эквивалентность этих контрактов.

New backend: isolated pinned environment; weights напрямуюHF→server; disk/VRAM
и artifact-size preflight. Checked requirements snapshot2026-10-08 задаёт ZIP<40GB;
native BF16~54GB weights при текущем ZIP_STORED превышают это ещё доruntime.
BF16 — diagnostic reference, пока не проверен допустимый package/quant; размер
ZIP_DEFLATE нельзя обещать без сборки. Public web refresh rules PDF недоступен,
но live comments2026-10-10 подтверждают ответ организатора16сентября:
40GB относятся кархиву,80GB кGPU. Participant report оpreinstalled vLLM0.19.1
не official serving guarantee; не полагаться на него приoffline packaging.
No downloads/installs requested by this assessment started; GPU не
занимается новым engine доN0/RF complete. First16rows speed screen не quality
acceptance; full matched46/repeats and packaging/runbook обязательны. BF16/quant
нового движка сравнивать как новый кандидат, не 'тот же model exact replay'.

## Порядок решения

1. Закончить текущие full N0/RF; сохранить receipts и source/quality regressions.
2. Freeze separate mechanical lazy-F and worker/slot controls; full offline replay
   плюс live profile по изменившимся call sequences. Gold/IDs не влияют наgate.
3. Native ngram/batch screen наunchanged Q8; если эффект слабый, native vLLM/SGLang
   candidate имеет приоритет перед тотальной asyncio rewrite.
4. Full paired quality/cause/target/time/recovery, peakVRAM/cold warmup. Выбрать
   кандидат поactual measurements, затем rebuild competition package/fresh GPUtest.

## Primary sources, проверены2026-10-10

- [Pinned llama.cpp server/flags/metrics](https://github.com/ggml-org/llama.cpp/blob/f498f864fbc0472004ee1c3616c1188c68eb157f/tools/server/README.md)
- [vLLM Qwen3.8-27B recipe](https://recipes.vllm.ai/Qwen/Qwen3.8-27B)
- [SGLang Qwen3.8-27B recipe](https://docs.sglang.io/cookbook/autoregressive/Qwen/Qwen3.8-27B)
- [vLLM GGUF limitations](https://docs.vllm.ai/en/latest/features/quantization/gguf/)
- [Official GGUF plugin tested coverage](https://github.com/vllm-project/vllm-gguf-plugin):
  Qwen3.5 Q4_K_M и embedded-nextn MTP уже тестируются; это не гарантияQwen3.8Q8.
  Same-file MTP требует nextn tensors. Наш mainGGUF и отдельный llamaMTPdraft
  нельзя считать готовым unified vLLM MTPcheckpoint без tensor mapping check.
- [vLLM quantization hardware matrix](https://docs.vllm.ai/en/latest/features/quantization/)
- [vLLM chunked-prefill tuning](https://docs.vllm.ai/en/latest/configuration/optimization/)
- [Organizer archive/GPU clarification](https://dsworks.ru/champ/aij26-guardian/comments)
