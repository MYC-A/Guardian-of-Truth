# Guardian Next: Compiled Evidential Monitor

## Решение

Базовая гипотеза — не просить одну LLM сразу выдать метку, а разделить задачу на
типизированные предложения и детерминированную проверку. LLM допускается только
как компилятор или экстрактор кандидатов. Она не превращает свою интерпретацию в
факт и не видит `label`/`explanation`.

Текущий минимальный arm `X5_PROPOSED_MIN` реализован рядом с V5.3 в
`guardian_truth.next`; V5.3 не изменён. Семантические arms и внешний blind test
ещё не выполнены, поэтому победитель пока не выбран.

```plantuml
@startuml
skinparam componentStyle rectangle
actor Evaluator
rectangle "Frozen input boundary" {
  [prompt]
  [candidate response]
}
component "Policy Compiler\nP0/P1/P2/P3" as Policy
database "PolicyBundle cache\ncontent hash" as PCache
component "Trace Normalizer" as Normalizer
component "Tool Effect Registry\nT0/T1/T2/T3" as Effects
database "Append-only\nEvidence Ledger" as Ledger
component "Blind Claim Extractor\nC0/C1/C2" as Claims
component "Entity Binder" as Binder
component "Four-valued Solver\nTRUE/FALSE/BOTH/UNKNOWN" as Solver
component "Fast exact path" as Fast
component "Evidence-seeking slow path" as Slow
component "Binary adapter" as Binary

[prompt] --> Policy : SYSTEM policy only
Policy --> PCache
[prompt] --> Normalizer : trace, no labels
[candidate response] --> Normalizer
Normalizer --> Ledger
[prompt] --> Effects : tool schemas/docs
Effects --> Ledger : effect semantics
[candidate response] --> Claims : response only
Claims --> Binder
Ledger --> Binder
PCache --> Solver
Binder --> Solver
Fast --> Solver
Solver --> Slow : only unresolved + expected gain
Slow --> Ledger : new evidence only
Solver --> Binary
Binary --> Evaluator : id,label
@enduml
```

## Инварианты

- `USER_ACTION != ASSISTANT_ACTION`.
- `INTENT != COMPLETED`, `CLAIM != OBSERVED`.
- `CALL_ATTEMPTED != EFFECT_CONFIRMED`.
- `FAILED` не означает ни `COMPLETED`, ни `NO_EFFECT` без контракта.
- `not found != absent`; отсутствие требует сертификата полноты.
- `UNKNOWN != FALSE`; противоречие сохраняется как `BOTH`.
- одинаковый тип поля не означает одинаковую сущность.
- старое наблюдение не становится текущим автоматически.
- имя инструмента и схема его аргументов не доказывают эффект.
- вывод LLM всегда остаётся интерпретацией до проверки решателем.

## Реализованный минимальный путь

1. `policy.compile_policy` сегментирует весь SYSTEM-текст, каждому сегменту
   назначает `compiled` либо `unknown`, компилирует только узкие точные шаблоны и
   хеширует только policy context.
2. `normalize.normalize_trace` детерминированно разделяет текст, вызовы и
   результаты; `build_evidence` создаёт append-only записи.
3. `effects.schema_registry` строит T0-контракты без выдуманных эффектов.
4. `claims.extract_claims` видит только response и различает intent, completed
   action, refusal и absence.
5. `binder` не поддерживает completed action одной попыткой вызова и не
   поддерживает absence без completeness certificate.
6. `logic` реализует четырёхзначную логику; `monitor` сохраняет точные находки
   V5.3 как incumbent protection.
7. `python -m guardian_truth.next.evaluate <stage>` воспроизводит каждый срез.

## Что ещё должно пройти до production-решения

- P1–P6: реальные policy arms на одинаковых frozen cases.
- T1–T3: человеческие и модельные контракты эффектов с отдельной оценкой.
- C1–C2: типизированное слепое извлечение claims и аудит покрытия.
- X1–X4/X6, L0–L2: end-to-end и long-context сравнения при равном бюджете.
- frozen external adapters и один полностью независимый источник.
- paired confidence intervals, McNemar и hierarchical bootstrap по траекториям.

Любая отсутствующая часть обозначается в machine-readable отчётах как
`unavailable`/`not_run`, а не заполняется предполагаемыми результатами.
