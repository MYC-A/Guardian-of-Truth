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

## Техническая проверка подключения

В первой попытке контроль завершился полностью. В adapter-arm обнаружены 22
предупреждения vLLM об исходных именах q/k/v и gate/up. Adapter-arm остановлен
до расчёта качества, контроль сохранён. Эти предупреждения сами по себе не
доказывают потерю весов: worker проверяет исходные имена, а manager затем
упаковывает их в qkv_proj и gate_up_proj. Первичное сообщение о доказанной
потере части адаптера было слишком категоричным.

В техническом повторе список target_modules и все настройки остаются прежними;
добавляется read-only RPC к worker после первого probe. Требуются все 50 исходных
модулей, их покрытие после упаковки и точное совпадение A/B с GPU-буферами.
При неуспешной проверке arm останавливается. Полностью законченный контроль
переиспользуется только после сверки config, inputs и exact coverage. Gold до
завершения обоих arms не читается. Это повтор из-за технической неопределённости,
не выбор лучшего quality-run. Ранее полученные classifier-only результаты
оцениваются с учётом исхода этой проверки; по одним warnings они не отвергаются.
