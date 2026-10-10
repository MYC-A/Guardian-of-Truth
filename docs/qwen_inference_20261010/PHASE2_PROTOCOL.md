# B2: безопасные границы оптимизаций и сравнение движков

Дата: 2026-10-10. Исторические прогоны, gold и submission ZIP не изменяются.
Новый runtime default сохраняет прежние prompts, checker precedence, retries и
missing-label recovery. Все новые оптимизации opt-in.

## Уже проверено

`--skip-inapplicable-f` пропускает только F extract/bind/check, когда полный
production inventory текущего хода не содержит assistant tool calls. Нынешние
F predicates — MAX_TOOL_CALLS_PER_TURN(n>=0) и NO_TEXT_WITH_TOOL_CALL — в таком
ходе не могут обнаружить нарушение. Это граница capability этих двух predicates,
не доказательство разрешённости хода. S/P и остальные проверки продолжаются.
Malformed assistant call остаётся call и не пропускается; max0 с одним call
тоже проверяется. Пустое извлечение не записывается в общий policy cache.

Полный replay `scripts/qwen_lazy_f_replay.py`: exact archive member hashes,
input/row fingerprints, request/model/attempt/tag identity и network tripwire.
Baseline обязан использовать весь frozen call set; missing и metadata failures
фатальны даже при optional-stage isolation. Gold используется только в scorer.

| Arm | valid rows | Calls | TP/FP/FN/TN | F1 | Binary/owner/accusation changes |
|---|---:|---:|---|---:|---:|
| Baseline frozen replies | 46 | 179 | 15/0/8/23 | .789474 | 0 |
| Lazy F, original order | 46 | 153 | 15/0/8/23 | .789474 | 0 |
| Lazy F, longest first | 46 | 153 | 15/0/8/23 | .789474 | 0 |

Убраны 26 unique inference calls, 39524 input / 3796 output tokens; 23 строки
имеют telemetry SKIPPED_NO_CURRENT_ASSISTANT_CALL. Не все 64 архивных F calls
можно удалить: часть нужна другим ходам и совместно использует policy cache.
GPU wall saving пока не измерен. Replay не гарантирует идентичные новые ответы
LLM при изменившемся расписании batch.

`--queue-order longest-first` — stable sort по сумме UTF-8 bytes prompt/response,
без gold/ID routing. Это proxy очереди, не token/context estimate. Итоговый файл
всегда сохраняет исходный порядок rows.

176 tests passed, 2 POSIX-only skipped на Windows. Отдельный code reviewer
подготовил engine diagnostic и проверил cascade; второй reviewer проверил lazy
F/CLI/replay. Найденный masked metadata failure исправлен до final replay.

## Последовательность GPU фаз

1. Frozen `cascade/logprob-budget-20261010`, SHA58a48d25334aff0b737f4d62a7c21dc6cf927d75:
   triage-only full valid46, 8 workers/8 slots, два one-token views, без threshold
   fitting. Внешний timeout900s и durable raw response capture, потому что
   собственный deadline начинается после triage, а исходный client теряет raw
   logprobs. Результат TP14/FP0/FN9/TN23, F1 .756757. Это не full cascade/B2.
2. `scripts/qwen_engine_scaling.py`: тот же pinned Q8/native, свежий сервер на
   каждый arm, CPU8, 8 slots ×32768 в обоих arms. Одни и те же 8 разных synthetic
   requests ×256 tokens, concurrency1 против8. Warmup16 tokens отдельно;
   ignore_eos и отсутствие retries фиксируют работу. Максимум18 completion calls;
   внешний timeout1200s. Native preflight/usage/finish/context/identity failures
   прекращают последующие arms. Сохраняются raw receipts и metrics.
3. Exact legacy reviewer-wire screen base/queue16/ngram, если diagnostic успешен.
   Это скорость конкретной нагрузки и admission differences, не pipeline F1.
   Все GPU phases последовательны на одной карте.
4. Сопоставимый полный B2 baseline/candidate valid46 для перспективного профиля.
   Отдельно lazy-F-only и engine/scheduling changes, не объединять неизвестные
   эффекты. Screen adoption: минимум10% wall gain, без новых technical failures;
   full valid46 обязан не добавить FP/FN и показать whole-script time. Один rep
   даёт development diagnostic, не гарантию на private test.

Scaling<2x не доказывает неисправность движка или бесполезность остальных flags.
68 tok/s из total pipeline output / wall — не isolated decode throughput.
100% одного CPU thread может означать CUDA polling; профиля причины пока нет.
Concurrency8 не обязана давать8× throughput на общей GPU.

## vLLM/SGLang: предпочтительнее сокращения анализа, но отдельный кандидат

Сначала сохраняем все B2 стадии, prompts, token budgets и условия recovery,
меняя только backend profile. Поддержка OpenAI API не гарантирует одинаковый
chat template, thinking/content placement, stop tokens и JSON schema behaviour.
Проверяем реальные rendered/tokenized inputs, отсутствие silent truncation,
served checkpoint identity, finish reason и usage. Не переносим старые receipts
на новый backend или другую квантизацию.

Метаданные доступных checkpoints сохранены в
`outputs/qwen_inference_20261010/backend_candidates.json`. Проверены только
metadata/config, веса не скачаны и модели не запущены:

- Official Qwen3.8-27B-FP8: all safetensors суммарно30866866928 bytes.
- Community GPTQ8: all safetensors суммарно33528450784 bytes, group32.

Это сумма файлов repo, не подтверждённый размер законченного submission.
Нужны ещё tokenizer/runtime/dependencies и проверка referenced weight index.
A100 поддерживает GPTQ/AWQ/Marlin по generic vLLM matrix; native FP8 W8A8
tensor-core path на Ampere отсутствует. Конкретный kernel/model/checkpoint path
нужно проверять на нашей карте. Q8 GGUF нельзя просто переименовать в GPTQ.

Предпочтительный первый новый backend — vLLM в отдельном pinned environment,
из-за опубликованного model recipe. SGLang — следующий отдельный контроль при
проблемах совместимости/скорости. Не меняем одновременно движок, веса, KV
precision, prompts, classifier и token budgets без отдельных ablations.
BF16 может служить диагностикой при достаточной VRAM, но ~54GB весов не помещаются
в нынешний40GB archive budget. Уменьшение max_tokens/compact pre-pass уже потеряло
1TP в одном live rep; это не безопасный default.

Primary sources:
- https://recipes.vllm.ai/Qwen/Qwen3.8-27B
- https://docs.vllm.ai/en/latest/features/quantization/
- https://docs.vllm.ai/en/latest/design/prefix_caching/
- https://huggingface.co/Qwen/Qwen3.8-27B-FP8
- https://huggingface.co/btbtyler09/Qwen3.8-27B-GPTQ-8bit

## Ограничения logprob ветки

Нельзя принимать её как готовый time-safe вариант. Независимое чтение58a:
deadline не ограничивает triage/startup; score_view выбирает первый stripped
digit variant вместо суммирования всех вариантов; отсутствующий digit заменяет
эвристическим floor, а не измеренной probability; prompt clipping может терять
политику/контрсвидетельства. Default threshold0.5 выше — только frozen diagnostic.
Raw capture wrapper не исправляет score semantics задним числом.

Перенос этих scores в final label, threshold fitting и budget cascade — новые
classifiers с отдельными quality/cost/technical-null checks. 0FP на23 negatives
не гарантирует100% precision на новых данных. Valid46 остаётся development.
