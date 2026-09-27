# POLICY-LICENSED RELATIONS — доказательство связи событие↔событие текстом политики

**Дата:** 2026-09-28 · **Ветка:** `codex/relation-research-20260928` · **Код/данные:** `experiments/searh_23/policy_licensing_v1/`

## 1. Резюме

Предыдущая фаза (RELATION_GRAPH_v1) показала: декомпозиция
`events → retriever → detector → direction → classifier → groups` выигрывает
у e2e LLM, retrieval recall@3 = 100%, но **precision детекции — узкое место**
(P=0.77–0.79), LLM-детектор строит «plausible-but-unsupported» рёбра
(66–76 FP), MP1-ловушка не проходится. Данное исследование проверяет главный
вопрос: **как доказать, что relation между A и B лицензирован КОНКРЕТНОЙ
политикой** — не «выглядит разумно», а «этот фрагмент текста связывает именно
эти события, соседний event родителем не является, и вывод меняется при
контролируемом изменении binding».

**Главный результат.** Механизм **EXTRACTIVE EVIDENCE (IDEA B)**
(двухшаговый: (1) модель обязана процитировать минимальный verbatim-спан
политики, лицензирующий пару; (2) отдельный evidence-centered судья решает
LICENSED/NOT_LICENSED/UNKNOWN, видя ТОЛЬКО цитату) достигает на запечатанном
held-out тесте:

| метрика (test, 14 кейсов, 98 пар) | DET-ce | BASE | **EVIDENCE** | DET-mistral |
|---|---|---|---|---|
| precision | 0.810 | 0.850 | **1.000** | 0.563 |
| recall | 0.944 | 0.944 | **0.944** | 1.000 |
| F1 | 0.872 | 0.895 | **0.971** | 0.720 |
| false edges | 4 | 3 | **0** | 14 |

На всём датасете (30 кейсов, 216 пар, 37 gold-рёбер): **EVIDENCE P=1.000,
R=0.946, F1=0.972, 0 FP за весь датасет** (BASE: P=0.895, 4 FP). MP1
(parent-swap ловушка): **12/12** у evidence/BASE/QA против 6/12 у
LLM-детектора. Контрфактивная проверка: parent-выбор evidence флипается
**6/6** при контролируанной замене binding (LLM-детектор: 3/6). Качество
evidence-спанов: **IoU с gold-спанами 0.96–0.97, minimality 0.99–1.01,
0 галлюцинаций за весь датасет**.

Минимальная полезная архитектура (§23) оказалась простой:
```
POLICY → events → EXTRACTIVE EVIDENCE (span + judge) → DIR → CLS → GRP
```
Listwise-соревнование, QA-формулировка, conformal-гейт, глобальный солвер
и Declare-слой НЕ добавляют точности поверх evidence (детали и honest
tradeoffs ниже). Real-frontend-трек (события из шумного пайплайна, не oracle)
деградирует до P=0.42 — узкое место сместилось в event extraction.

## 2. Замороженный датасет Level C (до инференса)

`frozen/` (коммит `e9c527a1`, SHA-манифест): 30 кейсов, 30 свежих доменов
(без пересечений со ВСЕМИ предыдущими сьютами), 128 source-backed событий,
37 gold-рёбер **с evidence-спанами** (char offsets), 216 неупорядоченных пар,
17.1% позитивов, 151 hard negative (правило зафиксировано a priori:
same-sentence ∨ condition-like→op-like ∨ op-op), 6 контрфактивных пар
(minimal edit: меняется ТОЛЬКО binding), renamed-сьют (tool_01…tool_30).

Семейства: parent-swap ×6 (MP1), swap-CF ×6, near-neighbour traps ×2,
nested ×2, shared-condition AND/OR ×2, NONE, cross-sentence,
same-sentence-unrelated, unless-exception, even-if, temporal op→op,
communication-adjacent, descriptive, multiple-independent-policies ×2,
misleading-tool-names ×2 (имена «validate_/audit_/process_» с правдивыми
описаниями).

Сплиты (зафиксированы до инференса): **calibration 6** (только conformal),
**validation 10** (development), **test 14** (вскрыт ПОСЛЕДНИМ, после
заморозки всех рук и порогов; 9/14 кейсов — самые твёрдые MP1-пары).
Протокольная оговорка (honest): один interim-принт conformal-руки содержал
test-строки ДО финального скоринга; после этого НИ ОДНОГО проектного
решения на основе test не принималось (дизайн evidence-руки был зафиксирован
на val: см. коммиты кода рук `ffccc0be` до вскрытия).

