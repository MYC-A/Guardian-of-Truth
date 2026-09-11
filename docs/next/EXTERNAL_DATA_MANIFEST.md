# External data manifest (pre-run freeze)

Зафиксировано 2026-09-11 до первого внешнего labelled run. Ни один adapter ещё
не запускался. Коммиты ниже нельзя менять внутри текущего evaluation cycle.

| Source | Frozen commit | Роль | Статус adapter |
|---|---|---|---|
| [ATFD](https://github.com/Galea-foo/atfd) | `690c9962155865b3b17333bbb9354c15d3eb4170` | мониторинг готовых agent trajectories | planned |
| [tau-bench](https://github.com/sierra-research/tau-bench) | `59a200c6d575d595120f1cb70fea53cef0632f6b` | policy + tool-agent-user trajectories | planned |
| [AgentDojo](https://github.com/sequrity-ai/agentdojo) | `357c80dea9af34323f709c3505d9e6d224654c7e` | unsafe/untrusted tool data | planned |
| [ToolSandbox](https://github.com/apple/ToolSandbox) | `c8571d7854316d2e1c5f288e59fe1e34e53f6dd1` | stateful effects/dependencies | planned |
| [BFCL/Gorilla](https://github.com/ShishirPatil/gorilla) | `6ea57973c7a6097fd7c5915698c54c17c5b1b6c8` | независимый tool-call/schema source | planned |

Исходный tau-bench repository сам предупреждает, что его задачи устарели и
направляет к более новой версии. Здесь он оставлен намеренно как требуемый
frozen источник; обновлённую линию следует оформить отдельным source/cycle.

Для каждого adapter до запуска должны быть дополнительно зафиксированы:
dataset subset/hash, licence check, преобразование ролей/вызовов/results,
label mapping, unsupported-row policy, grouping, sample budget и unit fixtures.
Пока этих файлов нет, `external` entrypoint возвращает `not_run`.
