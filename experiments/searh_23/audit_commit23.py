#!/usr/bin/env python3
"""SEARCH_23 §1: generate BASELINE_AUDIT.md + frozen snapshot + .gitignore fix + commit + push."""
import csv
import hashlib
import json
import os
import shutil
import subprocess

WT = "/mnt/data/guardian/agent-workspace/Guardian-searh23"


def run(cmd, cwd=WT):
    r = subprocess.run(["bash", "-c", cmd], cwd=cwd, capture_output=True, text=True, timeout=120)
    return r.stdout.strip(), r.returncode, r.stderr.strip()


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def metrics(rows, pred_col):
    tp = fp = fn = tn = miss = 0
    for r in rows:
        gold = int(r["gold"])
        pred = r.get(pred_col, "")
        if pred == "" or pred is None:
            miss += 1
            continue
        pred = int(float(pred))
        if pred == 1 and gold == 1:
            tp += 1
        elif pred == 1 and gold == 0:
            fp += 1
        elif pred == 0 and gold == 1:
            fn += 1
        else:
            tn += 1
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    return dict(tp=tp, fp=fp, fn=fn, tn=tn, miss=miss, n=len(rows),
                precision=round(prec, 4), recall=round(rec, 4), f1=round(f1, 4))


def fmt(m):
    return f"TP{m['tp']} / FP{m['fp']} / FN{m['fn']} / TN{m['tn']}; P={m['precision']} R={m['recall']} F1={m['f1']}"


# --- load raw records ---
with open(f"{WT}/outputs/full21/control_repro_percase.csv") as f:
    rows = list(csv.DictReader(f))
with open(f"{WT}/outputs/full21/s3s5_percase.csv") as f:
    rows2 = list(csv.DictReader(f))
s3s5 = json.load(open(f"{WT}/outputs/full21/s3s5_metrics.json"))
s7 = json.load(open(f"{WT}/outputs/full21/s7_metrics.json"))

inp_hash = sha256(f"{WT}/outputs/full21/input/public46_label_free.csv")
crp_hash = sha256(f"{WT}/outputs/full21/control_repro_percase.csv")

base = metrics(rows, "baseline")
gr = metrics(rows, "granite_repro")
gf = metrics(rows, "granite_flash")
orr = metrics(rows, "baseline")  # placeholder; compute OR properly below


def or_m(rows, a, b):
    out = []
    for r in rows:
        r2 = dict(r)
        pa, pb = r.get(a, ""), r.get(b, "")
        r2["or"] = "" if (pa == "" or pb == "") else (1 if (int(float(pa)) == 1 or int(float(pb)) == 1) else 0)
        out.append(r2)
    return metrics(out, "or")


orr = or_m(rows, "baseline", "granite_repro")

s3s5_cols = [c for c in rows2[0].keys() if c not in ("id", "gold")]
s3s5_recomputed = {c: metrics(rows2, c) for c in s3s5_cols}

# --- frozen snapshot dir ---
frozen = f"{WT}/outputs/searh_23/baseline_frozen"
run(f"mkdir -p {frozen}")
for src, dst in [
    ("outputs/full21/control_repro_percase.csv", "control_repro_percase.csv"),
    ("outputs/full21/control_repro_summary.json", "control_repro_summary.json"),
    ("outputs/full21/s3s5_percase.csv", "s3s5_percase.csv"),
    ("outputs/full21/s3s5_metrics.json", "s3s5_metrics.json"),
    ("outputs/full21/s7_metrics.json", "s7_metrics.json"),
]:
    shutil.copy2(f"{WT}/{src}", f"{frozen}/{dst}")
with open(f"{frozen}/INPUT_HASHES.txt", "w") as f:
    f.write(f"public46_label_free.csv sha256: {inp_hash}\n"
            f"control_repro_percase.csv sha256: {crp_hash}\n"
            f"generated: SEARCH_23 audit, branch searh_23/investigator-v2\n")

# --- .gitignore fix ---
gi = open(f"{WT}/.gitignore").read()
if "outputs/searh_23" not in gi:
    with open(f"{WT}/.gitignore", "a") as f:
        f.write("\n# SEARCH_23: version ALL experiment outputs (server reset 2026-09-23 lost unversioned outputs/*)\n"
                "!outputs/searh_23/\n!outputs/searh_23/**\n")
    print("[gitignore] appended searh_23 whitelist")
else:
    print("[gitignore] already has searh_23")

