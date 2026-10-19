# Guardian v3: состояние исследования — 19.10.2026

**Рекомендация для сабмита: оставить текущее правило R0 и текущие веса; новый ZIP
не собирать.** Сокращённая L1-серия завершена: свежая 4B LoRA обучена одну полную
эпоху на1666 примерах, парная оценка и независимый CPU-аудит завершены.
Смесь35B+LoRA при .40 дала F1 .6452→.6820 на real191 и .8293→.8780 на valid46,
но интервалы прироста включают ноль; самостоятельная LoRA провалила AUROC-гейты.
Исходные human/long-input/volume/runtime критерии не выполнены: EXPLORATORY_ONLY.
[Полный итог C–E](V3_C_E_RESULTS.md), [сырые evidence](v3_C_evidence/INDEX.json).
Платформенный F1 .4585 остаётся сообщённым прежним
результатом; попытки не расходовались. Production defaults и ZIP не менялись.

Исходная ветка judge-single-pass-20261013@7bc4a0b4;
новая research/v3-threshold-data-lora-20261019. Имя ветки взято из задания;
работа в этом отчёте фактически выполнена18–19.10.2026. Запрос сохранён в
[V3_USER_REQUEST.md](V3_USER_REQUEST.md).

| Часть | Статус | Измеренный результат / ограничение |
|---|---|---|
| A: правило решения | Завершена | R1/R2/R3 не прошли все критерии; выбран R0 |
| B1: источники | Проверены и закреплены6 | Два NC-источника исключены; генератор Compli не опубликован |
| B2/B4: схема и нормализация | Сокращённый frozen-v2 | TRAIN1666, DEV154, HOLDOUT301; исходный объём и long-input требования не выполнены |
| B4/B5: пересечения | Техническая проверка выполнена | Защищённые данные исключены до component split; это не доказательство качества меток |
| B3: естественные tau2 ошибки и новые Compli диалоги | Частично |54 официальные симуляции сохранены, не включены как обучающая разметка; TRAIN tau2 сконструирован |
| B5/B6: аудит меток, holdout, обоснования | Машинный и агентский аудит | HOLDOUT301 заморожен до обучения; проверенных человеком0 |
| C: L1/L2 v3 | L1 завершена |1666 строк/105 updates/1 эпоха/48м33с; L2 не запускалась |
| D: абляции | Base/LoRA и фиксированная смесь оценены | Дополнительный вето-слой не запускался |
| E: приёмка | Не пройдена | Локальный сигнал смеси; самостоятельная LoRA провалила перенос, исходные гейты не выполнены |
| F: ZIP | Не создавался | Приёмка E не пройдена; production сохранён |

Ниже сохранена история этапов18.10; её промежуточные статусы заменены итогом выше.

## A: вывод с интервалами

[Замороженный протокол](V3_A_DECISION_RULE_PROTOCOL.md),
[подробный результат](V3_A_RESULTS.md), [сырые свидетельства](v3_A_evidence/INDEX.json).
Критерии записаны до расчётов:80091e83 и уточнение7e7615ba.
Пять внешних/пять внутренних folds по conversation;1000 парных групповых
bootstrap на точку; сетка долей .12/.15/.20/.25/.35/.50/native.

Для R2 порог2.5 выбран во всех folds. При p=.12:
seen397 F1 .436893→.635514, разность+.198621,95% CI[.106103,.381878];
real191 F1 .380000→.375000, разность−.005000, CI[−.026444,.241288].
При p=.20 на real191 разность+.113238, но CI[−.048349,.174810] включает0.
Поэтому сильная цифра397 не удовлетворяет критерию подтверждения на обоих наборах.
R1 и R3 также не прошли низкопревалентный критерий. Результаты не используются
для ослабления требований или выбора новой сетки после просмотра.

