# Новые модульные пилоты: измерения и границы

Ветка `research/modular-step2-4-20261002`, отдельный worktree. Base
`bdc07e2c3dd9a84039cf94ea19909e1eaac1f2d0`. Этот документ продолжает
[аудит старта](MODULAR_STEP2_4_START_2026-10-02.md).
**Работа не завершена:** shortlist, взаимодействующие гибриды, adaptive vs
always-review и новый sealed ещё не оценены. Oracle Steps2–4 выполнены
в [следующем аудите](MODULAR_ORACLE_AND_SCOPE_AUDIT_2026-10-02.md); найден
и исправлен баг call ID, мешавший native-фактам. Ни один
помощник не объявлен победителем; конкурсный `scripts/predict.py` сохранён.

## 1. Что проверено на новых входах

Авторский dev96 содержит 12 конструкций; sealed160 — 20 других генераторов.
Manifest и gold заморожены до запросов. Проверка обнаружила 256 уникальных
входов и отсутствие точных совпадений с проверенными историческими входами.
Разные генераторы **не гарантируют независимость всех смысловых примитивов**.
Gold основан на авторской спецификации, независимая человеческая проверка
очереди50 не выполнена. Sealed не оценивали.

Пилот C0 использует неизменный R0 на 48 новых dev-входах: первые четыре
варианта каждой конструкции. Эта подвыборка не сбалансирована для всех
boolean-условий: в первых четырёх комбинациях `a=false`.

| Рукав | n | TP | FP | FN | TN |
|---|---:|---:|---:|---:|---:|
| C0: исходный R0 | 48 | 25 | 3 | 1 | 19 |
| G1: старая сводка | 2 | 1 | 0 | 0 | 1 |
| G2: связанный source graph | 2 | 1 | 0 | 0 | 1 |
| G2-linear: те же записи линейно | 1 | 1 | 0 | 0 | 0 |
| G3: до четырёх запросов | 1 | 1 | 0 | 0 | 0 |

Для графа это **незавершённые пилоты**, остановленные бюджетом. На первой
общей паре изменений относительно C0 нет. Складывать эти строки в одну
метрику «граф n6» нельзя. Scorer теперь разделяет arms и показывает
завершённые пары, coverage, UNKNOWN и групповой bootstrap CI.

У C0 три FP: `dev_implication::01`, `dev_request_effect::01/03`.
Естественный FN: `dev_inclusive_timezone::02`. Политика допускает действие
до `2026-10-02T12:00:00+03:00` включительно, текущее время
`2026-10-02T09:00:01Z`. Gemma правильно перевела дедлайн в `09:00:00Z`,
но затем назвала `09:00:01Z` временем **до** дедлайна. Первичный NO_ERROR
не дошёл до B. Это реальный пропуск модели, а не fault injection.

Новый код `typed_calculations.py` вычисляет сравнения timezone-aware ISO
литералов с точными source spans. В этом случае разница равна одной секунде.
Это проверенная арифметика, **не измеренное исправление решения**: ещё нужно
проверить, помогает ли такая подсказка J/B правильно применить правило.
Код не угадывает timezone и не объявляет отношения дат доказательством
применимости политики.

## 2. Mistral и Code/Instruct для предикатов

Четыре модели получили одинаковые 8 входов, query и **действующую**
signed-Horn `FORMAL_SCHEMA`. Температура0, отдельный общий бюджет, исходные
policy/history/target доступны целиком. Это query-specific перевод, не
измерение полноты всего policy.

| Модель | Ответы | Schema valid | Определённый проверенный вывод |
|---|---:|---:|---:|
| `MISTRAL_MODEL`: Ministral14b-latest | 8 | 7, из них 6 UNSUPPORTED | 0 |
| Codestral2508 | 8 | 5 | 2 FOLLOWS, оба согласуются с авторским gold |
| Magistral-small-latest | 0 | — | HTTP429 на 8 попытках |
| Kimi-k2.7-code | 0 | — | HTTP402 на 8 попытках |

Codestral правильно вывел `verified=true` из `IF a=true → verified=true`
и подтвердил наблюдение `active=true` для нужного ID. Но:

- `permission ↔ a AND (b OR c)` превратил в два независимых IFF:
  `permission ↔ a AND b` и `permission ↔ a AND c`. При `a=b=true,c=false`
  эти классические формулы несовместимы с истинным permission исходного
  правила. Signed-Horn forward solver может всё равно получить permission;
  определённый вывод solver не удостоверяет перевод.
- В negative-scope превратил условие политики/цель пользователя в факты
  `a=false,b=true`, хотя в истории `b=false`. Другой validator поймал
  недословную rule-цитату; её исправление само по себе не убрало бы ложные факты.

