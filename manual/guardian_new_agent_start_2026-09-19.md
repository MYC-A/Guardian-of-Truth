# Стартовая директива новому агенту — Guardian of Truth / AI Journey 2026

Ты подключаешься к действующему исследовательскому проекту **MYC-A/Guardian-of-Truth**. Цель — улучшить конкурсный F1 на обнаружении контекстных ошибок в итоговом `response` агента при входе `id,prompt,response` и собрать воспроизводимое локальное/offline Docker-решение. **У пользователя не будет обязательного доступа к сильной/дорогой удалённой LLM.** До любого кода прочитай полностью предоставленный файл `guardian_master_handoff_2026-09-19.md`. Это подробная история экспериментов, веток, коммитов, метрик, отрицательных результатов, soundness и незавершённых работ. Сверяй каждую важную гипотезу с первичными отчётами/кодом, ссылки в файле.

## Мандат 0 — НЕ УНИЧТОЖАЙ РАБОТУ ДРУГОГО АГЕНТА

Сначала read-only проверь `pwd`, `git status --porcelain=v1 -uall`, `git branch -avv`, `git rev-parse HEAD`, `git worktree list --porcelain`, `git log --graph --decorate --all --oneline -n 100`, `git check-ignore -v outputs/full_architecture_v1/...`, локальные незакоммиченные/игнорируемые файлы, директории моделей, кэши, активные долгие процессы и доступные GPU/диск/CPU. Предыдущий агент мог ещё работать. НЕЛЬЗЯ делать checkout/reset/clean/pull с риском конфликта, удалять `.env`, model files, logs, untracked/ignored output, переписывать старые замороженные branches или одновременно забивать чужой GPU. Отдельный worktree/ветка — только после выбора подтверждённой базы, проверки места и изоляции чужих процессов. Не коммить секреты.

## Мандат 1 — КАРТА РЕАЛЬНОГО СОСТОЯНИЯ

В master handoff зафиксирован remote snapshot примерно 19.09: девять опубликованных веток. `full-architecture-v1` был на `923bb445...` (WIP benchmark adapters), `core-engine-bakeoff-v1` не найден как remote branch, хотя `bf972b0` есть в истории; `semantic-pipeline-v1` — ДРУГАЯ линия, не предок `full-architecture-v1`; `competition-real-valid-codex` и `codex-update-run` параллельные. Перепроверь актуальность каждой ветки, merge-base, свежие коммиты и файлы; выяви LOCAL-ONLY/UNTRACKED/IGNORED результаты.

Создай `docs/HANDOFF_VERIFIED_YYYYMMDD.md` с таблицей: branch/ref/tip SHA/предок/есть код/есть артефакты/тесты PASS/не проверено/блокеры. Для каждой исторической метрики прикладывай data hash, model, конфиг, commit, статус viewed-dev vs independent, источник json/report и способ воспроизведения. НЕ смешивай `main V7 F1=.7556` с `E2E 144 F1=.834`, `codex fix2 F1=.606`, `C3 F1=.231` и FullArch N5 из другой архитектуры/кэша.

Особое внимание: **fix2 10 TP/F1=.606 был получен на недоказанных closure assumptions**. В `4639b46` это исправлено: 3 TP/.231 при закрытиях OFF. Не возвращай closed catalog или `additionalProperties=false` как formal proof без явной premise. В `competition-real-valid-codex` есть отдельно completion-invariant FALSE witness fix `300dc2e`; перепроверь, присутствует ли общий принцип в текущем core, но НЕ импортируй вместе с ним неподтверждённую catalog closure. В `0c2bda7` FullArch N5=TP4 FP2 при валидных сертификатах: изучи почему неверно извлечённое/замкнутое NL создало false verdict. Проверь, есть ли полный source-to-verdict trace и локальные 46-case/benchmark JSON за следующую session H.

## Мандат 2 — ВОССТАНОВИ НЕЗАВЕРШЁННЫЕ ПРОГОНЫ

В пользовательском логе предыдущего агента: bake-off 43/43, Phase A–E full architecture и N0/N5, SafePyramid smoke 234 (TP0 FP11), main 466 (TP5 FP43), FOLIO representability 27%/accuracy 45%, ProofWriter 61%/66%; BARRED частично исполнялся и исправлялся newline ASP, ContractNLI только начат. Отдельно проверь по локальным артефактам, какие прогоны действительно завершены/запечатаны, что входит в Git и какие результаты существуют только в ignored `outputs/full_architecture_v1/`. Если нет исходных файлов, пометь `LOG_ONLY / NOT_REPRODUCED`, не придумывай метрики. Не заявляй, что новый Clingo 43/43 означает конкурсный успех — это neutral-formal scenarios, не NL E2E.

## Мандат 3 — СРАВНИ СОВЕРШЕННО ДРУГИЕ АРХИТЕКТУРЫ ПРИ ОГРАНИЧЕНИЯХ ПОЛЬЗОВАТЕЛЯ

После сохранения базы проверь малые локальные **MiniCheck, LettuceDetect, Granite Guardian** (и другие релевантные, при подтверждённых весах/лицензиях) как standalone claim/faithfulness classifiers и как fallback для `UNRESOLVED`, не притворяясь, будто RAG-модель сама ловит все tool/policy ошибки. Попробуй раздельно policy/trace Declare или LTLf (PM4Py/Declare4Py/flloat), numeric/provenance Z3 как альтернативные механизмы для соответствующих классов правил, current Clingo и гибрид с маршрутизацией. Исследуй небольшой LOCAL extraction frontend/structured decoding вместо обязательного remote Mistral. Не устанавливай всё подряд, не делай зоопарк ради числа библиотек. Сначала ablation на доступном железе, затем обоснованная интеграция.

**Нельзя** сливать probability score с `PROVED_ERROR` в один внутренний статус. Neural detector может определять конкурсный 0/1 при формальном `UNRESOLVED`, но score не является сертификатом. Не усваивай gold/`explanation` из публичных 46 в инференс или правила. Обучение/калибровка на независимом train+calibration, dev46 использовать только как просмотренный диагностический набор; внешние benchmarks имеют другие цели и свои ограничения/abstain denominators.

## Мандат 4 — ПРОТОКОЛ И ФИНАЛ

Проверить официальный регламент по https://dsworks.ru/champ/aij26-guardian и PDF (ссылка в master): ~30 мин, <40 ГБ, A100/H100 discrepancy, сеть для первой задачи не установлена — считать офлайн до официального доказательства обратного. Код должен делать `python scripts/predict.py --input input.csv --output predictions.csv` по НЕВИДАННОМУ `prompt,response`, без заранее готового `phi.jsonl` именно для известных 46. Замер cold-start, memory/VRAM, Docker build `pip install .`, license, полные benchmark hashes и независимые tests. Существующий submission/ветки оставь неизменными, пока нет отдельного решения пользователя.

### Первый ответ пользователю после инвентаризации

Напиши на русском, конкретно: **какие ветки реально есть, какой HEAD локальный и remote, что реализовано, какие эксперименты воспроизводимы, какие результаты только в логе, что до сих пор требует Mistral/API, какие реальные незавершённые задачи и какие 2–3 независимо проверяемые архитектурные ablation запускать следующими**. Без необоснованных заявлений «всё готово», «сделано» или «нет ошибок». Только после этого переходи к реализации.
