# Проверка новых vLLM прогонов и места для сборки

Проверен remote snapshot `828f60a8` ветки `perf/qwen-inference-20261010`.
Архивы прочитаны через ZipFile без распаковки. CRC корректны; метрики пересчитаны
по исходному valid.parquet, проверены ровно 46 уникальных IDs. Независимый субагент
повторил проверки запросов, receipts, полноты и wall times.

| Профиль | TP/FP/FN/TN | F1 | Полное время |
|---|---|---:|---:|
| Historical llama.cpp Q8 B2 |15/0/8/23|.7895|1743.83s|
| vLLM FP8 eager 8×8 |15/1/8/22|.7692|1417.46s|
| vLLM FP8 CUDA graphs 16×16 |16/0/7/23|.8205|677.55s|

Ускорение graphs16 против eager8 — 2.09×; против исторического native — 2.57×.
Полное время включает startup, подтверждено outer start/end и exit0. Logs
подтверждают Marlin weight-only FP8, FlashAttention2 и CUDA graph capture.
В graph logs общий torch.compile занимает70.37s; число51s в исходном отчёте
не следует называть полным временем compilation без пояснения подэтапа.

## Что сохранилось и чего эти результаты не доказывают

Production src после f70a589f не менялся. Adapter убрал unsupported logging flag
и добавил startup-timeout. Все46 начальных pre-blind wires и64 turn-rules wires
совпадают между двумя фазами; downstream reviewer может измениться вслед за
ответами extraction. Model identity, request/wire hashes, native token preflight
и фактический prompt usage проверены. Transport не обрезает контекст молча.

Оба новых прогона имеют0 transport failures и0 DEFAULT_ZERO. Однако это не
означает0 технических/семантических gaps:

- Eager: один RAW_MODEL_DECISION после PRIMARY_INFERENCE_FAILURE/admission;
  причина NOT_VALIDATED. Строка всё равно входит в бинарную метрику.
- Graph16: один pre-blind ответ с finish_reason=length и INVALID_JSON;
  injection не выполнена. Final label получен остальными стадиями.
- Bounded pre-blind view имеет complete_input=False на всех46 строках обоих
  прогонов. NOT_EXECUTED_INPUT_BUDGET встречается в12 eager и14 graph16 строках.
  Это сохранённые upstream ограничения B2, не transport truncation.
- Четыре label flips не доказывают ни систематический прирост качества, ни
  статистическую «шумовость». Нужны повторения и cause/target review.
- Engine+quantization отличаются от исторического Q8; attribution одному
  engine невозможно. Между eager8 и graphs16 изменены graphs и concurrency.
- Полный valid46 не подтверждает время private/full competition набора.

Eager research ZIP содержит `../` member paths. Не распаковывать без проверки
путей. Это дефект упаковки receipts, не доказанный дефект runtime. Для нового
submission использовать root-relative paths и проверить архив отдельно.

## Место на A: и очистка

На исходной проверке свободно68.18GB (63.50GiB). Найдены три ненужных файла:

| Файл в A:\Guardian-submissions | Размер bytes | Основание |
|---|---:|---|
|guardian-qwen-b2-rebuilt_1.zip|30395847624|Старая версия до output recovery|
|guardian-qwen-b2-decision-first.zip|30395838923|Отклонённый вариант; NOT_FOR_UPLOAD marker|
|guardian-qwen-b2-20261008-r3.zip.partial|30447402247|FAILED download, preallocated файл|

Перед удалением проверены manifests:5341 runtime entries обоих старых архивов
равны сохранённому `guardian-qwen-b2-output-recover_new.zip`; совпадает model SHA.
Manifests и план сохранены локально в `A:\Guardian-submissions\cleanup_20261010`.
Самостоятельные model/runtime, актуальный output-recovery ZIP и результаты
экспериментов должны сохраняться. Directory totals включают hardlinks и не равны
физически занятому месту; освобождение измерять по Free после удаления.

**Удаление НЕ выполнено:** автоматическая проверка разрешений отклонила сначала
проверенный список точных файлов, затем одну literal-path команду. Дальнейшего
обхода запрета нет. Только три файла выше дают до91.24GB логических bytes;
фактический прирост Free требуется измерить после ручного удаления.

Targeted runtime tests текущего snapshot:103 passed. Production default и
конкурсный архив в этой проверке не менялись. Следующий шаг — повторить graphs16,
проверить причины/coverage, затем offline сборку vLLM с wheelhouse и проверкой
общего размера weights+runtime и запуска на целевой GPU.
