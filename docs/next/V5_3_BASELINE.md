# Frozen V5.3 baseline

## Итог

Базовый офлайн-детектор на полном `valid.parquet` получил **F1 0.685714**, precision **1.0**, recall **0.521739** и accuracy **0.760870** (`TP=12`, `FP=0`, `FN=11`, `TN=23`). Это воспроизведение состояния репозитория, а не оценка на независимом hidden test: файл содержит development sample, а его независимость от предыдущей разработки не установлена.

## Frozen source

| Поле | Значение |
|---|---|
| Ветка воспроизведения | `experiment/guardian-next-from-v5_3` |
| Commit | `afb7906c3a3244fbc4196fe5cb2ea18ee86e0d96` |
| Subject | `V5.3` |
| Commit date | `2026-09-08T21:14:55+03:00` |
| Root Git tree | `94601727906daa4bb7411a55e3a36359ede03809` |
| `src/guardian_truth` Git tree | `47d686087499bc9075a789097f82e441c81c96c5` |
| `tests` Git tree | `a6d51fa42b7d31243c8d7bd5ea9e54048302f72a` |
| Tracked source files | 34 |
| Tracked test files | 33 |
| `pyproject.toml` SHA256 | `63e2f0622b41c3c9ef827207d3765f9f1daa255f6d31a9708d402a987ad18930` |

Воспроизведение выполнено в отдельном worktree от точного SHA. Основной worktree не изменялся.

## Окружение

| Поле | Значение |
|---|---|
| Время фиксации | `2026-09-11T21:29:58.1068480+03:00` |
| OS | Microsoft Windows NT `10.0.18362.0` |
| PowerShell | `5.1.18362.145`, Desktop |
| Time zone | Russian Standard Time, UTC+03:00 |
| Python | CPython `3.13.7`, cache tag `cpython-313` |
| Python executable | `C:\Users\Igor\AppData\Local\Programs\Python\Python313\python.exe` |
| CPU | AMD Ryzen 7 5825U, 8 cores / 16 logical processors |
| Display adapter | AMD Radeon (TM) Graphics, driver `31.0.21921.1000` |
| NVIDIA/CUDA discovery | `nvidia-smi` отсутствует; NVIDIA GPU/CUDA этим способом не обнаружены |

Установленные версии, непосредственно относящиеся к запуску:

| Package | Version |
|---|---|
| guardian-truth | 0.2.0, editable from this worktree |
| pytest | 8.3.4 |
| pytest-asyncio | 0.25.0 |
| pandas | 3.0.2 |
| pyarrow | 25.0.1 |
| numpy | 2.4.4 |
| python-dateutil | 2.9.0.post0 |
| tzdata | 2026.1 |

Canonical JSON dependency manifest SHA256: `3b379566cd60f33df9e2089c7c8589a553dff9a903821faf07020268de3ba02b`.

Ожидаемые provider-переменные `GROQ_API_KEY`, `OPENROUTER_API_KEY`, `GEMINI_API_KEY`, `GUARDIAN_BASE_URL`, `GUARDIAN_MODEL`, `GUARDIAN_LOCAL_BASE_URL`, `GUARDIAN_LOCAL_API_KEY` в process environment отсутствовали. Их значения не читались и не записывались. Базовый запуск использовал `--backend none` и не загружал env-файл.

## Данные

`valid.parquet`:

- 46 строк и 45 trajectory groups, определённых префиксом `id` до `::`;
- колонки: `id`, `prompt`, `response`, `label`, `explanation`;
- классы сбалансированы: 23 строки с label 0 и 23 с label 1;
- null есть только в `explanation`: 23 строки;
- размер: 984388 байт;
- SHA256: `8e730cc999a6cf07c3f17f273300a17ce16539c5b6166885e74b41e93cfc47ba`;
- Git blob: `7bfbcc91d31cad30ecfc342404a730adf595e0d3`.

## Команды воспроизведения

Из корня worktree:

