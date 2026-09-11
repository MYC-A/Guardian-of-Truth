# Policy compiler

## Контракт

`PolicyBundle` компилируется один раз из SYSTEM-policy и не зависит от trace,
candidate response, target или gold label. Его cache key — SHA-256 исходного
SYSTEM-текста плюс имя arm. Повторная запись с тем же ключом, но другими байтами,
считается ошибкой.

Структура закрыта (`PolicyRule`, `CoverageItem`), словарь значений открыт. Всё,
что не поддержано точным компилятором, получает `unknown`, а не угадывается.
Coverage ledger содержит запись для каждого непустого структурного сегмента.

## Arms

| Arm | Смысл | Статус |
|---|---|---|
| P0 | текущие exact-шаблоны и structural compiler | реализован |
| P1 | прямой ответ той же локальной LLM | не запускался |
| P2 | `PolicyMeaning` той же LLM + deterministic compiler | не запускался |
| P3 | та же IR, более сильная/reasoning модель | не запускался |
| P4 | frozen candidate pool, oracle@k | не запускался |
| P5 | pairwise judge над тем же pool | не запускался |
| P6 | mutants + distinguishing worlds | не запускался |

P1–P6 должны использовать один и тот же frozen набор cases. До первого
оценивания фиксируются модели, prompts, schema, budgets и candidate pool.

## Метрики

- segment coverage и executable coverage;
- precision/recall правил и аргументов;
- mutant kill rate;
- distinguishing-world accuracy;
- compile latency/cost и cache hit rate;
- downstream end-to-end delta при неизменных остальных компонентах.
