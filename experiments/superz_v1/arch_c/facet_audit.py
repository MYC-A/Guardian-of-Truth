"""Semantic facet preservation audit for Architecture C.

Measures whether the theory variants (C0/C1/C2) PRESERVE the semantic
content of the original policy along the facets the user named:
  modality (модальность), conditions (условия), exceptions (исключения),
  participants (участники действия), temporal constraints (временные
  ограничения), scope (область действия) — plus thresholds (порог), the
  theory class the pipeline itself uses.

Two independent stages:
  1. REFERENCE extraction — facets are extracted from the ORIGINAL policy
     text withOUT seeing any theory (independent discovery; quotes verified
     against the source). Both providers run this independently; the
     reference used for auditing is the UNION of both providers' facets
     (dedup by quote overlap) so neither model's blind spots define the
     reference.
  2. THEORY audit — for each variant theory, an LLM judges, facet by facet,
     whether some theory element captures that facet's information
     (semantic containment, not string equality).

Output: preservation matrix variant x facet_type (captured / total),
per policy and aggregated. Facet loss between C1 and C2 (e.g. elements
dropped by mutual criticism that carried real facets) is exactly the
"lost semantic content" the user wants measured.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.zai_client import chat, extract_json, PROVIDER_MISTRAL, PROVIDER_ZAI
from arch_b.fact_ledger import locate_quote

HERE = Path(__file__).resolve().parent
RESULTS = HERE.parent / "results"
OUT = RESULTS / "arch_c_facets"

FACET_TYPES = ["модальность", "условие", "исключение", "участник", "время", "область", "порог"]

FACET_SYS = """Ты — независимый аналитик нормативных документов. Извлеки из
текста политики СМЫСЛОВЫЕ ГРАНИ каждого правила, НЕ интерпретируя, а только
грунтуясь в точных словах оригинала.

Типы граней:
- модальность — какое предписание вводит правило (запрет / обязанность / разрешение / требование подтверждения);
- условие — условие применимости (if / only if / при условии);
- исключение — случай, когда правило НЕ действует (except / unless / кроме);
- участник — субъект или объект действия (кто делает / над чем; клиент, менеджер, оператор, агент);
- время — временное или порядковое ограничение (в течение N дней, только один раз, до истечения);
- область — область действия правила (для каких операций/тарифов/типов обращений);
- порог — числовой порог применимости (свыше N, до N).

Для каждой грани скопируй ТОЧНЫЙ фрагмент оригинала (quote), по которому она
установлена. Одно правило может давать несколько граней. Не выдумывай грани,
которых нет в тексте.

Ответ строго JSON одной строкой (переносы в строках замени пробелами):
{"facets": [{"rule": "<краткое имя правила>", "type": "модальность|условие|исключение|участник|время|область|порог", "quote": "<точный фрагмент>", "note": "<одно предложение>"}]}"""

AUDIT_SYS = """Ты — аудитор полноты смысловой теории. Тебе дают:
- список ГРАНЕЙ политики, извлечённых независимо из оригинала (type + quote),
- ТЕОРИЮ политики: пронумерованный список элементов (класс + точная цитата).

Для КАЖДОЙ грани реши: передана ли информация этой грани каким-либо элементом
теории (семантически — не обязательно дословно)? Если да — укажи index элемента.
Если информация грани искажена или потеряна — captured=false и объясни что именно
потеряно (lost: "...").