## 3. Руки и механизмы

| рука | механизм |
|---|---|
| DET-ce | bge-reranker pair-score, пороги 0.50/0.35 (заморожены из v1) |
| DET-mistral / codestral | узкий pair-вопрос (реплика известного over-binding) |
| DET-pol / DET-tool | IDEA F: тот же вопрос без tool-семантики / без policy-текста |
| BASE | DET-ce-полоса(≥0.35) ∧ DET-mistral RELATED (реплика лучшей композиции v1) |
| LISTWISE | IDEA A: top-3 кандидата retriever'а КОНКУРИРУЮТ; either/consensus агрегация |
| EVIDENCE | IDEA B: extractive verbatim span → evidence-centered judge |
| QA | IDEA C: «какая operation constrained by X?» → verbatim span или NO ANSWER |
| CF-pairs | IDEA D (evaluation): 6 замороженных контрфактивов — флипается ли parent? |
| CF-gate | IDEA D (inference): генерация контролируемого CF + верификация + re-detection (CE-гейт и LLM-гейт) |
| G-conformal | IDEA G: MAPIE 1.5.0 SplitConformalClassifier (LAC, prefit LR на 7 pair-фичах) + target-precision пороги; калибровка ТОЛЬКО на calib |
| H-solver | IDEA H: CP-SAT + clingo (28/28 согласие), пререгистрированная objective `max Σ accept×support` при констрейнтах UNKNOWN-exclusion, DIR-fix, ацикличность, XOR/AND-группы |
| DECLARE | Declare4Py 2.2.0: парсинг mapped-констрейнтов + clingo-BMC сатисфицируемость/конформанс |
| FRONTEND + REAL | real-трек: структурные кандидаты → grounding → role-resolver → relation-стек на ПРЕДСКАЗАННЫХ событиях |
| REAL_ev | evidence-гейт на accepted-парах real-трека |

Все LLM-промпты name-blind; ~3554 вызовов, ~1.07M токенов, ~2.3 ч wall
(полная разбивка: `outputs/*/_usage.json`).

## 4. Detection: полная таблица (ALL / test)

| детектор | P (ALL) | R | F1 | FP(hard) | P (test) |
|---|---|---|---|---|---|
| DET-ce | 0.872 | 0.919 | 0.895 | 5(5) | 0.810 |
| DET-mistral | 0.507 | 1.000 | 0.673 | 36(32) | 0.563 |
| DET-codestral | 0.726 | 1.000 | 0.841 | 14(12) | 0.818 |
| DET-pol (policy-only) | 0.706 | 0.973 | 0.818 | 15(12) | 0.739 |
| DET-tool (tool-only) | 0.000 | 0.000 | — | 0 | 0.000 |
| BASE (ce∧mistral) | 0.895 | 0.919 | 0.907 | 4(4) | 0.850 |
| **EVIDENCE** | **1.000** | **0.946** | **0.972** | **0(0)** | **1.000** |
| QA-derived | 0.727 | 0.865 | 0.790 | 12(11) | 0.696 |
| LISTWISE (either) | 0.480 | 1.000 | 0.649 | 40(36) | 0.500 |
| LISTWISE (consensus) | 0.846 | 0.892 | 0.868 | 6(6) | 0.895 |

## 5. Ответы на 18 вопросов задания

**1. Почему текущий детектор создаёт plausible-but-unsupported рёбра?**
Три измеримых механизма. (а) **Tool-семантика как усилитель world-plausibility**:
pair-вопрос с tool-описаниями даёт 36 FP против 15 у того же вопроса без них
(P 0.507→0.706); tool-only вариант (без policy) даёт 0 RELATED — сами по
себе описания НИКОГДА не лицензируют, но в присутствии policy-текста bias'ят
модель к «тематически связанному». (б) **Отсутствие конкуренции в verify-мире**:
LLM подтверждает знакомый workflow («проверка→операция рядом»). (в) **Нет
требования цитаты**: модель отвечает RELATED без необходимости указать, ГДЕ
именно это написано. Все три лечатся одним механизмом — обязательной
verbatim-цитатой + судьёй по цитате.