```powershell
git rev-parse HEAD
python --version
python -m pip install -e ".[data]"
python -m pytest -q

python scripts/evaluate.py `
  --input valid.parquet `
  --output outputs/next/agent_baseline/evaluate.json

python scripts/predict.py `
  --input valid.parquet `
  --output outputs/next/agent_baseline/predictions.csv `
  --audit outputs/next/agent_baseline/predictions.audit.jsonl `
  --run-report outputs/next/agent_baseline/predictions.run.json `
  --backend none
```

Установка успешно заменила ранее установленный editable package `guardian-truth 0.1.0` версией `0.2.0` из frozen worktree; требуемые data dependencies уже присутствовали.

## Тесты

`python -m pytest -q`:

- **391 passed in 2.05s**;
- collection: 391 tests in 0.20s;
- единственное предупреждение — `PytestDeprecationWarning` от `pytest-asyncio`: `asyncio_default_fixture_loop_scope` не задан. Это не изменило исход тестов, но конфигурацию следует зафиксировать для будущих обновлений pytest-asyncio.

## Полный offline prediction

`scripts/predict.py --backend none` на всех 46 строках:

| Метрика | Значение |
|---|---:|
| TP / FP / FN / TN | 12 / 0 / 11 / 23 |
| Precision | 1.000000 |
| Recall | 0.521739 |
| F1 | 0.685714 |
| Accuracy | 0.760870 |
| Mechanical violations | 12 |
| Unknown/fallback labels | 34 |
| Semantic decisions | 0 |
| Runtime | 0.417944 s |

Runtime configuration: backend `none`, mode `graph`, recovery `off`, threshold `0.5`, score kind `uncalibrated`, budget `null`. Unknown преобразуется в label 0 как фиксированный технический fallback; это не доказательство корректности ответа.

## Existing evaluation matrix

`scripts/evaluate.py` выполняет четыре офлайн-конфигурации на всех 46 строках:

| Arm | TP | FP | FN | TN | Precision | Recall | F1 | Unknown |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| availability | 5 | 0 | 18 | 23 | 1.000000 | 0.217391 | 0.357143 | 41 |
| schema | 8 | 0 | 15 | 23 | 1.000000 | 0.347826 | 0.516129 | 38 |
| combined | 11 | 0 | 12 | 23 | 1.000000 | 0.478261 | 0.647059 | 35 |
| with_provenance | 11 | 0 | 12 | 23 | 1.000000 | 0.478261 | 0.647059 | 35 |

Provenance-arm построил 5753 facts, 78 version edges и 191 arguments; 19 примеров имели arguments. Статусы arguments: 133 `observed_match`, 48 `not_observed`, 4 `scope_conflict`, 6 `different_observed_value`. Диагностика: 20 `ambiguous_call_result_pair`, 27 `unparsed_result_not_indexed`. Эти числа измеряют структурное покрытие, не истинность и не калиброванную уверенность.

## Group-aware benchmark

Существующий `scripts/benchmark.py` нельзя напрямую применить к исходному Parquet:

1. `--input valid.parquet` завершается с `Input must be .jsonl or .csv`.
2. Простая конвертация в CSV завершается `_csv.Error: field larger than field limit (131072)`.
3. Простая конвертация в JSONL завершается `Explicit provenance/group metadata required`.

Для диагностики harness был создан производный JSONL без изменения содержимого `prompt`, `response`, `label`: `group_id` равен префиксу `id` до `::`. Это допущение явно фиксируется и не превращает sample в независимый benchmark.

```powershell
python -c "import pandas as pd; d=pd.read_parquet('valid.parquet'); d['group_id']=d['id'].str.split('::').str[0]; d.to_json('outputs/next/agent_baseline/valid_grouped.jsonl', orient='records', lines=True, force_ascii=False)"

