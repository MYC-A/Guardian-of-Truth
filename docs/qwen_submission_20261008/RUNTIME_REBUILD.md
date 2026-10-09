# Восстановление Linux runtime без прежнего сервера

Сервер выключен. Его SSH, диск и GPU этот путь не использует. Обычный CPU runner
GitHub Actions компилирует CUDA-код для A100 (`SM80`) и собирает отдельный архив
окружения. Веса28.6GB скачиваются отдельно из зафиксированного источника на дискA.
Итоговый конкурсный ZIP получается только после проверки и соединения этих частей.

Это **новая сборка окружения**, а не восстановление прежнего бинарника побайтно.
Политики, B2-промпты, wire-контракт, лимиты ответов и default8slots сохраняются.
Новые версии Python-зависимостей проверяются на полном replay двух valid46 фаз.
Новые ответы Qwen и скорость новой сборки без GPU не измерены. В manifest эта
граница записана как `GPU_INFERENCE=NOT_EXECUTED`.

## Зафиксированные компоненты

| Компонент | Значение |
|---|---|
| ОС/ABI | Linux x86_64 Ubuntu24.04, CPython3.12 |
| CUDA toolchain | `nvidia/cuda:12.8.1-devel-ubuntu24.04` |
| Digest linux/amd64 image | `sha256:4b9ed5fa8361736996499f64ecebf25d4ec37ff56e4d11323ccde10aa36e0c43` |
| llama.cpp | `f498f864fbc0472004ee1c3616c1188c68eb157f` |
| CUDA target | `CMAKE_CUDA_ARCHITECTURES=80`, checked against embedded cubins |
| Python wheels | `submission/requirements-runtime.txt`, every runtime dependency pinned |
| Модель | `ggml-org/Qwen3.8-27B-GGUF`, revision`71bc7b627595dc8a91039addd9c791ae548d6747` |
| GGUF | `Qwen3.8-27B-Q8_0.gguf`,28595763648bytes |
| GGUF SHA256 | `aab65c67ef0dad127960efef9247f1832bca105faa1c7a052cc039b223cf86a1` |

