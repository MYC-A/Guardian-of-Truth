# Проверка логики и методологии — 2026-10-07

## Статус проверки

Проверены текущие contracts P/S/F, их public wiring/fallback, neutral CB, evaluator и offline protocol. Новых API-вызовов, gold amendments или изменений runtime в рамках этого review нет. Этот файл — единственная запись review.

**Часть P/S/F является авторской проверкой:** этот reviewer реализовал эти модули и их новые контрасты. Нельзя представлять эту часть как независимый review. Независимый admission reviewer ранее обнаружил обход исключением `Administrators are exempt...`; после этого authority ограничена полным покрытием нормативного контекста грамматикой. Проверка CB/evaluator и методологии выполнена отдельно от их implementation.

## Что стало согласованнее

1. **Найденный текст больше не равен применимой норме.** P разделяет lexical candidate, поддержанную ограниченную грамматику, source closure и требование буквального происхождения. F разделяет proposal agreement, числовую согласованность, operation binding и полноту нормативного контекста.
2. **Открытый мир не превращается в закрытый при разборе.** S требует caller `tool_universe_closed=True`. P требует closure истории для absence, кроме норм, явно ограниченных данным входом. `complete_input` означает полноту прочитанного входа, а не всех событий мира.
3. **Неизвестная NL применимость не становится code proof.** Не разобранный нормативный документ, абзац, исключение или область действия дают HYPOTHESIS. Список source IDs, контекст которых не покрыт, остаётся в receipt.
4. **Actor ownership проверяется в слоях.** Только assistant-owned current calls/prose участвуют в P/S/F; parser-compatible USER/TOOL/SYSTEM контрасты не обвиняются. Direct recheck не сохраняет механический сертификат после изменения actor или появления unread POLICY.
5. **Буквальное происхождение отделено от семантического.** Отсутствие ID как готовой строки не доказывает, что ID придуман: он мог быть законно вычислен. Даже `must come directly from the user` не обязательно запрещает spelling/concatenation/normalization. Generic no-invent и обычный user-origin остаются гипотезами. Механическая проверка отсутствия допускается только для явно `verbatim` user-origin/source-only grammar. Без этого слова перенос от «provided/come directly» к «встречается буквально» не считается доказанным. Production-parser контрпример с user `concatenation of characters R and 42` и current `R42` воспроизвёл false certificate до последнего сужения и проходит после него.

## Реальные границы универсальности

Механизмы не используют benchmark IDs, доменные answer tables или имена конкретных инструментов для бизнес-решений. Field/tool identifiers берутся из текущего входа и сравниваются точно; `record` не становится alias для `record_id`. Это улучшает переносимость механизма.

**Семантическая поддержка остаётся ограниченной английской грамматикой.** P поддерживает узкие standalone user-origin/source-only конструкции; F — ограниченные turn-shape clauses и их собственные triggers. Не поддержаны произвольные paraphrases, многоязычные политики, общий inference применимости, произвольные exception chains или NL→ontology compiler. Нельзя называть такую поддержку универсальным пониманием политик.

Полное покрытие грамматикой намеренно консервативно: даже нерелевантный, но неразобранный нормативный абзац может оставить правило гипотезой. Это уменьшает риск false certificate, но может уменьшить recall. Исправление границы не эквивалентно улучшению F1. Возврат этих случаев требует отдельного source-based semantic binding/verifier и нового сопоставимого эксперимента.

P provenance FOUND означает только наличие значения. Он не доказывает правильного владельца, актуальности, результата операции или identity. P пока обходит строковые аргументы/строковые элементы массивов; вложенные структуры и произвольные computed values не покрыты полностью. S repeat-after-failure остаётся гипотезой, поскольку структурный повтор не устанавливает запрета повторов. Все эти ограничения должны оставаться видимыми при интерпретации NO_ERROR.

F `at a time` сохраняет прежний operational contract проверки текущего хода. Этот ограниченный профиль нельзя автоматически переносить на произвольные протоколы, где concurrency и один assistant turn имеют иной смысл.

## Целостность public pipeline

`Layers.decide` добавляет только MECHANICAL findings к R_fix. При отсутствии такого finding остаётся исходный R_fix verdict. HYPOTHESIS не становится разрешением и не отменяет отдельно найденное R_fix нарушение. Public CLI передаёт caller closure flags; bare parsed header не устанавливает closure.

Это согласованная граница ответственности, однако **fallback R_fix остаётся модельным**, с собственной применимостью, ложными обвинениями и неполным покрытием. То, что один unsafe mechanical путь закрыт, не доказывает истинности всех оставшихся ERROR. Поддержанный итог также не означает полную проверку всех требований и действий.

При unread POLICY pipeline понижает F/P authority. Direct P/recheck и F.recheck также защищены. F.check получает rules+targets, а не полный packet; использовать его отдельно как whole-input certifier без policy coverage нельзя.

## CB и evaluator: независимая часть review

