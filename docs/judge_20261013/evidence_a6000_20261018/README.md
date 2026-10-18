# Свидетельства GPU-исследования 18.10.2026

Компактные receipts не содержат текстов prompt/response, raw notes или секретов.
Текстовые receipts нормализованы в LF для одинаковых SHA256 на Windows/Linux;
содержимое исходных архивов не нормализуется и имеет отдельные контрольные суммы.
Полные runs скопированы с предоставленного сервера off-box; пути и SHA256 архивов
перечислены в итоговых отчётах. Наборы и sidecar gold восстанавливаются по
`../eval_data_20261018/SOURCES.lock.json` и data manifests; labels не передаются модели.

- `first-series-exact-scores.jsonl.gz`:963 строки dev520/regression397/valid46,
  с primary/final scores, exact/delivery/prepass status и input/base SHA.
  Valid46 полностью пересекается с397.
- `replay-exact-scores.jsonl.gz`:4680 свежих exact final scores, 520 rows×3 arms×3
  final replays. Generated notes одни и те же. Не являются4680 независимыми задачами.
- `dev_replay_r*.analysis.json`: все confusion matrices, AUC/AP, paired grouped CI,
  per-domain analyses, delivery/usage/source hashes и numerical diagnostics.
- `cpu-{local,linux}-25.{log,json}`: фактические25 тестов, команды, версии, exit0.
  Это целевые тесты, не full CI. GPU exact coverage измерено отдельно реальными
  vLLM calls и не вытекает из fake-engine CPU tests.
- `RUNTIME_READY.json`, `WEIGHTS_VERIFIED.json`: установленное отдельное окружение
  и проверка21 файлов закреплённой модели. Драйвер/окружение сервера не менялись.
- `MANIFEST.json`: размеры и SHA256 опубликованных свидетельств, count checks.

Проверенные команды тестов (с PYTHONPATH, указывающим на src активного checkout):

```text
python -m unittest tests.test_judge_note_replay tests.test_judge_partial_audit tests.test_judge_gpu_analysis tests.test_judge_answer_review
```

Модельный replay читает только source run, config и weights. Gold-side анализ
выполняется отдельной командой после получения полного exact coverage:

```text
python scripts/replay_judge_notes_20261018.py --run SOURCE_RUN --model MODEL --out FRESH_REPLAY
python scripts/analyze_judge_note_replay_20261018.py --replay FRESH_REPLAY --source-run SOURCE_RUN --inputs INPUTS.csv --labels-file labels.jsonl --out ANALYSIS.json
```

Повторное использование raw generations здесь намеренно: измеряется приём notes
при сохранённых генерациях. Эти запуски не заменяют полные offline-повторы,
matched blind/open A/B/C/D, отложенный eval или конкурсный runtime.
