# Universal repair v2 — ответ на independent review (research/independent-repair-review-20261006 @75efb437)

Ветка `research/guardian-universal-repair-v2-20261006` (от c1d8d785). Автор исправлений тот же, что и у v1: это **не независимая
проверка**; независимого субагента/второго аннотатора на этой платформе нет. Модель: только `ministral-14b-2512` (Gemma/Ollama — 429).

## 1. Итог
* **Код:** все 12 контрпримеров аудита превращены в контрактные тесты и исправлены (`tests/test_universal_repair_v2.py`, 19 тестов;
  старые 21 тоже проходят; полный suite: те же 20 legacy-падений, что и до правок).
* **Эффект на данных: нулевой.** Offline exact-key replay R_fix с v2-кодом на всех 13 set×rep (717 строк, 0 NOT_EXECUTED):
  0 изменений решений, 0 изменений пула кандидатов/статусов/сертификатов против A2 live (`outputs/universal_repair_v2/replay_*.json`).
  Дефекты реальные, но на этих наборах не срабатывали; метрики v1 остаются в силе. Одна регрессия, найденная replay
  (lb3L_003 r2: проверка подмены слов отвергла законную цитату «заголовок + правило»), исправлена (контекст ±3 слова) и закреплена тестом.
* **Holdout:** на отдельной версии gold (adjudicated v2) F1 R_fix .769/.806/.794, precision .833–.893, specificity .615–.769;
  constant-ERROR: F1 .843, precision .729, specificity 0. V4r = R_fix = R_comb побитно на holdout — repair на нём ничего не меняет.
* **Причины (judge v2):** только ~49 % TP R_fix имеют подтверждённую источниками и совпадающую с gold причину (163/335);
  на tau2 — 25–33 %. Метка верна, обоснование нет — это главный дефект качества, а не recall.
* **Funnel:** v1-утверждение «потолок только upstream» отозвано. Oracle probe: при правильно поданном кандидате неизменённый
  верификатор принимает 7/7 реальных holdout-FN и не принимает 4/4 ложных обвинения (3 REFUTED, 1 понижен до UNRESOLVED
  проверкой цитат). Т.е. проигрыш — в генерации кандидатов (A + триггеры), но доказано это лишь на 7+4 случаях.
* **Решение:** R_fix остаётся исследовательским opt-in (`guardian-review --repair r_fix`), default не меняется. Универсальность не заявляется.

## 2. Исправления кода (аудит → контракт)
| Контрпример аудита | Было | Стало |
|---|---|---|
| fuzzy: «at least»→«at most», «deleted»→«modified» | SUPPORTED | UNSUPPORTED (компараторы/кванторы точно; заменённое content-слово ≠ цитата) |
| посылка доказательства (decisive) по fuzzy | допускалась | только addressed JSON / verbatim |
| дубль-ключи JSON `{"limit":1000,"limit":100}` | брался последний | payload = None, SOURCE_JSON_INVALID, нет сертификата |
| mixed JSON/verbatim дубль одного листа (600+600) | сертификат | verbatim на JSON → единственный pointer, overlap → DUPLICATE_LEAF |
| A2 array-sum overlap (600 дважды) | 1300 | 700, нарушения нет |
| обычный `if`-guard («if the account is enterprise») | сертификат | applicability: if/whenever/only when/in case/as long as/если/в случае/пока |
| numeric entity (лимит счёта B к счёту A) | не проверялся | entity-conflict для ВСЕХ операций |
| parent identity массива (allowed тренера T-2) | терялась | member-листья несут id родителя |
| пустой allowed-set | KeyError | VIOLATED (пустое множество — валидный вход) |
| DF copy через другое поле (due_days 30 = «total 30») | SKIP | MISMATCH (поле должно подходить: дата-лист/слова ключа целым словом) |
| A1 pairing с failed-echo результатом | SKIP | MISMATCH (failed result не evidence) |
| «previous quote was wrong; new total 2+2=5» | NOT_ASSERTED | rejection scoped к клаузе, новое утверждение проверяется |
| mech bypass на NOT_EXECUTED/UNCHECKED | ERROR | только при verification_status == UNRESOLVED |

## 3. Диагностические контракты
**Judge v2** (`src/guardian_truth/repair/cause.py: judge_v2/invariant`, `experiments/universal_repair/judge_v2.py`): полный packet
(бюджет 120000: полный вход для всех lockbox/tau2 строк и 40/46 valid), coverage и declarations в запросе, без 6000-символьного
fallback; valid46 `explanation` передаётся как gold cause (в v1 терялось: 43 valid-TP судились без gold); cross-field инварианты —
противоречивый ответ = `inconsistent_unjudged`, не «correct». Перепроверка v1 (без вызовов): 25/377 противоречивых (22 — категория против полей).

Judge v2, все положительные предсказания V4r и R_fix (364 вызова, дедуп по set/id/тексту обвинения; a1-повтор 80 случайных: категория
совпала 77/80, correct/not 80/80):