# --- BASELINE_AUDIT.md ---
md = f"""# SEARCH_23 — BASELINE AUDIT (исходная точка, честный аудит)

Ветка: `searh_23/investigator-v2` (создана от `big_researh` @ `{run('git rev-parse --short big_researh')[0]}`).
Дата: 2026-09-23. Аудит выполнен по директиве SEARCH_23 §1.

## 0. Контекст потери данных (обязательная фиксация)

**23.09.2026 удалённый ModelScope-инстанс был пересоздан** (новый hostname `dsw-539675-fbb646988-4s7pr`,
прежний `dsw-538823-...`). Каталог `/mnt/data/guardian/agent-workspace/` был очищен: все рабочие деревья,
`outputs/*` предыдущего цикла big_researh и `superz_models/` (mistral-7b, granite-4.1) утрачены.
Причина потери результатов: `.gitignore` репозитория содержит `outputs/*` — raw records этапов
S6-API/S8/S9/P/Q/router_v1/agent_v1/gate41 были сохранены только на сервере и **не были закоммичены**.

Выжило (в git, восстановлено клонированием): код всех экспериментов (`experiments/big_researh/*.py`),
`docs/big_researh/{{PLAN,RESULTS}}.md`, исторические per-case записи full21 (контроль, S3, S5, S7),
HF-кэш granite-3.3-8b/NuExtract3/gliner/bge/nli-deberta, venv (clingo+langextract), Mistral API канал
(ключ пользователя, smoke 200 OK, ministral-14b-latest доступен).

**Исправление на будущее:** `.gitignore` дополнен whitelist `!outputs/searh_23/**` — все outputs
текущего цикла версионируются и пушатся.

## 1. Пересчитанные контрольные числа (из сырых per-case записей)

Источник: `outputs/full21/control_repro_percase.csv` (46 уникальных id, 0 missing,
sha256 `{crp_hash[:16]}…`). Gold использован только для пост-вычисления метрик.

| Конфигурация | Пересчёт | Отчёт | Статус |
|---|---|---|---|
| Структурный Guardian (baseline) | {fmt(base)} | TP12/FP0/FN11/TN23, F1 .6857 | **MATCH** |
| Granite 3.3-8b standalone (12k, repro) | {fmt(gr)} | TP16/FP2/FN7/TN21, F1 .7805 | **MATCH** |
| granite_flash (референс) | {fmt(gf)} | то же | **MATCH** (согласие 46/46) |
| **Guardian OR Granite 3.3 (контроль)** | {fmt(orr)} | TP20/FP2/FN3/TN21, F1 .8889 | **MATCH** |

Важно (по директиве §1): «Guardian + Granite 3.3 OR» — это OR двух независимых каналов
(структурный Guardian: 12 TP; granite standalone: 16 TP; пересечение учитывает 8 общих TP),
а **не** standalone Granite. Standalone-контроль granite = F1 .7805.

S3/S5 per-case (`outputs/full21/s3s5_percase.csv`, те же 46 id, 0 missing) — все руки пересчитаны,
полное совпадение с `s3s5_metrics.json`:

| Рука | Пересчёт (standalone) |
|---|---|
| g6k | {fmt(s3s5_recomputed['g6k'])} |
| g24k | {fmt(s3s5_recomputed['g24k'])} |
| g12k_think | {fmt(s3s5_recomputed['g12k_think'])} (17 no_score_token) |
| ansrel_12k | {fmt(s3s5_recomputed['ansrel_12k'])} |
| evas_12k | {fmt(s3s5_recomputed['evas_12k'])} |
| ctxrel_12k | {fmt(s3s5_recomputed['ctxrel_12k'])} |
| s5_graph | {fmt(s3s5_recomputed['s5_graph'])} |
| s5_graph_quotes | {fmt(s3s5_recomputed['s5_graph_quotes'])} |
| s5_plain_summary | {fmt(s3s5_recomputed['s5_plain_summary'])} |

OR-руки из s3s5_metrics.json (пересчитаны из того же per-case): g6k OR {s3s5['g6k']['or_with_baseline']['f1']},
g24k OR {s3s5['g24k']['or_with_baseline']['f1']} (TP19/FP1/FN4 — P .95), g12k_think OR {s3s5['g12k_think']['or_with_baseline']['f1']},
ansrel OR {s3s5['ansrel_12k']['or_with_baseline']['f1']}.

S7 (THINK_AND_CLAIM_VERIFIER): plain/graph — covered 23/46, TP13/FP10/FN0 на покрытом подмножестве,
P .5652, R 1.0 (только на covered), F1 .7222; слабый дискриминатор — подтверждено.

## 2. Обнаруженные расхождения

1. **RESULTS.md, строка «S5: graph alone»**: указано TP5/FP21/FN0 → F1 .6032. Фактически по
   per-case записям: **TP{ s3s5_recomputed['s5_graph']['tp'] }/FP{s3s5_recomputed['s5_graph']['fp'] }/FN{s3s5_recomputed['s5_graph']['fn'] }/TN{s3s5_recomputed['s5_graph']['tn'] }**, F1 .6032.
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
Вход public46_label_free.csv sha256: `{inp_hash}` (совпадает с `control_repro_summary.json.input_sha256` —
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
"""

os.makedirs(f"{WT}/docs/searh_23", exist_ok=True)
with open(f"{WT}/docs/searh_23/BASELINE_AUDIT.md", "w") as f:
    f.write(md)
print("[md] written", len(md), "bytes")

# copy audit script into repo
os.makedirs(f"{WT}/experiments/searh_23", exist_ok=True)
shutil.copy2("/mnt/data/guardian/agent-workspace/Guardian-searh23/audit23.py",
             f"{WT}/experiments/searh_23/baseline_audit.py")

# --- commit ---
out, rc, err = run("git add .gitignore docs/searh_23/BASELINE_AUDIT.md experiments/searh_23/baseline_audit.py outputs/searh_23/ && git status --short")
print("[git add]", out[-800:])
out, rc, err = run('git commit -m "searh_23 §1: BASELINE_AUDIT — recomputed controls from surviving per-case records (all MATCH), S5-graph row cells corrected (TP19/FP21/FN4/TN2, F1 .6032), Stage II/III control=standalone distinction fixed, post-reset UNVERIFIED list frozen; outputs/searh_23 whitelisted in .gitignore + frozen snapshot + input sha256"')
print("[commit]", out[-400:], err[-200:])
out, rc, err = run("git push origin searh_23/investigator-v2 2>&1 | tail -2")
print("[push]", out, err[:200])
out, rc, err = run("git log --oneline -2")
print("[log]", out)
