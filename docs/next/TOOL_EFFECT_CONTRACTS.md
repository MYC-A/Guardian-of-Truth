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
