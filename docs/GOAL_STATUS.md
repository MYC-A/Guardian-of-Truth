# V4: one-shot против минимальной декомпозиции

Рабочая отправная точка: пользовательский commit `e498c56e31ef161a7a36e1c814a751cec89e5850`.
Предыдущий goal завершён; его отрицательные результаты не отменяем и не запускаем UNKNOWN/RLM заново.

## Current canonical baseline

`outputs/claim_gate_20b_full/`: полный valid, 46 строк, strict, `openai/gpt-oss-20b`,
graph, 4800 символов evidence, 2048 output tokens, temperature=0, порог 0,5.
TP=14, FP=5, FN=9, TN=18, precision=0,7368, recall=0,6087, F1=0,6667;
fallback=18/46. Это исторический замер, а не обещание воспроизводимости стохастической генерации.
F1=0,75 на восьми строках не заменяет полный baseline.

## Current best candidate

Итоговый выбранный режим — исходный one-shot A (`KEEP_ONE_SHOT`). На фиксированном error-heavy screen строгий one-shot B
дал TP/FP/FN/TN=3/2/4/3, F1=0,5 против A=2/5/5/0, F1=0,286 на тех же строках.
Это был только label stop/go сигнал; Reason Precision B упал до 1/5, а Gemini-control
дал F1=0,25 против A=0,4444. Поэтому B не принят.

## Current bottleneck

У выбранного one-shot A остаются fallback=18/46 и Reason Precision 4/13–5/13.
Следующая узкая гипотеза — упростить только output schema/claim-validator, не добавляя
semantic stages, и проверить снижение `missing_grounding`/`truncated` без потери recall.

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

Этап C закрыт отрицательно. Последняя версия extractor с strict schema, exact unique `quote`
и coverage-gate пропустила `$317/$343` на Groq 20B и `$1000` на Gemini 3.5. Оба раза
coverage безопасно включил fallback. Согласно заранее объявленному stop-rule C не запускался
на полном screen и не принимается. Итог: [DECOMPOSITION_RESULT](DECOMPOSITION_RESULT.md).

## Next experiment

Один one-shot вызов с упрощённым output schema/claim-validator на новом frozen screen.
Цель — уменьшить `missing_grounding`/`truncated` и correct-label/wrong-reason TP без потери recall.

## Should we continue this goal?

Нет: текущая гипотеза получила измеримый отрицательный результат, stop-rule применён,
построчный аудит выполнен и выбран `KEEP_ONE_SHOT`. Указанный выше следующий опыт —
отдельный будущий goal, а не незавершённая часть decomposition.

## Проверяемые этапы

| Этап | Требуемое доказательство | Статус |
|---|---|---|
| 1. H1/H2/H3 | Числа и построчные источники, не прежняя оценка «1/8 полностью правильно» | Готово, H2 с ограниченной областью доказательства |
| 2. Reason Precision | Явный знаменатель semantic-positive, material-valid основание, coverage/неоднозначности | Готово |
| 3–4. Det-layer | Общие классы, контрпримеры, тесты, FP-аудит, shadow-абляция | Typed слой и 16 тестов; runtime только безопасная арифметика |
| 5. Narrow verifier/ledger/final | SUPPORTED/CONTRADICTED/RELATED_ONLY/INSUFFICIENT; fail-safe | Реализовано, автономные тесты проходят |
| 6. A/B/C screen | Одинаковые строки; baseline/strict/decomposed | A/B измерены; C не прошёл stop-gate |
| 7. Полный A/B/C | Только при положительном screen/coverage сигнале | Не требуется по stop-rule |
| 8. Выбор KEEP_* | Преимущество над хорошим one-shot, цена и переносимость | `KEEP_ONE_SHOT` |
| 9. Новый bottleneck | Fallback и Reason Precision выбранного варианта | Определён |
