# V4 semantic judge benchmark

Статус: протокол подготовки; измеренных победителей пока нет.

## Доступность

06.09.2026 авторизованный GET `/openai/v1/models` вернул HTTP 200 и, среди других,
`openai/gpt-oss-20b`, `openai/gpt-oss-120b`, `qwen/qwen3.6-27b`, `qwen/qwen3.8-27b`.
Это доступность каталога, не подтверждение качества или успешного конкретного JSON-запроса.
Ключ читается из игнорируемого `.env.example` и не включается в отчёты.

По [официальной документации Groq](https://console.groq.com/docs/rate-limits)
публичные free-limits этих моделей включают 8K TPM и 200K TPD; реальные ограничения
организации могут отличаться. Бюджеты будем фиксировать до вызовов, не повышая тариф автоматически.
Compound исключён: его встроенные инструменты меняют условия закрытого evidence benchmark.

## Единый протокол

Сначала замораживаются список claims, row set, оригинальные evidence spans,
независимые от проверяемых моделей relation-аннотации и хэши.
Для всех моделей одинаковы prompt, evidence packet, parser/validator, temperature=0,
лимит output tokens и набор утверждений. Отличается только модель; необходимый
провайдерский адаптер и различия native reasoning defaults фиксируются явно.
Совместимость reasoning-параметров зависит от модели — [API reference](https://console.groq.com/docs/api-reference).
Не трактуем одинаковую temperature как гарантию одинаковой детерминированности.

## Каскад

1. Фиксированный claim↔evidence audit set: relation accuracy, per-class ошибки,
   Reason Precision proxy, valid output %, entity confusion, wrong polarity,
   hallucinated rationale. Proxy не подменяет ручную Reason Precision полного valid.
2. Полный valid только лучшим кандидатам, с одинаковым inference-контуром и ресурсами:
   F1/P/R/TP/FP/FN/TN/fallback и ручной reason-аудит semantic positives.
3. Несколько повторов 2–3 финалистов на одном зафиксированном срезе:
   стабильность меток/причин, валидность, wrong-reason rate.

API/JSON failures не выбрасываются из основного знаменателя; отдельно показывается
качество среди пригодных ответов, если это помогает понять причину ограничения.
Сначала сравнение judge без det-сигналов, затем отдельная абляция выбранного judge с ними.
Ошибочная причина не превращает prediction в 0 автоматически.

## Рекомендации

- BEST_LEADERBOARD_CANDIDATE: пока не выбран.
- BEST_ROBUST_CANDIDATE: пока не выбран.
- RECOMMENDED_JUDGE: пока не выбран; размер/название модели не заменяют измерения.
