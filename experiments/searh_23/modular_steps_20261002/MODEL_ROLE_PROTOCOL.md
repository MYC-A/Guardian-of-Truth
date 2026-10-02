# MODEL_ROLE_PROTOCOL — матрица ролей и сравнение моделей (2026-10-02)

Ветка: research/modular-step2-4-20261002. Фаза бюджета: reviewer_repair
(300 попыток / 1M known / 200k unknown / 1.2M логических — израсходовано
300/300, known 465984, logical 597414; reconciliation dev2: 239/300 реальных).

## 1. Доступность каналов (receipts: model_census.json, 7 probe)

| provider | model | семейство | работоспособность | ограничения | latency probe | usage |
|---|---|---|---|---|---|---|
| ollama.com | gemma4:31b | gemma | ДА | JSON ok; seed учитывается (контенты различаются), метки стабильны | 0.57 s | репортится |
| ollama.com | gpt-oss:20b | gpt-oss | ДА | reasoning-оверхед (~102 токена на 6-токенный ответ); JSON ok | 1.7 s | репортится |
| ollama.com | gpt-oss:120b | gpt-oss | ДА (probe ok) | тот же reasoning-оверхед | 0.53 s | репортится |
| ollama.com | nemotron-3-nano:30b | nemotron | ДА | JSON ok | 0.7 s | репортится |
| ollama.com | nemotron-3-super/-ultra | nemotron | ДА (probe ok) | — | 1.1–4.4 s | репортится |
| aihorde | google/gemma-4-31b | gemma (транспортный дубликат) | ДА | БЕЗ usage-репорта → учёт по верхней оценке; НЕ независимое семейство | 6.65 s | нет |
| mistral | ministral-14b-latest (env) | mistral | ДА (production) | seed → random_seed адаптер | — | репортится |
| ollama.com | glm-5.3-flash | — | НЕТ: 402 OPEN_PERMANENT | блок до изменения квоты | — | — |

Независимые семейства подтверждены: gemma, gpt-oss, nemotron, mistral (4 ≥ 3).
Размеры одного семейства и разные воркеры одного endpoint независимыми НЕ считаются.

## 2. Замороженные банки и контракты

- **Ролевой банк** (12 кейсов, role_pilot/selection.json, FROZEN_BEFORE_RUN):
  6 ошибок + 6 чистых, 12 логических групп, вкл. 6 бывших FP-кейсов B
  (unless::02, negative_scope::02, units::00, retry_commit::00, latest::01,
  refusal_inventory::00). Mixed-target в замороженном dev отсутствует
  (покрыт офлайн-тестами + deferred-банком).
- **Отложенный банк** (24 новых кейса, dataset/deferred_bank/, manifest-хеши):
  новые конструкции — получасовые зоны (+09:30), «no later than the inclusive
  moment», XOR/NOT(x OR y), обратная импликация на новых переменных, новые
  величины (2.5 кг), scoped/overbroad отказы, MIXED-цели (вызов+текст).
  11 ошибок / 13 чистых; авторский gold, PENDING human review.
- **Контракты**: V0 = официальные инструкции (JUDGE_SYSTEM / B INSTRUCTION,
  без изменений); V1 = V0 + калибровочные clause из §5-фиксов
  (role_prompts.py: CALIBRATION — no-obligation-to-find, контекстная
  обоснованность вместо in-text цитирования, запрос≠исполнение, написанный
  текст политики governs, каталог=словарь определений, разрешённые импликации,
  абсолютные инстанты для дедлайнов). Выходной контракт единый (vote schema,
  validate_vote с дословной проверкой цитат).
- **Правила отложенного сравнения заморожены ДО просмотра результатов**
  (deferred_pilot/selection.json: binary mapping, no-tuning, метрики,
  Gk3-мажоритарность на уровне банка).

## 3. Матрица ролей — результаты (12-кейсовый банк, dual F1: raw | frozen-mapping)

