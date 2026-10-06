# Почему прежние correct findings и новый wrong-cause вывод не противоречат друг другу

Read-only дополнение к аудиту от 2026-10-06. Проверены исходные `raw_content`, промежуточные admissions/checks/verdicts и `decide_v4` на сохранённых записях. Новых моделей/judge/API вызовов нет; frozen файлы не менялись. Таблица ниже относится к внутренним LB2/LB3, не к новым external labels.

**Исправление admission/quotes сохраняет найденную моделью причину, но не гарантирует, что модель всегда найдёт правильную причину на новом наборе.** И V4 — новый интерфейс checkers, а не побитовое продолжение старого E: изменились задания, proof schema, кандидаты и их приоритет. Поэтому некоторые прежние correct findings сохранились, другие потерялись уже на новых границах. Из wrong-cause external AT нельзя делать вывод о всех DF/Ems/V4 findings.

## Пять реальных трасс от raw до final

| Пример | Было до исправления / raw | Admission и verification после изменений | Итог сохранённого V4 | Что это показывает |
|---|---|---|---|---|
| **G2e**, `lb2L_007`, stale slot | V2 A raw ERROR: слот 08:00 был свободен раньше, в последнем ответе остался только 18:00. Вся реплика отвергнута `EVIDENCE_REFERENCE_OR_ACTOR_INVALID`, потому что tool results названы system. | Admission v2 нормализовал только actor для result источников; тот же raw ERROR и та же причина admitted. | V4 ERROR от **A_adm2**, t0; причина про уже недоступный слот сохраняется. В архивном cause judge **PARTIAL**, не SAME. | Технический фикс работает. Но binary TP, частично совпадающая причина и strict ccTP — разные результаты; PARTIAL нельзя автоматически называть ложным обвинением. |
| **G3e**, `lb2L_018`, второй тренер не сертифицирован для boxing | V2 E raw/candidate правильно обвиняет **t1**. Verifier raw SUPPORTED, но v1 gate делает UNRESOLVED (`QUOTE_NOT_VERIFIED`). | Offline Q2 audit оставляет SUPPORTED; V3 E тоже SUPPORTED. **В V4 появились новые потери:** Ems raw VIOLATED с верной текстовой причиной, но `VALUE_NOT_IN_QUOTE`; AT raw ERROR t1 с верной причиной, но evidence quote не admitted. | V4 rep1 final **0**, candidate отсутствует: реальный FN относительно уже восстановленного V3. | Победа над старым verifier gate не означает, что новый proof/AT admission больше не теряет верные находки. Это потерянная correct cause, а не превращение её в wrong cause. |
| **H5e**, `lb2L_037`, 10–15 октября названы четырьмя ночами | V2 E принял арифметику `4*180=720` и SATISFIED: код проверял выбранные моделью неверные operands, не вычислил длительность. | V3 DF вычисляет **5 ночей**, candidate MISMATCH; verifier SUPPORTED. V4 DF4 делает `RANGE_NIGHTS` кодом, verifier SUPPORTED. | V4 ERROR от **DF4**, t0, та же настоящая причина «4 вместо 5 ночей»; архивный judge **SAME**. | Прежняя полезная идея здесь сохранена и strengthened; external AT wrong-cause не отменяет этот результат. |
| **CL3e**, `lb3L_000`, Wednesday 14 апреля 2025 | V3 DF выбрал WEEKDAY_OF и правильную дату, но put date into claimed_value; проверка `CLAIMED_VALUE_NOT_PARSED`, candidate нет. | V4 DF4 `WEEKDAY_ADJACENT` вычисляет Monday, candidate CODE_ONLY; verifier SUPPORTED в обеих reps. | V4 ERROR от **DF4**, t0, правильная причина; judge **SAME** в обеих reps. | Новый код исправил конкретную schema/capability потерю. Это полноценный сохранённый correct finding, хотя LB3 уже development для V4. |
| **BK3e**, `lb3L_055`, два перевода 400+900 при дневном лимите1000 | V3 E **в обоих reps** raw VIOLATED с верным `1300>1000`, но reconstructed JSON subset rejected: `EVIDENCE_QUOTE_NOT_VERIFIED`. | V4 rep1 Ems raw VIOLATED, затем `OPERANDS_MISSING`: 1000 ошибочно помечено term вместо bound. AT correct aggregate candidate SUPPORTED. V4 rep2 Ems правильно кодирует **0+400+900 LE1000**, получает VIOLATED, candidate SUPPORTED. | Rep1 ERROR от **AT**, target **t0**, правильная aggregate причина; rep2 ERROR от **Ems**, target **t1**, правильная причина. Judge **SAME** в обоих. | Исправление потенциала partly реализовано; proof contract ещё нестабилен. Correct cause и correct target различаются: rep1 действительно объясняет лимит, но плохо локализует второе действие. |

