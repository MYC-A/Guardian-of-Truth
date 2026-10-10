# Cascade: logprob-триаж + бюджетная эскалация в B2 — 2026-10-10

Ветка `cascade/logprob-budget-20261010` от `perf/qwen-inference-20261010` (`1ae6fb30`).
**Статус: реализовано и покрыто offline-тестами; на GPU НЕ запускалось, F1/время не измерены.**
Production CLI (`guardian_truth.submission.cli`), промпты B2, checkers и готовый ZIP не изменены.

## Почему другой подход

Цифры из уже опубликованного legacy B2 прогона
(`outputs/qwen_gpu_pilot_20261010/legacy_rep1_8911b35f.zip`, 179 calls, 1743.8 s):

| Измерение | Значение |
|---|---|
| Сгенерировано токенов | 118 421 (pre_blind 66 057, review 29 882, F 8 890, прочее ~13.6k) |
| Суммарный decode / prompt time запросов | 12 353 s / 809 s → decode ≈ 94% |
| Decode на поток, median / max | **9.6 / 38.4 tok/s** |
| Aggregate decode (118 421 / 1743.8) | ≈ 68 tok/s при 8 занятых слотах |
| Prefill на запрос, median | ≈ 930 tok/s |

Вывод: один поток даёт до ~38 tok/s, восемь параллельных — всего ~68 tok/s суммарно
(×1.8 вместо ожидаемых ×5–8 у memory-bound decode). Узкое место — batched decode
движка для гибридной архитектуры Qwen3.8, а не клиент и не очередь. Поэтому:

1. Нужно **меньше генерировать**: решение одним токеном с logprobs вместо тысяч токенов.
2. B2 тратить **только там, где он нужен**, и в пределах явного дедлайна.
3. Отдельно проверить движок с настоящим batched decode (vLLM).

## Что сделано

`src/guardian_truth/cascade/`:

- `triage.py` — запрос с `max_tokens=1`, `logprobs/top_logprobs=20`, P(нарушение) из
  распределения первого токена (`0`/`1`). Две формулировки с противоположной полярностью
  (`violation`, `compliance`), среднее снимает yes-bias. Раскладка сообщений
  prefix-cache friendly: общий system для всех строк → диалог+ход (общий для обеих
  формулировок) → вопрос в самом конце. `fit_prompt` сохраняет политику (до 60% бюджета)
  и самые новые блоки истории, огромные блоки режет head+tail, последний блок всегда
  сохраняется; при HTTP 400 (переполнение контекста) один повтор с половинным бюджетом.
- `controller.py` — чистая логика без I/O:
  - порядок эскалации: нечитаемый триаж первым, затем p по убыванию;
  - `Dispatcher` допускает следующую строку в B2, только если
    `now + оценка_строки ≤ deadline − reserve`; оценка консервативная
    (max(среднее с prior, p90 наблюдённых)); в hard-deadline зависшие строки бросаются;
  - `final_label`: валидный B2 сохраняется как есть; без B2 — `p ≥ direct_threshold`;
    опционально OR-правило (B2=0 → 1 при `p ≥ or_threshold`) для FN.
  - **Гарантия по умолчанию**: при достаточном бюджете и выключенных `skip_below` /
    `or_threshold` ответ совпадает с B2 построчно. Каскад может только потерять строки
    по дедлайну, но не изменить решение B2.
- `backend.py` — `TriageClient`; `VllmServer` (owned `vllm serve`, loopback, свой API key,
  offline env, prefix caching, проверка served model/context); `VllmLocalClient` —
  тот же контракт, что у `LocalClient` (точный подсчёт токенов перед каждым completion
  через `/tokenize` с chat template, тот же cache key/singleflight/отказ по контексту),
  поэтому B2 эскалация на vLLM идёт без изменений B2.