Ответ строго JSON одной строкой:
{"audits": [{"facet": 0, "captured": true, "element_index": 3, "lost": null},
            {"facet": 1, "captured": false, "element_index": null, "lost": "исключение для уже проверенных клиентов"}]}"""


def _verify_quote(policy_text: str, quote: str) -> dict:
    """Locate quote with emphasis-marker tolerance: models add **bold**
    markers absent from the source; strip them from the query before
    matching (source is matched as-is, plus a stripped fallback)."""
    import re as _re
    loc = locate_quote(policy_text, quote)
    if loc["found"]:
        return loc
    stripped = _re.sub(r"[*`]", "", quote)
    stripped = _re.sub(r"\s+", " ", stripped).strip()
    if not stripped or len(stripped) < 6:
        return loc
    # scan source with emphasis stripped, then confirm the span exists
    src_stripped = _re.sub(r"[*`]", "", policy_text)
    if stripped.lower() in _re.sub(r"\s+", " ", src_stripped).lower():
        return {"found": True, "method": "emphasis-normalized"}
    return loc


def extract_facets(policy_text: str, provider: str, tag: str) -> list[dict]:
    """Independent facet extraction from the ORIGINAL policy (no theory)."""
    user = "ТЕКСТ ПОЛИТИКИ:\n" + policy_text + "\n\nИзвлеки смысловые грани. JSON одной строкой."
    resp = chat(user=user, system=FACET_SYS, thinking=False, provider=provider,
                tag=tag, max_retries=2)
    if not resp.ok:
        return []
    data = extract_json(resp.content)
    facets = data.get("facets") if isinstance(data, dict) else None
    if not facets:
        import re
        # fallback: line-by-line JSON objects
        facets = []
        for m in re.finditer(r'\{[^{}]*"type"[^{}]*\}', resp.content):
            try:
                obj = json.loads(m.group(0).replace("'", '"'))
                if "quote" in obj:
                    facets.append(obj)
            except json.JSONDecodeError:
                continue
    out = []
    for f in facets:
        if not isinstance(f, dict) or f.get("type") not in FACET_TYPES:
            continue
        q = str(f.get("quote", ""))
        if not q:
            continue
        loc = _verify_quote(policy_text, q)
        out.append({
            "rule": str(f.get("rule", ""))[:80],
            "type": f["type"],
            "quote": q,
            "note": str(f.get("note", ""))[:200],
            "quote_verified": bool(loc["found"]),
        })
    return out


def union_facets(facets_a: list[dict], facets_b: list[dict]) -> list[dict]:
    """Union of two providers' facet lists, dedup by quote overlap."""
    out = list(facets_a)
    for b in facets_b:
        dup = any(
            a["type"] == b["type"]
            and any(w in a["quote"] for w in b["quote"].split()[:4] if len(w) > 4)
            for a in out
        )
        if not dup:
            out.append(b)
    return out


def audit_theory(facets: list[dict], elements: list[dict], provider: str, tag: str) -> list[dict]:
    """Judge facet-by-facet whether the theory preserves each facet."""
    f_lines = [
        f"[{i}] ({f['type']}) правило={f['rule']} | цитата: {f['quote']}"
        for i, f in enumerate(facets)
    ]
    e_lines = [f"[{i}] ({e['class']}) {e['text']}" for i, e in enumerate(elements)]
    user = (
        "ГРАНИ ПОЛИТИКИ (извлечены независимо из оригинала):\n" + "\n".join(f_lines)
        + "\n\nТЕОРИЯ ПОЛИТИКИ:\n" + "\n".join(e_lines)
        + "\n\nАудируй каждую грань. JSON одной строкой."
    )
    resp = chat(user=user, system=AUDIT_SYS, thinking=False, provider=provider,
                tag=tag, max_retries=2)
    if not resp.ok:
        return []
    data = extract_json(resp.content)
    audits = data.get("audits") if isinstance(data, dict) else None
    if not isinstance(audits, list):
        return []
    out = []
    for a in audits:
        if not isinstance(a, dict):
            continue
        try:
            fi = int(a.get("facet", -1))
        except (TypeError, ValueError):
            continue
        if not (0 <= fi < len(facets)):
            continue
        ei = a.get("element_index")
        try:
            ei = int(ei) if ei is not None else None
        except (TypeError, ValueError):
            ei = None
        out.append({
            "facet": fi,
            "facet_type": facets[fi]["type"],
            "captured": bool(a.get("captured")),
            "element_index": ei if (ei is not None and 0 <= ei < len(elements)) else None,
            "lost": a.get("lost"),
        })
    return out


def preservation_summary(facets: list[dict], audits: list[dict]) -> dict:
    by_type: dict[str, dict[str, int]] = {}
    for a in audits:
        t = a["facet_type"]
        d = by_type.setdefault(t, {"total": 0, "captured": 0})
        d["total"] += 1
        d["captured"] += bool(a["captured"])
    return {
        "n_facets": len(facets),
        "n_audited": len(audits),
        "n_verified_quotes": sum(1 for f in facets if f["quote_verified"]),
        "by_type": {
            t: {"captured": d["captured"], "total": d["total"],
                "rate": round(d["captured"] / d["total"], 4) if d["total"] else None}
            for t, d in sorted(by_type.items())
        },
        "overall_rate": round(
            sum(a["captured"] for a in audits) / len(audits), 4) if audits else None,
    }