### Точные архивные записи

- G2e: `outputs/verification_v2/runs/lb2_long/rep1.jsonl:9`; `rep1_v4dev3.jsonl:8`.
- G3e: тот же каталог, `rep1.jsonl:22`, `rep1_audit.jsonl:22`, `rep1_v3dev5.jsonl:36`, `rep1_v4dev3.jsonl:21`.
- H5e: тот же каталог, `rep1.jsonl:39`, `rep1_v3dev5.jsonl:40`, `rep1_v4dev3.jsonl:39`.
- CL3e: `outputs/verification_v2/runs/lb3_long/rep{1,2}_v3.jsonl:3`, `rep{1,2}_v4dev3.jsonl:3`.
- BK3e: тот же LB3 каталог, все четыре файла `rep{1,2}_v3.jsonl` и `rep{1,2}_v4dev3.jsonl:56`.
- Judge значения получены чтением `outputs/verification_v2/judge/verdicts.jsonl` по точному `jkey(final_accusation_text, original_gold_cause)`; новые verdicts не генерировались.

## Где именно осталось недоделанное универсальное решение

**G3e особенно показателен.** Ems передал member.value=boxing, но quote сертификаций содержит только strength/swim: leaf gate справедливо отвергает утверждение, что boxing скопирован оттуда. Для отсутствия в множестве нужно процитировать/адресовать **полное множество members**, а boxing взять из current call. Более того, model выбрал `NOT_MEMBER_OF`, хотя proof plan должен описывать **условие соблюдения** политики: `MEMBER_OF(requested_type, certified_for)`. Ослабить quote gate недостаточно: неправильная polarity оператора сделала бы найденную violation удовлетворённым условием. Это проблема operation/binding contract, а не доказательство бесполезности membership checker.

AT в том же G3e верно указал t1 и реальную причину, но model реконструировал JSON объект с trainer_id/certified_for, опустив другие поля original source. `leaf_quote_ok` не принимает его как точную цитату. Нужны addressed JSON fields либо несколько точных quoted premises; перенос old Q2 fix на новый interface не был полным.

BK3e rep1 также требует выправить operation-specific schema (role bound обязателен и отделён от terms), а не считать правильную textual reason достаточным typed plan. Rep2 показывает, что корректный план уже исполняется: checker idea не провалилась.

Для дополнительного подтверждения неустойчивости extraction: **TL3e** (`lb3L_003`, LB3 records line5) в V4 rep1 ещё не admitted как вычисление; rep2 правильный `BOUND_ADD_BUSINESS_DAYS(2025-03-13,3)` вычисляет **2025-03-18**, verifier SUPPORTED, judge SAME. Это extraction variance, а не external wrong-cause observation.

## Как объяснять пользователю результат

1. «Мы исправили технические удаления некоторых правильных причин» — подтверждается G2e/G3e и BK3e. «После этого все причины стали правильными» — не подтверждалось.
2. «Новый external прирост связан в основном с AT и часто не совпадает с первоначально выбранной substantive gold причиной» — отдельный вопрос состава данных, полноты альтернативных причин, target scope и judge contract. Проверку конкретных новых причин нужно делать по исходной политике, а не переносить verdict на DF.
3. «В V4 есть реально correct findings» — подтверждается H5e, CL3e, BK3e rep2, TL3e rep2. Есть и реальные регрессии admission/planning — G3e. Поэтому одновременно возможны полезный перенос отдельных code checkers, неточная external attribution и незавершённая архитектура.
4. Для следующей проверки нужна paired таблица **найдено raw -> admitted -> checker result -> verifier -> final cause/target**, а не только суммарный F1 или число SAME. Особенно важно сохранять candidate после изменения архитектуры и отдельно маркировать PARTIAL/alternative-valid/not-judged/incorrect.

Это объяснение не объявляет новый прирост: сравнение V3/V4 на просмотренных внутренних наборах остаётся diagnostic/development, а универсальность требует нового проверенного holdout.
