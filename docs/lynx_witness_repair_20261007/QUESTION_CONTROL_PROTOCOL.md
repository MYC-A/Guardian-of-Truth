# Lynx v5: отдельный контроль вопроса

До inference: v4 продолжает выполняться без изменений. Независимый source review нашёл, что v3/v4 turn-task передаёт «What does the document say?» вместо настоящего пользовательского вопроса. У banking task057 это прямо отражено в сохранённом FP reasoning. Это новая диагностическая гипотеза после анализа development valid46, не blind validation.

v5 меняет **только QUESTION** на последний USER event, адресованный production parser в исходном prompt. DOCUMENT и ANSWER берутся из точного frozen v4 packet, проверяется request SHA. Политика, catalog и история остаются в DOCUMENT. Нет новых инструкций по доменам, tools, benchmark IDs или gold. При отсутствии USER — NOT_EXECUTED. При превышении контекста — CONTEXT_NOT_FIT, без новой упаковки/обрезки.

Полные valid46, все23 positive и23 negative; одна реплика, same Lynx IQ4_XS/b11459, temperature0, output600, slot context8000, workers8. До46 inference calls, durable cap60, timeout180/call и1800/job. Старые outputs не перезаписываются. Новая фаза outputs/guardian_lynx_question_20261007; исходная v4 остаётся outputs/guardian_lynx_witness_20261007.

Метрики: TP/FP/FN/TN, precision/recall/F1 и technical coverage для всех46, paired flips v3/v4/v5. Проекция native FAIL→ERROR диагностическая: Lynx проверяет factual grounding, это не полный policy compliance detector. Не объявлять новые правильные причины по binary labels. Никакой смены default по одной development реплике.

Результат может показать исправление адаптера, отсутствие эффекта или ухудшение. Не выбирать лучшие строки/повтор и не менять задание после просмотра outputs. Дополнительные model families и повторения в эту быструю фазу не входят.