Ministral в валидном IR поменяла IF на ONLY_IF и потеряла нужное следствие.
В другом ответе выдумала знак стрелки в TOOL_RESPONSE; quote gate отверг его.

**Вывод:** Code-модель показала узкое преимущество на двух выводах, но
доверенный общий компилятор из неё пока не получился. 402/429 — проблемы
доступа, не оценки семантики. Ни один challenger не повышен в default.
Добавлен консервативный guard: state-факт должен ссылаться на предшествующее
наблюдение/вызов, не на policy, user goal или target. Эта новая проверка не
подменяет аудит смысла predicate/ID и отдельно отличается от исходного прогона.

## 3. Настоящий CCG/ccg2lambda

Запущены оригинальные EasyCCG → авторский `easyccg2jigg.py` → авторский
`semparse.py` и `semantic_templates_en_emnlp2015.yaml`, **без LLM-имитации**.
Изменена только совместимость PyYAML Loader; POS от NLTK, NER метки `O`.
Java и модель реально установлены. Авторская ссылка модели не работала;
получена копия data-layer общественного OCI-зеркала, image не запускался.
Checksum, источник и отличие от аутентифицированной авторской модели сохранены.

На восьми policy: 27 предложений, **16 успешных семантических результатов,
11 failed**. Все восемь процессов обработки завершились; это не 8/8 верных IR.
Coq отсутствует, native inference не выполнен; HOL в строковый Horn не подменяли.

Авторские шаблоны в этих входах не дали проверенного нормативного смысла:
`only if`, `unless`, `through` остались лексическими предикатами; OR и
область условий терялись. `If a is true, verified is true` превратилось в
`(exists x.(TrueP & _true(x)) -> exists x.(TrueP & _true(x)))` — различие
`a`/`verified` исчезло. Это конкретная потеря смысла до prover, а не
обоснование отказа от всех CCG-вариантов. Нужен отдельный проверенный modal
lexicon и bridge; текущий M2 не пригоден для автоматического verdict.

