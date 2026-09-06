# V4: evidence → semantic claim

Рабочая отправная точка: пользовательский commit `e498c56e31ef161a7a36e1c814a751cec89e5850`.
Предыдущий goal завершён; его отрицательные результаты не отменяем и не запускаем UNKNOWN/RLM заново.

## Current canonical baseline

`outputs/claim_gate_20b_full/`: полный valid, 46 строк, strict, `openai/gpt-oss-20b`,
graph, 4800 символов evidence, 2048 output tokens, temperature=0, порог 0,5.
TP=14, FP=5, FN=9, TN=18, precision=0,7368, recall=0,6087, F1=0,6667;
fallback=18/46. Это исторический замер, а не обещание воспроизводимости стохастической генерации.
F1=0,75 на восьми строках не заменяет полный baseline.

## Current best candidate

Новая V4 candidate ещё не выбрана. Текущий канонический baseline остаётся точкой сравнения.
Номер commit V4 сам по себе не означает выполнение нового V4 goal.

## Current bottleneck

Допустимая цитата не доказывает правильную сущность, дату, условие или логический переход.
Аудит 23 claims: 4/8 semantic TP имеют неправильную причину; Reason Precision 4/13–5/13,
cited RP 1/13–2/13. Семь неверных claims содержат узкий проверяемый предикат или неверную
привязку сущности; это ещё не автоматическое исправление семи причин. Подробности в ERROR_AUDIT.

## Accepted mechanisms

- Существующие точные availability/schema/rules/planning проверки сохраняются.
- Strict claim gate и неизменный порог сохраняются до нового контролируемого сравнения.
- Модельные суждения и будущие shadow-сигналы не становятся механическим verdict автоматически.
- Метки, explanation и аудитные решения не передаются judge как входные сведения.

## Rejected mechanisms

Не развиваем structured UNKNOWN, directed RLM, repeat/repair loops, произвольные веса,
multi-agent debate и большой causal graph. Подтверждённого полезного эффекта нет.
Параллельные статические аудиты строк не являются runtime-дебатами моделей.

## Current experiment

Этапы 3–6: typed deterministic predicates с консервативным abstention, standalone shadow
verifier и фиксированный claim benchmark. Аудит этапов 1–2 завершён; live V4 генерации ещё
не выполнялись. Shadow verifier не подключён к production prediction.

## Next experiment

Проверка det-layer на позитивных/негативных примерах и shadow-абляция; одинаковый claim
benchmark четырём доступным general-purpose judge, затем полный valid двум финалистам
и повторная проверка стабильности. До вызовов фиксируются prompt/набор/лимиты.

## Should we continue this goal?

Да. H1/H2/H3 и Reason Precision готовы; det-layer, многомодельный benchmark, выбор judge,
V4 candidate и её новый error audit ещё не завершены. Следующую архитектурную задачу не подменяем
этим списком намерений; REPLACE_GOAL будет предложен только после выполнения критериев.

## Проверяемые этапы

| Этап | Требуемое доказательство | Статус |
|---|---|---|
| 1. H1/H2/H3 | Числа и построчные источники, не прежняя оценка «1/8 полностью правильно» | Готово, H2 с ограниченной областью доказательства |
| 2. Reason Precision | Явный знаменатель semantic-positive, material-valid основание, coverage/неоднозначности | Готово |
| 3–4. Det-layer | Общие классы, контрпримеры, тесты, FP-аудит, shadow-абляция | Реализация и тесты |
| 5. Claim↔evidence verifier | ENTAILED/CONTRADICTED/RELATED_ONLY/INSUFFICIENT, shadow only | Реализован, 12 автономных тестов |
| 6. Judges | Одинаковые входы и настройки; claim → full → stability | Готовится claim benchmark |
| 7. Рекомендации | Leaderboard/robust/recommended отдельно, с числами | Не выбраны |
| 8. Candidate | Выбранный judge + принятые det-сигналы, full validation и новые ошибки | Не собрана |
| 9. Новый bottleneck | Повторный аудит всех остаточных FP/FN candidate | Не определён |
