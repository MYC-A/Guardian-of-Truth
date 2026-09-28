# EVENT_CANONICALIZATION_RESEARCH_2026-09-28

Фаза: EVENT_CANON_v1, ветка `codex/relation-research-20260928`
Вопрос фазы: какие source-backed mentions описывают ОДИН И ТОТ ЖЕ event
instance, а какие лишь семантически связаны, но должны оставаться разными
узлами — и поднимает ли их канонизация REAL Step-1 precision?

Все артефакты: `experiments/searh_23/event_canon_v1/` (frozen/, outputs/,
код ec_*). Коммиты-вехи: 15c17c16 (датасет до инференса) → 099bdf1d (код
рук до анализа) → 17fe8289 (gold alignment Track B до инференса
канонизации) → 310be386 (пороги dev до вскрытия test) → 09203f1f (дисциплин-фикс
UNKNOWN-не-мержится до любых Track B test-метрик) → финальные.

---

## 0. Резюме — главные результаты

1. **Диагноз подтверждён и квантифицирован.** Дубликаты mention-узлов —
   доминирующий источник потери precision на реальном frontend: с GOLD
   канонизацией тот же самый evidence-пайплайн поднимает real-track
   edge precision с **P=0.238 до P=0.672** (лишние рёбра 169 → 18,
   точных графов 0/38 → 10/38; на test-сплите P=0.733).
2. **Но zero-shot канонизация пока не даёт этого выигрыша**: лучшая
   реальная конфигурация (узкий LLM pair-judge + veto-кластеризация)
   поднимает P лишь до 0.294 (extra 169→82). Причина: pair-judge,
   дающий на gold-спанах mP=0.785, на шумных предсказанных спанах
   (trailing PP, NP-фрагменты, неверные границы) падает до mP=0.383 —
   он перестаёт узнавать passive-in-binding-clause references как SAME.
3. **Три представления канонического узла измерены**: node-level
   (односпановый) / multi-span (§13: хранить все спаны) / member-level
   CE-гейтинг + multi-span (mm). Только mm восстанавливает recall
   oracle-канонизации (0.451→0.578) без потери precision — CE-band v1
   оказался фактически same-sentence гейтом, и канонический узел обязан
   наследовать mention-level проходимость бэнда.
4. **Новые frontend-дефекты найдены**: (а) stanza спешит императивные
   глаголы-омографы ("Polish"→ADJ, "Radio"→PROPN) — 4 канонических
   события потеряны (frontend canonical recall 97.9%); (б) resolver-промпт
   содержит ИМЕНА инструментов вопреки name-blind замыслу — rename сдвигает
   роли 41/351 (11.7%) событий.
5. **Разложение остаточных FP real-трека**: из 82 лишних рёбер 66 (80%) —
   junk-узлы (сущностные NP, не отфильтрованные как не-события). Это
   следующий по величине рычаг после самой канонизации.

## 1. Диагноз входа (Q1: почему frontend создаёт duplicate events)

PL_v1 показал: oracle-события + evidence = P 1.000/R 0.946, но real frontend
P≈0.40 (93 лишних рёбра). Level D failure analysis уточнил механизм:
структурный кандидатогенератор (clause+NP) порождает по 2-4 узла на событие —
императив («Weigh each linen batch»), passive-reference внутри binding-клаузы
(«only after the batch is weighed»), номинализация («batch weighing»),
NP-фрагмент («linen batch»). Relation-стек честно строит рёбра между ними:
dup-to-dup рёбра и рёбра «не-тот-дубликат → операция». Плюс НОВОЕ: frontend
теряет события (гомографы Polish/Radio; §0.4) — канонизация не может
восстановить потерянное (frontend-уровень, не чинился: компоненты заморожены).

## 2. Level D frozen dataset (до инференса; коммит 15c17c16)

38 кейсов, 34 свежих домена, **255 gold упоминаний / 189 канонических
событий / 789 gold пар** (SAME 80, RELATED_BUT_DIFFERENT 94, DIFFERENT 613,
AMBIGUOUS 2), 73 gold рёбра с evidence-спанами, 4 CF-твина, renamed-сьют,
SHA-манифест. Сплиты dev 10 / calib 4 / val 8 / test 16 (test вскрыт после
заморозки порогов). Протокол соблюдён по цепочке коммитов (§0).

