# Guardian: исправления контрактов и проверка регрессий — 2026-10-07

**Исправления выполнены в `fix/guardian-contract-safety-20261007`. Детерминированная обработка R_fix/R_comb сохраняет прежние результаты; более строгий V6 теряет часть прежних TP. Это исправление границ доказательства, а не подтверждённый прирост качества полного Guardian.** Default `guard_adm2` сохранён. Production, исходные gold и исторические outputs не менялись.

Исходная точка: `9794f50df43e919147ee272b6eea5ada7094084a`, ранее предъявленный [аудит](../contract_safety_20261007/REPORT.md). Рабочее дерево: `C:/Users/Igor/Guardian-contract-fix-20261007`. Runtime заморожен и опубликован в `2483c436`; документы/receipts и последующая cause-only защита malformed transport metadata публикуются отдельным коммитом. Последняя защита не меняет model requests или detector dependency graph; независимо проверена 43 cause tests. Точный последний опубликованный SHA следует брать из Git remote, а runtime fingerprints — из receipts.

## Что исправлено

| Слой | Было | Исправление / предел |
|---|---|---|
| P: применимость | Требование для возврата переносилось на lookup; отрицание/OR и сокращение имени поля давали ERROR | Exact field/tool scope и grammar всего предложения; неподдержанные scope, polarity, source alternatives и контекст остаются HYPOTHESIS |
| P: источник | Отсутствующий `*_id` под общим «не выдумывай» считался выдуманным | Лексическое имя поля — поиск кандидата. Generic no-invent и ordinary user-origin не доказывают запрещённую деривацию/отсутствие происхождения. Mechanical требует явного `verbatim` user/source-origin требования и closure |
| S: каталог | Полнота разбора означала закрытый мир | Только explicit caller `tool_universe_closed=True`; default open. Certificate basis `CALLER_CLOSED_TOOL_UNIVERSE` |
| F: контекст | Extractor не видел следующую строку с исключением; одинаковые proposals считались достаточными | Новая wire `turn_rules_context_v3` получает все выбранные нормативные документы. Unparsed normative context или unread POLICY запрещает mechanical applicability |
| F: операции | Reporting считалось executing; ноль отбрасывался; malformed proposal падал | Полная bounded operation grammar, `n=0`, локальная schema validation, DROPPED/HYPOTHESIS diagnostics |
| P/S/F: актёр | Current call другой роли мог считаться действием ассистента | Проверяются assistant-owned actions; real-parser USER/TOOL/SYSTEM контрасты и stale-certificate recheck |
| Admission | Provider strict mode заменял локальную валидацию | Валидация по реально запрошенной JSON schema; duplicate keys/nonfinite JSON отвергаются; failed receipt не выдаёт verdict из content. Full receipt сохраняется в primary/controller, A_adm2 rereadmission и всех найденных receipt-aware wrappers |
| Cause judge | Valid body неуспешного HTTP/completion мог улучшить cause metric; V1 допускал category без остальных fields | Оба judge entrypoints проверяют receipt и полную локальную response schema; failure = technical_unjudged. V2 cross-field invariants сохранены |
| Retry | Новый transport gate первоначально выключил прежний успешный verifier retry | HTTP-success failed completion не принимается, но сохраняет один прежний `attempt+100` retry; quota/auth не повторяются |
| AT | Отсутствие второго target удаляло отдельный valid candidate первого | Per-item admission; уникальные valid candidates сохраняются, invalid/duplicated quarantined, непроверенные targets UNCHECKED |
| Pool | Разные причины/свидетельства схлопывались | Дедупликация полного candidate contract; второй отличный кандидат не исчезает из-за первого REFUTED |
| Evaluator | Замена операторов внутри строк; float до Decimal; NaN crash; IF/THEN терял consequent | Token-aware операции, исходные numeric tokens и exact Decimal, typed local failures; неподдержанный conditional отвергается |
| Evaluator → analysis | Ошибка одной формулы понижала все нормы документа | При нескольких requirements в одном source binding UNRESOLVED; вывод о собственной формуле не становится applicability proof |
| CB | Current action влияло на retrieval до его сокрытия | Neutral view строится из original prompt при пустом response до retrieval; отдельные `blind:` адреса и source bundle. Новый wire требует новых ответов |
| Budget / I/O | Windows fcntl import; partial usage=0; 429 вне attempts; byte preflight отличался от HTTP body | Windows/POSIX process lock, conservative reservation, durable attempts cap, shared actual wire serializer и UTF-8 I/O |
| Runner / scorer | Last-write-wins, неполные IDs, смешение разных code/config phases | Exact expected IDs, legal technical retries, immutable input/code/config phase manifest, process lock всей фазы, новые output roots |
| Telemetry | Optional verifier/layer failures терялись | Полный layer trace и terminal technical gaps; resolved first-invalid не считается конечным failure; optional gap отделён от whole-row retry |

