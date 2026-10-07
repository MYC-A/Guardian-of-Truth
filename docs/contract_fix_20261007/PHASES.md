# Фазы и authoritative receipts

Исторические inputs/gold/outputs/cache не перезаписаны. Перечисленные здесь файлы созданы новым аудитом и сохраняют его промежуточные состояния.

| Артефакт | Статус / назначение |
|---|---|
| `baseline_replay.progress.jsonl`, `fixed_replay.progress.jsonl` | Незавершённая первая фаза. Обнаружены потеря существующего bounded completion retry и Windows symlink holdout2. Не финальная оценка |
| `*_replay_v2.json`, соответствующие progress и `replay_comparison.json` | Завершённая фаза после восстановления retry; 28 projections, binary/reasons parity. Ещё до дополнительного primary receipt gate |
| `baseline_replay_frozen.json` | Финальный baseline на `9794f50d`: input/gold/source/runtime fingerprints; сеть заблокирована |
| `fixed_replay_frozen.json`, `frozen_pre_primary_comparison.json` | Snapshot `e5479c46`, до финального primary/cause receipt исправления. Сохранён как отдельная контрольная фаза |
| **`fixed_replay_final.json`, `replay_comparison_final.json`** | **Authoritative R_fix/R_comb runtime replay на `2483c436`: 28 доступных projections, 1578 rows, 0 binary/accusation/missing/source drift** |
| `v6_readmission.json` | Предыдущая диагностическая re-admission фаза; до последних P literal-origin/ownership contracts |
| **`v6_readmission_final2.json`** | **Authoritative V6 old-proposal re-admission**, actual pipeline v3, final P/S/F fingerprints, 80 exact old requests и 0 projection drift. Это не inference нового F wire |
| `tests.xml`, `tests_v2.xml`, `tests_final.xml`, `tests_wire_final.xml`, `tests_receipt_final.xml` | Промежуточные JUnit. `tests_v2.xml` содержит обнаруженные старые tests с чрезмерной authority no-invent: их смысловая миграция раскрыта в REPORT, не скрыта удалением receipt |
| `tests_all_final.xml` | 412 passed, 2 skipped после основного полного code freeze; последующие небольшие cause-only robustness checks отдельно |
| **`tests_published_final.xml`** | **420 passed, 2 skipped**, весь выбранный suite после cause-only дополнения; независимый reviewer отдельно подтвердил 43 cause tests |
| `install_smoke.json` | Isolated wheel build/import/CLI smoke; runtime dependencies уже доступны; build isolation устранила отсутствие global setuptools |
| **`install_smoke_final.json`** | Повторный isolated wheel build/import/CLI smoke после cause-only дополнения, включая malformed receipt probe; PASS |
| `CODE_REVIEW.md`, `LOGIC_REVIEW.md` | Cross-review исполнителей, с явными авторскими/независимыми границами. Более ранние замечания не заменяют итоговые paired receipts |

Промежуточный `v6_readmission_final.json` не создан: runtime fingerprint guard обнаружил изменение P и отказался публиковать смешанную фазу. Финальная `final2` выполнена целиком с неизменным P/S/F/pipeline. Перезаписывать или «чинить» её задним числом не нужно.

Последующая cause-only защита malformed transport metadata не меняет request, R_fix pipeline, binary projection или зависимости вычисления бинарного replay. Её валидация — отдельные cause tests, без переиспользования прежних judge вердиктов как новых.

Все архивные наборы здесь development/diagnostic. Повторы, budgets и extraction A/B используют общие inputs; их нельзя считать независимыми samples. Полный новый F-v3/neutral-CB automatic experiment, живой прирост F1 и независимый holdout в этой фазе NOT_EXECUTED.