Покрытие таксономии §6: passive/nominalization/anaphora/alias → SAME;
action↔check/observation/state/artifact, same-predicate-different
entity/actor/time/polarity/modality/occurrence → RELATED_BUT_DIFFERENT;
participial/plural/quantity traps → не-события; naturalistic длинные политики
(woodkiln 12 упоминаний / mountainhut 11 / oliveoil 10 / hydroponic);
misleading tool names (test_engraving). Gold AMBIGUOUS — 2 пары (pronoun
"It", implicit-agent passive).

## 3. Руки

| рука | механизм |
|---|---|
| A_lex | content-lemma overlap ≥0.5 (floor; переносимая часть LemmaECR/2n>n²-heuristic) |
| B_emb | bge-base cosine: span-only / span+sentence |
| C_ce | bge-reranker zero-shot (query=вопрос о coref, passage=контексты) |
| D_ud | stanza UD-signature (predicate/полярность/PROPN-NUM энтити/temporal/args/amod) + детерминированный компаратор: predicate-family mismatch→DIFFERENT; конфликты → RELATED; voice-агностик; subset-совместимость → SAME |
| E_xamr | X-AMR-style event-graph (LLM, 1 вызов на mention) + пререгистрированный компаратор (entities/time/occurrence_index/mode) |
| F_judge | узкий LLM pair-judge: exact spans + содержащее предложение + 1 предыдущее; SAME/RELATED/DIFFERENT/UNKNOWN |
| G_nli | nli-deberta-v3-base zero-shot (entailment как proxy) |
| H_EF_and/or | детерминированные композиции E∧F / E∨F |
| кластеризация | cc (транзитивное замыкание) / veto (констрейнед: DIFFERENT/RELATED блокируют merge; UNKNOWN не мержит и не ветирует) / average-link / complete-link / corr (CP-SAT, пререгистрированная objective) |

Все механизмы generic (никаких keyword-правил/доменных списков; D использует
закрытый класс английской темпоральной лексики как морфологию признака).
Blocking для LLM-рук: locality±1 ∪ lexical ∪ embedding-top3; **pair candidate
recall 79/80=0.988 (dev 1.0), кандидаты 633/789=80% от n²**.

## 4. Track A: pair-классификация (SAME-binary; ALL / test)

| рука | P | R | F1 | F1(test) | dangerous (RELATED→SAME) |
|---|---|---|---|---|---|
| A_lex | 0.278 | 0.787 | 0.410 | 0.419 | 66 |
| B_emb_span | 0.369 | 0.562 | 0.446 | 0.447 | 40 |
| B_emb_ctx | 0.183 | 0.725 | 0.292 | 0.242 | 47 |
| C_ce | 0.096 | 0.900 | 0.173 | 0.154 | 84 |
| G_nli | 0.151 | 0.838 | 0.255 | 0.220 | 47 |
| D_ud | 0.671 | 0.588 | 0.627 | 0.667 | 15 |
| E_xamr | **0.789** | 0.375 | 0.508 | 0.560 | **3** |
| **F_judge** | 0.620 | 0.785 | **0.693** | **0.651** | 13 |
| H_EF_or | 0.58 | 0.61 | 0.595 (dev) | — | 5 (dev) |
| H_EF_and | 1.000 | 0.222 | 0.364 (dev) | — | 0 (dev) |

Кластеризация (ALL, post-UNKNOWN-fix): **F_judge+veto CoNLL=0.846
(B³=0.936), mP=0.785, mR=0.760, FM=18/MM=19** (test: CoNLL 0.878, mP 0.740,
mR 0.852); H_EF_or+veto 0.812 (FM 71); F_judge+cc 0.810 (FM 71 — транзитивное
замыкание пере-мержит на val/test); E_xamr+veto: mP=0.844/mR=0.580 (test),
FM=8 — precision-safe профиль; D_ud+veto FM=23.

**Контрфактивы**: F_judge 5/7, D_ud/E_xamr 3/7, score-руки 0/7 —
CF-чувствительность требует дискретной реакции на identity-evidence
(entity/actor/time/polarity правки), которую пороги/greedy-сигналы не дают.

**Ablation D (§20)**: predicate-only → dangerous=38; +polarity 28; +entities
27; +temporal 23; +args 16 (главный precision-драйвер); +amod 15. Итог:
P 0.50→0.67. Признаки-предотвратители опасных слияний — args/entities
(who/what), затем polarity/temporal.

## 5. Track B: канонизация ПРЕДСКАЗАННЫХ упоминаний (реальный режим)

F_pol+veto_v2 (UNKNOWN не мержит): ALL **CoNLL=0.684, mP=0.383, mR=0.562,
FM=76, MM=44**; узлов 249 vs 189 gold (junk 66, impure 58). По сплитам:
dev mP=0.317/mR=0.333; val 0.407/0.479; test 0.363/0.752.