Регулярные выражения остаются в **ограниченном явно описанном compiler и поиске кандидатов**. Произвольная NL применимость ими не доказана. Правил по benchmark ID, suffix, конкретному домену или имени инструмента для выбора вердикта не добавлено. Имя tool используется только для точного связывания с его явным контрактом. Это улучшает переносимость механизма, но не доказывает универсальную семантическую полноту. Например, пользователь может назвать ID как «конкатенация символов R и 42»: отсутствие строки R42 не означает, что ID не сообщён. Только явная норма буквального использования позволяет коду решать по literal occurrence. USER-owned история сохраняет происхождение и при call/result-shaped тексте.

## Сопоставимый replay R_fix / R_comb

Полные valid46 ×3, LB1, LB2, LB3 ×2, external ×3, tau2h ×3, holdout2 ×2. Где сохранённого R_comb holdout2 нет, стоит NOT_AVAILABLE; вместо него не построено гипотетическое предсказание. Всего **28 доступных arm-проекций, 1578 row-проекций**; повторное использование одних строк не делает их независимыми примерами.

Клиент использует только exact request hash + provider/model/attempt cache identity, блокирует сеть и сохраняет каждый miss. Проверяются source SHA, полные expected IDs, binary, тексты и адресаты accusations. External содержит 70 исходных inputs, но только 68 имеют frozen-v2 gold; две строки явно исключены только из метрики. Windows symlink holdout2 разрешён через его известный Git target, без изменения исходного symlink или данных.

Ниже R_fix до → после, TP/FP/FN; F1. Эти числа — **исполнение сохранённых raw ответов**, не новые живые прогоны:

| Набор | До = после |
|---|---|
| valid46 r1 | 15/3/8; .7317 |
| valid46 r2 | 17/3/6; .7907 |
| valid46 r3 | 12/2/11; .6486 |
| LB1 | 22/3/6; .8302 |
| LB2 | 21/2/2; .9130 |
| LB3 r1 / r2 | 25/7/3; .8333 / 27/5/1; .9000 |
| external r1 / r2 / r3 | 36/1/16; .8090 / 37/1/15; .8222 / 38/1/14; .8352 |
| tau2h r1 / r2 / r3 | 27/4/14; .7500 / 30/3/11; .8108 / 28/2/13; .7887 |
| holdout2 r1 / r2 | 41/3/7; .8913 / 43/3/5; .9149 |

R_comb сохраняет прежние результаты как контроль; это не новое решение принять его default. Ранее известный дополнительный FP на LB3 r1 не исчез. Полная таблица и per-case сравнение — в JSON receipts.

[Финальное сравнение](replay_comparison_final.json): **0 binary flips, 0 изменений причины/адресата, 0 missing, 0 расхождений baseline с исторически сохранённым результатом**. Cache misses отсутствуют. Это проверка обработки тех же raw replies, а не измерение нового inference.

На этапе разработки transport gate потерял `ext_ret_019` r3: исправление incorrectly отключило предусмотренный bounded retry. Причина исправлена; первичный ошибочный completion не принимается, второй точный cached reply снова обрабатывается. Сохранённое binary TP не стало новым cause-correct TP: verifier ошибочно ставит историческое подтверждение h31 после текущего t0. Одинаковый итог не доказывает правильность причины.

## V6: ухудшение нельзя скрывать

[Финальный readmission receipt](v6_readmission_final2.json) восстанавливает **80 exact legacy extraction requests** и старые bound rules без расхождений. Затем старые proposals проходят **фактический текущий `Layers.findings`**, с тем же сохранённым R_fix и отдельными open/closed caller contracts. Это НЕ inference нового F-v3: прежний extractor полного нового контекста не видел. Предыдущий `v6_readmission.json` сохранён как отдельная фаза; промежуточный final отказался писать JSON при изменении runtime fingerprints.

Проверены 517 исходных строк, 514 с binary gold, 17 set×rep projections. В frozen120 три UNKNOWN сохранены и явно исключены только из binary score. Внешний readmission соответствует 68 размеченным строкам, тогда как runtime replay выше сохраняет все 70 inputs. Views 20k/400k × extraction A/B — повторные проекции, не независимые испытания.

| Budget/view | Потеря TP против legacy, open | Потеря TP, explicit closed | Изменение FP |
|---|---:|---:|---:|
| 20k A, аналогично B | 51 | 40 | 0 |
| 400k A, аналогично B | 59 | 48 | 0 |

