# Проверка минимальной декомпозиции

Статус: эксперимент завершён. Решение — `KEEP_ONE_SHOT`.
Итоговые данные и stop-rule: [DECOMPOSITION_RESULT](DECOMPOSITION_RESULT.md).

## A — замороженный baseline

Источник: `outputs/claim_gate_20b_full`, 46 строк `valid.parquet`, strict claim gate,
`openai/gpt-oss-20b`, graph reader, 4800 символов evidence, 2048 output tokens,
temperature=0, threshold=0,5. Исходный prompt и артефакты не изменяются.

| N | TP | FP | FN | TN | Precision | Recall | F1 | Fallback |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 46 | 14 | 5 | 9 | 18 | 0,7368 | 0,6087 | 0,6667 | 18 |

У baseline 40 логических semantic-row запусков и 6 механически решённых строк;
из-за повторов транспорта было 99 HTTP attempts, 143389 reported tokens и 1104,3 секунды.
Эти три величины нельзя смешивать: логический LLM-вызов и HTTP attempt при retry — разные единицы.

Ручной аудит всех 13 semantic-positive решений: Reason Precision 4/13–5/13
(30,77–38,46%), cited Reason Precision 1/13–2/13, correct-label/wrong-reason TP=4/8.
Неоднозначность границ связана с сериализованным JSON bank033; gold не переписывается.

## Контроль A/B/C

Схема потока: [PlantUML](10_decomposition_experiment.puml).

- **A BASELINE**: исторический неизменённый one-shot выше.
- **B STRICT ONE-SHOT**: та же модель, reader, evidence budget, parser, output budget,
  threshold и ровно один semantic запрос на нерешённую механически строку. Меняется только
  фиксированный verification appendix: entity/date/state/policy-condition/арифметическая проверка.
- **C DECOMPOSED**: extractor material checks → только доказательные exact checks кодом,
  остальные узкими пачками 2–4 в semantic verifier → check ledger → один final judge.

Первый экран использует замороженные `experiments/decomposition_screen_ids.json`:
все пять baseline FP, пять baseline FN и два semantic TP. Это намеренно error-heavy
development slice, не репрезентативная оценка F1. Он служит только stop/go gate.
При положительном сигнале B/C запускаются на всех 46 строках. Ни метка, ни explanation,
ни прежний audit не передаются моделям.

На этом экране A дал TP/FP/FN/TN=2/5/5/0, F1=0,2857. B дал 3/2/4/3,
F1=0,5000, fallback=3/12, 12 логических вызовов, 15 HTTP attempts, 53233 tokens и 335,9 с.
Однако ручной Reason Precision B равен лишь 1/5, а correct-label/wrong-reason TP=2/3.
Значит, B прошёл label stop/go, но пока не доказал улучшение оснований решения.

Первые C-вызовы были только format-smoke и не входят в метрики качества. После исправления
strict schema, reasoning effort, Unicode payload, точных уникальных цитат и coverage-gate
чистый smoke последней версии выполнен на Groq 20B и повторён на Gemini 3.5. Оба extractor
вернули неполный material set, поэтому сработал заранее объявленный stop-rule.

## Критерии принятия

Decomposition принимается только если относительно B она уменьшает реальные ошибки и/или
существенно повышает Reason Precision без уничтожения recall и с оправданной стоимостью.
`RELATED_ONLY`, `INSUFFICIENT` и невалидный sub-call не являются error. Невалидный final
judge использует прежний безопасный fallback 0. Один опровергнутый ошибочный reason также
не превращает всю строку в 0: в ответе может существовать другое нарушение.

Итоговая таблица должна содержать F1/P/R/TP/FP/FN/TN/fallback, логические calls,
HTTP attempts, reported tokens, latency, structured validity, Reason Precision,
wrong-reason TP, det catches и все изменившиеся строки. Полная quality-таблица обязательна
только для варианта, прошедшего stop-gate; не прошедшему C нельзя приписывать метрики решений.

Фактический stop-gate: последняя версия extractor пропустила очевидные material anchors
на одной и той же frozen smoke-строке и с Groq 20B, и с Gemini 3.5 Flash. C остановлен
до quality-run, как требовал протокол. B не принят: label-прирост Groq screen сопровождался
падением Reason Precision, а независимый Gemini screen дал худший recall/F1.
