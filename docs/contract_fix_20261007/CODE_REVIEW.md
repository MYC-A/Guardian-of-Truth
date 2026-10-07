# Проверка кода исправлений — 2026-10-07

## Область и независимость

Проверено текущее рабочее дерево `Guardian-contract-fix-20261007`, включая дополнения после коммита `6add1a20`: public wiring P/S/F, policy coverage gate, phase manifests, records/scorers, budget reservations, межпроцессная блокировка, byte cap и адресация evaluator. Финальный SHA должен быть указан основным отчётом после commit+push; этот review не выдаёт промежуточный commit за снимок всех проверенных изменений.

Автор этого review реализовал `verification/common.py`, admission/AT/pool изменения `repair/v5.py`, поздний общий receipt gate в `verification/admission.py` и подключение этого gate в reviewer entrypoints, а также `test_contract_safety_admission.py`. **Проверка этих собственных изменений не является независимым review.** Независимая часть этого файла касается кода других исполнителей: P/S/F, root wiring/records/budget, prepass и evaluator. Reviewer другого исполнителя отдельно нашёл transport failure bypass в common.call; исправление и контрасты добавлены автором соответствующего кода.

Новых model/API/SSH вызовов в review нет. Runtime других исполнителей не редактировался; root получал воспроизводимые findings и исправлял свой код. Новые тесты использовали deterministic boundary replies и временные файлы.

## Найденные и повторно проверенные границы

1. **Неизвестное исключение не должно получать механический сертификат.** В промежуточном P/F обычная фраза `Administrators are exempt from this limit/requirement` оставалась вне словаря guards. При двух совпавших F proposals и подтверждённом administrator получался ERROR. После замечания authority ограничена полнотой разбора всего переданного нормативного контекста. Повторены также другой текст `The preceding obligation is waived for this session`, разрыв абзаца и markdown с устаревшими примерами: теперь HYPOTHESIS. Это более общий механизм, чем добавление слова `exempt` в blacklist.

2. **Полнота прочитанного policy и полнота истории различаются.** В `Layers.findings` наличие POLICY gaps переводит F/P MECHANICAL в HYPOTHESIS с `UNRESOLVED_POLICY_COVERAGE`. Нельзя считать grammar coverage полученного subset сертификатом отсутствия исключений в непрочитанном policy. Caller closure истории не отменяет этот gate. S использует отдельный явный `tool_universe_closed`; полнота синтаксического разбора каталога сама не закрывает вселенную инструментов.

3. **Явно неуспешный transport не выдаёт verdict из своего content.** Даже schema-valid JSON при HTTP429/error finish не используется. При HTTP-success и `finish_reason=error` сохраняется прежний единственный bounded retry `attempt+100`, но первый content не принимается. HTTP401/402/403/429 не запускают этот retry. Это различие важно: первая версия защиты случайно выключила существующий успешный retry.

4. **Phase identity защищает resume.** `freeze_phase` сравнивает input/config/code fingerprints; прежний output без phase manifest отвергается. Expected IDs фиксируются отдельно, missing/invented IDs и второй успешный ответ отвергаются. Старые файлы не перезаписываются. Новые runners защищают весь цикл manifest → load → todo → execution → append межпроцессным lock, а не только локальный append между threads.

5. **Бюджет не освобождается из-за отсутствующих token fields.** Ранее truthy `usage={"total_tokens":4000}` превращался в ACTUAL с нулём токенов и стоимости. `charged_usage` теперь требует оба корректных неотрицательных integer поля; иначе остаётся консервативная reservation. Ошибочные/partial usage и 429 attempts проверяются отдельными контрастами. Общая запись ledger защищена межпроцессным lock и fsync.

6. **Byte cap проверяет фактическую сериализацию HTTP body.** `wire_body` общий для preflight и `post`. Ранее ensure_ascii=False preflight мог недооценивать body, отправляемый с JSON escape sequences. Completion reservation хранится отдельно; это byte cap, а не проверка provider token context. При переполнении нового injected request допускается явно записанный неизменённый baseline request, только если он сам проходит cap.

