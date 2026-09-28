# Level E: пригоден ли очищенный frontend для Guardian Step 1

Дата: 2026-09-28. Ветка: `codex/relation-research-20260928`.

## Протокол и границы вывода

Это продолжение [EVENT_CANON_v1](EVENT_CANONICALIZATION_RESEARCH_2026-09-28.md),
а не повторный подбор relation judge. Исходный набор Level E и gold зафиксированы
в `a8eda8d2` до inference. Код E1/E2 и изоляция output root зафиксированы в
`569b06b8`; исходные frontend-кандидаты и их ручная оценочная привязка — в
`dc89bd06`; код E3-рукавов — в `168e1023`. Имеются отдельные selection commits
для CE и few-shot до открытия E2 gold. Никаких изменений `scripts/predict.py`
или лицензирующего/направляющего/типизирующего relation stack нет.

Новые policy: 10 доменов, 27 gold canonical events и 10 gold edges. E1 содержит
95 предлокализованных spans с шестью метками, E2 — 80 пар, из них 10 пар
clean/noisy (20 отдельных входов). Все десять E3 policy синтетические,
созданы автором этого эксперимента и полностью заморожены одновременно.
Тест невелик и не заменяет реальные конкурсные траектории. Контролируемый
noise E2 — расширение границы; остальные типы шума из постановки не покрыты.

Старая выборка Level D `dev` использована для обучения/выбора числа примеров,
`val` для эпохи CE, `calib` для его порога. Старый `test` не использован.
Всё моделирование: Mistral `ministral-14b-latest` через API из серверного env,
локально на Vast RTX 3090 — Stanza, bge reranker и LoRA. Рабочий код и сырые
ответы лежат в `experiments/searh_23/event_frontend_level_e/`.

## Подтверждённый дефект извлечения до любого identity judge

Исходный реальный frontend дал 63 кандидата. Ручная привязка до новых
E1/E2/E3-прогонов: 28 из них не являются событиями, семь из 27 gold events
вообще не имеют кандидата. Это самостоятельный потолок recall; никакое
слияние узлов не может создать пропущенный event. Например, в ceramics
потеряны оба `Glaze vessel A/B`; в theater — `Rig spotlight A`; в orchard —
первое опрыскивание. Некоторые предложения одновременно раздуваются в
несколько кандидатов и теряют начальное действие.

## A. EVENTNESS

Сравниваются A1 UD/POS, A3 X-AMR-подобный LLM-граф, A4 узкий LLM, A5 гибрид.
A2 PropBank/SRL не запускался: совместимый checkpoint/инструментарий не был
установлен на сервере; выдавать A3 за полноценный AMR parser нельзя.
Состояния и UNKNOWN сохраняются как потенциальные узлы, а подтверждённые
ENTITY_ARTIFACT/OTHER снимаются. Результат на 95 frozen фрагментах (4
AMBIGUOUS исключены из бинарного подсчёта):

| Рукав | EVENT-like P | EVENT-like R | убрано junk | потеряно real | UNKNOWN |
|---|---:|---:|---:|---:|---:|
| A1 UD | 1.000 | 0.621 | 28/33 | 11/58 | 16 |
| A3 X-AMR-like | 0.637 | 1.000 | 0/33 | 0/58 | 0 |
| A4 narrow LLM | 0.942 | 0.845 | 30/33 | 9/58 | 0 |
| A5 hybrid | 0.943 | 0.862 | 30/33 | 8/58 | 0 |

A4/A5 снимают почти весь мусор, но одновременно выбрасывают 8–9 настоящих
событий. Для обязательной полноты Step 1 это слишком дорогая потеря.
У A1 видимая P=1.0 достигнута ценой ещё большего падения recall и 16 UNKNOWN;
его нельзя назвать надёжным фильтром. A3 вообще не снимает junk.
У адаптированного A3 event-mode schema нет полноценного entity/artifact
отрицательного класса: это диагностический перенос старого signature prompt,
не корректный тест способности настоящего AMR parser различать concept types.
По этому результату AMR/SRL направление не отбрасываем.
У A4 среди пропусков команды `Test tank water`, `Glaze vessel A`,
`Dispatch van 3`, `Dry seed tray Q`; другие промахи относятся к
номинализациям (`water test`, `flight approval`, `Reservation cancellation`,
`Payment verification`) и действию в причастной форме (`firing vessel A`).
Следовательно ошибка затрагивает и императивы, и event references.

