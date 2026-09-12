# Tool Effect Contracts

Схема инструмента описывает допустимые входы, но не доказывает изменение мира.
Поэтому T0 заполняет только `tool` и entity fields; `guaranteed_effects` пуст,
`failure_no_effect=UNKNOWN`, freshness/idempotence неизвестны.

Полный контракт содержит guaranteed/possible effects, reads/writes, entity
fields, freshness, idempotence, поведение при failure и provenance.

Порядок экспериментов:

1. T0 — schema/name, реализован как безопасная нижняя граница.
2. T1 — human/gold contracts; является эталонной семантикой для известных tools.
3. T2 — LLM extraction, сравнивается с T1 и не может само себя оценивать.
4. T3 — docs + traces + tests, только после фиксации T1/T2 protocol.

Запрещено: выводить эффект из имени функции, считать HTTP/tool success
подтверждением конкретного effect без контракта или считать failure доказанным
отсутствием эффекта.

## T1 reviewed subset

`contracts/tool_effects_v1.json` содержит 7 консервативных контрактов. Три
write-контракта (`cancel_reservation`, `exchange_delivered_order_items`,
`resume_line`) имеют явно проверяемый result predicate; четыре read-контракта
фиксируют freshness/read scope и отсутствие writes. Ни один write-контракт не
объявляет `failure_no_effect=true`.

Источник — явные tool descriptions из четырёх уникальных SYSTEM contexts
`valid.parquet`; success predicates дополнительно сверены с реально встреченными
result shapes без чтения labels/explanations. Это human-reviewed subset, а не
полный gold registry и не основание переносить контракт на другую версию tool.

**HYPOTHESIS:** trusted effects позволят отличить observed call от подтверждённого
business effect. **TEST:** T0 против T1 на том же trace normalizer и затем X5.
**DECISION:** `KEEP` как инфраструктуру и `REVISE` как coverage: автоматические
T2/T3 не допускаются до измеренного downstream ceiling от полного T1.
