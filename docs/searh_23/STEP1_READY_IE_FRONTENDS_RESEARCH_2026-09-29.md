# STEP1_READY_IE_FRONTENDS_RESEARCH_2026-09-29

Дата: 2026-09-29. Ветка: `codex/step1-ready-ie-frontends-20260928` (от
`codex/relation-research-20260928`). `scripts/predict.py` не изменялся.
Код и данные: `experiments/searh_23/event_ie_frontends_v1/`.

## 0. Протокол и цепочка коммитов

Датасет Level F заморожен ДО инференса (`9a21750e`): 15 кейсов / 133
типизированных упоминания (EVENT 52, ENTITY 32, EVENT_REFERENCE 22,
ARTIFACT 15, STATE_OR_FACET 8, CHECK 4) / 54 канонических события / 54
семантические связи / 38 аргументов / 23 нормативных ребра с evidence;
запечатанный F2 (5 кейсов) в том же коммите; 22 certificate-айтема
(adversarial minimal pairs); renamed-сьюты (opaque tool_NN); SHA-манифест.
Код адаптеров/сертификатов/скореров закоммичен ДО тестовых прогонов
(`fc8f1e57`), калибровка схем UIE/GLiNER — на СТАРЫХ Level E dev-текстах,
не на Level F. Результаты — отдельными коммитами после тестов
(`9b57039c`, `4f1066e2`). Механизм сертификата итерировался на 22
unit-айтемах (это dev-множество механизма); Level F downstream и запечатанный
F2 не использовались для настройки.

Окружение: Vast.ai RTX 3090 24G, Python 3.12.3, torch 2.10.0+cu128,
transformers 5.16.1, llama-cpp-python 0.3.35 (CUDA), paddlepaddle 3.0.0 +
paddlenlp 3.0.0b4 (патч aistudio_utils), gliner 0.2.29, amrlib 0.8.1
(SPRAY model_parse_xfm_bart_large, 83.7 SMATCH), stanza 1.14, LLM — Mistral
API `ministral-14b-latest` (temperature 0, json_object, кэш).

## 1. Резюме

1. **Ни одна готовая span-extractive IE-система не извлекает
   clause-level события из императивных политик.** UIE (uie-base-en),
   GLiNER, OneKE (13B, GGUF Q3_K_L) дают mention recall 0.04–0.11 против
   0.65 у текущего H2/Stanza-фронтенда: их архитектура —
   entity/trigger-спаны, а Guardian-онтология требует клауз-уровневых
   event-упоминаний с ролями. Это фундаментальный мисматч представлений,
   а не вопрос настройки.
2. **Лучший готовый кандидат-генератор — LLM с schema-guided промптом
   (LLM_SG)**: mention R .699, exact-span .481, typeAcc .753, macro-F1
   .561, единственная рука, предлагающая semantic links. DeepKE
   InstructKGC-шаблон близок по recall (.692), но спаны короче
   (exact .293). AMR (SPRING/BART) даёт структурно безупречный
   predicate/argument-граф, но как фронтенд over-генерирует (263
   кандидата, mP .156).
3. **Endpoint-grounded evidence certificate (E3) решает главную проблему
   Level E.** На 22 adversarial certificate-айтемах текущий механизм (E1)
   даёт **1/22 верных статусов** (18 ошибок: лицензирует
   argument-as-endpoint — точный ceramics-провал Level E, —
   дескриптивные цитаты, OR-членов; отвергает 9 простых позитивов).
   E3 (Q1–Q5 декомпозиция + отдельный endpoint-верификатор +
   детерминированная проверка спанов) даёт 11–15/22 с ≤2 ложными
   SUPPORTED. В downstream E3 поднимает oracle-граф с P .333/R .130
   (E1) до **P .565/R .565, exact 6/15** (FULL_GOLD), направление —
   обязательная семантика «A первым».
4. **Запечатанная F2-валидация (новые домены) подтверждает перенос
   механизма, но не фронтенда**: FULL_GOLD E3 = 4 correct (R .500) против
   E1 = 1 (R .125); но LLM_SG+E3 на F2 — 0 correct при 18 extra:
   сертификат лицензирует шум, когда узлы плохие. **Step 1 не готов к
   интеграции.**