| система | TP | FP | FN | TN | UNK | F1 raw | F1 frozen | комментарии |
|---|---|---|---|---|---|---|---|---|
| B_V0 (archived strict_always, mistral) | 6 | 6 | 0 | 0 | 0 | .7059 | .7059 | ERROR на ВСЕХ 12: каждое чистое решение обвинено |
| D_V1_mistral (прямой судья) | 6 | 1 | 0 | 5 | 0 | .9231 | .9231 | 5/6 FP снято одной калибровкой контракта; остаток units::00 (T16) |
| D_V1_gemma | 5 | 0 | 1 | 6 | 0 | .9091 | .9091 | все 6 FP сняты; FN = 1с-после-дедлайна (temporal-слабость семьи) |
| D_V1_gptoss | 6 | 0 | 0 | 6 | 0 | 1.0 | 1.0 | лучший прямой судья |
| D_V1_nemotron | 6 | 0 | 0 | 5 | 1 | 1.0 | 1.0 | 1 удержание (gold-0 → TN в frozen) |
| EJ_gemma_gemma (извлечение→проверка) | 5 | 0 | 0 | 6 | 1 | 1.0 | .9091 | self-пайплайн НЕ проигрывает прямому судье — вопрос измерения закрыт |
| EJ_gptoss_gptoss | 6 | 0 | 0 | 6 | 0 | 1.0 | 1.0 | |
| X_gptossE_gemmaJ (кросс) | 6 | 0 | 0 | 6 | 0 | 1.0 | 1.0 | лучший межмодельный кандидат |
| Gk3_gemma (k=3, temp 0.7, seeds 11/22/33) | 5 | 0 | 1 | 6 | 0 | .9091 | .9091 | seeds учитываются (10/12 контентов различны, request-hash 12/12), метки стабильны: мажоритарность = одиночный сэмпл; коррелированная семья, не 3 эксперта |
| G3_counterevidence (3-я роль Gemma) | — | — | — | — | — | — | — | 5/5 обвинений чекера NOT_REFUTED (корректные обвинения подтверждены); путь опровержения ложных обвинений live не тестировался (у чекера 0 FP) |
| B_without_A (якорение §8.6) | 6 | 0 | 0 | 0 | 0 | 1.0 | 1.0 | на error-кейсах вердикты B совпадают с B-with-A: якорение A НЕ причина FP (FP возникали при ПУСТЫХ prior findings) |

## 4. Отложенное сравнение (18/24 троек до потолка бюджета; dual F1)

| система | TP | FP | FN | TN | UNK | F1 raw | F1 frozen |
|---|---|---|---|---|---|---|---|
| C0_J_control (официальный V0 J, mistral) | 4 | 5 | 0 | 2 | 7 | .6154 | .5 |
| D_V1_gemma | 7 | 2 | 0 | 9 | 0 | .875 | .875 |
| D_V1_gptoss | 7 | 0 | 0 | 11 | 0 | 1.0 | 1.0 |

- gpt-oss снял ВСЕ 5 temporal-FP контроля (равенство инстантов, кросс-день);
  gemma сняла 3, её 2 FP — обе equal-instant конструкции (+09:30/+14:00);
  7 UNKNOWN контроля — JSON-контрактные отказы V0 (effect/perm группы).
- 6 кейсов банка не измерены (BUDGET_STOP на 300/300), X_gemmaE_gptossJ
  не запускался — задекларировано; перекоса выбора нет (round-robin,
  полные тройки).

## 5. Причинно-следственная цепочка исправления (§11)

старая ошибка → причина (атлас §5) → изменение → результат на тех же кейсах
→ новый контрпример:
- B-V0 FP ×6 (все чистые) → «обязан найти additional_error» + галлюцинации
  требований (T4/T5/T10/T12/T13/T16) → V1-калибровка контракта →
  mistral 5/6 снято (остаток units::00=T16), gemma 6/6, gpt-oss/nemotron 6/6
  → контрпримеры: mistral всё ещё требует явной проверки массы; gemma
  теряет TP на после-дедлайн кейсе (temporal-слабость);
- на НОВЫХ конструкциях: V0-контроль 5 FP + 7 UNKNOWN → V1-gptoss 0 FP 0 FN
  → контрпример: равенство инстантов остаётся слабостью gemma (2 FP).

## 6. Решение о рабочей цепочке

