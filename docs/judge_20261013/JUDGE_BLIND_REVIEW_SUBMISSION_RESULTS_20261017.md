# Полный blind-review ZIP — 17.10.2026

Собран новый полный ZIP решения: веса + offline Linux runtime + точка входа.

- Файл: [guardian-judge-qwen36-awq-blind-review-eef11fc4-20261017.zip](A:/Guardian-submissions/guardian-judge-qwen36-awq-blind-review-eef11fc4-20261017.zip)
- Размер: 30,677,896,079 байт (30.678 GB), меньше 40 000 000 000 байт.
- SHA256: `892bdf1ed39046b7ccdf2f42cb75ec066b4159070a9545ffe1ad6818d843425e`.
- Код: `eef11fc47329d44a6ce1696409dcc19fd2e9ddf4`.
- Remote: [judge-single-pass-20261013](https://github.com/MYC-A/Guardian-of-Truth/tree/judge-single-pass-20261013).
- [Linux CI](https://github.com/MYC-A/Guardian-of-Truth/actions/runs/39052903667): **234/234 passed, без skipped**; Python 3.12, реальный pinned encoder.

## IMPLEMENTED

В архиве явно включён D: legacy, сохранённый overall → один blind → final.
Три вызова на строку с резервным overall, одна загрузка Qwen3.6 AWQ.
Final использует сохранённый фактический primary input с проверкой хэшей.
Непоместившиеся notes отбрасываются; исходник ради них не сокращается.
При неполном exact final весь набор возвращается к primary. Hard override и .30 сохранены.
Repository production defaults остаются прежними; opt-in выбран только для этого ZIP.

## MEASURED — технические проверки

- Все 52636 файлов конечного ZIP проверены builder по size/SHA256/mode.
- Независимая проверка ZIP SHA256, путей, дублей, manifest/config, runtime import closure.
- 52224 runtime-файлов совпадают с проверенным исходным ZIP;
  проверены ELF Linux x86_64, executable bits, private loader, offline flags и toolchain.
- Runtime metadata/dependency closure: {"vllm": "0.19.1", "torch": "2.10.0", "triton": "3.6.0", "transformers": "5.8.0", "flashinfer-python": "0.6.6", "flashinfer-cubin": "0.6.6", "pandas": "3.0.6", "pyarrow": "26.0.0", "jsonschema": "4.26.0", "pydantic": "2.14.0", "pyyaml": "6.0.3"}.
- Qwen: cyankiwi/Qwen3.6-35B-A3B-AWQ-4bit,
  revision 00fcea2d3bcf5389b518d4fc082e5590e0ba4844.
  Все 21 файл соответствует pinned download receipt;
  шесть safetensors-шардов и индекс 95427 тензоров проверены.
- CPU fallback harness из кода конечного ZIP: четыре строки, literal/duplicate id,
  настоящий бинарный Parquet, gold isolation. Linux bootstrap обойдён, process cleanup
  адаптирован к Windows только в harness; это НЕ доказывает исполнение bundled runtime на Linux/GPU.
- Настоящий tokenizer на valid46: 46 строк,
  primary trimmed=2,
  final без notes overflow=0,
  blind overflow=0.
  Max primary/final/blind tokens: 48018/48216/42723.
  Это технические регрессии, не качество и не измерение production времени.

## GPU_UNTESTED / NOT_EXECUTED

Две ограниченные попытки настроенного SSH не дали доступ к GPU (timeout/refused).
Реальный GPU pilot, F1/AUC/AP, полнота содержательной blind delivery, peak VRAM,
cache counters и whole-script production timing НЕ ИЗМЕРЕНЫ.
Независимая оценка и data inventory/split experiment остаются отдельным этапом;
данные не объявляются отсутствующими. Схема не объявляется доказанно лучше overall.

Контроль сроков сохранён: stop 1380, kill 1530, watchdog 1680 с от predict.py,
внешний бюджет 1800 с включает холодный старт/внешнюю установку. CI/целостность
ZIP не являются доказательством прохождения закрытого входа за этот бюджет.

Итог: упаковка и доступные технические проверки пройдены;
вердикт качества/скорости — **INSUFFICIENT_EVIDENCE**.

## Запуск и воспроизведение

```bash
python scripts/predict.py --input INPUT.parquet --output OUTPUT.parquet
```

Локальная сборка закреплена в build_blind_review_submission_20261017.py;
независимая проверка — inspect_blind_review_submission_20261017.py.
Команда сборщика и закреплённые входы: [build protocol](BLIND_REVIEW_SUBMISSION_BUILD_20261017.md).
Копии результатов проверок: [inspection](blind_submission_receipts_20261017/BLIND_REVIEW_FULL_ZIP_INSPECTION_20261017.json),
[CI](blind_submission_receipts_20261017/BLIND_REVIEW_RELEASE_CI_20261017.json),
[tokenizer](blind_submission_receipts_20261017/BLIND_REVIEW_REAL_TOKENIZER_20261017.json).
Квитанции: `A:/Guardian-submissions/guardian-judge-qwen36-awq-blind-review-eef11fc4-20261017.verification.json`,
`BLIND_REVIEW_FULL_ZIP_INSPECTION_20261017.json`, `BLIND_REVIEW_RELEASE_CI_20261017.json`.

Для места старая отдельная копия runtime перенесена с проверкой 258 SHA256 на
C:/Users/Igor/Guardian-build-storage-20261017/server-runtime. Старый путь
A:/Guardian-submissions/vllm-fp8-build-20261010/server-runtime сохранён через junction.
Квитанция RUNTIME_STORAGE_RELOCATION_20261017.json. Предыдущие submission ZIP не перезаписывались.
