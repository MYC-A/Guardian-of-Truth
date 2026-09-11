# Evidence Ledger

Ledger — append-only последовательность `EvidenceRecord`. Запись всегда хранит
source span, event id, subject/predicate/object, entity tuple, freshness, status
и provenance.

Поддерживаемые статусы: `OBSERVED`, `ASSERTED`, `ATTEMPTED`, `CONFIRMED`,
`FAILED`, `SUPERSEDED`, `UNKNOWN`. Они не взаимозаменяемы.

- tool call создаёт только `call_attempted/ATTEMPTED`;
- tool result фиксирует наблюдённый ответ и его поля;
- failure фиксирует `FAILED`, но не создаёт `no_effect`;
- absence допускается только с `completeness_certificate`;
- более свежая запись не удаляет старую, а supersession должен быть явным;
- разные entity tuples не объединяются по совпадению типа поля.

Текущая реализация не назначает `CONFIRMED` автоматически: это станет возможно
только после подключения проверенного Tool Effect Contract.
