"""C2 — REAL mutual verification and correction of two theories.

Unlike the earlier single-arbiter arbitration, both models (GLM theory-A
author and Mistral theory-B author) independently criticize EVERY
divergence, each against the ORIGINAL clause with LangExtract-anchored
fragments (the element texts are byte-exact spans of the policy).

Criticism items (mechanically derived from the two anchored theories):
  1. span-disagreements: element present in one theory only
     (existing find_disagreements output);
  2. modality conflicts: overlapping spans where the two theories assign
     different MODAL classes (prohibition / obligation / permission) —
     these change what counts as a violation.

Each item is reviewed by BOTH providers. Repair rules (conservative,
recall-preserving — a rejection of one criticism never deletes the theory
as a whole; split verdicts keep the element flagged):
  - span-disagreement: both faithful -> keep; both invented -> drop;
    split/ambiguous -> keep with flag; one side unavailable -> keep with
    unreviewed_side flag.
  - modality conflict: both prefer same side -> class corrected to that
    side's reading; split -> both elements kept, flagged; both_compatible
    (granularity difference) -> both kept.

Correction (not only keep/drop): the reviewer may output corrected_class
for an element; the repaired theory applies it with provenance.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.trace_parser import split_policy_clauses
from common.zai_client import chat, extract_json, PROVIDER_ZAI, PROVIDER_MISTRAL
from arch_c.theory import _clause_for

HERE = Path(__file__).resolve().parent
RESULTS = HERE.parent / "results"
CROSS = RESULTS / "arch_c_cross"
OUT = RESULTS / "arch_c_mutual"

MODAL_CLASSES = {"запрет", "обязанность", "разрешение"}
CLASS_RU = {
    "запрет": "prohibition (запрет)",
    "обязанность": "obligation (обязанность)",
    "разрешение": "permission (разрешение)",
    "условие": "condition (условие)",
    "исключение": "exception (исключение)",
    "порог": "threshold (порог)",
    "область": "scope (область)",
    "время": "temporal (время)",
}

REVIEW_SPAN_SYS = """Ты — строгий критик смысловых теорий политики. Тебе дают:
- ОРИГИНАЛЬНУЮ клаузу политики (полный текст предложения),
- один смысловой элемент, который присутствует ТОЛЬКО в одной из двух теорий политики,
- вопрос: действительно ли эта клауза утверждает данный элемент?

Реши: element_faithful (элемент действительно выражен в клаузе), element_invented
(клауза этого не утверждает — элемент выдуман), или ambiguous (текст допускает
оба чтения). Обязательно процитируй решающие слова оригинала (decisive_quote).
Если элемент выражен, но его КЛАСС (модальность) выбран неверно, укажи
corrected_class из списка: обязанность|запрет|разрешение|условие|исключение|порог|область|время.

Не решай по общему смыслу — только по точным словам клаузы.
Пиши JSON одной строкой, без переносов внутри строковых значений (переносы в reason
замени на пробелы).

Ответ строго JSON: {"verdict": "element_faithful|element_invented|ambiguous",
"decisive_quote": "...", "reason": "...", "corrected_class": null|"..."}"""

REVIEW_MODAL_SYS = """Ты — строгий критик смысловых теорий политики. Две теории
по-разному классифицируют ОДНУ И ТУ ЖЕ клаузу политики. Тебе дают:
- ОРИГИНАЛЬНУЮ клаузу политики (полный текст),
- элемент теории A (класс + текст),
- элемент теории B (класс + текст),
- вопрос: какую модальность клауза действительно назначает этому действию?

Варианты решения:
- prefer_a — правильна классификация теории A,
- prefer_b — правильна классификация теории B,
- both_compatible — обе корректны как разные уровни детализации (например
  запрет + обязанность = одна и та же норма с двух сторон),
- ambiguous — текст допускает оба чтения.

Обязательно процитируй решающие слова оригинала (decisive_quote). Если ни A,
ни B не точны, укажи corrected_class (обязанность|запрет|разрешение|условие|
исключение|порог|область|время).

Пиши JSON одной строкой, без переносов внутри строковых значений (переносы в reason
замени на пробелы).

