# Парное сравнение полной ветки 35B на valid46 — 20.10.2026

По уточнению пользователя ветка 4B исключена из обеих версий. Сравниваются 35B
без адаптера и 35B с окончательной LoRA после полного прохода 1458 примеров.
В существующий ZIP изменения не вносятся.

Основа — ZIP `guardian-judge-qwen36-awq-open-review40-max-34fb1c75-20261018.zip`.
Его JUDGE_CONFIG.json сравнен с JUDGE_OPEN_REVIEW40.json и совпадает; canonical
SHA256 `413f663a1c5421ddbd7f1dceb1ad5442e85a1a4b557e5eef1366a6b6ced5ed36`.
judge_stage, prompting и review_stage совпадают с ZIP после нормализации CRLF.
Сохранена production-схема JUDGE_OPEN_REVIEW40 с текущими parser/mechanical fixes
и bounded_turn_shape=true:
overall с hints, open answer_audit, final, MAX(overall, final), квота .40 с hard.
LoRA действует на все generate-вызовы ветки 35B, включая генеративный review.
Промпты, квота, правила решения и размеры batch/context не подбираются.

Оба arms используют engine с поддержкой LoRA, но контроль получает request=None.
Заранее заданы технические изменения runtime относительно ZIP:
enforce_eager=true, async_scheduling=false, как в проверенном native GDN-LoRA runtime.
APC, max_num_seqs=64, max_num_batched_tokens=16384, deadlines и legacy citation
contract лучшего ZIP сохранены. Это проверка алгоритма полной
ветки в host venv; не подтверждение неизменного runtime ZIP на конкурсной GPU.

Один парный прогон, порядок base → adapter; без quality retries и выбора checkpoint.
Лимит одного arm 1790 секунд; штатные stage deadlines из production-конфига.
При техническом сбое сохраняются артефакты, причина разбирается до новой попытки.
Для сравнения требуются 46/46 exact overall и final в обоих arms и одинаковый
stage_input. Gold загружается оператором только после обоих инференсов; в stage
поступают исключительно id, prompt, response и production findings.

Сохраняются TP/FP/FN/TN, P/R/F1, изменения решений, coverage, данные доставки notes,
проверка применения LoRA ко всем generate-вызовам и время. valid46 уже просмотрен;
положительный результат остаётся локальной диагностикой. Promotion/ZIP/платформенная
отправка автоматически не выполняются.
