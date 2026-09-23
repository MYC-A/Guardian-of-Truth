# SEARCH_23 — BASELINE AUDIT (исходная точка, честный аудит)

Ветка: `searh_23/investigator-v2` (создана от `big_researh` @ `1c6297f`).
Дата: 2026-09-23. Аудит выполнен по директиве SEARCH_23 §1.

## 0. Контекст потери данных (обязательная фиксация)

**23.09.2026 удалённый ModelScope-инстанс был пересоздан** (новый hostname `dsw-539675-fbb646988-4s7pr`,
прежний `dsw-538823-...`). Каталог `/mnt/data/guardian/agent-workspace/` был очищен: все рабочие деревья,
`outputs/*` предыдущего цикла big_researh и `superz_models/` (mistral-7b, granite-4.1) утрачены.
Причина потери результатов: `.gitignore` репозитория содержит `outputs/*` — raw records этапов
S6-API/S8/S9/P/Q/router_v1/agent_v1/gate41 были сохранены только на сервере и **не были закоммичены**.

Выжило (в git, восстановлено клонированием): код всех экспериментов (`experiments/big_researh/*.py`),
`docs/big_researh/{PLAN,RESULTS}.md`, исторические per-case записи full21 (контроль, S3, S5, S7),
HF-кэш granite-3.3-8b/NuExtract3/gliner/bge/nli-deberta, venv (clingo+langextract), Mistral API канал
(ключ пользователя, smoke 200 OK, ministral-14b-latest доступен).

**Исправление на будущее:** `.gitignore` дополнен whitelist `!outputs/searh_23/**` — все outputs
текущего цикла версионируются и пушатся.

## 1. Пересчитанные контрольные числа (из сырых per-case записей)

Источник: `outputs/full21/control_repro_percase.csv` (46 уникальных id, 0 missing,
sha256 `5777dbcbf2b173f7…`). Gold использован только для пост-вычисления метрик.

| Конфигурация | Пересчёт | Отчёт | Статус |
|---|---|---|---|
| Структурный Guardian (baseline) | TP12 / FP0 / FN11 / TN23; P=1.0 R=0.5217 F1=0.6857 | TP12/FP0/FN11/TN23, F1 .6857 | **MATCH** |
| Granite 3.3-8b standalone (12k, repro) | TP16 / FP2 / FN7 / TN21; P=0.8889 R=0.6957 F1=0.7805 | TP16/FP2/FN7/TN21, F1 .7805 | **MATCH** |
| granite_flash (референс) | TP16 / FP2 / FN7 / TN21; P=0.8889 R=0.6957 F1=0.7805 | то же | **MATCH** (согласие 46/46) |
| **Guardian OR Granite 3.3 (контроль)** | TP20 / FP2 / FN3 / TN21; P=0.9091 R=0.8696 F1=0.8889 | TP20/FP2/FN3/TN21, F1 .8889 | **MATCH** |

Важно (по директиве §1): «Guardian + Granite 3.3 OR» — это OR двух независимых каналов
(структурный Guardian: 12 TP; granite standalone: 16 TP; пересечение учитывает 8 общих TP),
а **не** standalone Granite. Standalone-контроль granite = F1 .7805.

S3/S5 per-case (`outputs/full21/s3s5_percase.csv`, те же 46 id, 0 missing) — все руки пересчитаны,
полное совпадение с `s3s5_metrics.json`:

| Рука | Пересчёт (standalone) |
|---|---|
| g6k | TP17 / FP6 / FN6 / TN17; P=0.7391 R=0.7391 F1=0.7391 |
| g24k | TP15 / FP1 / FN8 / TN22; P=0.9375 R=0.6522 F1=0.7692 |
| g12k_think | TP9 / FP5 / FN4 / TN11; P=0.6429 R=0.6923 F1=0.6667 (17 no_score_token) |
| ansrel_12k | TP16 / FP4 / FN7 / TN19; P=0.8 R=0.6957 F1=0.7442 |
| evas_12k | TP4 / FP0 / FN19 / TN23; P=1.0 R=0.1739 F1=0.2963 |
| ctxrel_12k | TP1 / FP2 / FN22 / TN21; P=0.3333 R=0.0435 F1=0.0769 |
| s5_graph | TP19 / FP21 / FN4 / TN2; P=0.475 R=0.8261 F1=0.6032 |
| s5_graph_quotes | TP15 / FP5 / FN8 / TN18; P=0.75 R=0.6522 F1=0.6977 |
| s5_plain_summary | TP16 / FP16 / FN7 / TN7; P=0.5 R=0.6957 F1=0.5818 |

OR-руки из s3s5_metrics.json (пересчитаны из того же per-case): g6k OR 0.7917,
g24k OR 0.8837 (TP19/FP1/FN4 — P .95), g12k_think OR 0.6977,
ansrel OR 0.8261.

S7 (THINK_AND_CLAIM_VERIFIER): plain/graph — covered 23/46, TP13/FP10/FN0 на покрытом подмножестве,
P .5652, R 1.0 (только на covered), F1 .7222; слабый дискриминатор — подтверждено.

