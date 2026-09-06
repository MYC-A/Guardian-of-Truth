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

Полный кандидат ещё не выбран. На фиксированном error-heavy screen строгий one-shot B
дал TP/FP/FN/TN=3/2/4/3, F1=0,5 против A=2/5/5/0, F1=0,286 на тех же строках.
Это stop/go сигнал, не замена полного результата; три решения B были fallback.

## Current bottleneck

Нужно отделить эффект строгого prompt от эффекта архитектурного разложения. Допустимая цитата
не доказывает правильную сущность, состояние, условие или вывод. Extractor C сам может стать
новым источником ошибок; два первых технических pilot-вызова дали HTTP 400 json_validate_failed
и остановлены, а не посчитаны качеством архитектуры.

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

Этап C: extractor material checks → proof-safe exact routing / узкий verifier пачками 2–4 →
ledger → ограниченный final judge. Реализованы strict schemas, точные уникальные `quote`,
coverage-gate, безопасная арифметика и 0 LLM-вызовов после уже доказанного механического нарушения.
Старые format-pilot каталоги сохраняются и не смешиваются с результатом. Последний код ещё не
имеет чистого live-smoke: выбранная Groq 20B исчерпала token rate limit; смена модели сейчас
исказила бы A/B/C-сравнение.

## Next experiment

Чистый C-screen на тех же 12 строках. Если он лучше B по ошибкам/Reason Precision без провала
recall и чрезмерной цены — полный B/C на 46 строках; затем ручной reason audit всех новых
semantic positives и окончательное KEEP_ONE_SHOT/KEEP_STRICT_ONE_SHOT/KEEP_DECOMPOSED.

## Should we continue this goal?

Да. Baseline и B-screen готовы; чистый C-screen, полный B/C, cost/reason audit, выбор режима
и новый error audit ещё не завершены. Следующую архитектурную задачу не подменяем
этим списком намерений; REPLACE_GOAL будет предложен только после выполнения критериев.

## Проверяемые этапы

| Этап | Требуемое доказательство | Статус |
|---|---|---|
| 1. H1/H2/H3 | Числа и построчные источники, не прежняя оценка «1/8 полностью правильно» | Готово, H2 с ограниченной областью доказательства |
| 2. Reason Precision | Явный знаменатель semantic-positive, material-valid основание, coverage/неоднозначности | Готово |
| 3–4. Det-layer | Общие классы, контрпримеры, тесты, FP-аудит, shadow-абляция | Typed слой и 16 тестов; runtime только безопасная арифметика |
| 5. Narrow verifier/ledger/final | SUPPORTED/CONTRADICTED/RELATED_ONLY/INSUFFICIENT; fail-safe | Реализовано, автономные тесты проходят |
| 6. A/B/C screen | Одинаковые строки; baseline/strict/decomposed | A/B готовы; C format pilot остановлен |
| 7. Полный A/B/C | Метрики, calls/tokens/latency/validity и Reason Precision | Не выполнено |
| 8. Выбор KEEP_* | Преимущество над хорошим one-shot, цена и переносимость | Не выбран |
| 9. Новый bottleneck | Повторный аудит всех остаточных FP/FN выбранного варианта | Не определён |
