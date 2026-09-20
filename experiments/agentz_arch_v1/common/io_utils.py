"""Common IO, dataset loading, caching, metrics for agentz experiments."""
import json, os, subprocess, hashlib, tempfile, csv
from pathlib import Path

EXP = Path(__file__).resolve().parent.parent          # experiments/agentz_arch_v1
REPO = EXP.parent.parent                              # repo root
BRIDGE = EXP / "common" / "llm_bridge.mjs"
OUTZ = REPO / "outputs" / "agentz"
CACHE = EXP / "cache"

SYSTEM_PROMPT = ("You are an expert auditor of AI agent trajectories. You are strict, "
                 "skeptical and precise. You never invent facts that are not in the provided "
                 "context. Answer in the exact format requested.")


def run_llm(tasks, concurrency=3, cache_dir=None):
    """tasks: [{id, system, prompt, max_tokens?}] -> {id: content or None}"""
    if not tasks:
        return {}
    cache_dir = cache_dir or CACHE
    cache_dir.mkdir(parents=True, exist_ok=True)
    # in-process cache keyed identically to bridge
    def key(t):
        return hashlib.sha256(json.dumps([t.get("system", ""), t["prompt"],
                                          t.get("max_tokens", 2048)])).hexdigest()
    results, todo = {}, []
    for t in tasks:
        k = key(t)
        p = cache_dir / (k + ".json")
        if p.exists():
            try:
                results[t["id"]] = json.loads(p.read_text())["content"]
                continue
            except Exception:
                pass
        todo.append(t)
    if todo:
        with tempfile.TemporaryDirectory() as td:
            tf, of = Path(td) / "t.json", Path(td) / "r.json"
            tf.write_text(json.dumps(todo))
            cmd = ["bun", str(BRIDGE), "--tasks", str(tf), "--out", str(of),
                   "--cache", str(cache_dir), "--concurrency", str(concurrency)]
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
            if not of.exists():
                raise RuntimeError(f"bridge failed: {r.stderr[-2000:]}")
            for row in json.loads(of.read_text()):
                results[row["id"]] = row["content"] if row.get("ok") else None
    return results


def extract_json(text):
    """Best-effort JSON extraction from LLM output."""
    if text is None:
        return None
    t = text.strip()
    if "```" in t:
        for chunk in t.split("```"):
            c = chunk.strip()
            if c.startswith("json"):
                c = c[4:]
            c = c.strip()
            if c.startswith("{") or c.startswith("["):
                t = c
                break
    try:
        return json.loads(t)
    except Exception:
        pass
    # find first { ... last }
    a, b = t.find("{"), t.rfind("}")
    if a >= 0 and b > a:
        try:
            return json.loads(t[a:b + 1])
        except Exception:
            return None
    return None


# ---------------- datasets ----------------

def load_public46():
    """Contest public46 dev set (SEEN by project, diagnostics only)."""
    import pandas as pd
    df = pd.read_parquet(REPO / "valid.parquet")
    rows = []
    for _, r in df.iterrows():
        rows.append({"id": str(r["id"]), "prompt": r["prompt"],
                     "response": r["response"], "gold": int(r["label"])})
    return rows


def load_agenthallu(limit=None):
    """External AgentHallu dev subset adapted in benchmarks/agenthallu_v1 (by Codex line).
    Read-only reuse; label mapping lives in that folder's README/build script."""
    d = REPO / "benchmarks" / "agenthallu_v1" / "dev"
    gold = {}
    with open(d / "gold_binary.csv") as f:
        for row in csv.DictReader(f):
            gold[row["case_id"]] = int(row["gold_binary"])
    rows = []
    with open(d / "input.csv") as f:
        for row in csv.DictReader(f):
            if row["case_id"] in gold:
                rows.append({"id": row["case_id"], "prompt": row.get("prompt", ""),
                             "response": row.get("response", ""), "gold": gold[row["case_id"]]})
    if limit:
        rows = rows[:limit]
    return rows


def load_synthetic(split=None):
    """My own controlled pairs. split in {None,'dev','holdout'}"""
    p = EXP / "data" / "synthetic_pairs.json"
    rows = json.loads(p.read_text())
    if split:
        rows = [r for r in rows if r["split"] == split]
    return rows


def load_dataset(name):
    if name == "public46":
        return load_public46()
    if name == "agenthallu":
        return load_agenthallu()
    if name == "synth-dev":
        return load_synthetic("dev")
    if name == "synth-holdout":
        return load_synthetic("holdout")
    raise ValueError(name)


# ---------------- metrics ----------------

def prf(preds, golds):
    """preds/golds: dict id->0/1"""
    tp = fp = fn = tn = 0
    for i, g in golds.items():
        p = preds.get(i)
        if p is None:
            fn += g  # unresolved counted as 0 prediction
            continue
        if p == 1 and g == 1: tp += 1
        elif p == 1 and g == 0: fp += 1
        elif p == 0 and g == 1: fn += 1
        else: tn += 1
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "precision": round(prec, 4), "recall": round(rec, 4), "f1": round(f1, 4),
            "n": len(golds)}


def save_result(name, payload):
    p = OUTZ / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=1))
    print(f"saved {p}")