**2. Проходит ли listwise MP1?** Сам по себе — нет: MP1 exact 5/12 (either) /
0.417, LISTWISE-derived P=0.480-0.500 — конкуренция кандидатов НЕ устраняет
over-binding (модель выбирает «тематически правильного» родителя по
здравому смыслу). Consensus-агрегация (оба направления выбрали друг друга)
поднимает P до 0.846, но это уже не listwise-механизм, а симметризация.
Codestral+listwise: P=0.731 (val) — capacity помогает частично.

**3. Помогает ли extractive evidence?** Да, решающим образом: **P=1.000 /
R=0.946 / F1=0.972, 0 FP на всём датасете** (против BASE P=0.895, 4 FP).
Источник точности — не сама цитата, а связка «цитата+судья»: на 216 пар
модель нашла verbatim-цитаты для 37/37 gold-рёбер (100% recall извлечения),
для 7 отрицательных пар тоже (5 из них — «чужая» evidence другого ребра) —
и судья отверг ВСЕ 7, потому что цитата не связывает именно эти два события.
Evidence-спаны почти минимальны: IoU 0.96-0.97, minimality 0.99-1.01,
галлюцинаций 0.

**4. Помогает ли extractive QA?** Частично: P=0.727, R=0.865,
target_accuracy на test = 1.0 (16/16 правильных родителей среди
вербатим-ответов), но 34% NO ANSWER, none_correct 0.46 и 78% пар остаются
UNKNOWN (QA не смотрит на все пары). Сильнее pair-детектора, слабее evidence.

**5. Работает ли counterfactual licensing test?** Да — как диагностика И
как гейт. На 6 замороженных CF-парах: parent-выбор **EVIDENCE флипается 6/6**
(ce score падает 6/6 и растёт 6/6), DET-mistral — только 3/6, LISTWISE — 2/6.
Это прямое доказательство (вопрос 16). Inference-time CF-гейт (генерация
контролируемого контрфакта + верификация + re-detection): CE-гейт
LICENSED=25, WORLD_DRIVEN=10, UNVERIFIED=3; precision при «оставить только
LICENSED» = 0.92 (test ALL) — но на top of evidence он уже не нужен
(P=1.000 без него), а standalone убивает recall (R 0.946→0.556 из-за
UNVERIFIED_CF-абстенций). LLM-гейт: 21/38 WORLD_DRIVEN — детектор
действительно world-driven; его «licensed»-подмножество тоже чистое
(P=0.929), т.е. гейт консервативен, но не точнее evidence.

**6. Помогают ли same-policy hard negatives (fine-tune)?** Fine-tune НЕ
запускался: zero-shot evidence已达 P=1.000 (порог успеха §21 достигнут без
обучения). Hard negatives пригодились как ДИАГНОСТИКА: все 4 FP BASE —
hard (co-conditions и process-adjacent), т.е. лёгких ошибок нет вообще.

**7. Что даёт MAPIE/conformal?** Честный, но дорогой tradeoff. MAPIE LAC
(0.90, prefit LR на 7 фичах, калибровка на calib): на test singleton-set
принимает 0/98 пар (mean set size 2.0 — все пары «uncertain»). Целевые
пороги G2 (0.90/0.93/0.95): на test P=1.000 при покрытии 4/98
(96% abstention). Т.е. избирательность достижима, но при 10% coverage —
фиксируем как есть (stop-condition §20). Для Guardian ценность conformal —
в UNKNOWN-гейте на сложных парах, а не в основном пути.

**8. Что даёт global graph inference?** **Ничего на этом датасете** (честный
нулевой результат): CP-SAT и clingo (согласие 28/28) при пререгистрированных
констрейнтах (ацикличность, DIR-fix, XOR/AND) удаляют 0 из 38 candidate
рёбер во ВСЕХ вариантах support-весов. Причина: hairball-графы
однонаправленны и ацикличны; ацикличность ПЕРЕОРИЕНТИРУЕТ ребро вместо
удаления. Precision-проблема — локальный licensing, а не глобальная
несогласованность. Запрещённые эвристики (one-parent, closest-op,
same-sentence) не добавлялись.

