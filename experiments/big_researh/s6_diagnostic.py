#!/usr/bin/env python3
"""BIG_RESEARH S6 diagnostic (no GPU, no new LLM calls).

Part 1: Mistral API availability — programmatic check through existing code
        paths (job env, secrets file, repo client config). No secret printed.
Part 2: quality analysis of existing extraction records: dedup, classes,
        span validity, provenance regions (via event source offsets),
        new-vs-graph honesty check.
Part 3: FN/FP diagnostic set selection from the frozen control per-case file.
"""
from __future__ import annotations

import csv
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

REPO = Path("/mnt/data/guardian/agent-workspace/Guardian-big-researh")
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "experiments" / "full21"))
sys.path.insert(0, str(REPO / "experiments" / "superz_fullcycle"))

from guardian_truth.parsing import parse_events  # noqa: E402
from run_granite_modes import read_cases  # noqa: E402

OUT = REPO / "outputs" / "big_researh" / "s6_diagnostic"
OUT.mkdir(parents=True, exist_ok=True)

# ============================== PART 1 ==============================
print("=" * 72)
print("PART 1: Mistral API availability (programmatic, values never printed)")
api = {}
api["job_env_has_MISTRAL_API_KEY"] = "MISTRAL_API_KEY" in os.environ
api["job_env_mistral_vars"] = sorted(k for k in os.environ if "MISTRAL" in k.upper())
try:
    with open("/mnt/data/guardian/secrets/mistral.env", "rb") as f:
        f.read(1)
    api["secrets_file_readable"] = True
except PermissionError:
    api["secrets_file_readable"] = False
    api["secrets_error"] = "PermissionError (dir root:root 0700, job runs as guardianagent)"
except FileNotFoundError:
    api["secrets_file_readable"] = False
    api["secrets_error"] = "FileNotFoundError"

llm_src = (REPO / "src" / "guardian_truth" / "llm_client.py").read_text(errors="replace")
api["repo_llm_client_reads_env_var"] = bool(re.search(r'api_key_env|MISTRAL_API_KEY', llm_src))
gw_src = Path("/mnt/data/guardian/gateway-system/worker.py")
api["gateway_jobs_support_env_injection"] = False
if gw_src.exists():
    w = gw_src.read_text(errors="replace")
    api["gateway_jobs_support_env_injection"] = bool(re.search(r'request\.get\("env"\)', w))

api["conclusion"] = (
    "Mistral API is NOT reachable through the sanctioned execution channel: "
    "no MISTRAL_API_KEY in the job environment, the secrets file is root-only "
    "(PermissionError for guardianagent), and the Gateway jobs API has no "
    "env-injection parameter. Previous agents hit the same wall (CONTROL.md) and "
    "already downloaded mistral-7b-instruct-v0.3 as the declared substitute "
    "channel; that existing local server is what S6 uses. No new model download."
)
for k, v in api.items():
    print(f"  {k}: {v}")
print()

# ============================== PART 2 ==============================
print("=" * 72)
print("PART 2: existing extraction records — quality analysis")
cases = {c["id"]: c for c in read_cases(REPO / "outputs/full21/input/public46_label_free.csv")}
recs = [json.loads(l) for l in open(
    REPO / "outputs/full21/s6_langextract/records.jsonl", encoding="utf-8")]


def norm(t: str) -> str:
    return re.sub(r"\s+", " ", (t or "")).strip().lower()


def regions_for(case):
    """Map char offsets of the truncated prompt to document regions."""
    prompt = case["prompt"][:48000]
    events = parse_events(case["prompt"], "prompt")
    regions = []
    for e in events:
        if e.source.end <= len(prompt):
            label = {"system": "policy/system-instructions", "user": "user-message"}.get(
                e.role, e.role)
            if e.kind == "call":
                label = "tool-call"
            elif e.kind == "result":
                label = "tool-result"
            elif e.kind == "text" and e.role == "assistant":
                label = "assistant-text"
            regions.append((e.source.start, e.source.end, label))
    m = re.search(r"<policy>.*?</policy>", prompt, re.DOTALL)
    if m:
        regions.insert(0, (m.start(), m.end(), "policy-tagged"))
    return regions


def region_of(start, regions):
    for s, t, label in regions:
        if s <= start < t:
            return label
    return "unmapped"