5. **Rename-инвариантность подтверждена эмпирически**: LLM_SG+E3 на
   renamed-сьюте — 15/15 идентичных множеств рёбер; FULL_GOLD+E3 — 14/15
   (один CE-пограничный флип).

## 2. Что реально запускалось (и что нет)

| система | статус | детали |
|---|---|---|
| OneKE | запущена | zjunlp/OneKE (13B, Chinese-Alpaca-2), GGUF **Q3_K_L 7.08GB** через llama.cpp CUDA (диск контейнера 32GB не вмещает Q4_K_M 8.03GB — честно зафиксировано); точные README-инструкции NERen/EEen, батчинг схем |
| PaddleNLP UIE | запущена | paddlepaddle 3.0.0 + paddlenlp 3.0.0b4; uie-base-en; прямая и staged-руки; патч несовместимости aistudio-sdk |
| AMR | запущена | amrlib 0.8.1 + parse_xfm_bart_large (83.7 SMATCH); лицензии: BART-модель Apache-2.0-совместимая, SPRING-модель CC BY-NC-SA (не используется); transition-amr-parser (microsoft) — репозиторий удалён (404), задокументировано |
| DeepKE | запущена (LLM-путь) | точный английский eet_template из InstructKGC + Mistral API; supervised pip-модули требуют обучения — вне zero-shot сравнения (§28) |
| OmniEvent | НЕ запущена — задокументировано | off-the-shelf s2s-mt5-ed/eae чекпойнты раздаются с cloud.tsinghua.edu.cn ссылками, которые возвращают HTML-оболочку 7221B вместо архива (проверено curl); плюс transformers 5.x удалил MT5TokenizerFast — импорт падает; schema зашита assert'ом в ace/kbp/ere/maven/leven/duee/fewfc |
| OpenNRE | запущена | wiki80_bert_softmax; патч strict=False (torch-чекпойнт содержит position_ids); infer API dict-формат |
| GLiNER | запущена | gliner 0.2.29, urchade/gliner_base — «свежая система 2024–2026» сверх списка брифа |

## 3. Track A — качество фронтендов (15 кейсов, 133 gold-упоминания)

| рука | mP | mR | exact | typeAcc | macroF1 | links P/R | halluc-N | кандидатов |
|---|---:|---:|---:|---:|---:|---|---:|---:|
| CUR (H2+opaque resolver+POS rescue) | **.707** | .654 | .226 | — (нет типов) | — | — | 0 | 123 |
| DEEPKE (InstructKGC eet) | .643 | **.692** | .293 | .685 | .428 | — | 7 | 143 |
| GLiNER | .471 | .361 | .045 | .625 | .323 | — | 0 | 102 |
| **LLM_SG (schema-guided LLM)** | .596 | .699 | **.481** | **.753** | **.561** | .062/.093 | 16 | 156 |
| AMR | .156 | .308 | .053 | .512 | .130 | — | 0 | 263 |
| ONEKE (NERen) | .302 | .098 | .008 | .538 | .079 | — | 6 | 43 |
| ONEKE_EE (EEen) | .312 | .038 | .000 | .400 | .012 | — | 0 | 16 |
| UIE (direct) | .341 | .113 | .000 | .467 | .147 | — | 0 | 44 |
| UIE_STAGED | .379 | .083 | .015 | .636 | .138 | — | 0 | 29 |
| OmniEvent | н/д | н/д | — | — | — | — | — | модели недоступны |

CUR не знает новую онтологию (type UNKNOWN по построению — честно).
Галлюцинируют только LLM-руки (LLM_SG 16, DEEPKE 7, ONEKE 6): спаны,
которых нет в политике. UIE/GLiNER/OneKE дают точные offsets (provenance),
но не те спаны. UIE staged-режим (3 прохода: типы → аргументы → связи)
не лучше прямого. Аргументы извлекает только LLM_SG (и OneKE_EE
фрагментарно); UIE-nested-аргументы пусты.

## 4. Certificate units — 22 adversarial-айтема