def run_reference(providers: list[str]) -> None:
    """Stage 1: independent facet extraction per policy per provider."""
    import hashlib
    from common.trace_parser import parse_trace
    data_f = HERE.parent / "data" / "synth_pairs" / "synth_pairs_v1.jsonl"
    pol_by_hash = {}
    for line in data_f.open(encoding="utf-8"):
        r = json.loads(line)
        t = parse_trace(r["prompt"], r["response"])
        h = hashlib.sha256(t.policy_text.encode()).hexdigest()[:10]
        if h not in pol_by_hash:
            pol_by_hash[h] = (t.policy_text, r.get("domain", ""))
    for h in sorted(pol_by_hash):
        pol, domain = pol_by_hash[h]
        out_dir = OUT / h
        out_dir.mkdir(parents=True, exist_ok=True)
        for prov in providers:
            f = out_dir / f"facets_{prov}.json"
            if f.exists():
                continue
            fc = extract_facets(pol, prov, tag=f"FAC/{h}/{prov}")
            f.write_text(json.dumps(fc, ensure_ascii=False, indent=1))
            print(f"{h} ({domain}) {prov}: {len(fc)} facets, "
                  f"{sum(1 for x in fc if x['quote_verified'])} quote-verified", flush=True)


def run_audit(variants: list[str], provider: str) -> None:
    """Stage 2: audit each variant theory against the union reference."""
    import hashlib
    from common.trace_parser import parse_trace
    from arch_c.theory_case import load_variant_theory
    data_f = HERE.parent / "data" / "synth_pairs" / "synth_pairs_v1.jsonl"
    pol_by_hash = {}
    for line in data_f.open(encoding="utf-8"):
        r = json.loads(line)
        t = parse_trace(r["prompt"], r["response"])
        h = hashlib.sha256(t.policy_text.encode()).hexdigest()[:10]
        if h not in pol_by_hash:
            pol_by_hash[h] = (t.policy_text, r.get("domain", ""))
    summary = []
    for h in sorted(pol_by_hash):
        domain = pol_by_hash[h][1]
        out_dir = OUT / h
        fa = out_dir / f"facets_{PROVIDER_MISTRAL}.json"
        fb = out_dir / f"facets_{PROVIDER_ZAI}.json"
        if fa.exists() and fb.exists():
            facets = union_facets(json.loads(fa.read_text()), json.loads(fb.read_text()))
        elif fa.exists():
            facets = json.loads(fa.read_text())
        else:
            print(f"{h}: no reference facets yet", flush=True)
            continue
        (out_dir / "facets_union.json").write_text(json.dumps(facets, ensure_ascii=False, indent=1))
        for v in variants:
            f = out_dir / f"audit_{v}_{provider}.json"
            if f.exists():
                audits = json.loads(f.read_text())
            else:
                elements = load_variant_theory(h, v)
                audits = audit_theory(facets, elements, provider, tag=f"FAC/{h}/{v}")
                f.write_text(json.dumps(audits, ensure_ascii=False, indent=1))
            s = {"policy": h, "domain": domain, "variant": v,
                 **preservation_summary(facets, audits)}
            summary.append(s)
            print(f"{h} {v}: overall={s['overall_rate']} by_type=" +
                  json.dumps({t: d['rate'] for t, d in s['by_type'].items()},
                             ensure_ascii=False), flush=True)
    (OUT / "preservation_matrix.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", choices=["reference", "audit"], default="reference")
    ap.add_argument("--providers", default=PROVIDER_MISTRAL)
    ap.add_argument("--variants", default="C0,C1,C2")
    ap.add_argument("--audit-provider", default=PROVIDER_MISTRAL)
    args = ap.parse_args()
    if args.stage == "reference":
        run_reference([p.strip() for p in args.providers.split(",")])
    else:
        run_audit([v.strip() for v in args.variants.split(",")], args.audit_provider)
