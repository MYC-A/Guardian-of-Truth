# E2: недостающее сравнение с production35B и сдвиг доли классов

19.10.2026, до новых 35B scores и расчётов E2. Это продолжение замороженного
L1, не новое обучение и не повторное объявление просмотренного holdout слепым.
Существующие критерии E/F сохраняются. Human/volume/long/runtime ограничения
сохраняются; все результаты EXPLORATORY_ONLY, production/ZIP не меняются.

## GPU и идентичность

Единственный новый GPU-прогон: DEV154, затем HOLDOUT301, всего455 source-only
входов frozen-v2. Использовать scripts/eval_judge_valid.py и judge_stage.py
без изменения их поведения, сохранённый regression_r1/judge_config.json:
Qwen3.6-35B-A3B-AWQ, revision00fcea2d3bcf5389b518d4fc082e5590e0ba4844,
legacy context, open answer_audit explicit citations, max_exact overall/final,
chunk16, max_model_len49152, APC on, eager. Параметры сравнить с сохранёнными
перед запуском. CSV содержит только id/prompt/response, labels — отдельный
позиционно/ID проверенный sidecar, не передаваемый model stage. Порядок неизменен.
Сохранить конфиг, исходные входы, START/DONE/FAIL, primary spool, scores/logs и
хеши исполнявшихся скриптов. Финитный supervisor-job, 7200с stage budget,
внешний timeout7500с, без автоповтора. Это не конкурсный runtime-тест.
Для полного сравнения требуются конечные точные overall и final на455/455;
неполное покрытие не выдаётся за отрицательный результат модели.

## Arms и первичные сравнения

M0 = текущий35B max; M1 = frozen L1 adapter; контроль = base4B.
M3 = .50/.50 percentile-rank смесь M0/M1, веса не подбирать, ранги считать
внутри каждого оцениваемого батча, включая каждый ресэмпл. Правило R0 .40,
все hard positives сохраняются и расходуют квоту. Полнота M0 по обоим каналам
проверяется отдельно. Никакой настройки на HOLDOUT/real191/valid46/397.

На HOLDOUT: AUROC/AP, confusion/P/R/F1/FPR/false-discovery-rate, TP получено/
потеряно, FP снято/добавлено относительно M0. При matched recall целевое число
TP равно TP текущего M0@.40; все arms проходят детерминированный ranked prefix
(score desc, original-index asc) до этого числа TP, сохраняя hard positives.
Для M0 это также минимальный prefix при данном числе TP; отдельно показывать
его полное решение@.40. Сравнивать FP при одинаковом TP; gold здесь oracle для
диагностики, не готовый порог. Bootstrap1000 по component/conversation,
common draws, quota/ранги/целевой TP пересчитываются в каждом draw. Report CI95,
число one-class/zero-reference-FP пропусков; эффект зависит от группировки.
Относительное снижение FP >=15% с нижней границей >0 остаётся исходным требованием,
не ослаблять при малом/нулевом FP референса. M1 AUROC gate исходного плана сохраняется.

## Сдвиг доли классов

На HOLDOUT301, seen397 и real191 использовать все точки A:
p={.12,.15,.20,.25,.35,.50,native}. valid46 — только native regression.
Для p!=native ресэмплинг N строк с вероятностями пропорционально
w+=p/pi,w-=(1-p)/(1-pi), seed20261019. Сохранить draw indices и actual prevalence.
В bootstrap сначала common resample целых групп, затем такое же изменение
доли классов, одинаковые индексы для всех arms. Пересчитывать percentile ranks,
R0 quota и M2 на полученном батче, а не переносить исходные предсказания.
Report paired CI95 разницы F1 и FP/TP changes, all-positive reference.
Это симуляция prior shift внутри имеющихся данных, не реконструкция неизвестного
конкурсного domain shift. Низкая доля сама по себе не делает набор конкурсным.
Положительный point estimate с CI, включающим0, не подтверждает перенос.

## M2: только диагностический score-veto

Отдельно от semantic verifier проверить M2 поверх положительных M0@.40.
q=sigmoid(adapter exact log-odds) — условная YES/NO масса, НЕ откалиброванная
вероятность истинного нарушения. Сетка v={0,.01,.025,.05,.10,.20}, q<v снимает
только nonhard baseline-positive. Не заполнять освободившуюся квоту.
На DEV выбрать v с нулём потерянных TP и максимальным числом снятых FP;
при равенстве меньшее v; отсутствие полезного v означает v=0 (no-op).
Сохранить DEV-only решение до анализа HOLDOUT; оно не меняется в bootstrap.
Никакие gold violation_type/family/source не используются как runtime gate.
На HOLDOUT report FP снято/добавлено и TP loss; исходное ограничение TP loss<=2%
сохраняется. На protected cohorts — regression без настройки.
Этот score-veto не устанавливает точное согласие, применимость правила или
отсутствие другого нарушения и не допускается как семантически доказанный слой.
При выборе v=0 завершить ветку M2 без нового GPU-вызова.

## Разбор ошибок и завершение

Сохранить для всех changed decisions исходные policy/history/turn, label,
baseline/candidate решения, scores и source lineage; human review=false.
Описательная классификация ошибок не меняет метки и параметры. Различать
снятое ложное обвинение, потерянный TP, новый TP и новый FP. Сильный результат
на сконструированных источниках не заменяет независимый целевой holdout.
Сохранить результаты и offbox receipts, коммит+push с проверкой remote HEAD.
Следующее обучение/расширение данных обосновывается этими ошибками отдельным
протоколом до оптимизации; закрытые acceptance-гейты не обходить.