Исходники: [ccg2lambda](https://github.com/mynlp/ccg2lambda),
[EasyCCG](https://github.com/mikelewis0/easyccg).

## 4. Атомизация, native проверяльщики и SystemV2

Адаптация [FActScore](https://github.com/shmsw25/FActScore): извлечение
атомарных утверждений → retrieval только внутри случая → независимая B.
Wikipedia и внешних business-фактов нет. Policy/catalog сохраняются целиком;
цитаты проверяются все. Утверждения target и объяснения Guardian разделены.
Это перенос алгоритмической схемы, не запуск исходного Wikipedia backend.

Пять из шести запланированных случаев достигли журнала, но большинство
стадий получили 429/INVALID. Их нельзя оценить как пять нормальных решений.
В implication00 модель дополнительно предложила утверждение о существовании
товара; B дала правильный INSUFFICIENT для `verified`, но объяснила его
ложным ONLY_IF вместо исходного IF. Правильный status с неверным объяснением
сохранён как ошибка faithfulness.

Native MiniCheck/FactCG запущены последовательно на **одном** новом frozen
банке: oracle atoms, полный исходный document, порог0.5 до запуска.
MiniCheck обработал6/6:4 правильных support-классификации. FactCG4/6:2
правильных; оставшиеся два остановлены бюджетом. На общих четырёх случаях
обе модели дали **2/4** и одни и те же ошибки IF и latest-state.
Ни один вход не обрезан. Peak allocated VRAM: MiniCheck3.15GiB,
FactCG1.73GiB; общий peak RSS около3.86GiB. Это oracle-диагностика verifier,
не автономная атомизация и не оценка финального детектора.

Actual SystemV2 acquisition → ReviewedProgram → native Step2/Step3 →
`step4_goal` → `assess_local_reachability`/`decide_refusal` запущен на4
случаях. Во всех verified facts0, reachability UNKNOWN. Первый contract
пропустил поля a/b/c, эффект EXECUTED ошибочно связал с `$.item_id`;
остальные стадии частично заблокированы429. Итог «0 фактов» включает
ошибки семантического contract и доступа, поэтому не является чистой
оценкой архитектуры. Model contracts не помечаются DOC_EXPLICIT;
неполный model inventory не доказывает CLOSED. Новый gateway сохраняет
сырые ответы каждой стадии до внутренних преобразований.

## 5. SelfCheckGPT и TruLens triad

Первый SelfCheck-пилот действительно был неисправен: Gemma получила tuple
в content, Mistral отклонила OpenAI `seed`. Исходные неудачные запросы
сохранены, их не называют отрицательным результатом SelfCheck.
Исправление: распаковка `build_judge_user`; Mistral `random_seed` согласно
[нативному API](https://docs.mistral.ai/api/endpoint/chat).

Recovery на первом заранее выбранном случае: реальные k=3 judge-семпла
Gemma и k=3 реконструированных ответов Ministral, temperature0.7,
seeds19/37/53, max_tokens800. Старые ответы не заменены новыми.
Из-за несовместимости токенизатора выделенный venv использует Transformers
4.57.6; существующий сервисный venv сохранён.
Выполнен неизменный авторский класс
[SelfCheckNLI](https://github.com/potsawee/selfcheckgpt) с исходным
двухклассовым checkpoint. Согласие меток1.0, частотная entropy0;
contradiction-score объяснения0.0052, target0.8446. Это **один случай**:
эффект маршрутизации на уверенных FN и отличие от случайного отбора
не проверены. Sample consistency — не truth; SEP без hidden states не запускался.
Генерация target явно реконструирована, не выдаётся за исходный агентский prompt.

TruLens: использованы pinned авторские feedback templates через прозрачный
адаптер совместимого API, не полный native provider package. На одном
случае сравнили raw/G2/G2-linear, target/explanation отдельно, три score
отдельно. Raw/explanation: relevance3, context0, groundedness3;
G2/explanation:3/2/3. G2-linear частично429. Высокий score красивого
объяснения не является сертификатом; одного неполного сравнения недостаточно
для вывода о пользе графа. Coverage условий/исключений/latest остаётся
отдельным неподтверждённым флагом.
[Определение triad](https://www.trulens.org/getting_started/core_concepts/rag_triad/).

## 6. Сервис, артефакты и оставшаяся работа

На сервере отдельно поднят supervisor `guardian_modular_20261002`,
loopback18092, pinned checkout `ed641291`. Старый `guardian_research`,
18090/default R0 сохранён. Новые изменения кода **ещё не заменяют** этот
проверенный процесс: revision указан в receipt.
Живой HTTP, batch и CLI-resume проверены на четырёх точных архивных входах,
12001-character вход вернул UNKNOWN без обрезки. Симулированный отказ
помощника дал UNKNOWN; повторный replay восстановился. **Replay и симуляция
не являются новым cold API качеством или настоящим provider outage.**

Runnable новые профили включают строгую B source-bound-v2, always-review,
source graph/linear, атомарный аудит, native SystemV2 advisory и арифметику
ISO. Часть этих профилей только реализована, **не оценена end-to-end**.
Для графа, source proposals и native выводов видны provenance/coverage/
assumptions; UNKNOWN сохраняется в JSONL, CSV mapping0 явен.

Бюджет:218 actual API attempts,148 ответов с известным usage251508 токенов;
70 transport failures с неизвестным usage435414 консервативного upper bound;
7380 логических cache tokens;5365 native tokens. Общий счёт699667/700000,
model time423.35s. Это **не счёт выставленных провайдерами токенов**:
ошибки доступа conservatively занимают лимит. Никаких скрытых SDK retries.
Счётчик не обнулён ради продолжения; дополнительные запросы требуют нового
бюджета dev. Изначальный sealed-бюджет не расходуется на исправление пилотов.

Данные, raw predictions, CCG trees/XML, oracle/native scores, resource ledger,
HTTP/CLI receipts сохранены в `outputs/searh_23/modular_steps_20261002/`.
Модели и86MB архив зеркала не добавляются в Git. Цена/quality/coverage
API-blocked стадий отделены в `mechanism_audit.json` и `translator_audit.json`.

До sealed требуется: закончить парные graph/atomic/native пилоты, замерить
strict/always/adaptive B на новых dev-входах и естественном FN, оценить
взаимодействующий hybrid и oracle-подстановки, затем заморозить4–6
конфигураций и прогноз бюджета. **Sealed пока не запускать, default не менять.**

Уточнение после offline-аудита: oracle-подстановки, normalized historical
template audit и сохранность нового long-context layout уже проверены.
Старый V2 API-пилот дополнительно повреждён повторяющимися call ID, поэтому
его 0 фактов не являются чистой оценкой архитектуры. Исправление и численные
результаты: [oracle и scope](MODULAR_ORACLE_AND_SCOPE_AUDIT_2026-10-02.md).

Отдельный modular процесс после этого обновлён на `b0abb74c`: новый HTTP
layout/budget probe выполнен, старый R0 процесс сохранён. Результаты
`ed641291` выше остаются историческими, а не приписываются новой ревизии.
[Текущие operations и receipts](../../service/MODULAR_OPERATIONS.md).
