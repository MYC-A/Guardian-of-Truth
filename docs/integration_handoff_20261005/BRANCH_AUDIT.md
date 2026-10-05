# Повторный аудит веток и исполнения: 05.10.2026

Работа этой фазы — подготовка задания на интеграцию. Production/code исследований
и прошлые experimental outputs не менялись; inference API не запускались.

После успешного `git fetch origin` сняты **60 remote refs / 24 worktrees**.
Полные SHA, даты, subjects, ancestry и local/remote counts находятся в
[branch_inventory.json](branch_inventory.json). Это реестр refs с выборочным
углублённым аудитом ключевого кода, не полный review каждой исторической ветки.

Рекомендуемая исходная база: `8a9aa56dcd7e2ad3746a19f39161229cf9c1f97a`
(`research/whole-move-v1-20261005`). В ней уже входят V4/V5, Telecom,
hybrid mechanisms, retrieval bakeoff, U2/multipacket и corrections. Повторный
merge этих веток не нужен. Факт ancestry не подтверждает готовность runtime.

| Рабочая копия | Local HEAD | Remote HEAD | Отставание |
|---|---|---|---:|
| Guardian-modular-step2-4-20261002 | `744fc0c0` | `6135ae69` | 24 |
| Guardian-v11-policy-table-20261003 | `52861003` | `35ce9821` | 6 |
| Guardian-hybrid-assistants-20261001 | `871293c9` | `0296439b` | 1 |
| Guardian-v11-review-35ce9821 | `2d4f4d6e` | `2087b088` | 1 |

Эти локальные рабочие копии не переключались и не обновлялись. Для актуальных
выводов использовались remote refs и их tree/log. Некоторые выводы из старых
документов требуют проверки на актуальном runtime, не повторения по памяти.

Боковые research refs, имеющие commits вне базы, перечислены в JSON. Особенно
важна coverage-v2 `98b7fd2b`: divergence добавляет selector/harness/tests/design;
последующие corrections в основной линии надо сохранить при reuse. Боковая
source-search `149d4cf0` добавляет action-audit/V10 smoke/config/runtime;
это исторический кандидат для inspection, не автоматически лучший baseline.

Независимые read-only reviewers проверили source/retrieval/targets, semantic
lowering/time/ledger/controller и методологию/архивные scores. Один reviewer
запустил 114 focused tests (packer/coverage/mechanical/compact/bridge): passed.
Это отдельная выборка, не заявление о полной repo suite или готовности integration.

Новые findings в исходной базе воспроизведены отдельным offline probe:

- Потерянный `[ERROR]` receipt перед colon.
- Call body поглощает trailing prose.
- Неэкранированный body marker становится SYSTEM event.
- Дублирующийся target проходит packet resolve.
- SourceStore snapshot позволяет изменить raw при прежнем hash.
- `at_time` допускает наблюдение из будущего при ретроактивном valid_from.
- Lowering разных entity/field/value правил возвращает одинаковый core row.

См. [offline_probe_results.json](offline_probe_results.json),
[проверенный повтор](offline_probe_verified_results.json),
[исполняемый probe](../../scripts/integration_handoff_probe.py).
Framing finding относится к поддержке произвольных bodies, а temporal finding
— к экспортированному API; основной reviewed integration использует latest(as_of).
Не следует автоматически объявлять их причинами всех старых модельных FN.

Дополнительно подтверждены статическим review: promotion model/lossy readings
в authoritative/oracle-policy input, unresolved side-channel не обязательно
ограничивает verdict, mixing alternatives и jointly active norms, question
dedup без полного scoped key. При repairs агент должен сделать отдельные
end-to-end regression tests, а не считать static review оценкой их влияния.

Продукт этой фазы: [полный автономный промпт](AGENT_PROMPT.md),
[проверенные analogues и границы переноса](METHOD_FIT.md).