| R_fix | TP | gold-match + source-supported | из них с лишним ложным | alt. supported | gold_conflict | unsupported | inconsistent |
|---|---|---|---|---|---|---|---|
| valid46 (3 reps) | 44 | 19 | – | 0 | – | 23 | 2 |
| lb/lb2/lb3 | 95 | 88 | – | 0 | – | 7 | 0 |
| ext_tau2 (3) | 111 | 28 | – | 4 | – | 77 | 2 |
| holdout (3) | 85 | 28 | – | 1 | 1 | 52 | 3 |
| **всего** | **335** | **163** (151 чистых + 12 с лишним) | 12 | 5 | 1 | 159 | 7 |

FP: 37, из них 15 judge считает реальным другим нарушением (alt. supported → кандидаты на ошибку gold), 21 unsupported.
V4r отличается от R_fix ровно одной строкой (lb2L_018, G3e, supported_correct_core).

**Holdout adjudication v2** (`outputs/universal_repair_v2/holdout/adjudication_v2.json`, `GOLD_adjudicated_v2.json`; frozen gold не
тронут): перечитаны 25 строк с oracle-причиной «S». 15 SUPPORTED, 2 SUPPORTED_CAUSE_REVISED (tel_017: B1002 не просрочен;
air_021: сертификат до подтверждения фактов), 5 NOT_SUPPORTED (ret_002, air_020, air_057 → label 0; ret_033, ret_034 остаются 1
по format-причине), 3 UNCLEAR исключены (ret_014, ret_036, ret_038). Итог: 48 строк, 35 ERROR / 13 NO_ERROR. Не перечитаны:
16 format-only и 10 негативов. Поправка к v1: из DROPS (15 записей) реально исключено **13** строк. A1-holdout был просмотрен до A2 —
A2-результат на holdout это regression replay, не нетронутый тест.

| holdout | gold | TP/FP/FN/TN | precision | recall | specificity | F1 |
|---|---|---|---|---|---|---|
| constant ERROR | frozen | 41/10/0/0 | .804 | 1 | 0 | .891 |
| R_fix r1/r2/r3 | frozen | 27/4/14/6 · 30/3/11/7 · 28/2/13/8 | .871/.909/.933 | .659/.732/.683 | .6/.7/.8 | .750/.811/.789 |
| constant ERROR | adj. v2 | 35/13/0/0 | .729 | 1 | 0 | .843 |
| R_fix r1/r2/r3 | adj. v2 | 25/5/10/8 · 27/5/8/8 · 25/3/10/10 | .833/.844/.893 | .714/.771/.714 | .615/.615/.769 | .769/.806/.794 |

**Funnel v2** (`experiments/universal_repair/funnel_v2.py`): A UNKNOWN отдельно, NO_CANDIDATE по admission компонента,
UNCHECKED_QUEUE_BOUND распознаётся, CB помечен NOT_RUN (R_fix с with_cb=False — согласие/подтверждение ловит только A/GUARD).
R_fix FN (frozen gold, 120): A_NO_ERROR|NO_TRIGGER 76, A_NO_ERROR|компонент отработал без кандидата 25, A_UNKNOWN|NO_TRIGGER 7,
VERIFIER_REFUTED 6, UNRESOLVED 4, A_UNKNOWN|INVALID_JSON_PLAN 2. С adjudicated holdout NO_TRIGGER 76→66. Владельцы положительных:
A_adm2 318 + GUARD 3 = 321/372; AT 36, Ems 10, DF4 5.

**Oracle probe** (`experiments/universal_repair/oracle_probe.py`, 11 live-вызовов): 7 реальных holdout-FN (air_048/029 —
неотменяемый basic economy; tel_052 — чужая линия; ret_026 — несуществующий способ оплаты; ret_023/028 — удаление через modify;
air_021 — преждевременный сертификат) с вручную поданными правилом/фактами/причиной → 7/7 SUPPORTED. Правило и факты были в
20k-пакете детектора в 6/7 (ret_023: правило вне пакета). Ни одно из 7 отношений не выразимо в proof5 (дизъюнктивная применимость,
ключи JSON-объекта, join, структурные/процедурные ограничения). 4 ложных обвинения → 3 REFUTED + 1 UNRESOLVED (raw SUPPORTED,
понижен проверкой цитат). Это стадия верификации при идеальной генерации; n мал.

## 4. Что не сделано / ограничения
* Независимая аннотация holdout и новый нетронутый task-disjoint holdout — не выполнены (нужен другой аннотатор/данные).
* CB/closure не подключены (помечены shadow); новый matched эксперимент не проводился — v2-код не меняет ни одного запроса/решения,
  поэтому повтор live дал бы те же ответы из кэша.
* Judge — та же модель, что и детектор; inter-judge согласие не измерено.
* Вызовы v2: judge 4+364+80, oracle 11 (кэши: `outputs/universal_repair_v2/cache/{judge,oracle}`), детектор 0.