Из трёх идентичных strict-final replay получен sd_obs35B/vLLM=.286794 по520
входам/1560 разностям. Это шум скоринга с сохранёнными notes, не полный повтор
production. Отдельный78-row audit base4B/Transformers даёт наблюдённый разброс0.
Проверены200 реализаций для каждого sd .05/.10/.25/.50/1.00 и измеренного sd.
Все новые правила прошли критерий3% на измеренном sd, но не основной критерий A5(a).

## B: источники, фактическая подготовка и ограничения

[Протокол](V3_B_DATA_PROTOCOL.md),
[sources_manifest.json](v3_B_evidence/sources_manifest.json),
[скачанные файлы и SHA256](v3_B_evidence/DOWNLOADS.json).
Данные скачивались на SSH-сервере, сторонний код не исполнялся. Все три ToolRM
Arrow-файла проверены по upstream LFS SHA256; RAGTruth закреплён commit SHA.
Материалы и черновик сохранены вне сервера в B-evidence.tar.gz, хеш проверен.

| Источник | Revision | Лицензия в закреплённом источнике | Использование сейчас |
|---|---|---|---|
| tau2-bench |96a3ef92329baf908ffe9dfe188cea34e8701d2a | MIT | Только источник/инвентаризация задач |
| CompliBench |593543022f67914e7ec9a312b7fa39c8a75e508a | Apache-2.0 | Генератор новых диалогов отсутствует; eval не используется для train |
| ToolRM |beaa8e0caaccd227286fef7910c1ef03d48f4b75 | Apache-2.0 в dataset card |3000 черновых ходов,1500 пар |
| RAGTruth |c103204b9ce28d6bbad859304bf30de72b8ed8fe | MIT |2000 черновых ходов |
| HaluBench |5966a87929f51c204ab3cbef986b449495cc97b6 | CC-BY-NC-2.0 | Исключён: совместимость с конкурсом не установлена |
| APIGen-MT-5k |abc4a517d67c541f85f6470cbd8fd3186b36830e | CC-BY-NC-4.0 | Исключён: совместимость с конкурсом не установлена |

