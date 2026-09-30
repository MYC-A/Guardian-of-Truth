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

## Step 3: candidate-centred development after the sealed run

In `7227f1a1`, before additional API calls, a second independent prompt was
frozen. It asks about each *validated structured contract meaning* separately
and requires one exact reply quote or `NONE` per candidate. It sees no tool
history or policy. This is a **post-sealed development iteration** and has
not been scored as transfer on the already opened sealed split.

On 21 dev cases, 11 model calls used 5,267 tokens. For exact
`(predicate, mode)` pairs it produced **11 correct, 13 extra, 10 missing**
(P .458, R .524); only 8/21 cases were exact. It repaired the first probe's
two dangerous mode errors on the offer `I can swap ...` and present state
`is dispatched`. It also relabelled passive completed events such as
`refund ... was processed` and `device ... has been swapped` as `STATE_CLAIM`,
and inferred an extra `notice.emergency` state from the adjective in
`I published emergency notice ...`. This shows both the benefit and the menu
bias of supplying tool meanings. It is not safe as an automatic proof input.
The raw proposals and all errors are in `outputs/step3_candidate_dev.json`.

The original frozen dev split has **no refusal cases**; its refusal cases are
only in sealed. Step 4 tuning therefore needs a new, separately frozen
development set and another unseen split, rather than optimizing against the
already opened sealed gold.

## Остальные этапы

### Первый связанный proof runtime: reviewed/oracle acquisition

`integration/proof_engine.py` объединяет source-scoped `ReviewedProgram`,
документированные Step 2 `WorldFact`, append-only ledger, as-of проверку
действия и проверку claim. Он поддерживает трёхзначные AND/OR, явное
исключение и numeric activation guard. Для `I did X` требуется доказанный
эффект вызова агента: один поздний read состояния не доказывает, что это
сделал агент. Каталог управляемого инструмента привязан к версии через
fingerprint, а факт с другой сущностью, суммой или после действия не подходит.

Контроль `eval_reviewed_bridge_dev.py` использует **вручную разобранные**
четыре dev-политики в `reviewed_policy_programs_dev.json` и **gold**
интерпретации ответов (claim spans, predicate, entity, value). Из входов
автоматически извлекаются только Step 2 факты по структурированным
контрактам. Получилось **21/21 итоговых меток и 16/16 статусов проверяемых
действий** на dev. Это upper-bound проверка связи и логики, не оценка
автоматического Step 1/3. Policy source сейчас привязан к целому исходному
тексту; granular source spans для всех операций компилятор пока не выдаёт.
Шесть контрфактических проверок покрывают позднее одобрение, чужую сумму,
изменённый контракт producer, исключение без второй обязанности,
`I did X` после одного read и неполный инвентарь. Они выявили и закрыли
опасную ошибку: state observation прежде неверно считался доказательством
авторства действия. Машинные цепочки лежат в `outputs/reviewed_bridge_dev.json`.

Следующая проверка нашла ещё один разрыв: claim о возврате **250** мог
связаться с эффектом возврата **100** для того же заказа. Теперь проверка
claim требует полного совпадения всех параметров документированного producer,
а значения scope должны встречаться в том же исходном предложении.
Сумма `250` в полном предложении принимается, даже если модель выделила
подцитату `refund for O-72 was processed` без числа. Число в другом
предложении и подмена суммы дают UNKNOWN. После усиления тот же oracle
контроль остаётся 21/21; восемь контрфактических runtime-тестов проходят.

### Частично автоматический связанный прогон

`eval_auto_claim_bridge_dev.py` использует **тот же вручную разобранный
policy program**, автоматические Step 2 факты и сохранённые до его написания
ответы Step 3 candidate prompt. Код принимает factual claim только при
дословной уникальной сущности, значении из документированного контракта и
полном совпадении дополнительных аргументов. Фразы с отрицанием,
нелицензированным значением или непокрытыми словами остаются UNKNOWN.

На 21 dev траектории: **17/21 вердиктов**; ERROR **6/6**, ложных ERROR **0**,
NO_ERROR **6/10**, UNKNOWN **9/21**. Четыре корректных случая спрятаны в
UNKNOWN: два service-ответа, emergency-публикация с лишним кандидатом
`notice.emergency`, и просьба предоставить identity с непокрытым будущим
действием. Это development result: нет автоматического Step 1 acquisition,
нет Step 4, а dev ответы модели уже разбирались. Сохранённый per-case proof
trace: `outputs/auto_claim_bridge_dev.json`. Четыре дополнительных
адверсариальных проверки компилятора claims покрывают неверную сумму,
неверный ID, отрицание и непокрытое второе предложение.

### Step 4: отдельный frozen local-reachability контроль

`56795f5d` заморозил до кода Step 4 новый набор **16 отказов**: 8 dev
(library, warehouse), 8 sealed (clinic, grid), без общих доменов. Входы
содержат ручные `reviewed_goal`, исчерпывающий список goal-capable вызовов
и `ReviewedProgram`; gold-метки отдельно. Это **oracle acquisition**,
не автоматическое понимание user request и свободной policy. Случаи
включают доступное действие, явный запрет, неизвестное условие, чужой ID,
чужое количество, отзыв/восстановление разрешения, исключение, AND и
полный каталог без инструмента.