## B. SAME_EVENT на чистых и шумных spans

Five frozen inputs B1 raw, B2 UD core, B3 raw+core, B4 core+sentence, B5
raw+core+arguments. `UNKNOWN` не сливается. Few-shot 0/3/5/8 выбран на
36 старых dev парах: победили **8 примеров, 9 TP / 1 FP / 3 FN**, против
**6 TP / 1 FP / 6 FN** у zero-shot. Выбор `04a48139` зафиксирован до E2.

Трёхклассовая LoRA CE с новой головой дала на старом `val` 0 SAME TP за все
три эпохи. Бинарная LoRA с сохранённой pretrained-головой оказалась лучше,
но на `val` максимум 6 TP / 14 FP, а выбранный порог 0,75 на старом `calib`
дал 5 TP / 3 FP. Конфигурации с зафиксированными порогами: `ad2a431c`.
Это слабый претендент на основной слой; sealed E2 всё равно проверяется.

| Рукав | SAME TP | SAME FP | SAME FN | P | R | RELATED→SAME | clean/noisy совпало |
|---|---:|---:|---:|---:|---:|---:|---:|
| B1 raw | 18 | 0 | 14 | 1.000 | 0.563 | 0 | 5/10 |
| B2 core | 13 | 2 | 19 | 0.867 | 0.406 | 0 | 10/10 |
| B3 raw+core | 13 | 2 | 19 | 0.867 | 0.406 | 1 | 8/10 |
| B4 core+sentence | 20 | 7 | 12 | 0.741 | 0.625 | 6 | 10/10 |
| B5 raw+core+args | 18 | 0 | 14 | 1.000 | 0.563 | 0 | 8/10 |
| eight-shot | 19 | 0 | 13 | 1.000 | 0.594 | 0 | 6/10 |
| CE 3-class | 0 | 0 | 32 | — | 0.000 | 0 | — |
| CE binary | 0 | 2 | 32 | 0.000 | 0.000 | 2 | — |

На 80 sealed E2 парах CE не переносится: трёхклассовый не нашёл ни одного
SAME_EVENT, бинарный сделал два опасных слияния и ни одного правильного.
Few-shot улучшил базу лишь на один TP; это небольшой эффект на малом наборе.
B5 сохранил TP/FP базы и улучшил устойчивость метки clean/noisy с 5/10 до
8/10. B2/B4 получили 10/10 стабильности, но часто стабильно ошибались:
SAME на положительных clean/noisy было только 4/10 и 6/10 соответственно.
Устойчивость не равна правильности. В E2 B3 ухудшил общую точность пары,
поэтому уменьшение опасных слияний на REAL E3 не считаем универсальным
преимуществом этого представления.

## C. Frontend repairs

Opaque tool IDs в resolver prompt устранили зависимость ролей от переименования
на новом наборе: **0/63** изменённых ролей между original/renamed. При этом
от исходного resolver получено **11/63** других ролей: проверка rename-инварианта
сама по себе не гарантирует качества ролей. Исходный общий POS rescue с
условием `NOUN/ADJ/PROPN + DET` восстановил **0** кандидатов на E3.

После просмотра этих пропусков начат **отдельный exploratory follow-up**.
Его нельзя считать sealed E3 улучшением: постановка механизма следует из
обнаруженных ошибок. Узкий LLM решает, начинается ли отдельное предложение
с императива; это не вся policy и не поиск бизнес-глаголов. На E4,
зафиксированном до вызовов, label найден у 7/8 команд и 0/12 не-команд,
но полное точное копирование span получилось только у 2/8. Поэтому второй
вариант оставляет LLM только решение о типе и кодом берёт всё исходное
предложение до терминальной пунктуации. На свежем E5: **6/7** точных
положительных и **0/9** ложных; `Service generator 8` остался UNKNOWN.
`Polish brass valve 2` был пропущен на E4: омограф полностью не решён.

