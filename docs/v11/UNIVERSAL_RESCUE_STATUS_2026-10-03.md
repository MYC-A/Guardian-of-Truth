# Текущее состояние универсальных исправлений

**Частично:** 187 тестов проходят; старые ответы после lossless admission дают
GPT 15 атомов / Nemotron 2, общий атом 1 вместо 0. Улучшение public46 не измерено.

Изолированная ветка `research/v11-universal-rescue-20261003`:
`2456e7f8` доказательные пути + ledger, `1271c945` M2 premise,
`d1351135` bounded inventory, `5bb6d7cf` frozen source-only probe.
Ветка peer не менялась; `scripts/predict.py` и сервис не менялись.

## Подтверждено кодом

Receipt требует единственного assistant-вызова. Состояние не берётся из orphan/user
результата, чужого родителя или противоречивого latest response. ANY/ALL проверяют
scope до wildcard; TARGET требует parent и child. Сравниваемый ID не перестаёт
быть identity anchor. Разные 36-значные числа не сливаются в DECISIVE; explicit
literal-null сохраняется, PATH-null остаётся UNKNOWN. Сквозные counterexamples
проходят admission, а не только тестируют приватный helper.

Знаменатель прежнего manifest остаётся 4 при отсутствии таблиц (recall 0),
RELATED_ONLY не считается точной обязанностью. M2 требует read receipt и отсутствие
ID **во всех** остальных предыдущих событиях, включая assistant text и calls.

## Что ещё НЕ решено

1. Свободное текстовое согласие. Exact operation/arguments протокол проверяется;
   на реальных историях confirmation теперь UNKNOWN **84/84**, вместо прежних
   TRUE3/UNKNOWN81. Это исправление недоказанных решений ценой покрытия, не успех
   на естественном языке. Нужен отдельно замороженный semantic action/consent parser.
2. Полный compiler. Ledger сохраняет source obligations, guard/exception и
   непредставимость; lowering-admission проверяет структуру, не семантическое
   следование. Все три модели могут согласовать неверный proxy. Поэтому source-only
   expectations и ручной аудит нужны отдельно от количества atoms/agreement.
3. Представимость DSL. Многие обязанности требуют происхождения пользовательских
   данных, количества, составной сущности, роли вложенного инструмента и успешного
   эффекта. PRIOR_CALL и exists не заменяют эти требования. UNSUPPORTED не означает
   отсутствие ошибки в ответе; этот слой сам не выдаёт NO_ERROR.

## Запущенный frozen опыт

Remote SSH alias `new`, worktree `/workspace/guardian/repos/guardian-v11-rescue-5bb6d7cf`,
Python `/workspace/guardian/venv/bin/python`. Foreground SSH — ранее согласованное
исключение; Supervisor/сервисы/ключи не изменены. Frozen version `v11-rescue-probe/1`.
До старта budget: 44 HTTP, 313149 known, 76976 unknown bound, pending0.
Единый предел V11 450 / 3M, Mistral breaker429 сохранён.

A repaired one-shot / B source-ledger chunks64 + lowering, те же4policies/triggers
и GPT120b high / Nemotron ultra / Gemma31b. 28 audit-only expectations записаны до API.
Ожидания читаются из draft policy snapshot, сохранённого как
`freeze_draft_before_audit.json`; финальный freeze включает их Git blob.
Результаты, raw replies, source-only errors и costs будут сохранены отдельно.

## Независимый аудит frozen orchestration — учитывать при интерпретации

- B invalid lowering-envelope теряет отдельный счётчик unresolved dispositions.
  Если ledger содержит N obligations, а lower-invalid — показать N unaccounted
  lowerings дополнительно, без изменения frozen основного отчёта.
- `original.controls/atom_findings` вызывает `evaluate_atom` напрямую: там нет
  actor-фильтра outer `evaluate_table`. Если control содержит не-assistant target,
  такую находку исключить в дополнительном аудите, не прятать исходную строку.
- Resume при исчерпанном budget/auth сначала делает stop, затем может перезаписать
  result пустыми rows. **Не запускать resume после stop.** Сохранённые raw receipts
  остаются; восстановление progress показать отдельным audited artifact.

Код frozen опыта после старта не правится. Следующее исправление получает новую
версию/freeze. Эти дефекты не основание переписывать результаты уже открытых моделей.
