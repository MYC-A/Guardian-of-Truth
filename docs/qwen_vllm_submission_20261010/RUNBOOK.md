# Guardian B2 — новый offline кандидат vLLM FP8 graphs16

Это отдельная сборка полного legacy B2. Старый GGUF не используется. Backend:
vLLM0.19.1, Transformers5.8.0, официальный Qwen/Qwen3.8-27B-FP8 revision
017b9c7af6b5689d5dd426a76e0bc077eb5ca20a, 16 workers/slots, context32768,
thinking off, prefix caching, chunked prefill, CUDA graphs. Prompts/stages,
admission и output recovery остаются прежними. При отсутствии восстановленной
метки выбранный пользователем fallback0 сохраняется и отражается в receipts.

## Интерфейс полного архива

```bash
pip install .
python scripts/predict.py --input /data/test.parquet --output /data/predictions.parquet
```

Поддерживаются CSV/Parquet по содержимому. Output — настоящий Parquet с id,label,
все входные ID и их порядок сохранены. Gold и прочие колонки не передаются в
pipeline; используется immutable clean snapshot. Существующий output запрещён.
Пустой input не запускает GPU. Optional --work-dir указывает новый writable
каталог ВНЕ архива с diagnostics/caches. По умолчанию создаётся fresh temp dir.
Основной deadline1800s; startup600s внутри него, HTTP600s. Для большего private
набора прохождение общего platform limit ещё должно быть измерено.

## Runtime и ограничения проверки

Архив содержит Linux x86_64 CPython3.12, pinned wheel dependencies, private
native libraries и GNU toolchain/headers для offline compilation. Host supplies
NVIDIA driver/libcuda, он не включается. Исходная среда Ubuntu24.04/A10080GB.
Dockerfile использует Ubuntu24.04. Для direct platform run совместимость host
driver, native helper executables и cold compilation требуют фактической проверки.
CUDA toolkit и ключи API не нужны для обычного model inference; поддержка
дополнительных JIT путей должна подтверждаться offline GPU-прогоном.

На research venv graphs16 valid46:16TP/0FP/7FN, F1.8205, whole677.55s,
0 transport errors/default-zero. Это один development repetition и **не**
проверка данного нового архива. Есть один output-limit отказ blind extraction;
bounded source gaps B2 сохранены. Не обещать прирост качества либо private runtime.

## Сборка и транспорт

GitHub workflow: .github/workflows/qwen-vllm-runtime.yml. CPU CI устанавливает
185 hash-locked wheels, собирает portable runtime, проверяет imports/child Python,
публичный empty input и тесты. Artifact guardian-vllm-fp8-runtime-<SOURCE_SHA>
содержит guardian-vllm-runtime.zip, manifests, requirements freeze и CPU receipts.
**Это PARTIAL_RUNTIME_TRANSPORT, без model weights; его нельзя загрузить в конкурс.**

На сервере полная prepare фаза дополнительно хэширует реальные FP8 assets.
Runtime экспортируется отдельно, веса можно получить с сервера либо прямо HF.
На ПК обе версии downloader используют pinned manifest, несколько потоков,
resumable .partial и проверку полного SHA перед atomic publication.

Рабочая папка ПК:
`A:\Guardian-submissions\vllm-fp8-build-20261010`

Модель:
`model\017b9c7af6b5689d5dd426a76e0bc077eb5ca20a`

Прямое скачивание:

```powershell
python scripts/download_vllm_model_http.py --manifest A:\Guardian-submissions\vllm-fp8-build-20261010\MODEL_MANIFEST.json --destination A:\Guardian-submissions\vllm-fp8-build-20261010\model\017b9c7af6b5689d5dd426a76e0bc077eb5ca20a --workers 8 --duration 7200
```

Не запускать два downloader одновременно на одну папку. Незавершённые parts
сохраняются; повтор команды продолжает их. MODEL_EXPORT_DONE.json означает,
что все78 assets проверены; количество includes66 weight shards и metadata.

После завершения model+runtime использовать scripts/assemble_vllm_submission.py:
проверяются обе части, root-relative paths, exact file set, ZIP CRC/SHA,
cap строго40_000_000_000 bytes и отсутствие перезаписи существующего output.
Новый полный ZIP имеет model/<REV>, runtime/, src/, scripts/predict.py,
pyproject.toml в корне. Нет benchmark inputs, gold, predictions, API/private keys.

## Что проверить после объединения

1. Успешные runtime CPU receipts и полный model manifest.
2. Final ZIP SHA, размер, modes644/755, source/engine/model identity.
3. pip install . без доступа к index; empty input через публичный script.
4. Relocated Linux runtime, fresh cache и полный valid46 через публичный script
   на A10080GB, с recording whole wall/startup/compile/calls/gaps/fallbacks.
5. При другом host/container — совместимость driver/glibc/helper tools.

До этих проверок статус — assembled candidate, не validated deployment.
Старый guardian-qwen-b2-output-recover_new.zip хранится как резерв.
Большие runtime/weights/ZIP не коммитить в Git; публиковать code и receipts.