7. **Технический gap и whole-row retry не одно и то же.** Primary reviewer/prepass failure управляет retry строки. Terminal optional verifier/layer failures отдельно попадают в `technical_gaps`; fallback decision не запускает бесконечный полный rerun. Успешный bounded retry не считается terminal failure из-за `first_invalid`. Runners сохраняют `layer_trace`, включая extraction steps, вместо потери NOT_EXECUTED слоя F.

8. **Document ID не идентифицирует единственную норму.** `apply_eval` больше не понижает все requirements одного source ID. Если source соответствует нескольким requirements, binding остаётся UNRESOLVED; изменение applicability возможно лишь при единственном requirement в analysis. Это ограничение адресации, а не доказательство применимости этого requirement.

## Проверка архивного эффекта

Независимо пересчитаны пары `baseline_replay_v2.json` / `fixed_replay_v2.json`: одинаковые phase keys, expected IDs, source fingerprints и множества строк. Это сохранённая фаза до позднего общего primary receipt gate; финальный replay после него публикуется root отдельной фазой.

| Проверка | Результат |
|---|---:|
| Сопоставимых фаз set/rep/arm | 28 |
| Row projections | 1578 |
| Изменений binary | 0 |
| Изменений полного accusation | 0 |
| Missing requests после ремонта | 0 |

Это replay обработки сохранённых ответов R_fix/R_comb, **не новое inference качество F/CB/CBT/CBTE**. Изменённый full-context F wire и neutral prepass требуют новых ответов; старый request cache не становится совместимым от совпадения текста цитаты.

Разобран временно потерянный `ext_ret_019`, ext_tau2 rep3 R_fix. Первый verifier ответ, key `43735f...`, HTTP200/finish=error, содержит оборванный JSON с tab loop. Второй, attempt102/key `4cbbfd...`, полностью schema-valid SUPPORTED. После восстановления bounded retry тот же cached chain снова даёт binary1 без сети. Но причина SUPPORTED ошибочно говорит, что history h31 наступил после current t0. В h30 перечислены изменения, h31 явно подтверждает их, затем начинается current move. Сохранение этого binary TP не означает исправления причины.

`v6_readmission.json` честно обозначен OLD_PROPOSAL_READMISSION_NOT_V3_INFERENCE. Потери прежних срабатываний от новых semantic gates нельзя скрыть за нулём изменений в R_fix/R_comb replay. Указанные в основном отчёте потери TP требуют сохранения conservative candidate opt-in и не дают оснований объявлять его улучшенным default.

## Проверки и оставшиеся ограничения

На последних root patches отдельно выполнены `test_contract_safety_records.py`, `test_contract_safety_prepass.py`, `test_v6fix_cli.py`, `test_addons_evaluator.py`, `test_addons_hook.py`: **80 passed**. Среди них — четыре независимых процесса с общим counter/lock, изменение input/config/code при resume, partial usage, exact wire byte cap и неоднозначная адресация requirement. Ранее admission + две universal repair серии после retry correction: **69 passed**. Эти числа пересекаются с общим suite; складывать их как количество уникальных тестов нельзя. Финальный общий suite публикует root отдельно.

В проверенном scope после повторных исправлений не осталось воспроизведённого блокирующего дефекта. Это не доказательство отсутствия других ошибок. Сохраняются существенные ограничения:

- Grammar gate намеренно консервативен: непрочитанный или неразобранный нормативный контекст может уменьшать recall даже при фактически неприменимом исключении. Нужен измеряемый semantic binding, а не ослабление gate ради прежних TP.
- Уникальный requirement в одном model analysis не означает, что исходный source содержит одну норму. Evaluator проверяет вычисление model-selected expression/bindings; он не получает права самостоятельно доказать policy applicability.
- Byte reservations не заменяют provider tokenizer/context validation и актуальную проверку тарифа. Budget caps — защита попыток и оценка расхода, не качество модели.
- Windows `msvcrt.LK_LOCK` ограниченно ждёт занятую блокировку. Второй длительный runner может завершиться lock error; это безопасный отказ, а не распределённый scheduler/resume service.
- Retry legality ограничена primary technical-failure chains и frozen phase identity. Ручная подмена ledger/manifest не является threat model данного локального research runner; независимую аутентификацию provider receipts этот код не даёт.
- `cause_auto` в research scorer остаётся вспомогательным совпадением target/markers. Это не source-based adjudication истинности причины.
- Новых inference экспериментов после wire изменений и независимого нового gold здесь нет. Replay, unit pass и code review не обосновывают universal deployment либо прирост бинарного F1.