Ответ строго JSON: {"verdict": "prefer_a|prefer_b|both_compatible|ambiguous",
"decisive_quote": "...", "reason": "...", "corrected_class": null|"..."}"""


def load_theories(policy_hash: str) -> tuple[list[dict], list[dict], str]:
    d = CROSS / policy_hash
    A = [e for e in json.loads((d / "theory_a_glm.json").read_text())
         if e.get("span_exact") and e.get("start") is not None]
    B = [e for e in json.loads((d / f"theory_b_{PROVIDER_MISTRAL}.json").read_text())
         if e.get("span_exact") and e.get("start") is not None]
    return A, B


def find_modality_conflicts(A: list[dict], B: list[dict]) -> list[dict]:
    """Overlapping spans where the two theories assign DIFFERENT MODAL
    classes (prohibition/obligation/permission). Granularity overlaps
    (условие/порог/область/исключение vs anything) are NOT conflicts."""
    out = []
    for a in A:
        if a["class"] not in MODAL_CLASSES:
            continue
        for b in B:
            if b["class"] not in MODAL_CLASSES:
                continue
            if a["class"] == b["class"]:
                continue
            ov = min(a["end"], b["end"]) - max(a["start"], b["start"])
            if ov > 10:
                out.append({
                    "kind": "modality_conflict",
                    "element_a": {k: a[k] for k in ("class", "text", "start", "end")},
                    "element_b": {k: b[k] for k in ("class", "text", "start", "end")},
                })
    return out


def criticism_items(policy_hash: str, policy_text: str, clauses: list[dict]) -> list[dict]:
    """All items for mutual criticism: span-disagreements + modality conflicts."""
    d = CROSS / policy_hash
    A, B = load_theories(policy_hash)
    items = []
    dis = json.loads((d / "disagreements.json").read_text()) if (d / "disagreements.json").exists() else []
    for x in dis:
        el = x["element"]
        items.append({
            "kind": "span_disagreement",
            "side": x["side"],
            "element": {k: el[k] for k in ("class", "text", "start", "end")},
            "clause": x.get("clause") or _clause_for(clauses, policy_text, el["start"], el["end"]),
        })
    for c in find_modality_conflicts(A, B):
        mid = (c["element_a"]["start"] + c["element_a"]["end"]) // 2
        c["clause"] = _clause_for(clauses, policy_text, mid - 1, mid + 1)
        items.append(c)
    return items


def _parse_review(content: str) -> dict | None:
    """Robust parse: strict JSON first, then regex fallback for the common
    broken-JSON failure mode (raw newlines inside string values)."""
    from common.zai_client import extract_json as _ej
    data = _ej(content)
    if isinstance(data, dict) and data.get("verdict"):
        return data
    m = re.search(r'"verdict"\s*:\s*"([a-z_]+)"', content)
    if not m:
        return None
    out = {"verdict": m.group(1)}
    q = re.search(r'"decisive_quote"\s*:\s*"((?:[^"\\]|\\.)*)"', content)
    if q:
        out["decisive_quote"] = q.group(1)
    c = re.search(r'"corrected_class"\s*:\s*"?([а-яё]+)"?', content)
    if c:
        out["corrected_class"] = c.group(1)
    r_ = re.search(r'"reason"\s*:\s*"((?:[^"\\]|\\.)*)"', content)
    if r_:
        out["reason"] = r_.group(1)
    return out


def review_item(item: dict, provider: str, tag: str) -> dict:
    """One provider reviews one criticism item against the ORIGINAL clause."""
    if item["kind"] == "span_disagreement":
        user = (
            "ОРИГИНАЛЬНАЯ КЛАУЗА ПОЛИТИКИ:\n" + item["clause"]
            + "\n\nЭЛЕМЕНТ ТЕОРИИ (присутствует только в теории " + item["side"] + "):\n"
            + f"class={item['element']['class']} ({CLASS_RU.get(item['element']['class'], '')})\n"
            + f"text={item['element']['text']}"
            + "\n\nВыражен ли этот элемент в оригинальной клаузе? Ответь JSON."
        )
        sysp = REVIEW_SPAN_SYS
    else:
        user = (
            "ОРИГИНАЛЬНАЯ КЛАУЗА ПОЛИТИКИ:\n" + item["clause"]
            + "\n\nЭЛЕМЕНТ ТЕОРИИ A:\n"
            + f"class={item['element_a']['class']} ({CLASS_RU.get(item['element_a']['class'], '')})\n"
            + f"text={item['element_a']['text']}"
            + "\n\nЭЛЕМЕНТ ТЕОРИИ B:\n"
            + f"class={item['element_b']['class']} ({CLASS_RU.get(item['element_b']['class'], '')})\n"
            + f"text={item['element_b']['text']}"
            + "\n\nКакую модальность назначает оригинал? Ответь JSON."
        )
        sysp = REVIEW_MODAL_SYS
    resp = chat(user=user, system=sysp, thinking=False, provider=provider,
                tag=tag, max_retries=2)
    rec = {"provider": provider, "review_ok": resp.ok, "review_error": (resp.error or "")[:200]}
    if resp.ok:
        data = _parse_review(resp.content)
        ok_verdicts = ({"element_faithful", "element_invented", "ambiguous"}
                       if item["kind"] == "span_disagreement"
                       else {"prefer_a", "prefer_b", "both_compatible", "ambiguous"})
        if data and str(data.get("verdict", "")).lower() in ok_verdicts:
            rec["verdict"] = str(data["verdict"]).lower()
            rec["decisive_quote"] = str(data.get("decisive_quote", ""))
            rec["reason"] = str(data.get("reason", ""))[:500]
            cc = data.get("corrected_class")
            rec["corrected_class"] = cc if cc in CLASS_RU else None
            # verify decisive quote against the clause
            from arch_b.fact_ledger import locate_quote
            rec["decisive_quote_found"] = locate_quote(item["clause"], rec["decisive_quote"])["found"]
        else:
            rec["review_ok"] = False
            rec["review_error"] = "bad-json"
    return rec


def build_repaired_theory(policy_hash: str, policy_text: str, clauses: list[dict],
                          reviews_by_item: dict[int, list[dict]]) -> dict:
    """Union theory after mutual criticism, with per-element provenance.

    Elements agreed by both theories (span overlap, no conflict) -> kept_agreed.
    Criticized elements per repair rules (see module docstring).
    """
    A, B = load_theories(policy_hash)
    items = criticism_items(policy_hash, policy_text, clauses)

    # index criticized elements by (side, start, end)
    criticized = {}  # (theory, start, end) -> list of review outcomes
    for i, item in enumerate(items):
        rvs = reviews_by_item.get(i, [])
        if item["kind"] == "span_disagreement":
            side = "A" if item["side"] == "A_only" else "B"
            key = (side, item["element"]["start"], item["element"]["end"])
            criticized.setdefault(key, []).append(("span", rvs))
        else:
            criticized.setdefault(("A", item["element_a"]["start"], item["element_a"]["end"]), []).append(
                ("modal", rvs, "a", item))
            criticized.setdefault(("B", item["element_b"]["start"], item["element_b"]["end"]), []).append(
                ("modal", rvs, "b", item))

    def element_status(theory: str, e: dict) -> dict:
        el = {k: e[k] for k in ("class", "text", "start", "end")}
        if "attributes" in e:
            el["attributes"] = e["attributes"]
        key = (theory, e["start"], e["end"])
        if key not in criticized:
            return {**el, "status": "kept_agreed", "theory": theory}
        entries = criticized[key]
        # collect all verdicts about this element
        verdicts, corrected = [], None
        for entry in entries:
            kind, rvs = entry[0], entry[1]
            for r in rvs:
                if not r.get("review_ok"):
                    continue
                if kind == "span":
                    verdicts.append(("span", r["verdict"]))
                    if r.get("corrected_class"):
                        corrected = r["corrected_class"]
                else:
                    side_of_elem = entry[2]
                    v = r["verdict"]
                    if v == f"prefer_{side_of_elem}":
                        verdicts.append(("span", "element_faithful"))
                    elif v == f"prefer_{'b' if side_of_elem == 'a' else 'a'}":
                        verdicts.append(("span", "element_invented"))
                    else:
                        verdicts.append(("span", "ambiguous"))
                    if r.get("corrected_class"):
                        corrected = r["corrected_class"]
        if not verdicts:
            return {**el, "status": "unreviewed_side_missing", "theory": theory}
        vs = {v for _, v in verdicts}
        n_sides = len({r.get("provider") for r in rvs_all if r.get("review_ok")}) if (rvs_all := entries[0][1]) else 0
        both_sides = n_sides >= 2
        if vs == {"element_faithful"}:
            out = {**el, "status": "kept_after_review", "theory": theory}
        elif vs == {"element_invented"} and both_sides:
            # BOTH sides concede the element is invented -> drop
            out = {**el, "status": "dropped_invented", "theory": theory}
        elif vs == {"element_invented"}:
            # only one side reviewed and rejected -> keep, challenged
            # (a one-sided rejection never deletes; recall-preserving)
            out = {**el, "status": "challenged_one_sided", "theory": theory}
        else:
            out = {**el, "status": "ambiguous_kept", "theory": theory}
        if corrected:
            if both_sides or len(entries) == 0:
                out["corrected_class"] = corrected
                out["class_original"] = out["class"]
                out["class"] = corrected
            else:
                out["corrected_class_proposed"] = corrected
        return out

    elements = [element_status("A", e) for e in A] + [element_status("B", e) for e in B]
    return {
        "policy_hash": policy_hash,
        "n_source_a": len(A),
        "n_source_b": len(B),
        "elements": elements,
        "n_items": len(items),
        "status_counts": {},
    }


def run(providers: list[str], max_seconds: float = 600, only_missing: bool = True) -> None:
    """Run mutual reviews for all policies, all items, given providers.
    Incrementally persisted per (policy, item, provider)."""
    import time
    from common.trace_parser import parse_trace

    t0 = time.time()
    # recover policy texts from the synth dataset (first case per hash)
    data_f = HERE.parent / "data" / "synth_pairs" / "synth_pairs_v1.jsonl"
    pol_by_hash = {}
    import hashlib
    for line in data_f.open(encoding="utf-8"):
        r = json.loads(line)
        t = parse_trace(r["prompt"], r["response"])
        h = hashlib.sha256(t.policy_text.encode()).hexdigest()[:10]
        if h not in pol_by_hash:
            pol_by_hash[h] = (t.policy_text, r.get("domain", ""))

    for h in sorted(pol_by_hash):
        pol, domain = pol_by_hash[h]
        clauses = split_policy_clauses(pol)
        items = criticism_items(h, pol, clauses)
        out_dir = OUT / h
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "items.json").write_text(json.dumps(items, ensure_ascii=False, indent=1))
        print(f"=== {h} ({domain}): {len(items)} criticism items", flush=True)
        for i, item in enumerate(items):
            for prov in providers:
                rf = out_dir / f"item{i:02d}_{prov}.json"
                if rf.exists() and only_missing:
                    continue
                if time.time() - t0 > max_seconds:
                    print("[mutual] time budget reached", flush=True)
                    return
                rec = review_item(item, prov, tag=f"CM/{h}/i{i}/{prov}")
                rf.write_text(json.dumps(rec, ensure_ascii=False, indent=1))
                print(f"  item{i} {prov}: ok={rec['review_ok']} "
                      f"verdict={rec.get('verdict')} quote_found={rec.get('decisive_quote_found')}",
                      flush=True)


def finalize() -> None:
    """Combine reviews into repaired theories for all policies."""
    from common.trace_parser import parse_trace
    data_f = HERE.parent / "data" / "synth_pairs" / "synth_pairs_v1.jsonl"
    pol_by_hash = {}
    import hashlib
    for line in data_f.open(encoding="utf-8"):
        r = json.loads(line)
        t = parse_trace(r["prompt"], r["response"])
        h = hashlib.sha256(t.policy_text.encode()).hexdigest()[:10]
        if h not in pol_by_hash:
            pol_by_hash[h] = (t.policy_text, r.get("domain", ""))

    for h in sorted(pol_by_hash):
        pol, domain = pol_by_hash[h]
        clauses = split_policy_clauses(pol)
        items = criticism_items(h, pol, clauses)
        out_dir = OUT / h
        reviews_by_item = {}
        for i in range(len(items)):
            rvs = []
            for prov in (PROVIDER_MISTRAL, PROVIDER_ZAI):
                rf = out_dir / f"item{i:02d}_{prov}.json"
                if rf.exists():
                    rvs.append(json.loads(rf.read_text()))
            reviews_by_item[i] = rvs
        repaired = build_repaired_theory(h, pol, clauses, reviews_by_item)
        from collections import Counter
        repaired["status_counts"] = dict(Counter(e["status"] for e in repaired["elements"]))
        repaired["domain"] = domain
        (out_dir / "repaired_theory.json").write_text(
            json.dumps(repaired, ensure_ascii=False, indent=1))
        print(f"{h} ({domain}): " + json.dumps(repaired["status_counts"]), flush=True)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--providers", default=PROVIDER_MISTRAL,
                    help="comma-separated: mistral,zai")
    ap.add_argument("--max-seconds", type=float, default=600)
    ap.add_argument("--finalize", action="store_true")
    args = ap.parse_args()
    if args.finalize:
        finalize()
    else:
        run([p.strip() for p in args.providers.split(",")], max_seconds=args.max_seconds)