Падение против Track A (mP 0.785→0.383) — центральная находка фазы: тот же
judge на предсказанных спанах не узнаёт passive-reference («Inspect the fuel
hose before every refuelling» ~ «only after the hose is inspected» →
RELATED: модель читает trailing-PP как временнóе якорение ДРУГОГО вхождения).
Плюс NP-фрагменты получают SAME от judge за «same prescribed action»
(«Record the fuel volume» ~ «fuel volume»).

**§21 (tool-семантика)**: F_tool на dev: mP=0.422 vs F_pol 0.317,
CoNLL 0.697 vs 0.650 — для identity tool-описания ПОМОГАЮТ (+0.10 P),
противоположно relation-licensing (PL_v1: −0.20 P). Объяснение: инструмент
типизирует predicate, но не лицензирует связь. Рекомендация для Level E:
включить tool-описания в identity-judge, НЕ включать в relation-детекцию.

## 6. Track C: downstream relation graph (главная таблица)

REAL frontend → [канонизация?] → evidence-licensed relation стек (ev →
evjudge → dir → cls, промпты PL_v1 без правок, CE-band 0.35):

| режим | P (ALL) | R | extra | missing | typed | exact |
|---|---|---|---|---|---|---|
| raw (без канонизации) | 0.238 | 0.651 | 169 | 29 | 0.56 | 0/38 |
| canon v1 (node-level CE) | 0.303 | 0.405 | 68 | 44 | 0.63 | 1/38 |
| canon ms (multi-span) | 0.301 | 0.413 | 71 | 44 | 0.61 | 0/38 |
| **canon mm** (member-CE+ms) | 0.294 | 0.467 | 82 | 40 | 0.57 | 0/38 |
| oracle v1 | 0.681 | 0.451 | 13 | 39 | 0.56 | 7/38 |
| oracle ms | 0.667 | 0.444 | 15 | 40 | 0.56 | 7/38 |
| **oracle mm** | **0.672** | **0.578** | **18** | 30 | 0.59 | **10/38** |

oracle mm на test: **P=0.733, R=0.629, extra=6, exact=4/16**.

Механизм представления (mm): CE-band v1 — фактически same-sentence гейт
(кросс-предложенческая пара marina inspect↔fuel получила CE=0.0006!).
Канонический узел с min-start якорем терял проходимость бэнда, когда binding
живёт в предложении ДРУГОГО упоминания. member-level CE-гейтинг (узел-пара
проходит бэнд, если хоть одна пара участников проходит) + multi-span рендер
узла (§13: «никогда не выбрасывать оригинальные spans») восстанавливают
recall (0.451→0.578) при сохранении precision.

**Разложение 82 extra у canon mm**: 66 (80%) junk-узлы (сущностные NP прошли
evidence-гейт), 5 dup-to-dup, 11 wrong-pair. Т.е. второй по важности рычаг —
event-vs-entity фильтрация узлов (не реализована в этой фазе — заморожено;
количественно оценён headroom).

## 7. Rename (§15)

Track A-руки не видят имён инструментов вообще (структурная инвариантность).
Frontend: спаны 0/351 диффов (экстракция policy-only), но роли 41/351 (11.7%)
сдвигаются — resolver-промпт содержит поле "name" (byte-diff промптов
original/renamed). Это до-существующий дефект name-blind дизайна H2; для
канонизации не критично (F промпты без tools), но рекомендация Level E:
убрать имя из resolver-промпта. test_engraving (misleading names) — 0
role-диффов. Полная rename-репликация downstream не проводилась: инвариантность
канонизации структурна (спаны/промпты идентичны), чувствительность изолирована
в resolver и измерена напрямую.

## 8. Ответы на 20 вопросов брифа

1. **Почему frontend создаёт дубликаты?** Кандидатогенерация clause+NP
   legitimately извлекает несколько поверхностных форм одного события
   (императив/passive-in-binding/nominalization/NP) — дубликаты не ошибка
   парсера, а свойство представления. Плюс теряет 4 события (homograph-баг).
2. **Самые частые типы дублей?** (а) passive-reference внутри binding-клаузы
   («only after X is VERBed») — главный источник dup-рёбер; (б) participial
   NP внутри клаузы; (в) номинализация-субъект лог-клаузы; (г) сущностные NP
   (junk, дают 80% остаточных FP).