## 2. Обнаруженные расхождения

1. **RESULTS.md, строка «S5: graph alone»**: указано TP5/FP21/FN0 → F1 .6032. Фактически по
   per-case записям: **TP19/FP21/FN4/TN2**, F1 .6032.
   F1 верен, но ячейки TP/FN в таблице RESULTS.md ошибочны (при TP5/FP21/FN0 F1 был бы ≈.32).
   Скорее всего TP5/FN0 — числа более старого S5-прогона (full21/hybrid-research), попавшие в таблицу
   вместе с F1 текущего прогона. Корректная строка: TP19/FP21/FN4/TN2.
2. **Stage II/III контроль — не OR**: router_v1 и agent_v1 сравнивались с granite standalone
   (F1 .7805), не с Guardian+Granite OR (.8889). В RESULTS.md это не было выделено явно:
   agent_v1 (TP16/FP1/FN7, F1 .80) снимал FP у standalone-granite-конфигурации и **не испытан**
   поверх OR- или P+Graph-конфигураций (см. также директиву §1, строку Agent v1 исторических
   ориентиров). Устраняется в §3 SEARCH_23 (рука 1: Guardian+Granite без investigator).
3. Мелкое: в RESULTS.md «P: pgljudge 22 TP» при «+L ухудшает» — непроверяемо (см. §3 ниже);
   Claims о «46/46» для P+G+L также непроверяемы после потери raw records.

## 3. Непроверяемые после сброса числа (честная маркировка)

Следующие числа из RESULTS.md/коммит-сообщений d34d6da/ea9e706 **не имеют сохранившихся raw
records** и потому помечаются «UNVERIFIED (post-reset)». Отчёт не перерисовывается задним числом;
числа сохраняются как заявления предыдущего цикла, не как воспроизводимые факты:

- S6 API LangExtract: 46/46, 5258 извлечений, 89% span_ok (runner сохранён, records потеряны);
- S8 Clingo: 64 карты / 28 bound / 0 нарушений (скрипт сохранён, outputs потеряны);
- S9 NuExtract: карточки 46/46; judge-абляции n_cards F1 .2286 / n_cards_quotes .375 / gn_cards .30;
- P (p_api): pjudge .7143; **pgjudge TP23/FP14/FN0 F1 .7667 R1.0**; pgljudge .7458; pglcljudge .7188;
- Q: 3332 расхождений, 12 глубоких вопросов, 5 span-verified, 1 downstream flip;
- router_v1: routing recall 1.0, метки = контролю, трассы маршрутов;
- agent_v1: 167 tool calls, FP 2→1, F1 .80 (трассы потеряны);
- Gate granite-4.1: F1 .8095 standalone, 43/46 согласий с 3.3 (per-case потеряны; сама модель
  4.1 тоже потеряна — требуется повторное развёртывание по директиве §0/§2.1);
- Mistral base judge (hist.): TP20/FP10/FN3 F1 .7547.

**План восстановления в текущем цикле**: (a) granite-4.1 переразвернуть и перезапустить
gate-сравнение на том же протоколе (§2.1) — per-case предсказания будут пересозданы и
версионированы; (b) P-канал (pgjudge) перезапускается end-to-end в §3/§5, т.к. это
обязательный вход Investigator v2; (c) S6-API records перегенерируются адресно (§5.2:
targeted extraction, не full-history ETL); (d) S8/S9/router/agent — по мере необходимости
для абляций, с версионируемыми outputs.

## 4. Замороженный снапшот

`outputs/searh_23/baseline_frozen/`: копии control_repro_percase.csv, control_repro_summary.json,
s3s5_percase.csv, s3s5_metrics.json, s7_metrics.json, INPUT_HASHES.txt.
Вход public46_label_free.csv sha256: `9f6f5fc496d25e80a008adb589ddcb30fb681d0da131fb83c37fc220c5089e93` (совпадает с `control_repro_summary.json.input_sha256` —
вход контрольного прогона идентичен текущему).
Аудит-скрипт: `experiments/searh_23/baseline_audit.py` (этот прогон).

## 5. Рабочие controls на весь цикл SEARCH_23

1. **Guardian OR Granite 3.3** (F1 .8889, TP20/FP2/FN3/TN21) — сильный контроль.
2. Granite 3.3 standalone (F1 .7805) — контроль для standalone-агентов.
3. Granite 4.1 standalone (переразвёртывается, ожидание ~.8095 по прежнему протоколу —
   будет заново подтверждён/опровергнут перезапуском).
4. pgjudge (R 1.0) — candidate generator; перезапускается, прежнее TP23/FP14 — заявление, не факт.
5. Mistral ministral-14b-latest API — операционален (200 OK, JSON-mode подтверждён).

Все сравнения в SEARCH_23 — на общих 46 id, метрики пересчитываются единым скриптом из
per-case CSV/JSONL, missing считаются отдельно, gold не используется инференсом.