| рука | status-acc | false-SUPPORTED | UNKNOWN |
|---|---:|---:|---:|
| E1 (текущий механизм) | **1/22** | 6 | 3 |
| E3 финальная (консервативная) | 11/22 | **0** | 9 |
| E3 промежуточная (без ко-условия/направления-уточнений) | 15/22 | 1 | 2 |
| E3W (= E3 + AMR-witness) | 11/22 | 0 | 9 |

E1 лицензирует: argument-as-endpoint (cf_neg_09 «the gauge glass →
igniting» — точный аналог ceramics `glaze → inspect` из Level E),
дескриптивное «usually precedes», OR-членов, обратные направления как
прямые; и одновременно отвергает 9 простых позитивов (NOT_LICENSED).
Финальная E3-конфигурация жертвует полнотой ради точности (принцип
Guardian: ложное установленное ребро хуже UNKNOWN): 0 ложных SUPPORTED,
2 ошибочных UNSUPPORTED (reference-chain «This inspection» — верификатор
не резолвит анафору; cross-sentence «This must be completed»). Промежуточная
версия — сбалансированная (15/22), но 1 ложный SUPPORTED. Обе
зафиксированы; финальной выбрана консервативная.

Детерминированная верификация: все цитируемые спаны обязаны быть
verbatim-подстроками политики (case-tolerant, с очисткой markdown-кавычек
— formatting noise, не семантика); `a_in_relation`/`b_in_relation` обязаны
лежать ВНУТРИ `relation_text`; иначе — UNKNOWN/UNSUPPORTED с причиной.
Парафраза без источника → UNKNOWN. AMR predicate-vs-argument witness
(§18): реализован, но финальный judge сам ловит argument-endpoints;
witness остаётся детерминированным страховочным слоем (срабатывает только
на SUPPORTED-кандидатах).

## 5. Track B — полный downstream, строгий scorer

Замороженный стек (портирован 1:1 с event_canon_v1): member-level CE band
0.35 (sentence+tool-semantics конструкция) → evidence → judge → DIR
(role/position fallback) → CLS. Разница рук — только evidence-механизм и
фронтенд.

| вход | E1 P/R | E1 correct | E1 exact | E3 P/R | E3 correct | E3 exact |
|---|---|---:|---:|---|---:|---:|
| FULL GOLD | .333/.130 | 3 | 1/15 | **.565/.565** | **13** | **6/15** |
| ORACLE LINKS | .300/.130 | 3 | 1/15 | .591/.565 | 13 | 6/15 |
| ORACLE TYPES (singleton) | .188/.261 | 6 | 1/15 | .276/.696 | 16 | 1/15 |
| ORACLE MENTIONS (singleton) | .265/.391 | 9 | 2/15 | .276/.696 | 16 | 1/15 |
| LLM_SG | .286/.174 | 4 | 2/15 | .167/.174 | 4 | 2/15 |
| CUR | .048/.043 | 1 | 0/15 | .038/.087 | 2 | 0/15 |
| DEEPKE | .000/.000 | 0 | 1/15 | .037/.062 | 1 | 0/10 |
| AMR | .000/.000 | 0 | 0/15 | .000/.000 | 0 | 0/10 |
| GLINER / UIE / ONEKE / ONEKE_EE / UIE_ST | ~.000 | 0 | 1/15 | — | — | — |

Оракулярная лестница (E3): извлечение (singleton-упоминания) достигает
R .696; группировка (канонизация) срезает до R .565; потолок лицензирования
с группировкой — R .565/P .565. Типизация (ORACLE_TYPES vs
ORACLE_MENTIONS) на downstream не влияет (UNKNOWN проходит type-гейт как
потенциальный узел — по дисциплине «не угадывать»).

## 6. Запечатанная F2-валидация (5 новых доменов, 8 рёбер)

| вход | P | R | correct | extra | exact |
|---|---:|---:|---:|---:|---:|
| FULL_GOLD E1 | .500 | .125 | 1 | 1 | 0/5 |
| **FULL_GOLD E3** | .444 | **.500** | **4** | 5 | **1/5** |
| LLM_SG E1 | .111 | .125 | 1 | 8 | 0/5 |
| LLM_SG E3 | .000 | .000 | 0 | 18 | 0/5 |