quality = []
for rec in recs:
    cid = rec["id"]
    case = cases[cid]
    exts = rec.get("extractions", [])
    span_ok_exts = [e for e in exts if e.get("span_ok")]
    new_exts = [e for e in exts if e.get("is_new_vs_graph")]

    texts_norm = [norm(e.get("text")) for e in exts]
    uniq = set(texts_norm)
    dup_within = len(texts_norm) - len(uniq)
    by_text = {}
    for e in exts:
        by_text.setdefault(norm(e.get("text")), set()).add(e.get("class"))
    cross_class = sum(1 for v in by_text.values() if len(v) > 1)

    classes = Counter(e.get("class") for e in exts)
    regions = regions_for(case)
    prov = Counter(region_of(e.get("start", -1), regions) for e in span_ok_exts)
    prov_new = Counter(region_of(e.get("start", -1), regions) for e in new_exts)

    q = {
        "id": cid, "latency_s": rec.get("latency_s"),
        "n_extractions": len(exts), "n_span_ok": len(span_ok_exts),
        "span_validity_rate": round(len(span_ok_exts) / max(1, len(exts)), 3),
        "n_new_vs_graph": len(new_exts),
        "n_unique_texts": len(uniq), "n_dup_within_case": dup_within,
        "n_texts_in_multiple_classes": cross_class,
        "classes": dict(classes),
        "span_ok_by_region": dict(prov),
        "new_by_region": dict(prov_new),
    }
    quality.append(q)
    print(f"  {cid}: extr={q['n_extractions']} span_ok={q['n_span_ok']} "
          f"({q['span_validity_rate']:.0%}) new={q['n_new_vs_graph']} "
          f"uniq={q['n_unique_texts']} dup={q['n_dup_within_case']} "
          f"cross-class={q['n_texts_in_multiple_classes']} lat={q['latency_s']}s")
    print(f"    classes: {dict(classes)}")
    print(f"    span_ok regions: {dict(prov)}")
    print(f"    NEW regions:     {dict(prov_new)}")

print()
print("  Over-extraction assessment (319 extr/case treated as suspect):")
for q in quality:
    rate = q["span_validity_rate"]
    print(f"    {q['id']}: span-valid only {rate:.0%}; duplicates {q['n_dup_within_case']}; "
          f"cross-class repeats {q['n_texts_in_multiple_classes']} -> "
          f"usable signal is roughly span_ok & unique ≈ "
          f"{q['n_span_ok'] - q['n_dup_within_case']}")
print()

# ============================== PART 3 ==============================
print("=" * 72)
print("PART 3: FN/FP diagnostic set (frozen control per-case)")
gold, granite, baseline = {}, {}, {}
for row in csv.DictReader(open(REPO / "outputs/full21/control_repro_percase.csv")):
    gold[row["id"]] = int(row["gold"])
    granite[row["id"]] = int(row["granite_repro"])
    baseline[row["id"]] = int(row["baseline"])

fps = [cid for cid in gold if granite[cid] == 1 and gold[cid] == 0]
fns = [cid for cid in gold if granite[cid] == 0 and gold[cid] == 1]
print(f"  control granite FP cases ({len(fps)}): {fps}")
print(f"  control granite FN cases ({len(fns)}): {fns}")

done_ids = {r["id"] for r in recs}
prefer_fn = [c for c in fns if any(k in c for k in (
    "airline__9", "task_003", "retail__27", "t27", "service_issue"))]
diag = []
for c in fps:
    if c not in done_ids and len(diag) < 2:
        diag.append(c)
for c in prefer_fn:
    if c not in done_ids and c not in diag and len(diag) < 6:
        diag.append(c)
for c in fns:
    if c not in done_ids and c not in diag and len(diag) < 6:
        diag.append(c)
tn_contrast = [c for c in gold if granite[c] == 0 and gold[c] == 0 and c not in done_ids]
if tn_contrast:
    diag.append(tn_contrast[0])
print(f"  diagnostic set ({len(diag)}): {diag}")

(OUT / "api_check.json").write_text(json.dumps(api, ensure_ascii=False, indent=1))
(OUT / "records_quality.json").write_text(json.dumps(quality, ensure_ascii=False, indent=1))
(OUT / "diagnostic_set.json").write_text(json.dumps(
    {"fp_cases": fps, "fn_cases": fns, "diagnostic_set": diag}, indent=1))
print(f"\n  artifacts -> {OUT}")
