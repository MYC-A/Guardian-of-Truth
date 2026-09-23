#!/usr/bin/env python3
"""SEARCH_23 §1 BASELINE AUDIT: recompute metrics from surviving per-case records.

Surviving raw records (in-repo, pushed):
  outputs/full21/control_repro_percase.csv   (id, gold, baseline, granite_repro, granite_flash)
  outputs/full21/s3s5_percase.csv            (S3 context arms + S5 graph arms)
  outputs/full21/s7_metrics.json
Lost in server reset 2026-09-23 (outputs/* gitignored, workspace wiped):
  S6-API records, S8 clingo outputs, S9 cards/judges, P/Q/router/agent traces, gate41 per-case.

This script recomputes everything recomputable, compares with reported numbers,
and emits BASELINE_AUDIT.md content. Gold used ONLY for post-hoc metric computation.
"""
import csv
import hashlib
import json
import os

WT = "/mnt/data/guardian/agent-workspace/Guardian-searh23"


def metrics(rows, pred_col):
    tp = fp = fn = tn = miss = 0
    ids = []
    for r in rows:
        gold = int(r["gold"])
        pred = r.get(pred_col, "")
        ids.append(r["id"])
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
    return dict(tp=tp, fp=fp, fn=fn, tn=tn, miss=miss, n=len(ids), precision=round(prec, 4), recall=round(rec, 4), f1=round(f1, 4))


def or_metrics(rows, a, b):
    out = []
    for r in rows:
        r2 = dict(r)
        pa, pb = r.get(a, ""), r.get(b, "")
        if pa == "" or pb == "":
            r2["or"] = ""
        else:
            r2["or"] = 1 if (int(float(pa)) == 1 or int(float(pb)) == 1) else 0
        out.append(r2)
    return metrics(out, "or")


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


print("== input hash ==")
inp = f"{WT}/outputs/full21/input/public46_label_free.csv"
print("public46_label_free.csv sha256:", sha256(inp))
inp2 = f"{WT}/outputs/full21/control_repro_percase.csv"
print("control_repro_percase.csv sha256:", sha256(inp2))

print("\n== control_repro_percase.csv audit ==")
with open(inp2) as f:
    rows = list(csv.DictReader(f))
print("columns:", list(rows[0].keys()))
print("n rows:", len(rows))
ids = [r["id"] for r in rows]
print("unique ids:", len(set(ids)))

base = metrics(rows, "baseline")
gr = metrics(rows, "granite_repro")
gf = metrics(rows, "granite_flash")
orr = or_metrics(rows, "baseline", "granite_repro")
print("baseline (structural Guardian):", json.dumps(base))
print("granite_repro (3.3 12k):", json.dumps(gr))
print("granite_flash:", json.dumps(gf))
print("baseline OR granite_repro:", json.dumps(orr))

# agreement repro vs flash
agree = sum(1 for r in rows if r["granite_repro"] == r["granite_flash"])
print("granite_repro vs flash agreement:", agree, "/", len(rows))

# reported reference values
reported = {
    "baseline": dict(tp=12, fp=0, fn=11, tn=23, f1=0.6857),
    "granite_33": dict(tp=16, fp=2, fn=7, tn=21, f1=0.7805),
    "or": dict(tp=20, fp=2, fn=3, tn=21, f1=0.8889),
}


def cmp(label, got, exp):
    ok = all(got[k] == exp[k] for k in exp)
    print(f"  {label}: {'MATCH' if ok else 'MISMATCH'} (got {json.dumps(got)} vs reported {json.dumps(exp)})")


print("\n== compare with reported ==")
cmp("baseline", base, reported["baseline"])
cmp("granite_33", gr, reported["granite_33"])
cmp("OR", orr, reported["or"])

print("\n== s3s5_percase.csv audit ==")
with open(f"{WT}/outputs/full21/s3s5_percase.csv") as f:
    rows2 = list(csv.DictReader(f))
print("columns:", list(rows2[0].keys()))
print("n rows:", len(rows2))
ids2 = [r["id"] for r in rows2]
print("same id set as control:", set(ids2) == set(ids))

# recompute each prediction column
s3s5_reported = json.load(open(f"{WT}/outputs/full21/s3s5_metrics.json"))
for col in rows2[0].keys():
    if col in ("id", "gold"):
        continue
    m = metrics(rows2, col)
    rep = s3s5_reported.get(col, {}).get("standalone")
    tag = ""
    if rep:
        ok = all(m[k] == rep[k] for k in ("tp", "fp", "fn", "tn"))
        tag = " MATCH" if ok else f" MISMATCH vs {json.dumps({k: rep[k] for k in ('tp','fp','fn','tn')})}"
    print(f"  {col}: {json.dumps(m)}{tag}")

print("\n== s7_metrics.json ==")
print(open(f"{WT}/outputs/full21/s7_metrics.json").read()[:1500])