Механизм E3 переносится на новые домены (оракул), но реальный фронтенд на
F2 проваливается: сертификат с шумными узлами лицензирует мусор — 18
extra. Это и есть главный оставшийся риск.

## 7. Rename-инвариантность (§26)

LLM_SG+E3: **15/15 кейсов с идентичными множествами рёбер** (span,
relation, direction) при opaque tool_NN. FULL_GOLD+E3: 14/15 (в f_ski
один CE-пограничный флип 2→1 ребра). CUR-resolver — opaque-слоты
(инвариантность доказана в Level E: 0/63). render_tool name-blind по
построению. Ablation «policy only vs policy+tool descriptions»: фронтенды
LLM_SG/AMR/UIE/GLiNER/OneKE работают только от policy-текста (инструменты
не входят в их промпты); tool-описания входят только в общий downstream
(grounding + tool_semantics) — одинаково для всех рук.

## 8. Ответы на 27 вопросов брифа

1. **OneKE?** Запущен (13B GGUF Q3_K_L, точные README-инструкции NERen/EEen).
   На английских императивных политиках извлекает изолированные номиналы
   («annealing»), пропускает императивы; mR .098/.038; как schema-guided
   экстрактор для Guardian непригоден zero-shot. Причина частично
   квантизация (Q3 вместо Q4 — диск контейнера), частично
   китайско-ориентированный base.
2. **UIE?** Запущена (uie-base-en, direct + staged). Извлекает артефакты и
   entity, но не event-клаузы: mR .113/.083. Extractive-природа (точные
   offsets) подтверждена, но таксономия спанов не переносится на
   clause-level события. Staged (3 прохода) не лучше прямого.
3. **AMR?** Реальный парсер (amrlib SPRAY BART-large 83.7 SMATCH).
   Структурно отлично различает predicate/argument (inspect-01 :ARG1 glaze),
   state-обёртки (complete-01 over test-01), номинализации (the annealing →
   anneal-01), :mode imperative, :polarity, temporal before/after. Но как
   фронтенд: 263 кандидата (over-generation), mP .156; ломается на части
   императивов («Anneal» → antique). transition-amr-parser недоступен
   (репозиторий удалён).
4. **DeepKE?** LLM-путь (InstructKGC eet-шаблон) запущен: mR .692 (второй
   результат), но exact .293 (короткие спаны) и 7 галлюцинаций; downstream
   слаб (0–1 correct). Supervised-модули требуют обучения — вне
   zero-shot-сравнения.
5. **OmniEvent?** Не запущен: чекпойнты s2s-mt5-ed/eae раздаются битыми
   ссылками (HTML вместо архива), transformers 5.x не импортирует
   MT5TokenizerFast, schema зашита в новостные онтологии. Задокументировано
   как отрицательный результат запускаемости.
6. **Лучше CUR по mention precision?** CUR сам (.707); из готовых систем —
   никто (лучшая готовая LLM_SG .596, DEEPKE .643, но это LLM-руки, не
   «готовые экстракторы»).
7. **По recall?** DEEPKE (.692) и LLM_SG (.699) — обе LLM-руки; готовые
   экстракторы ≤ .36 (GLiNER).
8. **EVENT vs ENTITY?** LLM_SG (typeAcc .753); AMR структурно различает
   идеально (predicate vs concept), но спан-привязка шумная; UIE/GLiNER
   путают.
9. **EVENT vs STATE?** AMR структурно (complete-01/finish-01-обёртки);
   LLM_SG по типам лучше остальных, но STATE-класс редкий в предсказаниях.
10. **EVENT vs ARTIFACT?** UIE находит артефакты лучше всех (document or
    record — стабильные находки), LLM_SG/DEEPKE тоже различают; OneKE
    путал («Record» → document).
11. **ACTION vs CHECK?** Слабо у всех: CHECK-класс почти не извлекается
    (4 gold, лучшие находят 0–2). AMR выделяет verify-01/measurement
    предикаты, но без надёжного спан-маппинга.