3. **SAME vs RELATED_BUT_DIFFERENT?** SAME = две поверхности одного
   предписания/вхождения (voice/nominalization/anaphora не меняют identity).
   RELATED = то же семейство предиката, но другой instance: check vs action,
   состояние-результата vs действие, другая сущность/актор/время/полярность,
   требование vs выполнение. Онтология Level D зафиксировала это на 789 парах.
4. **Готовые ECR-системы?** SECURE/CorefPrompt/EasyECR-pipelines требуют
   обучения и старого стека (py3.9/torch1.x) — не запускаемы в текущем
   окружении без отдельной среды; их переносимая zero-cost часть (lemma-
   heuristic) = рука A (floor, over-merges). EasyECR-вывод о
   негенерализуемости между датасетами подтверждён нашим переносом: даже
   лучшие zero-shot сигналы (F) деградируют при смене «clean gold спаны →
   шумные предсказанные спаны». MAD-ECR — кода нет. OmniEvent — не coref.
5. **MAVEN-ERE transfer?** Датасет требует обучения pair-scorer'а; zero-shot
   переноса pretrained-представлений не проводилось (стек/лицензии);
   зафиксировано как auxiliary-опция для fine-tune-фазы, НЕ как валидация.
   Guardian-style held-out не заменён.
6. **SRL/UD-представление (D)?** F1 0.627 / test 0.667, dangerous 15/94;
   ud-сигнатуры дают дешёвый precision-сигнал (mP 0.78-0.86 в кластеризации),
   но: irregular morphology (swept/sweep) и clause-verb head («the inspection
   finds a crack» → predicate=find) дают системные FN; PropBank-SRL
   (allennlp) потерян при ребилде venv — задокументировано.
7. **AMR/X-AMR (E)?** Precision-чемпион (P 0.789, dangerous 3/94, E+veto
   FM=8 при mP 0.844 на test), но recall компаратора низок (0.375): жёсткие
   правила конфликтов + LLM-графы с clause-verb predicate. Структурированное
   представление работает как precision-фильтр, не как полный решатель.
8. **CrossEncoder (C)?** Zero-shot провален (F1 0.173): reranker отвечает
   «relevant» на ведущий вопрос про пару в общем контексте (все скоры
   0.8-1.0). Нужен fine-tune (§22), zero-shot непригоден.
9. **Narrow LLM (F)?** Лучший F1 (0.693/0.651 test) и лучший CF (5/7);
   on Track B деградирует (mP 0.383) — вход-чувствительность к шуму спанов.
10. **Candidate generation?** Locality±1 ∪ lexical ∪ emb-top3: recall
    0.988, но сокращение лишь до 80% от n² (данные плотные, всё «рядом»).
    Для Guardian blocking — не узкое место; judge-стоимость остается O(кандидаты).
11. **Кластеризация?** veto — стабильно лучший профиль (F+veto CoNLL 0.846,
    FM 18): констрейнед-мерж с DIFFERENT/RELATED-вето предотвращает
    транзитивный over-merge (cc даёт FM 46-71 на test/ALL). corr (CP-SAT) ≈
    veto/complete, al ≈ cc. Главный кластерный риск (A≈B,B≈C,A≠C) закрывается
    именно veto/complete, не замыканием.
12. **False merges?** Track A F+veto: 18 (на 80 gold SAME пар, 789 всего);
    E+veto: 8. Track B: FM=76 (в основном junk-NP втягивания и
    «generic-reference ~ repeat-reference» конфьюжны).
13. **Missed merges?** Track A F+veto: 19; Track B: 44 — главный паттерн:
    passive/gerund-generic references на шумных спанах (judge отвечает
    RELATED).
14. **Sealed Level D (test)?** Pair: F 0.651; clusters: F+veto CoNLL 0.878
    (mP 0.740/mR 0.852); downstream raw P=0.274, oracle-mm P=0.733/R=0.629.
15. **Rename?** §7 выше: канонизация структурно инвариантна; resolver
    name-чувствителен (11.7% ролей) — дефект H2-фронтенда, рекомендация
    Level E.
16. **Контрфактивные пары?** 4 CF-твина (entity/actor/temporal/polarity);
    F 5/7, D/E 3/7, score-руки 0/7 — система, не дающая дискретного ответа,
    не флипается вслед за identity-evidence (ожидаемо и информативно).
17. **REAL FRONTEND?** §6 таблица: raw 0.238/0.651 → canon-mm 0.294/0.467 →
    oracle-mm 0.672/0.578 (test 0.733/0.629). Precision почти утраивается
    только при ПРАВИЛЬНОЙ канонизации; текущая zero-shot канонизация даёт
    +0.06 P и −0.18 R.
