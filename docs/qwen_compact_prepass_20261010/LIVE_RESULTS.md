# GPU pilot — промежуточные результаты

Снимок runtime: `8911b35f8ca895aad5c68bbe1fca7d1721f7f867`.
Qwen3.8-27B Q8_0, native llama.cpp f498f864f/build11459,
A100-SXM4-80GB, 8 workers, 32768 context/slot, CPU threads8.
Профиль default: explicit FlashAttention не выбран по предварительному probe.
Исходный valid46 — development диагностика, не независимый holdout.

## Контроль legacy, rep1 — завершён

| rows | TP | FP | FN | TN | F1 | CLI time |
|---|---|---|---|---|---|---|
| 46/46 | 15 | 0 | 8 | 23 | .789474 | 1743.834s, 29:03.834 |

Время включает запуск/health model server, весь pipeline, остановку model server
и запись predictions. Подготовка сервера, synthetic probes и offline scoring
исключены. Это время limited valid46, не private/full competition test.
Почти 30 минут на46 строках не подтверждают выполнение полного лимита конкурса.

Все46 live labels совпали с сохранёнными binary traces; полный ID set уникален.
Offline reproject ничего не изменил: before/after одинаковы, changes=[].
Они означают живую запись и повтор той же projection, а не эффект ремонта.
Missing labels, RAW_MODEL_DECISION и DEFAULT_ZERO — по0.
179 model calls, 686653 input tokens, 118421 output tokens.
Все179 receipts: HTTP200/finish_reason=stop.

| stage | calls | input tokens | output tokens |
|---|---|---|---|
| blind pre | 46 | 178705 | 66057 |
| reviewer | 46 | 329705 | 29882 |
| turn_rules_context_v3 | 64 | 91212 | 8890 |
| остальные checkers/verifiers | 23 | 87031 | 13592 |

Blind pre даёт55.78% генерации, reviewer25.23%. Сокращение pre output имеет
измеримое основание, но эти доли не равны возможному wall speedup: input,
очередь, shared GPU compute и зависимые стадии остаются. Средняя генерация,
делённая на весь CLI wall,67.91tokens/s; это не isolated decode TPS.
Сумма call seconds перекрывается между workers и не является временем прогона.

Export original bytes SHA256:
`5c9697f0802f75a4038752493d0f77537dc25412c1e4395c2d244108e93d6724`.
Каждый member проверен по manifest; score независимо пересчитан по actual
predictions.parquet и valid.parquet. Gold не участвует в runtime.

Отдельный субагент подтвердил46 row fingerprints, live label==trace binary,
локальную same-source projection без binary flips,179 уникальных call keys,
completionHTTP179/cachehits0 и суммы usage. Credential patterns в export не
найдены. Root повторил independent analyzer дважды с одинаковым JSON; три
негативных integrity probes (tampered member, missing ID, label/trace drift)
отвергнуты. Это review обработки/метрик, не source-based аудит всех15 причин.

## Остальные arms

Compact rep1 начался после legacy. N0/RF ожидают complete marker обеих arms;
GPU jobs не перекрываются. Для них quality/time метрик здесь пока нет.
N0/RF — отдельная matched пара без blind/F layers; её сравнение с B2 смешивает
удаление стадий с эффектом retrieval. Retrieval — lexical TF-IDF reading aid,
не LSH и не code-issued certificate.

Один ordered legacy→compact repetition — feasibility screen. Для устойчивого
скоростного вывода нужны повторения с чередованием порядка и учётом загрузки,
GPU warmup/page cache. Current running freeze не меняется, default остаётся legacy.
Новый ready competition ZIP по этому промежуточному результату не пересобирается.

## Воспроизведение локальной проверки

```powershell
python -X utf8 scripts/qwen_pilot_summarize.py --bundle outputs/qwen_gpu_pilot_20261010/legacy_rep1_8911b35f.zip --input valid.parquet --arm legacy --output <NEW_JSON_PATH>
```

Скрипт не вызывает модели и не перезаписывает отчёт. Проверяет SHA каждого
export member, input SHA, полный ID set, live labels vs traces и published scorer.
Raw export и independent summary лежат в `outputs/qwen_gpu_pilot_20261010/`.