**9. Что даёт Declare4Py?** Работающий формальный слой ПОСЛЕ извлечения.
Declare4Py 2.2.0 парсит все mapped-шаблоны (precedence/response/not_response);
check_satisfiability требует бинарник lydia (недоступен — задокументировано),
поэтому сатисфицируемость и конформанс реализованы clingo-BMC по канонической
Declare-семантике: все 13 gold-графов test-сплита сатисфицируемы;
комплаент-трейсы конформны 13/13; нарушающие отклонены 13/13; инжектированный
цикл A→B→C→A детектирован как UNSAT. Маппинг: PRECONDITION/STATE_GATE/
ORDER→precedence, RESPONSE→response, EXCEPTION≈not_response (аппроксимация),
EVEN_IF — шаблона нет, OR-группы невыразимы в обычном Declare (документировано).
Declare-слой НЕ доказывает правильность перевода NL→граф — только
внутреннюю корректность формальной модели (подтверждено).

**10. Улучшает ли комбинация механизмов precision?** Нет: лучшие комбинации
не превосходят evidence-одиночку. A(either): P=0.480; A+B union: 0.947;
A+B intersect: P=1.000 но R=0.895; BASE+CF-gate: R падает 0.919→0.622;
B+CF-gate: R 0.946→0.676. Комбинация K (A+B+D+G) не собиралась — по
результатам ablation каждый из A/D/G либо нейтрален, либо вреден поверх B.

**11. Какой accepted-edge precision достигается?** **1.000** (35/35
принятых рёбер верны на всём датасете; test 17/17). Это выше целевого
диапазона §21 (0.93–0.95) при recall 0.946.

**12. Какова UNKNOWN/abstention rate?** Основной путь (evidence): 0%
UNKNOWN — 2 FN вместо abstention. QA: 78% пар UNKNOWN (для непокрытых).
Conformal: 96% abstention при P=1.0. CF-gate: 13/38 → UNKNOWN.

**13. Что происходит на real frontend (не oracle)?** События из
структурного пайплайна (event recall 0.938, но +шум: NP-кандидаты,
passive-спаны, UNKNOWN-роли): BASE relation-стек на предсказанных событиях —
**P=0.405, R=0.901** (ALL, с DIR-вопросами; при fallback-ориентации
P=0.306): 93 лишних рёбра. Узкое место сместилось в event extraction:
шумные события порождают пары, где «сынок в одном предложении» +
тематическая близость дают false licensing. Evidence-гейт на real-треке
восстанавливает половину (extra 92→50, P→0.407 при fallback; §6) —
см. полный разбор ниже.

**14. Что после rename?** Качество сохраняется: DET-ce идентичен по
построению (name-blind); BASE renamed P=0.895/F1=0.907 против 0.895/0.907
original (совпадение до 4-го знака); misleading-tool-names кейсы
(test_archery, test_crane) в evidence-путь прошли без FP — утечки имён
инструментов нет ни в одном компоненте.

**15. Какие minimal pairs всё ещё не проходят?** Ровно два FN evidence:
(а) **cross-sentence anaphora** (val_signal: условие в S1, binding через
анaфору в S2) — extractor не может дать ОДИН verbatim-спан, покрывающий оба
события; (б) **over-minimal evidence + строгий судья** (test_spray:
extractor процитировал «unless the wind speed exceeds…» без главного клауза
«Spraying may proceed…», судья корректно отверг изолированную цитату).
Оба — понятные механизмы, чинятся показом evidence+предложения судье
(отложено: требует Level D по §7).

**16. Есть ли доказательство, что система читает policy binding, а не world
plausibility?** Да, тройное: (а) контрфактивный флип 6/6 у evidence
(parent меняется вслед за текстом при неизменных событиях/роли/мире);
(б) 0 FP при 17.1% позитивов и 151 hard negative — включая случаи, где
world-knowledge подсказывает связь (стерилизация→нанесение тату,
фруктирование→сбор урожая, взвешивание→стирка); (в) судья отвергает
«чужую» evidence (5 wrong-parent цитат отклонены). LLM-детектор те же
тесты проваливает (3/6, 14 FP) — т.е. тест различает механизмы.

**17. Какие механизмы дали 0 или отрицательный результат?** Listwise
(either): P=0.480 — отрицательный; global solver: 0 изменений — нулевой;
QA: ниже evidence — частичный; conformal: P=1.0 при 4% coverage —
непригоден как основной; CF-gate поверх evidence: −0.37 recall — вреден;
tool-семантика в pair-промпте: −0.20 P — вредна; NLI в v1 — уже был
отрицательный. Позитивны: evidence (главный), consensus-симметризация
(второстепенно), DIR/CLS/GRP (подтверждена стабильно: direction errors 0,
typed 32/35 = 91%, группы AND/OR верны).