Карточки источников: [ToolRM](https://huggingface.co/datasets/ibm-research/ToolRM-train-data),
[CompliBench](https://github.com/UCSB-NLP-Chang/CompliBench),
[RAGTruth](https://github.com/ParticleMedia/RAGTruth),
[HaluBench](https://huggingface.co/datasets/PatronusAI/HaluBench),
[APIGen-MT](https://huggingface.co/datasets/Salesforce/APIGen-MT-5k).
Это фиксация опубликованных условий, не утверждение, что NC обязательно запрещает
любое исследование или что лицензия репозитория автоматически решает все вопросы
происхождения компонентов. Ограниченные источники не включены без подтверждения.

ToolRM фактически содержит correct/incorrect tool calls. Просмотрены458575 пар:
172043 прошли узкую структурную проверку;240390 различий без однозначного
структурного доказательства исключены из этого адаптера.121 correct-call случая
конфликтуют со схемой адаптации и исключены, а не автоматически переименованы в
ошибочные.41967 no-call пар исключены: у них нет исходного текста корректного
ответа; пустой assistant target создал бы искусственный признак класса.
Остальные причины исключения (парсинг/несвязанные результаты) записаны в DONE.
Пары выбраны детерминированно со стратификацией по источнику/типу ошибки;
варианты генераторов связаны одним scenario по пользовательскому диалогу.

RAGTruth: только upstream train и quality=good, исключены828 случаев с одной
лишь subtle-разметкой как неоднозначные по материальности и2848 по split/quality.
Взяты1700 корректных и300 нарушающих ответов. Исходный контекст представлен как
результат искусственного read-tool; инструмент реально не выполнялся.
Нормализующая политика ToolRM/RAGTruth создана адаптером, а не взята из конкурса:
это перенос схемы задач и upstream gold, ещё требующий проверки соответствия.

Черновик:5000 строк,1800 положительных (**36%**), источники ToolRM60%/RAGTruth40%.
Домены ToolRM: SGD1702, xlam1298; RAGTruth: Data2txt628, Summary675, QA697.
Максимум5840 токенов; **ни одного>16k**. Подтверждённых hard negatives **0**.
Эти числа не удовлетворяют объёму15–25k, капу источника40%,20% длинных входов
и требованию трудных корректных. Структурные ToolRM ошибки также могут уже
перехватываться основным кодом: их количество не доказывает компенсацию FP35B.

Рендер каждого из5000 примеров проверен настоящим закреплённым токенизатором:
training_text равен production build_prompt побайтово, обрезок нет; annotations
не попадают в запрос. Отдельные тесты проверяют изоляцию меток и отказ от
молчаливой обрезки.

Деконтаминация против397+520+1893=2810 защищённых входов:
точный нормализованный текст, MinHash128 по истории+целевому ходу (32bands×4,
проверка Jaccard>=.80) и436 явно именованных пар entity key/value. Совпадений0,
в черновике осталось5000 строк. Найдено789 внутренних near-links, group/scenario/
pair/near компоненты объединены:3499 компонентов для будущего split.
MinHash вероятностный,32-битные shingle fingerprints допускают коллизии;
неструктурированные псевдонимы ID охвачены не полностью. Это не доказательство
полной семантической независимости.

tau2 содержит airline50, retail114, telecom2285, banking_knowledge97 и mock10 задач.
Это инвентарь источника, не готовая разметка ходов и не запущенные симуляции.
mock — технический домен; его нельзя выдавать за разнообразие реальных политик.
Следующим шагом для tau2 нужен отдельный проверенный симулятор/turn-label oracle,
сначала технический пилот, затем масштабирование. Траекторный провал сам по себе
не является ошибкой каждого хода.

## Граница исходного полного C (снимок до сокращённой серии)

1. Нет полного v3 датасета с естественными ошибками, трудными корректными,
   длинными историями и требуемым разнообразием; повторно обучать5k черновик
   вместо указанного набора было бы подменой эксперимента.
2. В опубликованном Compli есть оценка и готовые данные, но нет запрошенного
   генератора guideline variants. Ссылка запрошена у пользователя/Opus. Без
   Compli или дополнительного разрешённого источника сочетание лимитов
   tau2<=40%,ToolRM<=3k,RAG<=2k позволяет максимум8333 строки, меньше15k.
3. Пользователь сообщил, что человеческую проверку сейчас обеспечить не может.
   Требование B5 о полностью проверенном человеком holdout не отменено.
   Подготовлены250 случайных5% карточек; человеческих проверок0,35B-аудит
   расхождений не запускался. Доля исправленных меток **не определена**, а не0%.
   Полные300 holdout-карточек пока не выделялись и не замораживались.

Readiness-проверка даёт **train_ready=false**:
[TRAIN_READINESS.json](v3_B_evidence/TRAIN_READINESS.json).
Отказ от запуска C сейчас следует из этих конкретных требований к данным;
это не отрицательный результат ещё не проведённого обучения и не доказательство
бесполезности LoRA. L1/L2, выбор эпохи, абляции и runtime не измерены.

Полные кандидаты, карточки, исходные лицензии, выполненные скрипты, START/DONE,
логи и контрольные суммы: [v3_B_evidence/INDEX.json](v3_B_evidence/INDEX.json).
Протоколы будущих C/E должны быть закоммичены до их запусков/открытия holdout.

## Продолжение по ограничению «уложись в часы», 18.10 20:49 UTC

Пользователь разрешил продолжить самостоятельно и потребовал часы вместо дней.
Зафиксированы V3_CONTINUATION_PROTOCOL.md, V3_HOURS_PROTOCOL.md и
V3_C_E_HOURS_PROTOCOL.md. Цель15-25k не заменяется искусственным размножением:
запускается отдельная сокращённая серия EXPLORATORY_ONLY с сохранением провалов
исходных требований. Человеческая проверка по-прежнему0; ACCEPT/ZIP закрыты.

ToolACE Apache2 добавлен как отдельный закреплённый источник, а не как отсутствующий
генератор Compli. Модели/данные скачаны на сервере и проверены по upstream LFS/
Git object hash, размеру и локальному SHA256. Qwen3-8B закреплена b968826...;
для L1 остаётся свежая Qwen3-4B-Instruct-2507 cdbee75..., без старых адаптеров.

4B и8B выполнили по18 официальных tau2-траекторий;35B выполняет следующую серию.
Траектории пока помещены отдельно: общий reward не превращается в метку хода.
В текущем коротком кандидате вместо этого явно сконструированные истории retail
по настоящим политике/DB и контрасты фактов ToolACE, плюс части ToolRM/RAGTruth.
Это иной, ограниченный источник сигнала; естественные ошибки tau2 пока не обучают L1.

Подготовлено4226 строк:1576 положительных,2092 сконструированных трудных корректных,
максимум5682токена,0>16k. Native retail code подтвердил исходные данные/переходы
для1724 строк; согласие не проверяется самим API и доказывается отдельно историей.
После проверки против2810 защищённых входов исключено254 строки, осталось3972.
Полная семантическая независимость и человеческая истинность не сертифицированы.

До обучения предусмотрен слепой5% аудит35B, затем разбор расхождений с исходником,
пилот скорости без optimizer updates, заморозка компонентов/сущностей/split и
выбор короткого TRAIN по заранее заданным капам/хешам/времени. L1 ещё не начат.
Промежуточные весовые точки, optimizer/RNG/order и отдельные логи будут сохраняться.
Ориентир окончания сокращённой серии02:18:43UTC19.10, не обещание прироста.

Настроен проверенный Windows task с30мин проверками, максимум4 новых запуска
Codex по необходимости; штатный GPU-прогон проверяет скрипт без LLM-запросов.
Контроллер сервера и все GPU-задания имеют конечное время. Самостоятельное
возвращение Codex/внешняя копия зависят от включённого локального компьютера и
доступной авторизации/квоты; серверный уже запущенный скрипт работает отдельно.

## Scheduled source review, 18.10 21:42 UTC

L1 ещё не запускался. Слепой аудит35B завершён:205 строк,33 расхождения или
технических сбоя. Эти33/205 не являются частотой ошибок разметки. Разбор всех33
по исходным правилам/истории: [решение отклонить текущий набор](v3_hours_audit_evidence/MACHINE_AUDIT_REVIEW_REJECTED_V1.json).
Есть ошибки35B в области действия правил, индексации JSON и учёте defaults;
также найдены реальные проблемы данных: календарные даты ToolRM без опоры
во входе и ненадёжные отрицательные QA/Summary метки RAGTruth при строгом
требовании подтверждать факты контекстом. Машинная структурная проверка этих
семантических проблем не выявляла. Доля исправленных меток не измерена;
метки не менялись, человеческих проверок по-прежнему0.

По [протоколу исправления](V3_SOURCE_REPAIR_PROTOCOL.md), зафиксированному
до нового набора/обучения, в карантин целыми компонентами отправлены329 строк:
219 RAGTruth QA/Summary и110 ToolRM из55 компонентов. Новый набор3643 строк:
tau21470,ToolACE1602,ToolRM490,RAGTruth Data2txt81;1405 положительных.
SHA2563e7f97f058ed8af46e25733c63832b8172559e8779f8454d03125f81dacffcdd.
Повторная механическая проверка и независимое локальное воспроизведение
фильтра совпали. Карантин сохраняет полные старые строки и причины исключения;
новые данные ещё НЕ разрешены для обучения. Запущен повторный слепой35B-аудит
с конечным таймаутом2400с, контроллер ожидает отдельного разбора нового SHA256.

Все имеющиеся tau debug-каталоги, включая неудачные/остановленные версии,
логи/обёртки supervisor и доступные версии исходников включены в новые архивы
с покомпонентными SHA256. Точные архивы и команды указаны в
[handoff](V3_AUTOMATION_HANDOFF.md). Отсутствующие исходники ранних попыток
не восстанавливаются задним числом как оригиналы. Production и ZIP неизменны;
сокращённая серия остаётся EXPLORATORY_ONLY, исходные human/long-input gates
не пройдены. Рекомендация сейчас: сохранить текущий сабмит без изменений.

Внешние копии проверены21:44UTC: три архива113672037байт, все SHA256 архивов
и внутренних файлов совпали. [Результат проверки](v3_hours_audit_evidence/TICK1_BACKUPS_VERIFIED.json).
В materialized source-каталогах сервера нет Git metadata; дополнительные
revision/license receipts и фактические tau Python-исходники сохранены отдельно,
пустой Git HEAD не выдаётся за проверенный commit. Успешно завершены54 tau2
траектории (по18 для4B/8B/35B); они остаются вне обучающей разметки.

## Scheduled repaired-source review, 18.10 22:08 UTC

The repaired3643-row candidate completed a fresh blind35B sample:190 rows,
24 disagreements or technical failures(7 malformed JSON outputs). All24 cases
were reviewed against their full inputs, plus all5 sampled RAGTruth Data2txt
records. ToolACE answers match independently indexed zero-based JSON values;
tau2 refusal targets accurately deny non-pending cancellations without writes;
ToolRM cases expose teacher schema/default/scope mistakes. No labels changed;
24/190 is not an annotation-error rate. This is agent source review, not human
review or certification of every inherited label. Detailed decisions and hashes:
[repaired-source review](v3_hours_audit_evidence/MACHINE_AUDIT_REVIEW_V2.json).

Review was committed before unlocking the existing controller at22:08:07UTC.
Only the new candidate SHA3e7f97f0... is approved for shortened exploratory
training. The longest-ten full-input forward/backward pilot is running without
optimizer updates; deterministic freeze and fresh L1 follow only if source40%,
positive30-40% and hard-negative30% checks pass. No new model endpoint or duplicate
GPU job was launched. Original human/long-input/volume and acceptance gates
remain unmet; no quality or runtime improvement has yet been measured.

The controller retains the frozen02:18:43UTC deadline, checkpoints and finite
timeouts. The current live phase and new backup verification are recorded in
[handoff](V3_AUTOMATION_HANDOFF.md). Production and ZIP remain unchanged;
recommendation remains to keep the existing submission until acceptance is proven.

The pilot subsequently completed10/10,73.44s whole-script time,1653.1tokens/s
for forward/backward passes and11282222592bytes peak allocated memory. These
are technical-pilot measurements, not full training/evaluation/submission runtime.
The first freeze failed before optimization:672/1672 positives(40.1914%).
[Repair protocol](V3_FREEZE_REPAIR_PROTOCOL.md) was committed before correction;
all failed evidence retained. Whole-pair class/hash selection removes six TRAIN
singleton positives without label changes. Four focused data/selection tests pass.

NEW frozen hours-frozen-v2 matches independent local replay:1666TRAIN rows,
666 positives(39.976%),1000 negatives including755 hard negatives;4,662,007tokens.
Sources:tau2=600,ToolACE=600,ToolRM=400,RAGTruth=66. Source<=40%,positive30-40%
and hard-negative>=30% gates pass. Original long-input and human gates fail.
DEV154,HOLDOUT301,65 untrained stress contrasts adding zero independent scenarios.
The component split is unchanged by the class repair. Frozen manifest SHA256
57aa807977966115b547defdad893b09268aea423cb2034d623bb788527d3b7a;
[manifest and file hashes](v3_hours_audit_evidence/hours-frozen-v2_FROZEN.json).

The existing finite controller restarted with --frozen-name hours-frozen-v2 and
launched the fresh L1 training stage at22:13:58UTC. No previous optimizer state
was resumed. One-epoch target105updates,checkpoints every20updates; actual completed
rows/updates and quality remain pending. Do not claim a completed epoch or useful
adapter until the recorded run and paired evaluation complete. Offbox source/log
backups and their per-file hash checks are recorded in the handoff and evidence.