На E3 этот follow-up добавил 10 кандидатов; по оценочной привязке это
восстановило шесть из семи ранее отсутствовавших gold events — осталось
только `Dispatch van 3` в fleet. При первом grounding короткий `Glaze`
неверно связывался с `inspect_glaze`; после восстановления полного span
семантический reranker всё равно выбрал этот tool. Общая проверка совпадения
леммы действия с начальной леммой description исправила **2** привязки к
`glaze_vessel`. Это относится только к exploratory рукаву и требует новой
независимой проверки на реальных policy.

## D. Замороженный downstream Step 1

Во всех canonical рукавах одна и та же цепь: `frontend → member-level CE band 0.35 →
extractive evidence → evidence judge → DIR → CLS`. Для canonical nodes
сохранено multi-span представление. `scripts/predict.py` не тронут. Все
запуски находятся в разных output roots; `GOLD canonicalization` использует
только реально найденные кандидаты, `FULL GOLD nodes` дополнительно даёт
gold mentions/roles/tools и служит верхним контролем.

| Вход | correct | extra | missing | P | R | typed | exact/10 |
|---|---:|---:|---:|---:|---:|---:|---:|
| REAL raw | 9 | 43 | 1 | .173 | .900 | 9 | 1 |
| EVENTNESS only | 9 | 14 | 1 | .391 | .900 | 8 | 3 |
| CANON F/veto | 4 | 15 | 6 | .211 | .400 | 4 | 2 |
| EVENTNESS + CANON F | 6 | 2 | 4 | .750 | .600 | 6 | 5 |
| CANON B3 | 9 | 32 | 1 | .220 | .900 | 9 | 1 |
| EVENTNESS + CANON B3 | 8 | 12 | 2 | .400 | .800 | 8 | 4 |
| fixed frontend only | 9 | 44 | 1 | .170 | .900 | 9 | 1 |
| fixed + CANON F | 4 | 15 | 6 | .211 | .400 | 4 | 2 |
| fixed + gate + CANON F | 6 | 2 | 4 | .750 | .600 | 6 | 5 |
| GOLD canonicalization | 8 | 0 | 2 | 1.000 | .800 | 8 | 8 |
| FULL GOLD nodes | 9 | 3 | 1 | .750 | .900 | 9 | 6 |
| exploratory rescue raw | 9 | 51 | 1 | .150 | .900 | 9 | 0 |
| exploratory rescue + CANON F | 5 | 20 | 5 | .200 | .500 | 5 | 2 |
| exploratory rescue + gate + CANON F | 6 | 6 | 4 | .500 | .600 | 6 | 3 |

Основная таблица использует строгую оценку `le_score_strict_graphs.py`.
Исторические alignment-метрики сохранены в `SCORE/downstream_metrics.json`
для совместимости: их значения нельзя подменять числами из этой таблицы.
В строгой оценке дубли не увеличивают
recall, обратное ребро не покрывает правильное направленное ребро,
узел с несколькими canonical labels или NON_EVENT не получает зачёт
по одному удачно совпавшему участнику. На четырёх ручных контролях
(дубликат, обратное направление, загрязнённый узел, правильное ребро)
поведение проверено. Это аудит оценки, не изменение relation stack.
По уже завершённым контролям: RAW — 9 правильных уникальных рёбер,
43 лишних, 1 пропуск, P=0.173/R=0.900; GOLD canonicalization —
8 правильных, 0 лишних, 2 пропуска, P=1.000/R=0.800, exact 8/10.
RAW в историческом scorer выглядит как P=0.385/R=0.952, поскольку
20 отдельных predicted edges могут покрывать всего 9 уникальных gold edges.
Полные строгие результаты сохранены отдельно в `strict_graph_audit.json`.

EVENTNESS без слияния — единственный основной рукав, который заметно
сократил лишние рёбра **при сохранении наблюдавшегося recall .900**:
43 → 14, P .173 → .391. Но E1 показал реальные потери событий, а E3
потерял 3 настоящих mentions; здесь оставшихся дублей хватило для тех же
9 gold edges. Перенос этого эффекта на политики без дублей не доказан.
Слияние F с gate подняло P до .750 ценой recall .600: такое улучшение
не принимается как победа. Повышение recall извлечения в rescue само по
себе не улучшило граф; ошибки объединения и мусорные узлы остались.