- `cli.py` — `--mode triage-only|cascade`, `--backend llamacpp|vllm`, `--deadline`
  (весь процесс, default 1680 s), `--reserve`, `--b2-prior-seconds`, пороги.
  Лейблы не читаются (используется `read_rows` из submission).

`scripts/engine_probe.py` — 10-минутный тест: aggregate tok/s при 1/2/4/8 параллельных
запросах на уже запущенном сервере. Вердикт `ENGINE_DOES_NOT_BATCH`, если ×8 < 2× от ×1.

`scripts/cascade_calibrate.py` — offline: AUC триажа (общий и по формулировкам),
лучший порог, OR-порог и **кривая F1 от k** (k строк получают B2 в порядке приоритета;
время ≈ k × стоимость строки / workers). Это главный инструмент выбора бюджета.

Тесты: `tests/test_cascade.py` — 14 passed (полярность, нечитаемый ответ, обрезка,
общий префикс, сохранение B2 по умолчанию, порядок, оценщик, бюджет/дедлайн/зависание,
повтор при переполнении, калибровка).

## План запуска на GPU (по порядку, каждый шаг — отдельный output)

1. **Engine probe, llama.cpp** (~10 мин): поднять текущий сервер, затем
   `python scripts/engine_probe.py --base http://127.0.0.1:PORT --model "<MODEL>" --api-key-env KEY`.
2. **Triage-only на valid46, llama.cpp** (оценка ~5–8 мин: ≈450k prefill-токенов на первую
   формулировку при ~1–2k tok/s; вторая в основном из кэша):
   ```bash
   export PYTHONPATH=src:. PYTHONUTF8=1
   python -m guardian_truth.cascade.cli --mode triage-only --input valid.parquet \
     --output /workspace/guardian/results/triage_NEW.parquet \
     --work-dir /workspace/guardian/results/triage_NEW --root /workspace/guardian/runtime
   python scripts/cascade_calibrate.py --scores /workspace/guardian/results/triage_NEW/triage_scores.jsonl \
     --labels valid.parquet --b2 <legacy_rep1>/predictions.parquet --output calib.json
   ```
   Решение: если AUC < 0.70, триаж годится только как порядок эскалации, не как классификатор.
   Если кривая F1(k) выходит на плато F1 B2 при k ≪ 46 — каскад экономит время пропорционально.
3. **Cascade на valid46** с откалиброванными порогами и `--deadline 1680`; сравнить с B2:
   F1, полный набор ID, owners (B2 / TRIAGE / DEFAULT_ZERO), wall.
4. **vLLM-профиль** (отдельная окружение/упаковка): HF-чекпойнт Qwen3.8-27B в FP8
   (на A100 — weight-only, Marlin) или GPTQ/AWQ-Int8, ≤ ~30 GB под архив 40 GB.
   Сначала engine probe (ожидание: масштабирование ×5+), затем triage-only, затем cascade
   с `--backend vllm --vllm-model <dir> --b2-prior-seconds <по probe>`.
   Числа B2 на другом движке/квантизации — новая версия, нужен полный matched valid46.

Критерии принятия: не хуже B2 по F1 на valid46 при wall ≤ 28 мин **и** гарантированная
запись полного ответа при любом размере входа (дедлайн). Valid46 — development,
один TP ≈ 0.03 F1; пороги, подобранные на нём, нужно перепроверить на отдельном наборе.

## Ограничения и риски

- Logprobs в chat completions у llama.cpp b11459 и vLLM поддерживаются; если сервер
  не вернёт `top_logprobs`, строка получает `p=None` (эскалируется первой, без B2 → 0).
- Одна цифра без рассуждения слабее B2 на сложных строках — поэтому триаж прежде всего
  задаёт **порядок** B2, а не заменяет его.
- `--reasoning off` у llama.cpp и `enable_thinking=False` у vLLM: тот же режим, что в B2.
- Брошенные по дедлайну строки получают решение триажа; процесс завершается `os._exit(0)`
  после записи результатов, чтобы не ждать HTTP timeout зависших запросов.
