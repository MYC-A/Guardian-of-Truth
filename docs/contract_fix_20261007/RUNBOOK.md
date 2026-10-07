# Воспроизведение contract fix

Работать в отдельном checkout fix-ветки. Python 3.10+; проверено на Windows Python 3.13.7. Исходные outputs/gold/cache не редактировать. Новый output filename обязателен: replay/comparison/readmission отказываются его перезаписывать.

## Установка

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e '.[data,dev]'
$env:PYTHONDONTWRITEBYTECODE='1'
$env:PYTHONPATH='src'
```

`PYTHONDONTWRITEBYTECODE` предотвращает изменение исторических tracked pyc. Explicit UTF-8 I/O исправлен в затронутых research runners; `-X utf8` также нужен старым архивным модулям, импортируемым replay.

## Тесты

```powershell
python -X utf8 -m pytest -q tests/integrated_v1 tests/verification_v2 tests/test_verification_v3.py tests/test_verification_v4.py tests/test_guardian_v6.py tests/test_contract_safety_records.py tests/test_contract_safety_layers.py tests/test_contract_safety_admission.py tests/test_contract_safety_cause.py tests/test_contract_safety_prepass.py tests/test_addons_evaluator.py tests/test_addons_hook.py tests/test_semantic_study.py tests/test_v6fix_cli.py tests/test_v6fix_contrast.py tests/test_v6fix_external.py tests/test_universal_repair.py tests/test_universal_repair_v2.py
```

## Exact raw replay

Нужен отдельный baseline checkout на `9794f50d`, с tracked inputs/cache. Не переключать пользовательский WIP. Исторический Windows symlink holdout2 скрипт разрешает через явный `outputs/guardian_v6/holdout2`.

```powershell
python -X utf8 scripts/contract_fix_replay.py --runtime-root C:/Users/Igor/Guardian-contract-safety-20261007 --output docs/contract_fix_20261007/baseline_NEW.json
python -X utf8 scripts/contract_fix_replay.py --runtime-root C:/Users/Igor/Guardian-contract-fix-20261007 --output docs/contract_fix_20261007/fixed_NEW.json
python -X utf8 scripts/contract_fix_compare.py --before docs/contract_fix_20261007/baseline_NEW.json --after docs/contract_fix_20261007/fixed_NEW.json --output docs/contract_fix_20261007/comparison_NEW.json
```

Каждый replay пишет отдельный durable `.progress.jsonl`, final JSON — только после завершения и проверки неизменности runtime fingerprints. Скрипт не возобновляет неполную progress-фазу автоматически; после прерывания сохранить её как history и выбрать новый filename. `--sets`, `--reps`, `--arms` позволяют явную диагностику, но она не заменяет полный запуск.

## V6 legacy proposal re-admission

```powershell
python -X utf8 scripts/contract_fix_v6_readmission.py --output docs/contract_fix_20261007/v6_NEW.json
```

Скрипт берёт frozen old F-v2 source из Git только для восстановления прежнего request; новые F-v3 ответы не симулируются. Готовые old proposals заново проходят actual current pipeline. Open/closed arms — явные альтернативные input contracts, не выбор лучшего предсказания по gold.

## Public entry point и ограничения

```powershell
guardian-review --help
```

Default profile сохранён. `--repair r_fix` использует исправленный deterministic path с прежним model contract. `--repair v6fix` — opt-in bounded safety profile. `--tool-universe-closed` и `--history-complete` допускаются только когда вызывающая сторона действительно гарантирует соответствующий полный universe; наличие `[AVAILABLE TOOLS]` или полного прочитанного input недостаточно. Flags не разрешают игнорировать policy exceptions.

Новый F-v3 wire и neutral CB требуют новых exact replies. Offline miss — NOT_EXECUTED, сохранённый fallback binary не является выполненным новым F/CB experiment. Новые semantic/add-ons phases пишут в `outputs/guardian_contract_fix/`, фиксируют inputs/config/code и expected IDs; прежние historical run roots запрещены. Частичные старые реплики scorer принимает только с явным expected-ID manifest/override и пометкой subset.

Live model matrix в этой фазе не выполнялся. Provider tokenizer/context preflight, independent holdout, cause truth и межмодельный перенос требуют отдельного замороженного протокола.