18. **Насколько поднялась precision evidence-пайплайна?** P(raw)=0.238 на
    плотных Level D политиках (PL_v1 на своих данных давал 0.405 — наши
    политики плотнее, evidence-гейт слабее discriminate). С gold-канонизацией
    P=0.672 (+0.43 абсолютных, ×2.8). С текущей zero-shot канонизацией
    +0.06. Причина разрыва — Track B качество кластеров (mP 0.38).
19. **Главный bottleneck после канонизации?** По убыванию эффекта:
    (а) качество канонизации на шумных спанах (headroom P 0.29→0.67);
    (б) junk-узлы (66/82=80% остаточных FP — нужен event-vs-entity гейт);
    (в) evidence-гейт на плотных политиках (11 wrong-pair FP у oracle-mm);
    (г) frontend-потери (4 события) и роль-шум (typed=0.57-0.59 vs 0.93
    oracle-track в PL_v1).
20. **Step 1 готов к интеграции?** НЕТ. Доказано: (а) механизм выигрыша
    существует и квантифицирован (oracle-mm P 0.672); (б) существующие
    zero-shot компоненты не дают его; (в) путь: identity-judge, устойчивый к
    шумным спанам (few-shot с dev-примерами / fine-tune CrossEncoder на
    Guardian-парах из dev+val / prompt с суженными спанами), event-vs-entity
    гейт, member-level CE + multi-span представление узла (уже реализовано
    здесь и подтверждено oracle-методом). predict.py не тронут (research
    branch).

## 9. Отрицательные и нулевые результаты (честно)

- C_ce zero-shot: F1 0.173 — ведущий шаблон делает reranker-скор
  неинформативным.
- G_nli: 0.255 — NLI-entailment не proxy для event identity.
- B_emb: косинус-пространство плотное (SIM 0.65-0.81 перекрывается с
  DIFF 0.44-0.84); span+context ХУЖЕ span-only (контекст доминирует и
  сливает всё в предложении) — противоположно интуиции «больше контекста
  лучше».
- H_EF_or: F1-pair лучший на dev, но в кластеризации до UNKNOWN-фикса
  взрывался (FM 275) — псевдо-скоры UNKNOWN как 0.5 ≥ threshold мержили
  неопределённость; фиксировано дисциплинарно (UNKNOWN никогда не мержит).
- Fine-tune не проводился: zero-shot НЕ достиг целевых показателей Track B,
  но время фазы ушло на изоляцию причин (вход-чувствительность judge);
  fine-tune — первый пункт Level E.
- MAVEN-ERE/SECURE перенос не проводился (стек/обучение) — зафиксировано
  как риск, не как результат.

## 10. Стоимость

~4925 LLM-вызовов / ~1.96M токенов (mistral-14b): frontend 351 + renamed
351 + E 255 + F 633 + TrackB F_pol 1055 + F_tool 295 + downstream ~1900.
Wall ~4.7 ч (последовательные фазы). GPU: пики ~6 ГБ (3090). Все сырые
выходы в outputs/_cache (кэш-файлы с промптами и usage).

## 11. Что делать дальше (Level E, приоритеты)

1. Identity-judge на шумных спанах: (а) few-shot F с dev-примерами
   passive-reference; (б) сужение спана до predicate-ядра перед judge
   (UD-голова); (в) fine-tune CrossEncoder на dev+val парах (633+val
   размеченных пар уже есть как данные).
2. Event-vs-entity гейт узлов (убивает 80% остаточных FP): resolver-UNRELATED
   + UD-голова-не-событие → не-узел.
3. Frontend: убрать имена из resolver-промпта; починить Polish/Radio
   homograph-баг (POS-Constraints или lexicon-lookup в кандидаторе).
4. Встроить member-level CE + multi-span узлы (реализовано, validated
   oracle-методом) + UNKNOWN-вето кластеризации (реализовано).
5. Отдельный Level D2: multi-span evidence для 2 FN PL_v1
   (cross-sentence anaphora + over-minimal quote) — НЕ смешивать с
   канонизацией (§25 брифа), теперь можно.

Главный принцип фазы подтверждён практикой: «эти два упоминания относятся к
одному вхождению» — отдельный, измеримый класс суждения; семантическая
близость (B/C/G) его НЕ решает; дискретные identity-evidence сигналы
(полярность/энтити/время/predicate-family в D/E, явный pair-judge в F) —
решают частично; устойчивость к шумным спанам — новый фронт.
