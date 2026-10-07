# Lynx: результаты полного valid46 и остановка новых экспериментов

Все46 исходных строк, неизменный gold23/23. Одна диагностическая реплика. Новая фаза e6632db4, тот же Lynx70B IQ4_XS/b11459. Native turn projection FAIL→ERROR проверяет практическую корреляцию с binary task, не превращает factual grounding в полный policy checker.

| Arm | TP | FP | FN | TN | Precision | Recall | F1 |
|---|---:|---:|---:|---:|---:|---:|---:|
| Старый Lynx v3 |9|2|14|21|.8182|.3913|.5294|
| Новый witness v4, старый QUESTION сохранён |5|6|18|17|.4545|.2174|.2941|
| Qwen B2 baseline |13|1|10|22|.9286|.5652|.7027|
| Qwen + Lynx old accusation view |9|1|14|22|.9000|.3913|.5455|
| Qwen + Lynx old view + current action |11|1|12|22|.9167|.4783|.6286|
| Qwen + Lynx new source witness + current action |8|1|15|22|.8889|.3478|.5000|

Все перечисленные arms имеют46 пригодных binary decisions, без technical exclusions. Baseline Qwen включает3 fallback accusation records: наличие доставленного pre-pass и качество решения не следует смешивать. Фильтр сохраняет ERROR при native PASS, удаляет при FAIL. Это row-level диагностика; binary positive не доказывает правильность конкретной причины.

Для нового standalone witness относительно v3:2 FN→TP,6 TP→FN;1 FP→TN,5 TN→FP. Итого14 flips, net−4TP/+4FP. Более полный input не гарантирует улучшения модели. Full original prompt удалось разместить для18/46 turn checks; остальные28 имеют явно перечисленные gaps. Считать FAIL на неполном view доказанным нарушением нельзя.

Добавление текущего действия к старому accusation document исправляет реальный adapter defect и net сохраняет на2 больше binary TP, чем old filter. Однако всё ещё теряет2 из13 baseline TP и оставляет единственный FP. Новый witness filter теряет5 из13TP, FP не убирает. Ни один фильтр не проходит prereg criterion no TP lost + FP removed. В осторожном control, сохраняющем baseline при gaps/failure, old/action arms совпадают с baseline; new witness:12TP/1FP/11FN, F1.6667, также хуже.

**Решение:** measured Lynx arms не принимать в основной detector/filter. Исправления witness и исходные raw сохраняются как исследовательские артефакты. Default/production не менялись. Это ограниченный отрицательный результат конкретного serving/task/adaptation, не доказательство бесполезности всех Lynx конфигураций, графов, claim extraction или source-addressed evidence.

Независимый source review отдельно обнаружил неправильный QUESTION «What does the document say?», ошибки source authority, procedural verification и model polarity. Отдельный v5 question-only arm был зафиксирован, но пользователь остановил дальнейшие эксперименты. Его частичные receipts сохраняются; полного comparable v5 результата нет, гипотеза об эффекте QUESTION не закрыта. Новых вызовов после остановки не планируется.

## Исполнение и сохранение

Завершённая v4 фаза:104 новых model calls,530351 tokens, usage отсутствует у0 calls. Верхняя оценка112, часть exact requests повторно использована через cache. Все полученные checks VALID. Полный reviewed re-score совпал по confusion matrices/F1 с original score; новый receipt дополнительно содержит precision/recall и hashes. Старый score не перезаписан.

Публикация сначала отказала, потому что новый output root попадал под outputs/* ignore. Это наша инфраструктурная ошибка, не сбой inference. Добавлены точные allowlist roots и исключения locks/tmp; публикация возобновлена без повторного inference, SHA d1ce9912a5a18b28b0c2a58b54dbb03ed70cd719 проверен удалённо. Original BLOCKED state сохранён, объяснение — publication_recovery.json. Independent code/source review выполнен отдельным агентом;31 связанных локальных тестов проходят. Это не независимая разметка cause gold.

Артефакты: outputs/guardian_lynx_witness_20261007/{runs.jsonl,score.json,score_reviewed.json,execution_summary.json,packets/,cache/attempts.jsonl}. Детерминированная независимая арифметическая сверка Git blobs: scripts/audit_lynx_metrics.py, без checkout Windows-недопустимых model paths, без сети.

valid46 — development diagnostic, не hidden test. Конкурсные548 строк из пользовательского сообщения — другой набор, поэтому F1.7027 здесь нельзя считать победой над конкурсным F1.61091.