SHA Actions checkout/setup-python/upload/attest также закреплены в YAML. Digest
официального CUDA image проверен через Docker Registry. Требование явно выбирать
CUDA architecture на машине без GPU описано в [документации pinned llama.cpp](https://github.com/ggml-org/llama.cpp/blob/f498f864fbc0472004ee1c3616c1188c68eb157f/docs/build.md#override-compute-capability-specifications).

## Сборка и проверка

Workflow: `.github/workflows/qwen-submission-runtime.yml`. Автозапуск ограничен
веткой `submission/qwen-offline-20261008` и изменением собственных build inputs;
есть ручной `workflow_dispatch`. Это ordinary`ubuntu-24.04`runner, не платная
GPU-машина. Timeout45минут; неудачная сборка не становится готовым runtime.
До CUDA pull проверяется минимум18GB свободного места у рабочего дерева и Docker.
Cleanup разрешён только на ephemeral GitHub-hosted Linux runner для четырёх явно
названных лишних SDK paths. После завершения build удаляются только собственные
llama source/build, venv, wheels, smoke intermediates и использованный CUDA image;
runtime, manifest, логи и подписываемые artifacts сохраняются. Перед DockerCOPY
снова проверяется запас места по фактическому размеру runtime.

Workflow выполняет:

1. Устанавливает pinned binary wheels в изолированный CPython3.12 venv и проверяет
   `pip check`; checkout read-only внутри CUDA build container.
2. Checkout pinned llama.cpp; compile `llama-server` CUDA SM80 без обнаружения GPU.
3. Сохраняет CPython, whitelist site-packages, stdlib и рекурсивные native `.so`.
   Все отсутствующие userspace зависимости — ошибка. `libcuda`/`libnvidia` и CUDA
   stubs в артефакт не входят: настоящий driver предоставляет GPU-хост.
4. Проверяет native imports и настоящий public entrypoint на пустом CSV с Parquet
   output; `pip install . --no-index` использует stdlib-only build backend. Запускает
   actual rebuilt`llama-server --version` через bundled ELF loader, проверяет
   returncode0 и source revision, если доступен реальный NVIDIA driver.
   Только точная loader-ошибка отсутствующего host driver даёт
   `NOT_EXECUTED_MISSING_HOST_DRIVER`. Ошибки userspace библиотек, символов
   и crashes остаются фатальными. Stub для исполнения не используется.
5. Запускает boundary/wire tests, POSIX signal ownership и полный точный raw replay
   сохранённых baseline46/speed16-46. Сеть replay блокируется; отсутствие request
   hash не допускает fallback. Replay — проверка обработки, не новое качество.
6. Создаёт реальный Docker image и запускает его public entrypoint на CPU при
   `--network=none --read-only`, unprivileged user. Пустой вход не вызывает Qwen.
   Дополнительно обе full46 raw replay фазы выполняются внутри этого image через
   bundled CPython; источники диагностики монтируются read-only только на время
   теста и не попадают в артефакт.
7. Создаёт `guardian-qwen-a100-runtime.tar.gz` без `model/`, проверяет file hashes,
   подписывает архив и manifest через GitHub Sigstore build provenance. Подробнее:
   [официальная документация action](https://github.com/actions/attest-build-provenance/tree/e8998f949152b193b063cb0ec769d69d929409be).
8. Загружает runtime, manifest, подпись и CPU receipts в artifact с retention3days.

`BUILD_PROVENANCE.json` содержит actual GCC/G++/CMake/nvcc/Python versions, dpkg
inventory, code commit, source revision, compile flags и embedded CUDA targets.
Ubuntu packages устанавливаются из текущего репозитория и их версии записываются.
Поэтому здесь обещается воспроизводимый путь и проверенная идентичность полученных
файлов, а не битово одинаковые результаты любой будущей компиляции.

## Локальное соединение частей на дискеA

Выполняемый операторский supervisor `scripts/complete_qwen_submission.py` может
закончить весь путь самостоятельно: ждёт конкретный успешный CI, скачивает его
artifact, проверяет transport/tar/manifest/commit, соединяет проверенные веса,
создаёт `.zip.partial`, проверяет все байты и только затем атомарно публикует ZIP.
Опрос CI — раз в60секунд, общий предел90минут; failed CI останавливает процесс,
автоматических rerun и перезаписи прежних файлов нет. Статус и logs лежат в новом
`--phase` каталоге. `READY_VERIFIED_PACKAGING` означает готовую упаковку;
GPU-инференс, качество и time limit остаются отдельными проверками.

На2026-10-09 целые исходные веса уже доступны по нормальному имени
`A:/Guardian-submissions/model/Qwen3.8-27B-Q8_0.gguf`: это hardlink на проверенный
browser download, а не ещё одна28.6GB копия.

После успешного workflow скачать его artifact целиком. Внутри находится runtime
tar.gz, внешний SHA256, `RUNTIME_MANIFEST.json` и `runtime-attestation.sigstore.json`.
GitHub Actions artifact ZIP — транспортный контейнер; **организаторам его не
отправлять**: весов в нём нет.

Для проверки подписи доступен:

```powershell
gh attestation verify A:\Guardian-submissions\runtime-build\guardian-qwen-a100-runtime.tar.gz --repo MYC-A/Guardian-of-Truth
```

Не принимать файл из чужого run/commit лишь по знакомому имени. Проверять привязку
artifact к ожидаемой ветке/HEAD/run и archiveSHA256; подпись подтверждает происхождение,
а не качество модели.

На Windows helper использует stdlib и не требует CUDA/модельных библиотек:

```powershell
python -X utf8 scripts/rebuild_qwen_runtime.py extract `
  --archive A:\Guardian-submissions\runtime-build\guardian-qwen-a100-runtime.tar.gz `
  --destination A:\Guardian-submissions\qwen-runtime-rebuilt `
  --expected-sha256 <ПРОВЕРЕННЫЙ_SHA256_RUNTIME_ARCHIVE>

python -X utf8 scripts/rebuild_qwen_runtime.py assemble `
  --runtime A:\Guardian-submissions\qwen-runtime-rebuilt `
  --model A:\Guardian-submissions\model\Qwen3.8-27B-Q8_0.gguf `
  --destination A:\Guardian-submissions\qwen-final-stage-rebuilt

python -X utf8 scripts/build_qwen_submission.py zip `
  --stage A:\Guardian-submissions\qwen-final-stage-rebuilt `
  --destination A:\Guardian-submissions\guardian-qwen-b2-rebuilt.zip
```

Все output paths новые; существующие каталоги/архивы не перезаписываются. Extract
проверяет transportSHA, разрешает только обычные файлы/каталоги, запрещает traversal,
Windows ADS и любые symlink/hardlink entries; размер извлечения ограничен4GB. Runtime
manifest проверяется целиком до публикации каталога. ELF headers должны быть Linux
x86_64; driver/stub inclusion отвергается даже при совпавшем inventory.

Assembly сначала проверяет **полный** SHA28595763648-byte GGUF, затем копирует
runtime и делает hardlink весов на том же дискеA. При невозможности hardlink выходит
с ошибкой, не создаёт молча ещё одну28.6GB копию. Новый full`MANIFEST.json` совместим
с `build_qwen_submission.py`: weight hash и inventory повторно проверяются перед
ZIP. ZIP сохраняет корневые paths, ZIP64 и Unix permissions755/644 независимо отNTFS.
Runtime archive/reference не является подставным model fixture; production сборка
не создаёт ни фиктивных весов, ни готовых предсказаний.

## Что остаётся непроверенным без GPU

- Новые model predictions и elapsed time с новым CUDA binary.
- Фактическая совместимость host NVIDIA driver и GPU memory profile на платформе.
- Hidden input length/distribution и укладывание всей оценки в30минут.

CPU checks могут доказать корректность установки, импорта, I/O, Unix permissions,
обработки прежних raw ответов и manifest. Они не доказывают полное GPU end-to-end
качество или соблюдение временного лимита на неизвестном тесте. Исторические server
results сохраняются отдельно, новая сборка не наследует их как свои измерения.

## Первый реальный CI отказ и исправление, 2026-10-09

Run37812838193 от8октября завершился после компиляции CUDA при финальном link
`llama-server`: GNUld не находил `libcuda.so.1` и оставлял `cuMem*` references
неразрешёнными. Это не отказ загрузки весов и не ошибка Qwen-предсказаний.
Pinned llama.cpp с включённым VMM требует `CUDA::cuda_driver`; toolkit stub
называется `libcuda.so`, но его ELF SONAME — `libcuda.so.1`.

Исправленный builder создаёт отдельный link-only SONAME symlink **вне stage**
и передаёт `-Wl,-rpath-link,<dir>`. Ни driver, ни stub не входят в архив и не
используются для исполнения CPU smoke. VMM не отключён. Для built ELF задан
`CMAKE_INSTALL_RPATH=$ORIGIN` и `CMAKE_BUILD_WITH_INSTALL_RPATH=ON`; readelf
дополнительно отклоняет посторонние RPATH/RUNPATH. POSIX regression использует
настоящий GCC для проверки транзитивной зависимости и отсутствия runtime path.
Исправление ещё требует успешного нового CI; локальный unit pass его не заменяет.

## Исправление проверки происхождения vendor files

В точных wheels `pydantic==2.11.7` и `jsonschema==4.25.1` воспроизведены ложные
отказы первоначального final verifier: публичный пример пароля в docstring
считался private credential, а vendor `benchmarks` — нашими research data.
Это дефект операторской проверки, отдельный от compile/link и модели.

`PINNED_VENDOR_FILES.json` фиксирует17 объявленных зависимостей и4669 файлов:
официальные Linux CPython3.12 wheels проверены по PyPI SHA256, затем вычислены
точные file hashes. Любой vendor scope требует совпадения **содержимого**, а не
имени библиотеки или текста примера. Changed/unregistered vendor files
отклоняются; наши private/research sources остаются под прежними проверками.
Generated pip metadata проверяется отдельно. Registry — операторский артефакт,
не добавка к модельному pipeline и не доказательство отсутствия любых секретов.
Сборка CI не перезапускается из-за этой проверки. Первый completion watcher
остановлен до скачивания и помечен SUPERSEDED; новая phase использует исправленный
verifier, тот же CI run и те же проверенные веса.

## Второй CI отказ: notice path, 2026-10-09

Run37869021647 завершил compile/link на100%, RPATH audit и сбор native/Python
зависимостей, но остановился на `CUDA_REDISTRIBUTABLE_LICENSE_MISSING`.
Сборщик неверно предполагал наличие `EULA.txt` в двух локальных toolkit путях.
Этот отказ не является ошибкой весов или отрицательным GPU-экспериментом.

Теперь в repository и final package включён неизменённый официальный
[CUDA12.8.1 EULA PDF](https://docs.nvidia.com/cuda/archive/12.8.1/pdf/EULA.pdf):
228502bytes, SHA256`94736434ff4409100167951f4a76c0a6ab9ba98cf75b41bb74fae53610d9940b`.
`preflight` проверяет точные байты до Docker/CUDA compilation; build повторяет
эту проверку перед clone. PDF сохраняется как binary Git artifact без EOL
преобразований. Отсутствующий/изменённый notice теперь fail-fast, а не late fail.

После успешной компиляции записывается `ENGINE_COMPILE_RECEIPT.json`. При позднем
отказе workflow сохраняет отдельный `FAILED_COMPILE_SNAPSHOT` с compiled binaries
и configuration. Он не содержит ready runtime manifest и не принимается обычным
downloader/assembler как успешный результат. Проверки cuobjdump/CPU install/
replay/Docker нового run по-прежнему требуют собственного успешного исполнения.

## Использование runtime, скачанного браузером

После успешного CI37872100649 автоматический HTTP download оборвался с
WinError10054. Пользователь сохранил полный transport ZIP вручную на дискеA.
`complete_qwen_submission.py --local-artifact <ZIP>` использует этот файл без
повторного скачивания: сначала проверяет successful run/exact commit, затем
размер и полный SHA256 по независимым authenticated GitHub artifact metadata.
Далее выполняются те же transport/tar/manifest/assembly/final gates.

Manual source:1157010908bytes, SHA256
`73a193fc779d24180d06a1a687a9e58450dc88f846e99e962950dc846d0e1db6`.
Phase: `A:/Guardian-submissions/completion-manual-6b1413f1/`.
Исходный failed transport phase сохраняется отдельно, его partial не принят.
Эта смена способа передачи не меняет runtime bytes, веса, inference prompts
или измеренные предсказания. Final ZIP публикуется только после полной проверки.