FULL GOLD тоже не является безошибочным детектором. Его три лишних ребра:

- ceramics: `glaze → inspect`, цитата `Inspect vessel A's glaze before
  firing vessel A.` говорит об `inspect → fire`;
- theater: `check → rig`, цитата требует проверку перед `activate`;
- fleet: `charge → check`, цитата требует проверку перед `dispatch`.

Единственный пропуск FULL GOLD — orchard `verify → spray_on_Friday`.
Таким образом, правильные узлы не исправляют неверную привязку настоящей
цитаты к другому действию. Это следующий отдельный этап проверки licensing;
в данном опыте его код и prompts оставлены прежними.

До подсчёта рёбер отдельно проверены сами canonical nodes. Для исходных
63 REAL кандидатов F/veto имел 5 неверных слияний разных событий и 15
слияний с `NON_EVENT`. Рукав B3 (`raw + UD predicate core`) уменьшил первое
число до **1**, но оставил **9** слияний с `NON_EVENT`. После A4 gate у B3
стало 0 слияний с мусором ценой удаления **3 реальных упоминаний**
(`e_seedbank`, `e_ceramics`, `e_drone`). Это mention-pair счёт, не метрика
итогового графа и не достаточное основание для интеграции.

## Дополнительные проверки и ограничения

### Ошибка ontology, которую нельзя исправлять пересмотром sealed gold

В `SYSTEM_CORE_ID` написано: result state не является action. При этом
frozen E2/E3 объединяет `Test tank water` и `the water test is complete`
в один E1; аналогично объединены проверка журнала и завершённость проверки,
одобрение полёта и состояние записи одобрения. Это не одно и то же
утверждение о мире. Bare nominal `water test` может ссылаться на событие,
а целая клауза `the water test is complete` утверждает состояние этого
события. `Recorded approval` дополнительно несёт требование записи.

Поэтому часть FN identity judge согласуется с его инструкцией и не доказывает
плохого понимания английского. Старые gold, prompts и числа сохранены;
переименовывать эти ответы в TP после прогона нельзя. В следующем новом
протоколе нужно явно различить:

1. event identity — одно событие/операция;
2. reference to event — точная именная группа, указывающая на это событие;
3. facet/state — завершённость, одобрение, запись, проверенное состояние;
4. artifact — документ/журнал/запрос с информацией о событии;
5. separate check — самостоятельная проверка этого состояния.

Тогда `completion_state → event` связывается типизированной ссылкой,
а обязательство `open ONLY_IF completion_state` остаётся про состояние.
Нельзя удовлетворить его одним упоминанием действия `test`. Это изменение
ontology требует **нового frozen gold**, а не новой настройки на E2.
До такого опыта текущие SAME_EVENT scores не считаются окончательной
проверкой различения ACTION/STATE. Для action/check остаются реальные FP,
например B4 сливает `Inspect vessel A's glaze` и `Fire vessel A`.

### Ограничение реализации predicate core

В B2–B5 проверялся простой UD core. Он выбирает последний VERB в фрагменте,
в nominal/passive случаях может потерять аргументы, а B2/B3 передают только
predicate/mode. При пересечении границы предложения `ud_core` иногда вообще
не находит span: у ceramics P02 пришёл пустой predicate/UNKNOWN, но judge
всё равно слил его с inspection. Поэтому результаты — проверка конкретного
простого нормализатора, не доказательство бесполезности качественного SRL/AMR
или многосоставного representation. Exact original spans не выбрасывались.

### E6/E7: исправления границ и POS как отдельные практические опыты

E6 заморожен в `57f53766` до кода `81c640a9`: 12 новых авторских текстов,
36 ожидаемых cores. Прежний min/max hull возвращал вырезанную subordinate
clause обратно, если после неё оставались другие descendant tokens.
Новый разделитель сохраняет отдельные непрерывные source chunks и выбирает
основным только chunk с predicate; другие clauses и gate-obliques исключены.
Для каждого predicate сохранены исходные offsets и lemma. Это общий код,
без доменных словарей, названий инструментов или условий по case ID.

