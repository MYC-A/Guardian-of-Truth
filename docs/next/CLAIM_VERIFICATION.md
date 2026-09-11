# Claim verification

Claim extractor получает только candidate response. Prompt, trace, id, label и
explanation закрыты. Это предотвращает подгонку формулировки claim под доступное
доказательство.

Минимальная схема различает `action`, `state`, `attribution`, `intent`,
`refusal`, `fact`, `absence`. Текущий C0 точно выделяет ограниченное множество
явных intent/completed/refusal/absence формулировок; остальные предложения
остаются непокрытыми и не интерпретируются как безопасные.

Binder сохраняет все entity keys. Completed action требует explicit effect
confirmation; attempted/failed call недостаточен. Absence требует completeness
certificate. False refusal требует исчерпывающий сертификат допустимого плана,
а не наличие похожего инструмента.

Оценивать нужно отдельно extraction coverage, kind accuracy, entity binding,
evidence entailment/contradiction и end-to-end conditional gain.
