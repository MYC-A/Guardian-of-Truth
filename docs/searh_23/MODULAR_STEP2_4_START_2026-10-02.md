# Начало модульного исследования — 2026-10-02

Задание: `A:\GIS_Загрузки\Guardian_Codex_Prompt_Modular_Steps2_4_2026-10-02.md`.
Ветка `research/modular-step2-4-20261002`, изолированный worktree
`C:\Users\Igor\Guardian-modular-step2-4-20261002`.
Base после fetch: **bdc07e2c3dd9a84039cf94ea19909e1eaac1f2d0**;
origin исходной ветки не продвинулся. Чужие Windows worktrees не менялись.

## Что действительно уже работало

| Механизм | Фактический запуск | Ограничение |
|---|---|---|
| R0, R2, H3 | Полный service runtime на dev80/sealed160; raw predictions, hashes, joint completion gate | Только четыре повторяющихся логических формы; у J FN=0 |
| Phi→J, без/с графом | M01/M11 dev; M11 sealed и160 реальных переводов | Схема валидна у121;35 определённых отношений;1 FP/1 FN, нулевая добавка к J |
| FactCG/MiniCheck/Granite | Исправленные native adapters на общем dev-банке80; Granite также исполнялся в H3 | Native classifier и гибрид имеют разные задачи/метрики |
| Codestral→IR |16 общих dev примеров, exact cache recovery после adapter fix |8 valid против11 у Ministral; не проверяет все Code/Instruct модели |
| Independent B v2 |12 искусственно испорченных upstream ответов |9 recovered против5 у v1; естественный transfer не проверен |
| HTTP/CLI R0 | Живые ERROR/NO_ERROR, outage→UNKNOWN, recovery, context boundary, batch, audit | API-backed; не офлайн качество |
| CCG/ccg2lambda, FActScore adaptation, SelfCheck-NLI, Triad | Пока в этой новой постановке не выполнены | Репозитории получены; установка и пилоты впереди |

Не называем прошлые AMR и relation experiments непробованными.
`operation_check/oc_run_amr.py` реально использует amrlib+RBW aligner,
condition/concession/time edges. Нового AMR прогона пока не планируем:
без отдельного изменения scope/modal bridge он повторял бы старый опыт.
`RELATION_GRAPH_RESEARCH_2026-09-28.md` сохраняет retrieval/RD/DIR/RC
и новые мини-кейсы; результат не переносится автоматически на state graph.

## Точное сопоставление System Research V2

Оригинал: `experiments/searh_23/system_research_v2/steps_2to4.py`,
`system_eval.py`, `src/guardian_truth/integration/`.

- Step1: `auto_programs`/`run_s1a` → `ReviewedProgram`; это модельный разбор
  политики, не достоверная полнота исходного текста.
- Step2: `acquire_auto_contracts` → validation/contrastive question →
  `enriched_case` → `facts_from_documented`. Проверяется OBSERVED/REQUESTED/
  EXECUTED, producer, ID, value path и время. V2 измерил P/R=.30/.30 на
  прозаических contracts; синхронизация vocab между Step1 и Step2 слаба.
- Step3: `step3_raw` → literal-grounded claim compiler → `check_claim`.
  V2 sealed recall=.458, несмотря на precision1.0; проблема не решена
  одним точным quote gate.
- Step4: `step4_goal`/`validate_goal` → `ReviewedGoal` →
  **`assess_local_reachability` → `decide_refusal`**. Reachability выдаёт
  REACHABLE/OPEN/CLOSED/UNKNOWN и требует полноты каталога, условий и
  проверенных effect contracts. Пустой inventory не доказывает CLOSED.
- Агрегация: `decide_reviewed`, system multi-Phi consensus и service
  `aggregate_review` — отдельная функция, не переименованный Step4.

Историческое4/4 automatic reachability относится к своему синтетическому
scope. Full-auto System V2 sealed exact10/20, coverage .25;
oracle Step1 дал17/20. Поэтому oracle prerequisites и автоматический
goal extractor не подменяют автоматически работающую общую систему.

## Сервер и ресурсы

Прочитан полностью `/etc/vast-agents-guide.md`; это unprivileged контейнер,
`workspace_is_volume=false`. SSH guardian-vast работает. RTX3090 24576MiB,
GPU idle1MiB; overlay32GB, свободно2GB. Старый `guardian_research` RUNNING,
checkout pin6f72cb77, default r0-service-v1, loopback18090. Его не меняем.
План нового процесса — другой checkout и приватный порт18092.
Нельзя объявлять работоспособность Docker-in-Docker: guide запрещает engine.

Получены оригинальные источники вне проектного Git:

| Проект | Revision |
|---|---|
| ccg2lambda | a68cb264413791150011c347c64a7b35e2f7270d |
| EasyCCG | e42d58e08eb2a86593d52f730c5afe222e939781 |
| SelfCheckGPT |19b492a2a380931bf1ed0ca94a9565c9aa7b03e1 |
| FActScore |f28272deffcf33efc1f1117d5479c10bb75221a9 |

Наличие исходников ещё не является работающим модулем. EasyCCG jar есть,
Java/Coq не обнаружены; models нужно получить. SelfCheck-NLI потребует
отдельного model cache в пределах диска. Новые зависимости — отдельный
venv с существующим torch, без переустановки CUDA/driver.

## Дефекты, которые надо воспроизвести прежде пилота

1. Действующая FORMAL_SCHEMA действительно включена в `formal_messages`.
2. Default B v1 не проверяет все дополнительные quotes так строго, как
   opt-in v2; новый evaluated path обязан использовать строгий вариант,
   исходный C0/R0 сохраняется контрольным неизменным arm.
3. Cache текущего llm хэширует model/messages/sampling, но явные schema/
   normalization/revision/config fingerprints должны попасть в request
   identity новых модулей. Case ID сам по себе не ключ.
4. Старые split только domain-disjoint. Новый manifest обязан разделить
   generators/логические структуры; проверить это до API.

Дополнительные проверки: target-as-evidence, permission-as-occurrence,
policy-as-fact, future/other-ID, revocation/error/version semantics,
licensed aliases, model contract≠DOC_EXPLICIT, explicit context coverage,
SDK retries, invalid/timeout/access failures и scorer alignment.

Новый пилотный API бюджет общий для jobs:300 новых вызовов,
700000 логических токенов,90 минут. Sealed бюджет и shortlist будут
заморожены отдельно до доступа к его gold. До этого допускается только
проверка input hashes и logical-group manifest, не оценивание sealed.