| E6 | покрыто cores | покрыто чисто | кандидатов с несколькими cores | через предложение |
|---|---:|---:|---:|---:|
| прежний parser | 33/36 | 23/36 | 8 | 1 |
| head-anchored chunks | 31/36 | 29/36 | 1 | 0 |

Неудачи сохранены: в drum не найден самостоятельный `Rotate drum 6`,
в relative укорочен `remain sealed`. Prism и coupon уже пропускались
исходным parser из-за POS. E6 после этих ответов не дорабатывали.

E7 заморожен в `002f2dba` до кода `df244f6a`: ещё 10 авторских текстов,
28 ожидаемых cores, включая десятичные числа, сокращение `Dr.`, цитируемую
метку с точками и длинную modal clause. Для hypothesis arm к тексту временно
добавляется синтаксический prefix `You must`, затем все source offsets
переводятся обратно. Prefix не может попасть в span или evidence.
Гипотезы остаются `UNRESOLVED`, их нельзя считать подтверждёнными events.

| E7 | найдено cores | смешанных фрагментов | вторичных неподтверждённых кандидатов |
|---|---:|---:|---:|
| исходный parser | 16/28 | 0 | 0 |
| chunks на глобальном UD | 15/28 | 0 | 0 |
| UD отдельно по source sentences | 19/28 | 0 | 0 |
| плюс альтернативный POS | 25/28 | 0 | 7 |

E7 измеряет предложение candidates, не precision eventness, actor identity
или downstream. Сокращения и quotes пока не гарантированно разрешены.
Этот компонент нельзя повышать до готового фронтенда по одному recall.

### Аудит оценок и кластеризации