Суммы относятся к всем set×rep проекциям одного view. Их нельзя складывать по A/B/budgets или считать числом уникальных ошибок. Default open на этом архиве совпал с сохранённым R_fix по каждому примеру. Все оставшиеся mechanical findings в closed-arm принадлежат S/UNDECLARED_TOOL; у F/P на этих архивных входах остаются только hypotheses.

Конкретные последствия при 20k A:

| Набор | Legacy V6 TP/FP/FN | Новый open | Explicit closed |
|---|---|---|---|
| valid46 r1 | 16/3/7 | 15/3/8 | 16/3/7 |
| valid46 r2 | 19/3/4 | 17/3/6 | 18/3/5 |
| valid46 r3 | 14/2/9 | 12/2/11 | 13/2/10 |
| external r1 | 39/1/13 | 36/1/16 | 36/1/16 |
| external r2 | 41/1/11 | 37/1/15 | 37/1/15 |
| external r3 | 41/1/11 | 38/1/14 | 38/1/14 |
| holdout2 r1 | 46/3/2 | 41/3/7 | 41/3/7 |
| holdout2 r2 | 46/3/2 | 43/3/5 | 43/3/5 |

**V6 quality non-regression criterion НЕ выполнен.** Причина — отсутствие общего автоматического semantic applicability/exception resolver: bounded compiler не может доказать, что другие абзацы политики не меняют правило. Простое снятие этого gate вернёт известные ложные certificates. Новые контрасты доказывают исправление этих границ, но не оправдывают потерянный recall как прирост качества.

## Проверки, review и ограничения

- **420 passed, 2 skipped**: [последний JUnit receipt](tests_published_final.xml), включая финальное cause-only дополнение. Тесты охватывают новые parser-based contrasts, admission/queue/evaluator/cause judge, CLI, integrated pipeline, verification V2/V3/V4, старые repairs и V6. Это выбранный релевантный suite, не весь исторический monorepo.
- Два Linux-isolation tests пропущены на Windows. Sandbox не переходит к небезопасному исполнению на host, а возвращает ISOLATION_UNAVAILABLE.
- Межпроцессный lock проверен конкурентными отдельными процессами; fresh wheel install/import/CLI smoke прошёл. Первый no-build-isolation preflight отказал из-за отсутствующего global setuptools; обычная isolated build успешно установилась. Runtime dependencies pydantic/jsonschema уже были доступны.
- [Code review](CODE_REVIEW.md) и [logic review](LOGIC_REVIEW.md) указывают авторство: review чужих модулей независим от их implementation, проверка собственных модулей так не названа. Независимого нового benchmark annotator и judge здесь нет.
- Новых model/API/SSH вызовов нет. New-wire F/CB качество NOT_EXECUTED; Gemma/Mistral repetitions на новом wire не заявляются.
- Byte cap проверяет реальный сериализованный HTTP body, но не заменяет actual provider tokenizer/context limit. Незавершённые источники и UNKNOWN не означают ALLOW.
- R_fix остаётся модельным fallback с известными FP, wrong causes и пропусками. Regex support/точная цитата/математическое равенство не доказывают entity/time/applicability binding.
- Исторические tests, утверждавшие «любой unseen ID под no-invent/user-origin = mechanical violation», переведены на проверку наблюдаемой provenance/HYPOTHESIS; исходная внешняя policy не заменена более сильной. Новые positive controls отдельно проверяют explicit verbatim user/source-origin требования. CaMeL plaintext adapters также не восстанавливают исходную typed capability/taint authority: сохранённые запреты без буквального контракта остаются hypotheses, а не объявляются разрешёнными действиями.

## Решение и следующий шаг

Сохранить детерминированные исправления и воспроизводимость в fix-ветке. Более строгий V6 — opt-in safety candidate; **не принимать как подтверждённое улучшение F1 и не включать default**. Source observations, hypotheses и mechanical findings теперь лучше разделены, но большой универсальный semantic compiler не реализован.

Следующая необходимая работа: на полных реальных пропусках дать oracle source-bound applicability/exception/role relations, проверить доступный ceiling неизменёнными checkers; затем построить автоматический resolver этих конкретных отношений с исходными policy spans и опровергающим контекстом. Заморозить новый F/CB wire, полные baseline/candidate inputs и budgets, выполнить парные model runs и независимый новый holdout. Gold/IDs не должны входить в resolver или routing. Эту отдельную inference-фазу нельзя заменить нынешним raw replay.

Воспроизведение и выбор receipts — [RUNBOOK.md](RUNBOOK.md).