Neutral CB теперь получает original prompt, очищая response **до** parsing/retrieval. Видимый prepass не зависит от current-action query. Отдельное пространство `blind:` IDs и приложенный prepass source bundle предотвращают молчаливое смешение адресов с основным review packet. Это корректное устранение прежней утечки на уровне code path.

Новый neutral input меняет request/wire. Старые CB ответы нельзя считать предсказаниями на новом входе. Прежний blind/open контроль также не гарантирует равенства views после изменения retrieval: новый matched experiment должен зафиксировать source/context и фактический бюджет.

Evaluator проверяет только собственные expression/bindings модели. Exact numeric tokens, Decimal, nonfinite rejection и string-preserving tokenization исправляют вычисление; они не устанавливают смысл нормы. `interpretation=MODEL` и `binding=MODEL` отражают эту границу правильно. `source_status=VERBATIM/NUMERIC_EQUAL` остаётся слабой проверкой присутствия, а не proof entity/field/exception binding.

`apply_eval` меняет анализ только при внутреннем противоречии и просит re-derive; сам не выдаёт ERROR. Остаточное ограничение: требования связываются по source ID, поэтому противоречие одного выражения может понизить несколько разных требований из одного source. Это потенциальная потеря полезного анализа; её частота и влияние на качество в этой фазе не измерены.

## Проверки и вывод по качеству

Новые P/S/F parser-based контрасты включают положительные explicit verbatim user-origin/source-only случаи, lawful computed ID under no-invent/ordinary user-origin, permitted alternative sources, разные поля/действия, source siblings, cross-paragraph exceptions, receipt администратора, zero limits, роли и unread-policy mutation. Дополнительно проверены USER-owned call/result-shaped history messages: они сохраняют буквальное пользовательское происхождение и не становятся tool authority только из-за синтаксиса. На момент review отдельный слой tests/test_contract_safety_layers.py: **55 passed**. Вместе с tests/test_contract_safety_admission.py: **102 passed**. Это проверка реализованных границ, а не новая оценка качества модели.

Независимо проверено финальное распространение failed receipt gate: integrated/v5/v3/v4/second/confirm не повторно допускают JSON, отбросив известный HTTP/completion failure. Дополнительный controller probe с полностью корректным UNKNOWN: HTTP429/stop и HTTP200/error дают ровно один call и technical null; HTTP200/stop и HTTP200/length с полным valid contract дают два call (controller работает). Полный JSON при length сохраняется; явный failed receipt не становится verdict. Обходов после финального изменения не обнаружено.

PROTOCOL правильно разделяет pure fixes replay, legacy proposal re-admission и NOT_EXECUTED new-wire inference. Правило принятия требует отсутствия новых FP и потерянных TP на каждом полном сопоставимом наборе/повторе. Эти требования нельзя заменить unit pass или общей суммой F1.

Первая progress-фаза replay показывала потерю ext_ret_019 в R_fix external rep3 (38→37 TP, 14→15 FN, FP1), поэтому blanket «качество не ухудшилось» по этой фазе недопустимо. На момент записи final v2 replay ещё формируется; промежуточные progress-файлы не являются окончательным verdict. Финальный отчёт должен использовать завершённые receipts текущего кода, указать новые request misses и классифицировать каждую потерю, включая отказ от прежнего неподдержанного обвинения.

Legacy F proposal re-admission измеряет выживание старых proposals после новых границ. Full-policy F и neutral CB live quality в данной offline фазе **NOT_EXECUTED**. Даже отсутствие регрессий unchanged-wire R_fix не доказывает неухудшения нового полного automatic stack.

## Рекомендация

Сохранить fixes в отдельной ветке и оставить прежний production default. Принимать pure fixes только по завершённому matched replay. Более строгие semantic authority gates полезны как исправления contracts, но их recall/cost требует отдельной оценки; не смешивать эту рекомендацию с объявлением прироста качества. Для broad NL policies нужен отдельно проверяемый source-based applicability mechanism, с oracle ceiling и новыми automatic outputs, а затем независимая разметка нового holdout.


## Дополнение root после завершения проверок

Замечание reviewer по `apply_eval` исправлено: source ID с несколькими requirements больше не понижает их все; binding остаётся UNRESOLVED, отдельно вычисленное выражение сохраняется как наблюдение. Это подтверждают contrast test и CODE_REVIEW. Даже unique requirement не становится source-based semantic certificate.

Финальный replay R_fix/R_comb `fixed_replay_final.json` на 2483c436 и `replay_comparison_final.json` завершён: 28 projections / 1578 rows, 0 binary/reason/target/missing расхождений, 0 drift относительно прежних сохранённых результатов. Ранняя потеря ext_ret_019 устранена восстановлением bounded retry; промежуточные receipts сохранены.

Финальная V6 re-admission `v6_readmission_final2.json` завершена с неизменными fingerprints. Open/closed arms теряют соответственно 51/40 TP при 20k и 59/48 при 400k относительно legacy, без изменения FP. Это regression: правило принятия по качеству не выполнено. F/P на этих архивных входах больше не имеют mechanical authority. Вывод об отсутствии регрессий относится только к unchanged-wire R_fix/R_comb replay, а не к новому полному automatic stack.