`cluster_metric_audit.json` использует micro merge counts и отдельно считает
удалённые настоящие mentions. В legacy macro recall случаи без gold merge
давали 1.0: поэтому EVENTNESS_ONLY имел видимый merge recall .300 при
**нуле** слияний. В micro оценке у него 0 TP, 0 FP, 20 missed merge pairs.
Также прежний `ceaf_e` фактически использовал intersection size (CEAF-M),
а greedy alignment не всегда максимален. Новый аудит считает CEAF-E с
φ4 = 2|intersection|/(|gold|+|predicted|) и точным maximum matching.
Определение взято из [Luo, 2005](https://aclanthology.org/H05-1004/).
Coref metrics в этом аудите считаются на retained mentions; потери
из полного первоначального inventory не скрыты и указаны рядом.

Дополнительный clustering replay (`d1f31cda`) сравнивает complete-link и
constrained correlation partition. Во втором все пары внутри кластера
обязательно SAME_EVENT; UNKNOWN, RELATED, DIFFERENT и отсутствующая пара
запрещают слияние. Objective — максимальное число сохранённых SAME agreements.
Три ориентации transitivity выполнены по конструкции clique partition.
Replay начат после E3-разбора и помечен exploratory, алгоритм по gold
не выбирается. Если ordered spans/start/roles/tools/members совпадают с
основным рукавом, старый downstream результат переиспользуется; соответствие
записано в `outputs_clustering/reused_predictions.json`.

Replay завершён (`CLUSTERING_COMPLETE`). Complete-link и constrained
correlation дали одинаковый partition на этом наборе: без gate P .250,
R .400, 12 лишних рёбер, exact 3/10; с gate P .750, R .600, exact 5/10,
то есть полностью тот же графовый результат, что gate+veto. Без gate
TP merge pairs выросли 12 → 15, FP упали 20 → 17; все 5 слияний разных
настоящих событий остались. Более строгий solver не исправил неверные
SAME_EVENT решения pair judge. Повторные downstream calls исключены
только для точно одинаковых входов, а не по совпадению итогового score.

Ограничение воспроизводимости legacy aggregator: при равном числе голосов
`max(set(roles), key=roles.count)` зависит от порядка множества. Сохранённые
node attributes являются фактическим входом данного прогона; многократной
оценки variance не делали. В следующем frozen frontend равные голоса
нужно разрешать детерминированно через UNKNOWN с сохранением всех
исходных role/tool alternatives. Пересчитывать нынешние labels ради
лучшей метрики нельзя.

## Внешние ECR-корпуса и реализации

[MAVEN-ERE](https://github.com/THU-KEG/MAVEN-ERE) предоставляет события,
coreference и temporal/causal связи в документах; репозиторий
имеет GPL-3.0 license, а test gold скрыт. [ECB+](https://github.com/cltl/ecbPlus)
размечает event/entity mentions и intra/cross-document coreference в новостях.
[SECURE](https://github.com/taolusi/SECURE) строит LLM-обогащённые отдельные
mentions, retrieval кандидатов и pairwise классификацию для ECB+/GVC/FCC;
его окружение описано для Python 3.10.13. [EasyECR](https://github.com/hqyang/EasyECR)
унифицирует загрузчики и оценку ряда ECR-корпусов и моделей. Это источники
метода для будущего domain-transfer, а не подтверждённый выигрыш Guardian.
External-only / pretrain→Guardian / mix ablation здесь **не выполнялись**;
цифры переноса не заявляются. Основной ограничитель Guardian — политический
action/check/artifact scope с короткими императивами и tool semantics,
который не совпадает с новостным cross-document ECR.

## Решение

Основные frozen запуски закончены (`E12_COMPLETE`, `E3_COMPLETE`,
`RESCUE_COMPLETE`). **Step 1 не готов к интеграции.** Конкурсный detector
не менялся. Полезный подтверждённый компонент — очистка junk; подтверждённые
ограничения — потери настоящих событий и неправильное связывание действий.
Далее нужна привязка цитаты к обоим конкретным событиям, а не только
проверка тематической близости. Даже FULL GOLD имеет такие ошибки.

В сравнении с partial-GOLD canonicalization описательно закрыто около 26%
разницы precision: (.391 − .173)/(1.000 − .173). У этого oracle recall .800,
поэтому это не сопоставимый целевой score и не доказательство общего headroom.
С FULL GOLD при таком же recall .900 доля составляет около 38%; обе величины
относятся только к десяти авторским policy и к текущей ontology.

## Ответы на вопросы Level E

| Вопрос | Проверенный ответ |
|---|---|
| Надёжно убрать junk? | A4 убрал 30/33, но потерял 9/58 gold-real. Надёжная безопасная фильтрация не получена. |
| Сколько событий потерял gate? | E1 A4: 9; REAL E3: 3 настоящих mentions. Это разные наборы и единицы. |
| Помогает core? | B3 снижает event false merges E3 5→1, но E2 TP/FP хуже базы. B5 устойчивее к boundary noise при тех же TP/FP. |
| Помогает few-shot? | 19TP/0FP вместо 18TP/0FP на E2. Небольшой выигрыш, downstream few-shot отдельно не запускался. |
| Помогает CE обучение? | Нет в данном опыте: обе LoRA имеют 0TP на sealed E2. Training: 150 пар, всего 18 SAME. |
| Внешние корпуса? | Изучены методы и интерфейсы; transfer/fine-tune не запускался. Эффект не измерен. |
| Что лучше на шуме? | B5: 8/10 устойчивых меток при P=1.0, R=.563. Частичные boundary expansions, не все виды шумов. |
| Какой SAME precision? | E2 B1/B5/few-shot: 1.0 на 18/18, 18/18, 19/19 predicted SAME. REAL F/veto micro: 12/32=.375. |
| Опасные слияния? | REAL F/veto: 5 event↔event + 15 с junk; B3: 1 + 9; gate не устранил event↔event ошибки F. |
| Clean→noisy? | База совпала по метке 5/10, B5 8/10, eight-shot 6/10. Стойкая ошибка тоже считается совпадением. |
| Passive references решены? | Нет гарантии; отдельные active/passive пары работают, completed-state positives конфликтуют с ontology prompt. |
| Nominalization решена? | Нет: eventness теряет nominal references; identity смешивает event reference со state facet в gold. |
| Tool-name leakage убрана? | У opaque resolver 0/63 изменений ролей при rename. Это только проверка resolver. |
| POS/homograph misses решены? | Частично: rescue E3 6/7 пропущенных событий; E5 6/7 commands; E7 candidates 25/28 с альтернативным POS. |
| После rename? | Роли инвариантны в данном тесте; полный downstream rename-run не выполнялся. |
| Counterfactuals? | В E2 есть разные entity/occurrence и action/check negatives. Нового end-to-end policy counterfactual-run не было. |
| REAL precision вырос? | EVENTNESS_ONLY .173→.391 в строгой оценке на десяти author policies. |
| REAL recall вырос? | Нет; лучший сохранённый уровень .900 совпал с RAW. Графовые канонизаторы снижают recall. |
| Exact graphs? | RAW 1/10; EVENTNESS_ONLY 3/10; gate+F 5/10 при R=.600; FULL GOLD 6/10. |
| Oracle headroom закрыт? | Описательно около 26% precision-gap до partial canonical oracle; не переносимый target. |
| Что осталось? | Смешанные source spans, facet/state ontology, ошибочная привязка цитаты к событиям, слабый pair judge на REAL spans. |
| Готов к интеграции? | Нет. Есть полезные компоненты и полностью сохранённые отрицательные результаты. |

## Артефакты и воспроизведение

`experiments/searh_23/event_frontend_level_e/` содержит frozen inputs/gold,
prompts, split/selection configs, E1/E2 raw outputs, E3 node/edge records,
E4–E7 controls, per-item errors, обе оценки графов и аудит coreference.
Выбранные адаптеры: `outputs/CE_GUARDIAN/epoch_1/` и
`outputs/CE_BINARY/epoch_8/`; обучение, val curves и calibration также
сохранены. Полные API response caches содержат raw/model/usage/latency,
ключей и заголовков запросов в них нет. API secrets остаются на сервере.

`hash_audit.json` проверяет frozen manifests, неизменность содержимого
предварительно закоммиченных inputs/gold и полноту всех 18 рукавов. У E6/E7
исходные hashes относятся к Windows CRLF. Замороженные файлы сохраняются
побайтно в исходной форме (`frozen/*.json -text` в `.gitattributes`), а аудит
также записывает canonical LF hash для проверки на другой платформе.
Политики, метки и привязки при этом не менялись.

Локальный пересчёт без GPU и без API:

```powershell
py -3 experiments/searh_23/event_frontend_level_e/le_eventness.py score
py -3 experiments/searh_23/event_frontend_level_e/le_identity.py score
py -3 experiments/searh_23/event_frontend_level_e/le_error_report.py
py -3 experiments/searh_23/event_frontend_level_e/le_score_strict_graphs.py
py -3 experiments/searh_23/event_frontend_level_e/le_score_cluster_audit.py
py -3 experiments/searh_23/event_frontend_level_e/le_score_e3_clusters.py
py -3 experiments/searh_23/event_frontend_level_e/le_verify_artifacts.py
```

Серверные batch scripts: `le_remote_e12.sh`, `le_remote_e3.sh`,
`le_remote_rescue.sh`, `le_remote_clustering.sh`. Они пропускают уже
сохранённые predictions. E6/E7: `le_anchored_boundaries.py run/score`,
`le_sentence_hypotheses.py run/score`. Повторный inference — отдельный
новый запуск, существующие frozen results не перезаписывать.

Фактическая среда нового Vast: Python 3.12.3, torch 2.10.0,
transformers 5.16.1, sentence-transformers 6.0.1, stanza 1.14.0,
peft 0.21.0. Все сохранённые API responses обслужены
`ministral-14b-latest`; LoRA/Stanza/rerank работали на GPU, Mistral через API.
Точные сохранённые token totals и median/p95 request latency лежат в
`resource_summary.json`. Они исключают потерянные ответы/retries; стоимость
в валюте и peak GPU memory не измерялись. Legacy `_usage.json` downstream
может перезаписывать arm total и считать обращения к cache как вызовы;
для бюджета используем агрегат фактических сохранённых API responses.
