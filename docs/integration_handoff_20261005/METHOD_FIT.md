# Первичные источники: что имеет смысл проверять для Guardian

Проверено 05.10.2026. Это небольшой набор кандидатов для агентского задания,
не исчерпывающий literature review и не заявленный перенос качества на Guardian.
Механизмы не исполнялись в этой handoff-фазе.

| Метод / первичный источник | Подтверждённое назначение | Наша гипотеза и минимальная проверка | Ограничение переноса |
|---|---|---|---|
| [Self-RAG, paper](https://arxiv.org/abs/2310.11511) | Обученная модель с reflection tokens для retrieval по необходимости и оценки генерации. | Проверить идею условного поиска по unresolved dependency против direct и fixed second pass при равных calls/tokens. Это наша адаптация, не воспроизведение метода. | QA/factuality задачи не устанавливают policy applicability. Prompt-only critique не заменяет обучение оригинального метода. |
| [ALCE, paper](https://arxiv.org/abs/2305.14627), [код авторов](https://github.com/princeton-nlp/ALCE) | End-to-end retrieval/answer benchmark, отдельные метрики correctness и citation quality. | Разнести exact addressing, поддержку factual claim и normative applicability. Измерить cause-valid TP отдельно от literal quote success. | Даже supported factual claim не доказывает обязательство или исключение; адаптер в Guardian scorer необходим. |
| [τ-bench, код авторов](https://github.com/sierra-research/tau-bench) | Диалоги user/agent/tools с policy и оценкой final state/reliability. | Кандидат на новые реалистичные traces: извлечь target turn, сохранить исходную policy/историю и независимо аннотировать binary violation. Сначала проверить происхождение и overlap с valid46. | Final task success не равен нарушению текущего хода. Ранее использованные tasks не hidden. Нельзя предполагать происхождение valid46 только по похожим названиям доменов. |
| [τ²/актуальный repository](https://github.com/sierra-research/tau2-bench) | Дальнейшее развитие task environment; README отмечает несовместимость части banking_knowledge scores после grading update. | Pin конкретный commit/task release и фиксировать source hashes, contract и adapter. Обновлённые task definitions пригодны для нового отдельного benchmark. | Новая версия не основание молча менять original valid.parquet labels или объявлять сопоставимость старых результатов. |
| [AgentDojo, код авторов](https://github.com/ethz-spylab/agentdojo) | Динамическое окружение оценки prompt-injection attacks/defenses. | Наш вывод: отдельные source-boundary probes для quoted role markers и untrusted tool text. Сначала lossless adapter и parser traversal; потом тест utility вместе с resistance. | Это security challenge set, не основной policy-violation scorer. Его task success/attack metrics нельзя смешивать с Guardian F1. |

Перед внедрением любого нового механизма агент должен записать assumption mapping,
версию, минимальный comparator, source/label independence, стоимость, отрицательные
контроли и измеренный результат. Чужой leaderboard и большое framework API не
являются подтверждением, что механизм закрывает наши реальные ошибки.
