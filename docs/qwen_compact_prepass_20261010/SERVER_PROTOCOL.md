# Замороженный план первого live сравнения

Ни один вызов этой фазы пока не выполнен. Адрес/ресурсы сервера пользователь
предоставит отдельно. Не подключаться к старому выключенному серверу и не
поднимать новый самостоятельно.

## Фиксируем до inference

1. Этот commit/clean branch и хэши фактически запущенных source files; profiles
   `legacy`, `dedup`, `compact`, max pre3400/3400/1700. Review1700, F700,
   R_fix/checkers/admission/recovery0 одинаковы. F-extraction не выключается
   одновременно с compact: это другая абляция.
2. Исходный valid46: SHA256
   `8e730cc999a6cf07c3f17f273300a17ce16539c5b6166885e74b41e93cfc47ba`.
   Полный набор, gold только после inference. Labels/IDs не подаются в prompts.
   У датасета статус development/diagnostic.
3. Actual model/checkpoint Qwen3.8-27B-Q8_0, GGUF SHA
   `aab65c67ef0dad127960efef9247f1832bca105faa1c7a052cc039b223cf86a1`;
   тот же llama.cpp/runtime. Зафиксировать GPU/driver/native build/props.
4. Workers8, context32768 per slot, reasoning off, temperature0, FlashAttention
   и batching либо одинаковые defaults, либо отдельный явно записанный профиль.
   Без изменения serving settings между arms. Actual tokenizer + reserved
   completion preflight остаётся обязательным; без silent truncation.
5. Отдельные NEW output/work directories на каждый arm/rep. Cache identity
   включает полный request/model/attempt; изменённый reviewer wire не имеет
   права использовать прежний reply. Same pre в dedup допускает compatible
   exact-request cache для quality диагностики, но cached timing не считать
   live speed. Для timing inference cache выключен/fresh; server prefix-cache
   state/cold start явно записывается и не смешивается между arms.

## Порядок и критерии

Первым сделать один короткий schema/runtime smoke, затем полный **legacy46 и
compact46** с одинаковыми serving settings. При технической ошибке исправить
причину как новую версию/arm; не сохранять мнимую предсказанную оценку по gold.
После полного первого сравнения решить, стоит ли оплачивать dedup46 и повторы.
Не оставлять бесконечную очередь пилотов. Все существующие outputs сохранять.

Один повтор — feasibility, не основание менять default. Для принятия compact:
минимум3 полных matched repetitions, median whole-script cold wall time не
больше85% baseline, cumulative TP не меньше baseline, cumulative FP не больше,
median binary F1 не меньше,100% aligned binary output, нет новых confirmed
unsupported cause/target regressions. Если эти критерии не достигнуты, сохранить
кандидат отдельно и оставить legacy. Не менять thresholds после результатов.
При статистически неопределённом сравнении или отсутствии независимого нового
holdout не заявлять универсальный перенос/улучшение. Новый holdout должен быть
размечен по source до outputs и содержать отрицательные контрасты.

Считать отдельно: generated pre tokens, delivered/discarded pre, schema invalid,
source/context gaps, RAW_MODEL_DECISION/DEFAULT_ZERO, component/checker cost,
input/output tokens, prefill/decode time, full cold wall time, TP/FP/FN/TN/F1,
paired gained/lost rows и причины/targets. No-answer→0 входит в полный denominator.
Нельзя считать summed parallel call latency временем всего скрипта.

## Команды на Linux после проверки путей

`CODE_ROOT` — отдельный checkout этой ветки; `RUNTIME_ROOT` — ранее проверенный
распакованный runtime/model archive, не перезаписанный новым кодом.
`PYTHON_BIN` — совместимый interpreter/venv с pinned зависимостями. Эти пути
сначала обнаружить на предоставленном сервере, а не угадывать по старому host.

```bash
export PYTHONPATH="$CODE_ROOT/src:$CODE_ROOT"
export PYTHONDONTWRITEBYTECODE=1
export PYTHONUTF8=1

"$PYTHON_BIN" -m guardian_truth.submission.cli \
  --input "$INPUT46" --output "$PHASE/legacy/rep1/predictions.parquet" \
  --root "$RUNTIME_ROOT" --work-dir "$PHASE/legacy/rep1/receipts" \
  --pre-profile legacy --workers 8 --context 32768

"$PYTHON_BIN" -m guardian_truth.submission.cli \
  --input "$INPUT46" --output "$PHASE/compact/rep1/predictions.parquet" \
  --root "$RUNTIME_ROOT" --work-dir "$PHASE/compact/rep1/receipts" \
  --pre-profile compact --workers 8 --context 32768

"$PYTHON_BIN" "$CODE_ROOT/scripts/qwen_submission_reproject.py" \
  --input "$INPUT46" --traces "$PHASE/compact/rep1/receipts/traces.jsonl" \
  --output-dir "$PHASE/compact/rep1/score" --output-recovery fallback-zero \
  --expected-input-sha256 8e730cc999a6cf07c3f17f273300a17ce16539c5b6166885e74b41e93cfc47ba
```

Создать output parents заранее. Scorer требует полный expected ID set,
source fingerprints и binary labels; не скрывает missing/failed rows.
Соответствующий baseline score — та же команда с legacy paths. `--attach`
допустим только как отдельная warm timing фаза с подтверждённым alias/context;
её wall time нельзя сравнивать с cold starts.

После измерений commit+push code/protocol/receipts/results с independently
checked cause regressions. Новый конкурсный ZIP собирать и проверять отдельной
фазой после выбора профиля, не заменять проверенный старый архив заранее.
