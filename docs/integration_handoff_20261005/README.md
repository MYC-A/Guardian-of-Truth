# Задание следующему агенту: полная интеграция Guardian

Главный документ: **[AGENT_PROMPT.md](AGENT_PROMPT.md)**. Его можно целиком передать
агенту как новую задачу. Он самостоятельный: содержит репозиторий, базу и ветки,
известные результаты, проблемы и конкретные проверки по всем слоям, архитектуру,
план реализации, матрицу прогонов, правила универсальности и commit/push.

Это новое задание на реализацию, а не утверждение, что исправления из него уже
выполнены. Архитектуру разрешено менять по результатам проверки. Production,
исторические gold и замороженные experiments сохраняются.

Дополнительные материалы:

- [BRANCH_AUDIT.md](BRANCH_AUDIT.md): актуальность refs и локальных worktrees,
  ancestry и пределы проведённого аудита.
- [branch_inventory.json](branch_inventory.json): 60 remote refs и 24 worktrees
  на момент снимка после fetch.
- [offline_probe_results.json](offline_probe_results.json): 7 воспроизведённых
  структурных/контрактных дефектов, 0 inference HTTP.
- [offline_probe_verified_results.json](offline_probe_verified_results.json):
  тот же результат после согласования authority временного fixture; первый
  diagnostic record сохранён.
- [scripts/integration_handoff_probe.py](../../scripts/integration_handoff_probe.py):
  исполняемая read-only проверка исходной базы.
- [METHOD_FIT.md](METHOD_FIT.md): первичные источники и границы применения аналогов.

Простой путь первой интеграции: original SourceStore → все current targets →
original declaration guard → corrected U2 + direct reviewer → scoped ledger →
explicit result. Lossless binding и bounded additional search добавляются и
оцениваются отдельно. Последний compact reviewer не выбран как замена baseline.

Промпт прошёл независимый code/source и semantic/logic review. Сам handoff
подготовлен в отдельной ветке `research/integration-handoff-20261005` на базе
`8a9aa56d`; исходный runtime не менялся. Новых model runs не было.

Дополнение по запросу пользователя: обязательный saved-cache replay всех valid46
и отдельный **Gemma baseline46 / integrated46**; SSH-конфигурация, server layout,
provider profiles и получение дополнительных моделей — в разделах 7.2.1–7.2.2
и 11 основного промпта.

Приватная полная копия с пользовательскими credentials хранится вне Git:
`C:\Users\Igor\Documents\PROMPT_GUARDIAN_FULL_INTEGRATION_PRIVATE_2026-10-05.md`.
Публичная версия содержит env references и пути. SSH alias разрешён локальным
`ssh -G`, доступность сервера и моделей в этом дополнении не проверялась live.

Быстрый полный cache replay:
[script](../../scripts/integration_handoff_cache46.py),
[результат](cache46_verified_replay.json). Он не выполняет модельных запросов
и не перезаписывает original outputs. Локальный derived cache содержит 552
predictions; 184 original request files из manifest отсутствуют — raw/wire
readmission потребует их восстановления, saved metrics replay уже доступен.