**18. Достаточно ли надёжен Step 1 для интеграции?** Для oracle-трека —
да с оговоркой: P=1.000/R=0.946/typed 0.91/direction 0/группы OK
укладывается в требования §21 (≥0.93–0.95 при разумной coverage, 0%
UNKNOWN при основном пути). Для продакшена — нет: real-frontend-трек
P=0.405 означает, что licensing-механизм должен применяться к
ОЧИЩЕННЫМ событиям; следующий шаг — дедупликация/слияние структурных
кандидатов (passive-спаны с их полными клаузами, NP-кандидаты с
глагольными) ДО relation-слоя. Интеграция в `scripts/predict.py` не
производилась (красная линия §11).

## 6. Real-трек с evidence-гейтом

BASE-accepted пары real-трека прогнаны через ev+evjudge
(`outputs/REAL_ev/`, скоринг `pl_real_ev_score.py`; ориентация —
role/position fallback, DIR-вопросы не переиспользовались):

| real-трек (ALL) | correct | extra | direrr | missing | P | R |
|---|---|---|---|---|---|---|
| BASE на предсказанных событиях | 48 | 92 | 17 | 7 | 0.306 | 0.873 |
| + evidence-гейт | 46 | 50 | 17 | 8 | **0.407** | 0.852 |

Обязательная цитата убирает **46% ложных рёбер** (92→50) ценой 2 TP
(recall −0.02). Причина оставшихся 50 extra: **дубликаты событий** —
passive-спан («only after the batch is weighed») и глагольная клауза
(«Weigh each linen batch») это ДВА предсказанных события одного gold-события;
policy-цитата лицензирует их «внутреннюю» пару, и она засчитывается как
extra. Вывод: licensing-механизм переносится на real-трек (наполовину
сам исправляя шум), но полный выигрыш требует дедупликации/слияния
структурных кандидатов ДО relation-слоя — это теперь главный рычаг Step 1.

## 7. Стоимость и воспроизводимость

~3554 вызовов (~2954 уникальных, кэш), ~1.07M токенов, ~2.3 ч wall
с кэшированием и 429-backoff. Локальные руки (bge-reranker/base, stanza,
CP-SAT, clingo) — минуты на RTX 3090. Версии: Python 3.12.3,
torch 2.10.0+cu128, transformers 5.16.1, sentence-transformers 6.0.1,
clingo 5.8.2, ortools 9.x, MAPIE 1.5.0, Declare4Py 2.2.0,
mistralai 1.2.3 (ministral-14b-latest, codestral-latest; temperature 0,
json_object). Коммиты: датасет ДО инференса `e9c527a1`; код рук до
анализа `ffccc0be`; результаты `fc097bb6` (+ финальный после отчёта).
Все сырые выводы, промпты, пороги, сплиты, манифесты — в
`experiments/searh_23/policy_licensing_v1/{frozen,outputs}/`.

## 8. Ограничения (honest)

- 30 кейсов / 216 пар — достаточны для механизменных выводов (5 семейств
  ловушек, MP1×12, CF×6, renamed, misleading-tools), но НЕ для
  заявлений «solved» (§19): нужны независимые семьи больших объёмов.
- 2 FN evidence имеют понятные механизмы, но их фикс = новое дизайн-решение
  → требует Level D датасета.
- Real-трек: event extraction не дедуплицирован; P=0.405 — свойство
  текущего frontend, а не licensing-механизма.
- Conformal-интерим напечатал test-строки до финального скоринга
  (решений по ним не принималось — задокументировано в §2).
- CF-гейт использует LLM-генерацию контрфактов: 3/38 UNVERIFIED (генератор
  не прошёл контроль) — гейт честно абстинирует, но это его потолок
  применимости.

## 9. Следующие шаги

1. Level D датасет (после любых изменений судьи/экстрактора) + фикс
   cross-sentence (multi-span evidence) и over-minimal цитат
   (судья видит evidence + содержащее предложение).
2. Дедупликация/слияние структурных кандидатов frontend'а до relation-слоя
   (passive↔active клаузы, NP↔глагол) — главный рычаг для real-трека.
3. Опционально: fine-tune CrossEncoder на (policy, pair, evidence)→
   LICENSED с same-policy hard negatives — только если понадобится
   локальная модель без LLM-звена; zero-shot порог уже достигнут.
4. Declare-слой уже пригоден для формальной валидации извлечённых
   графов (циклы, недостижимость, conformance) — подключить как
   post-processing Stage.