12. **Кто сохраняет source spans?** UIE/GLiNER — точные offsets по
    построению (лучшая provenance); AMR — lemma-anchoring (все спаны
    verbatim, но короткие); LLM-руки — 90% verbatim, 10–16 галлюцинаций;
    OneKE — частично.
13. **Кто извлекает arguments?** Только LLM_SG (частично) и OneKE_EE
    (фрагментарно); UIE-nested на policy-текстах пуст; AMR даёт ARG-структуру
    в графе (не в спанах).
14. **Кто строит semantic links?** Только LLM_SG (REFERENCE_OF/SAME_EVENT;
    P/R .062/.093 — слабо); AMR structural (time/ARG-рёбра) не перенесены
    в candidate-links; UIE staged-RE пуста.
15. **Кто hallucinate nodes?** LLM_SG 16, DEEPKE 7, ONEKE 6 (парафразы);
    экстрактивные (UIE/GLiNER/AMR/CUR) — 0.
16. **Кто hallucinate relations?** LLM_SG — единственная рука с
    предложенными связями; неразрешённые ссылки отброшены детерминированно
    (unresolved_links записаны).
17. **Помогает ли AMR predicate/argument structure?** Да — как структурный
    WITNESS (§18): предикат vs аргумент детерминированно различимы в
    графе; judge в финальной E3 ловит argument-endpoints сам, AMR-witness
    остаётся страховкой. Как фронтенд — нет (over-generation).
18. **Помогает ли endpoint-grounded evidence?** Решающим образом:
    certificate-айтемы E1 1/22 → E3 11–15/22 (0–1 ложный SUPPORTED);
    downstream FULL_GOLD R .130→.565, exact 1/15→6/15; F2 R .125→.500.
19. **Исправляет ли он FULL GOLD wrong-endpoint failure?** Да —
    аргумент-как-эндпоинт (cf_neg_09) и «правильная цитата к чужой паре»
    (cf_neg_06/07) отвергаются; ко-условия AND-групп больше не
    лицензируются попарно (добавлено в промпт после диагностики, до
    запечатанного F2).
20. **Dense policies?** Хуже у всех: f_harvest (5 событий, 2 state, 2
    artifact, 3 reference) — LLM_SG находит 10/14 упоминаний, но
    downstream строит 2 из 3 рёбер; E1 там же — 0.
21. **После tool rename?** 15/15 идентичных рёбер (LLM_SG+E3), 14/15
    (FULL_GOLD+E3, один CE-флип). Стек name-blind эмпирически.
22. **STRICT graph precision/recall?** Лучший реальный: LLM_SG E1
    P .286/R .174 (4 correct, exact 2/15); LLM_SG E3 P .167/R .174.
    Оракул: FULL_GOLD E3 P .565/R .565 (exact 6/15) против E1
    P .333/R .130.
23. **Сколько exact graphs?** Основной Level F: 6/15 (FULL_GOLD E3);
    2/15 (LLM_SG E1/E3); 0/15 (CUR, AMR). Запечатанный F2: 1/5
    (FULL_GOLD E3), 0/5 (LLM_SG).
24. **Где теперь bottleneck Step 1?** По лестнице оракулов: (а) качество
    узлов реального фронтенда (LLM_SG R .699 + шум → F2-коллапс E3);
    (б) канонизация/группировка (R .696 → .565); (в) лицензирование
    (потолок ~.57 даже на FULL GOLD); (г) типизация CHECK/STATE почти не
    извлекается.
25. **Можно ли выбросить часть H2/Stanza-frontend?** Частично: H2 даёт
    лучшие спаны-клаузы (mP .707) — оставить как candidate-генератор;
    его resolver-роли бесполезны для новой онтологии; NP-junk теперь
    отсекается типизацией LLM-слоя, а не POS-эвристиками. Полная замена
    не обоснована (LLM_SG точнее типизирует, но спаны хуже: exact .481
    vs .226... наоборот: .481 ЛУЧШЕ. Но mP ниже).
26. **Минимальная лучшая архитектура?** `LLM schema-guided фронтенд
    (типизация+спаны+связи) → H2-клаузы как спан-приор → typed node gate
    (ENTITY/ARTIFACT out) → endpoint-grounded certificate (Q1–Q5,
    детерминированная верификация, консервативная дисциплина) → DIR → CLS`
    + AMR как опциональный структурный witness.
