# Guardian Step 1–4: интеграционный журнал

Дата: 2026-09-30. Ветка: `codex/system-integration-step1-4-20260930`.

## Старт и граница результата

Ветка создана от `codex/llm-first-extraction-f6-20260929` (`376122bb`).
Из `codex/integration-eval-20260929` (`57113a82`) перенесены только
отрицательная проверка области действия `scope_conflict`, проверка
наблюдения результата с подтверждённым контрактом, журнал фактов и запрос
необходимого условия к моменту действия. Ветки целиком не объединялись.
`scripts/predict.py` не менялся. Это **промежуточный** отчёт: полный
автоматический путь Step 1–4 и его sealed оценка пока отсутствуют.

## Step 1: paired F6 scope-veto regression

Протокол заморожен до нового API-прогона в `c10bed0b`, код сравнения —
в `f664f3fb`. Оба рукава использовали одни и те же 24 политики F6,
сохранённые raw extractor/sanitation результаты, `ministral-14b-latest`,
один relation stack и один строгий scorer. В обоих процессах установлен
`PYTHONHASHSEED=0`. Единственное переключение — `W1_SCOPE_GUARD`.
Результаты и per-case данные лежат в
`experiments/searh_23/system_integration_v1/outputs/`.

| Рукав | Верные связи | Лишние | Пропущенные | P | R | F1 | Точных графов | Загрязнённых концов |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| F6 RAWSAN | 24 | 6 | 19 | .800 | .558 | .658 | 10/24 | 3 |
| + scope veto | 25 | 8 | 18 | .758 | .581 | .658 | 11/24 | 4 |

Контрольный рукав воспроизвёл архивные aggregate цифры F6. Guard изменил
узлы в пяти случаях. `l_snowroute`: разделил plough северной и южной дороги,
восстановил одну правильную связь. `l_roastery`: отделил фразу «Cooling may
begin once…» и вызвал одну лишнюю связь. `s_incubator`: отделил проверку
прогрева от прогрева, но relation stack добавил второй ошибочный
`PRECONDITION`. `s_telegraph` изменил узлы без изменения связей.
`s_fishery` убрал смешение fish 44/45 в узле, но ошибочная связь осталась.

Таким образом, scope veto полезен как **запрет некоторых неверных
отождествлений**, но в данном полном стеке не улучшает F1 и ухудшает
точность. По умолчанию он выключен. Включение требует отдельного
механизма, который после разделения узлов не превращает новые пары в
ложные нормативные связи. Подгонять relation stack на этих пяти просмотренных
случаях запрещено протоколом.

Техническая воспроизводимость: manifest F6 хранит SHA256 канонического
JSON с отсортированными ключами (`737a9602…`), а SHA256 байтов файла иной
(`8937b3c9…`). Это не разные данные. В старом `build_nodes_v3` тип узла
при равенстве голосов выбирается через `max(set(types), key=types.count)` и
может зависеть от хеширования; новый paired прогон фиксирует seed.

Дополнительная проверка показала, что новый контроль воспроизвёл
исторические F6 scores не только суммарно, но и для каждого случая.
На прежнем авторском наборе J этот же veto исправил 8/8 рёбер против
0/8 у контроля; F6 показывает предел переноса этого результата.

Выходные F6 графы сохраняют 101 узел и исходные цитаты связей, но не
сохраняют `governed_tools` ни у одного узла. Reranker выбирал top-1
инструмент лишь во время relation inference. Даже если сохранить этот
выбор, это кандидат на область действия, а не подтверждённый контракт
эффекта инструмента. Результат 24/43 рёбер сам по себе ещё не создаёт
`policy → governed action → verified world fact`.

## Step 2: перенесённая граница доказательства

`src/guardian_truth/step2/trusted.py` сначала устанавливает точное
наблюдение: уникальное спаривание вызова и результата, тот же инструмент,
порядок, путь в JSON, значение и ID сущности с обеих сторон. Семантический
`WorldFact` создаётся только при совпадении с переданным приложением
`ReviewedBinding`; флаг или предикат модели сам по себе не даёт такого
права. Факты хранятся в append-only журнале и запрашиваются на срезе до
целевого действия. `RuntimeProofLayer` проверяет лишь узкий `only if`
при заранее подтверждённых rule и binding.

Перенесённые 18 синтетических oracle-контролей прошли; это регрессия
границы, **не** измерение автоматического получения контрактов из
произвольной политики и описаний инструментов. Исторические точные
оценки автоматического Step 2 на другом наборе были значительно ниже
oracle; их нельзя подменять результатом этих 18 контролей.

Исторический `strict_step2_score.py` повторно оценён на сохранённых
автоматических выходах test split (19 gold facts). Он требует совпадения
предиката, сущности, типизированного значения, силы и provenance:

| Step 2 рукав | Верных / выданных | Precision | Recall |
| --- | ---: | ---: | ---: |
| F structural | 7/16 | .438 | .368 |
| H hybrid | 9/17 | .529 | .474 |
| I contract, oracle | 11/11 | 1.000 | .579 |

Это уже записанные результаты других рукавов, здесь только воспроизведён
строгий scorer на сохранённых выходах. Они подтверждают, что автоматический
semantic binding пока ограничен; oracle I не является готовым acquisition.

## Новая trajectory suite и первый Step 2 acquisition

В `68f56606` до изменения Step 3/4 заморожена suite из **41 полной
траектории**: 21 dev и 20 sealed, домены не пересекаются. В каждом случае
записаны политика, пользовательская цель, каталог инструментов, история
вызовов и результатов, ответ агента, gold правила/факты/claims,
временной срез действия, достижимость и итоговая метка. Источники и
SHA256 — в `experiments/searh_23/system_integration_v1/frozen/trajectories_v1/`.
Набор авторский синтетический; он проверяет механизмы, а не доказывает
внешний перенос на реальные траектории.

Узкий автоматический `acquire_documented` читает только **структурированные,
явно заданные приложением** контракты в каталоге: поле сущности, путь
результата, предикат, силу и допустимые значения. Затем каждое значение
повторно проходит `trusted.assess` с точным ID, результатом и временем.
Из свободного описания инструмента он контракт не выводит. На dev:
**41/41 точных WorldFact, 0 лишних**. Это ожидаемый верхний предел для
явно документированных контрактов в авторских случаях, а не результат
решения общей проблемы NL contract acquisition. Таймаут/ошибка не создают
WorldFact даже при наличии похожего поля в payload.

## Step 2: one-shot sealed check and raw observation boundary

The documented-contract compiler was unchanged after the dev check. Its first
sealed evaluation returned **20/40 exact facts, 0 extra, 20 missing**
(precision 1.000, recall .500). Two held-out families have only prose tool
descriptions; the compiler deliberately cannot infer semantic contracts from
them. This is a coverage failure, not evidence that those tool results contain
no useful information. The 41/41 dev result applies only where the authored
catalog supplies explicit structured contracts. Neither score measures a
complete Guardian verdict. The sealed score is recorded as-is in
`outputs/step2_documented_sealed.json`; no post-result compiler tuning is
allowed on this split.

`integration/observations.py` now retains transport-verified scalar JSON
fields from all uniquely paired tool results, including prose-only tools and
failure payloads. It records the exact call, result index, path, value and
payload type. This is source data only: it assigns no business predicate,
entity scope, effect strength or authority. Three boundary tests pass. The
next semantic acquisition stage must remain separately measured and must not
promote a model guess into a reviewed contract.

## Step 3: first frozen response-only claim-mode probe

The prompt and validator were committed in `5cb2db41` before model calls.
One `ministral-14b-latest` JSON request per distinct reply was made, without
policy, tools, history or gold in the prompt. The model proposed exact reply
substrings and one of six modes; code accepted only unambiguous literal
substrings. This is an inventory probe, not claim-to-fact binding.

| Split | Cases | Distinct replies / API calls | API tokens | Strict exact span+mode claims | Exact cases |
| --- | ---: | ---: | ---: | ---: | ---: |
| dev | 21 | 11 | 3,696 | 1/21 | 1/21 |
| sealed | 20 | 10 | 3,350 | 2/22 | 0/20 |

The strict metric is sensitive to whether the model includes a period or
surrounding words. A **post-hoc diagnostic, not a replacement score**, greedily
aligns a proposed span only if it covers at least half the gold span. Dev:
20/21 aligned, 18/20 aligned modes correct. Sealed aggregate: 20/22 aligned,
18/20 aligned modes correct. The dev mode failures include a future offer
(`I can swap ...`) called `CLAIMED_COMPLETED`, and a present state
(`is dispatched`) also called `CLAIMED_COMPLETED`; the conditional dispatch
sentence was split into action and condition, so no single aligned claim.
These are dangerous errors for a violation detector even though most
surrounding spans overlap. No rule, threshold, prompt or model was changed
after opening sealed gold. Raw replies and per-case errors are saved in
`outputs/step3_modes_{dev,sealed}.json`.

## Остальные этапы

Step 3: первый mode extractor измерен, но не подключён к этому runtime и
не связывает claims с проверенными фактами. Step 4: доказанная
достижимость допустимого продолжения и отказ пока не подключены. Нет
end-to-end TP/FP/FN/UNKNOWN, общей стоимости, multi-policy и ablation
Step 3/4. Набор из 41 траектории уже заморожен; следующий шаг — связать
Step 3/4 с текущим журналом фактов, отдельно измеряя автоматический путь
и ablation с заранее заданными контрактами.

Текущий статус: **NOT READY** как конкурсный интегрированный детектор.