`integration/reachability.py` проверяет гипотетический следующий вызов через
тот же `check_call` и Step 2 ledger на времени ответа. Валидная ветка
требует документированного эффекта инструмента, точных аргументов из user
request и всех применимых policy gates. Возможный read неизвестного условия
даёт `OPEN`, а не обещание успеха. Отсутствующий инструмент даёт `CLOSED`
только при явно проверенном исчерпывающем списке и полном каталоге.
На **dev**: reachability 8/8, verdict 8/8 (2 ERROR, 3 NO_ERROR, 3 UNKNOWN).
Пять дополнительных контрпримеров проверяют, что hypothetical call не
становится фактом, неполный каталог/goal не закрывают мир, чужой аргумент
и слабый effect contract не доказывают путь, а OPEN не превращается в ERROR.
Код был заморожен и запушен в `9659c2e9` до единственного sealed-прогона.
На **sealed**: reachability **8/8**, verdict **8/8** (3 ERROR, 3 NO_ERROR,
2 UNKNOWN), без ложных тревог и скрытых под UNKNOWN ошибок. Результат
сохранён в `outputs/refusal_v1_sealed.json`; после открытия меток алгоритм
не менялся. Этот набор составлен тем же исследователем и построен из
схожих шаблонов в новых доменах. Он подтверждает перенос механической
логики между шаблонами, **не** доказывает автоматическое понимание целей,
правил или внешний перенос на реальные разговоры. В oracle-входах вручную
дано, какие действия исчерпывают путь к цели; без этого `CLOSED` и
`NO_ERROR` не разрешены.

`OPEN` в текущей реализации означает, что в каталоге есть документированный
read для неизвестного условия. Отдельного доказательства, что такой read
разрешён всеми возможными политиками, пока нет; поэтому этот статус
**никогда не даёт ERROR** и приводит к итоговому UNKNOWN. Для сильного
вывода о восстановлении пути нужна подтверждённая policy-scope проверка
самого read. Сильный `REACHABLE` требует доказанного допуска целевого
действия, но не гарантирует, что будущий вызов успешно завершится.

Step 3: первый mode extractor измерен, но не подключён к этому runtime и
не связывает claims с проверенными фактами в автоматическом пути. Step 4: доказанная
достижимость допустимого продолжения и отказ пока не подключены. Нет
end-to-end TP/FP/FN/UNKNOWN, общей стоимости, multi-policy и ablation
Step 3/4. Набор из 41 траектории уже заморожен; следующий шаг — связать
Step 3/4 с текущим журналом фактов, отдельно измеряя автоматический путь
и ablation с заранее заданными контрактами.

Текущий статус: **NOT READY** как конкурсный интегрированный детектор.

### Action-conditioned policy acquisition: frozen probe

Отдельный протокол `ACTION_CONDITIONED_V1_PROTOCOL.md` и все входы были
зафиксированы в `7ef61547` до API-вызовов. Вместо полного разбора policy
модель `ministral-14b-latest` получила исходную короткую policy, **один
заранее выбранный** effect-action из каталога и меню наблюдаемых предикатов.
Один вызов на policy при temperature 0. Модель предлагала обязательные
условия, AND/OR, exception, numeric activation, temporal и точные исходные
цитаты. Схемный валидатор проверяет буквальные цитаты и ID из каталога;
семантическое следование он не доказывает.

| Split | Policies / API calls | API tokens | Exact required predicates | Valid schema + quotes | Full exact IR |
| --- | ---: | ---: | ---: | ---: | ---: |
| dev | 6 | 3,473 | 6/6 | 4/6 | 3/6 |
| sealed | 2 | 1,229 | 2/2 | 2/2 | 1/2 |

Ошибки dev поимённо: `payments` скопировал описание инструмента вместо
фрагмента policy как action quote; `records` написал парафраз с `...` вместо
дословной цитаты условия; `warehouse` выдумал порог `quantity > 0`, которого
в policy нет. На sealed `clinic` правильно назвал permit и emergency-exception,
но выдал `ANY` при одном обязательном условии вместо ожидаемого `ALL`.
Последнее семантически эквивалентно на этом случае; первичный strict score
после открытия ответа не менялся. `grid` разобран полностью.

Вывод узок: action-conditioned запрос с готовым меню фактов резко облегчает
поиск условий, но пока не даёт проверенного автоматического `ReviewedProgram`.
Здесь всего восемь авторских коротких политик, два sealed примера и
**oracle-подсказка о governed action**; задача самостоятельного обнаружения
всех governed actions и доказательства полноты policy не проверялась.
Результаты с сырой выдачей и стоимостью находятся в
`outputs/action_conditioned_{dev,sealed}.json`. `scripts/predict.py` не менялся.