27. **Готов ли Step 1 после F2?** **Нет.** F2 показал: механизм
    сертификата переносится (оракул), но реальный фронтенд на новых
    доменах даёт 0 correct при 18 extra — нужен следующий цикл:
    качество узлов + контроль ложных лицензий на шумовых кандидатах
    (например, certificate-гейт по type/качеству спана, unknown-node
    policy), затем новый sealed-набор.

## 9. Отрицательные и нулевые результаты (честно)

- OneKE zero-shot на английских политиках непригоден (mR .098); квантизация
  Q3_K_L — задокументированное ограничение диска.
- UIE-base-en: таксономический перенос схемы на clause-events не работает;
  staged-режим не добавляет.
- OmniEvent: модели недоступны (битые ссылки), импорт несовместим с
  transformers 5.x, schema зашита — запуск невозможен.
- OpenNRE wiki80_bert_softmax: предсказывает отношение для ВСЕХ 22 пар
  (13/13 позитивов и 9/9 негативов «non-trivial») — нулевая
  дискриминативность на policy-парах; подтверждает вывод relation_edges_v1.
- AMR как фронтенд: over-generation (263 кандидата), императивные
  омографы ломают лемму-привязку; ценность — только как witness.
- E1 на Level F-политиках катастрофичен (1/22, R .130): «P=1.000» из
  PL_v1 не переносится на плотные политики с новой онтологией —
  одноэтапный judge без endpoint-декомпозиции не масштабируется.
- E3 консервативная теряет recall на reference-chain/cross-sentence
  (2 фиксированных FN-механизма — анафора «This inspection» и
  причастные модификаторы «a trained operator»).
- Prompt-итерации E3 (v2→v3) показали trade-off: сбалансированная версия
  (15/22, 1 false-SUPPORTED) vs консервативная (11/22, 0 false-SUPPORTED).
  Выбрана консервативная — по принципу «не устанавливать ложное».

## 10. Стоимость и воспроизводимость

LLM-вызовы (Mistral API, кэш): фронтенды ~340 (CUR 109, DEEPKE+LLM_SG
~120, units ~60) + downstream ~2600 уникальных (E1/E3 × 7 входов ×
пары) + F2/rename ~400. Токены: ~2.4M суммарно (см. outputs/_usage
агрегаты в кэше). GPU: OneKE ~2.5 c/политика (Q3, 3090), AMR ~20 c/кейс
(CPU), bge-reranker — минуты. Wall: ~4 ч параллельных воркеров.
Модели: OneKE-Q3_K_L GGUF (ADChahaha, Apache-совместимая конвертация),
uie-base-en (bcebos), urchade/gliner_base (Apache-2.0), amrlib
model_parse_xfm_bart_large (MIT-экосистема), wiki80_bert_softmax
(thunlp OSS). Лицензии зафиксированы; SPRING-модель amrlib (CC BY-NC-SA)
не использовалась.

Локальный пересчёт без GPU/API: `python3 lf_score.py`, `python3
lf_score_trackB.py` (LF_SUITE=f2 для запечатанного), `python3
lf_certificate.py E3 rescore`. Повторный inference не перезаписывает
существующие outputs.

## 11. Следующие шаги

1. Узловой контроль для E3: certificate-гейт, чувствительный к качеству
   спана/типа узла (шумовые узлы → UNKNOWN вместо лицензии) — прямой
   ответ на F2-коллапс LLM_SG+E3.
2. Reference-resolution в endpoint-верификаторе (2 фиксированных
   FN-механизма) — отдельный узкий вопрос, вероятно с AMR-помощью.
3. Гибрид фронтенда: H2-клаузы (спан-P) + LLM-типизация (type-F1) —
   проверка на новом sealed-наборе.
4. CHECK/STATE-классы: расширенная выборка (сейчас 4+8 gold) — отдельный
   Level G.
5. Канонизация: группировка срезает R .696→.565 — member-level
   evidence-лицензирование с последующей группировкой рёбер.