Исторические gold, caches, outputs и production в review не менялись. Final merge/default decision остаётся отдельным измеряемым шагом.

## Позднее дополнение: одинаковая защита primary и повторного admission

После замечания root выполнен parser-compatible probe: при policy `Never write FORBIDDEN` и current `FORBIDDEN` полностью валидный ERROR JSON принимался primary `_step` и повторно A_adm2, даже если receipt содержал HTTP429 либо HTTP200/finish=error. Public review и run_v5 возвращали binary1. Таким образом, защита только verification.common.call не покрывала primary reviewer.

После остановки предыдущего frozen replay добавлен общий `receipt_failure` / `interpret_receipt_v2`. Он применяется к полному receipt в integrated primary/controller, run_v5, verification pipeline/v3/v4/second и v6 confirmation recheck. Известный failure нельзя снять повторным разбором raw_content; raw-only interpret_v2 сохранён как отдельный offline parser API. Raw content, HTTP status, finish reason и technical/null projection сохраняются. Wire requests не меняются; integrated request_bytes считает тот же wire_body, который отправляется HTTP transport.

Новые 18 контрастов проверяют оба primary admission profiles, public review, run_v5, receipt helper, пять остальных receipt-aware entrypoints и успешный полностью валидный JSON с finish=stop/length. После дополнения admission tests и две universal repair серии: **87 passed**. Автор реализовал этот gate, поэтому эта проверка — implementation verification. Отдельный reviewer уведомлён о необходимости независимой проверки, а финальный replay выполняет root после нового freeze.

## Позднее дополнение: receipt и schema judge причин

Независимый reviewer prepass обнаружил ещё один receipt-aware обход в `repair/cause.py`: judge/judge_v2 могли принять валидный body при известном HTTP/completion failure и засчитать категорию в cause metrics. По поручению root автор этого файла реализовал общий `_judge_response`; эта реализация также не называется собственным независимым review.

Теперь оба judge сначала проверяют тот же transport_failure contract. Известный HTTP429 или HTTP200/finish=error даёт `technical_unjudged`, с raw content, status и finish telemetry. Локальный JUDGE_SCHEMA требует все четыре поля FIELDS, rationale и category, точные string/enum types и отсутствие неизвестных полей. Полностью валидный JSON при finish=length допускается по общему правилу. Wire остаётся прежним `json_object`, исторические ответы/оценки не переписываются.

Отдельные cross-field invariants v2 сохранены: полностью schema-valid противоречивый judgement остаётся `inconsistent_unjudged`. V1 получил schema/receipt защиту, но не новую v2 методологию задним числом. Его известный fallback к префиксу raw response при отсутствии packet, ограничения source coverage и смысловой source adjudication этим исправлением **не решены**. Валидная схема judge не доказывает истинности его оценки.

Добавлены 35 cause contrasts: failed receipts, положительные stop/length replies, отсутствие каждого обязательного поля, неправильные типы/enums/extra keys и сохранение v2 invariants. Вместе с admission и двумя universal repair сериями: **122 passed**; прежние тесты не потребовали изменения ожидаемых результатов. Reviewer prepass получил исправление для независимого повторного исполнения. Новых inference/judge вызовов и заявлений об изменении cause quality здесь нет.

Независимый prepass reviewer повторно выполнил 35 cause tests и нашёл небольшой metadata defect: non-dict transport (например `[1]`) вызывал AttributeError ещё до общего failure gate. После завершения frozen binary replay root разрешил узкое исправление: status извлекается только из dict, malformed receipt сохраняется в telemetry и даёт technical_unjudged. Добавлены восемь контрастов обоих judge для HTTP403, string/list/int transport. Wire и detector binary dependency graph не меняются; это отдельное cause-only дополнение после снимка финального binary replay, а не замена его frozen runtime.

Финальный независимый повтор prepass reviewer: **43 cause tests passed**, замечаний к safe formatter не осталось. Root после этого выполнил весь выбранный suite: **420 passed, 2 skipped**; свежая isolated wheel build, imports, malformed-receipt cause probe и CLI help также PASS. Установочный smoke использует уже доступные runtime dependencies и не является проверкой установки всех optional extras в пустой ОС.