- **Лучшая одиночная модель-судья: gpt-oss:20b с V1-контрактом** (1.0 на
  обоих банках, dual-F1). Рекомендуемая конфигурация для следующего этапа:
  direct judge D(gpt-oss:20b, DIRECT_V1), одношаговый.
- **Кросс-кандидат: gpt-oss extractor → gemma checker** (1.0 на банке);
  Gemma→Gemma self-пайплайн .9091 frozen (встаёт вровень с direct-gemma —
  схема НЕ проигрывает разномодельному вызову на этом банке).
- Трёхвызовные Gemma-варианты (k=3, 3 роли) НЕ дают прироста против
  одиночного вызова на этом банке (коррелированность семьи) — честный
  негатив; условный вызов третьей роли на disagreement остаётся отдельным
  routing-arm для будущей проверки (спорных случаев не возникло: 0 FP).
- default R0/C0 не менялся и не заменён (изменение продакшн-маршрута —
  вне мандата этого задания; измеренный выигрыш задокументирован).
- Воспроизводимость: `python role_pilot.py --run [--arms ...]`,
  `python deferred_pilot.py --run`, `python score_roles.py`,
  `python score_deferred.py` в experiments/searh_23/modular_steps_20261002
  (venv /workspace/guardian/venv); сырые ответы/usage/request-hash в
  role_pilot/role_predictions.jsonl и deferred_pilot/predictions.jsonl;
  receipts в repair_receipts/.

## 7. Ограничения (честные)

- Банки малы (12 + 18 измеренных троек): group-CI не вычислены, «не
  универсальность/конкурсный тест».
- Авторский gold обоих банков не прошёл человеческую ревизию (PENDING);
  спорные места сохранены, не подогнаны (refusal_inventory::02
  disputed-lean-keep).
- EJ/Gk3/G3/cross не перемеряны на отложенном банке (потолок бюджета);
  X_gemmaE_gptossJ не измерен вовсе.
- Aihorde-канал без usage-репорта: только верхние оценки.
- Механический temporal-модуль (§7.C) остаётся advisory; структурный
  shortcut-рукав с материализованным вердиктом сравнения (F1-структурный)
  не перемерен против pure-model на новых банках — измерение разделено
  по заданию §8 и остаётся в remaining-work.


---

## Addendum 2026-10-02 (all-methods-noft cycle): deferred comparison completed to 24/24

The six previously unmeasured goals (def_effect_new::05, def_mixed::00,
def_mixed::01, def_perm_new::06, def_perm_new::07, def_mixed::02) were run on
phase modular_all_noft_20261002 with the SAME frozen rules and systems
(selection deferred_completion/selection.json, FROZEN_BEFORE_RUN; gold v2 —
def_mixed::01 provenance repaired, label unchanged). 28 attempts / 41,327
known tokens / 98.3 model-seconds.

Full 24-case dual-F1 (score_deferred_completion.py, gold v2):

| system | TP | FP | FN | TN | UNKNOWN | F1 raw | F1 frozen |
|---|---|---|---|---|---|---|---|
| C0_J_control (mistral V0) | 5 | 5 | 0 | 2 | 12 | .6667 | .4762 |
| D_V1_gptoss | 11 | 0 | 0 | 13 | 0 | 1.0 | 1.0 |
| D_V1_gemma | 11 | 2 | 0 | 11 | 0 | .9167 | .9167 |

New-case notes: the 18 archived triples are unchanged (journal untouched);
the 6 new rows add 1 TP + 5 UNKNOWN to C0 (the source_ref JSON-contract
failure family, 2 attempts each), 3 TP + 3 TN to gpt-oss (still perfect),
3 TP + 3 TN to gemma (the 2 FPs remain the archived equal-instant
constructions — no new FP). The historical "18/24" wording above is
superseded by 24/24 measured; the archive journals were published verbatim
in raw_journals/ (role 174 rows/201 calls incl. 34 reask calls; deferred 54
rows/78 calls; deferred_completion 18 rows/28 calls) with sha256 in the
README. Wording re-check (assignment §3.4): role bank = 12 cases over 10
logical groups (confirmed against the journal); control model C0_J_control
is mistral ministral-14b-latest (confirmed, line 17); UNKNOWN counts and
retries are as journaled above.