python scripts/benchmark.py `
  --input outputs/next/agent_baseline/valid_grouped.jsonl `
  --output outputs/next/agent_baseline/benchmark_zero.json `
  --scores outputs/next/agent_baseline/benchmark_zero.scores.jsonl `
  --assign-splits --bootstrap-samples 1000 --seed 0 --baseline zero

python scripts/benchmark.py `
  --input outputs/next/agent_baseline/valid_grouped.jsonl `
  --output outputs/next/agent_baseline/benchmark_structural.json `
  --scores outputs/next/agent_baseline/benchmark_structural.scores.jsonl `
  --assign-splits --bootstrap-samples 1000 --seed 0 --baseline structural
```

Hash split дал 32 train, 6 calibration и 8 test строк; в test — 4 positive и 4 negative, 8 независимых по принятому group key групп. Во всём производном наборе 45 групп, exact/whitespace duplicates не обнаружены.

Zero baseline против candidate (`availability,schema,provenance`) на восьми test-строках:

- baseline F1 0.0;
- candidate: `TP=1`, `FP=0`, `FN=3`, `TN=4`, precision 1.0, recall 0.25, F1 0.4;
- delta F1 +0.4, paired group-bootstrap 95% interval `[0.0, 0.857143]`;
- manifest: `d7693e945bb0b9c03d207df5061a75135ce054d826199e43c6f8eaaf0cc19027`.

Structural baseline против того же candidate:

- baseline F1 0.666667, candidate F1 0.4;
- delta F1 -0.266667; один regression, ноль corrections;
- manifest: `ca8b51b31963ccdd1d62b6ff624dc1c944ba8851a736eeac6da0124b75c66640`.

Оба запуска имеют `test_kind=user_supplied_test_independence_not_established`. Восемь test-строк и bootstrap interval с восемью группами слишком малы для выбора архитектуры.

## Artifact hashes

| Artifact | SHA256 |
|---|---|
| `evaluate.json` | `6711c2a277f9a26568a3d058e1d2fbf9d003c64b5aeadccd51d2e902d44c61fa` |
| `predictions.csv` | `07dff1f61d1cde4ae2aa93d7bf51f42b92e792fedcaf62b12bef9f1e5cb8d790` |
| `predictions.audit.jsonl` | `65327e3ea7c9fdd01d22546afe3ac534749e57c6cd0dd2cafedffb5eaab362c4` |
| `predictions.run.json` | `e16ee8edb3c4c6c19c60c4c2976267cee443cb8b59973f6b988b04238ca68762` |
| `benchmark_zero.json` | `9401a73c265dcbab2436a019176f8e5dc4d721e026316305a74da6b16701b1d4` |
| `benchmark_zero.scores.jsonl` | `3008f4cd99f7e5c9d7841c8c9fdf4c59ccbb3cea3c209bea5ed47d7df53b576b` |
| `benchmark_structural.json` | `661eeb25332f7f40ab4155896a2efa37f21ddb2b32a5c9dfa67de6793f8845cd` |
| `benchmark_structural.scores.jsonl` | `f49415d714ea14699bde2a0ca2f9592ca422c54365645b6c4ada1ab096c76cb8` |

## Интерпретация и ограничения

- На этом sample детерминированные нарушения имеют нулевой FP, но это наблюдение на 23 negative rows, а не гарантия precision на новой выборке.
- Высокий precision получен ценой большого числа unknown и FN; `unknown -> 0` искусственно повышает accuracy при недостатке доказательств.
- `evaluate.py` combined и production-like `predict.py` отличаются: последний использует полный default check set и находит 12, а не 11 нарушений. Поэтому canonical V5.3 end-to-end baseline здесь — результат `predict.py` F1 0.685714; matrix из `evaluate.py` остаётся component audit.
- Восемь строк group-aware test split не дают устойчивой оценки; результаты сохранены для воспроизводимости harness, но не используются как итоговая оценка качества.
- Runtime и artifact hashes, содержащие runtime duration, могут измениться при повторном запуске; source/data hashes и confusion counts должны оставаться стабильными при том же окружении и SHA.
