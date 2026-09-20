"""Architecture C — joint policy-theory construction and verification.

Pipeline:
  C0: single LLM theory of the policy (structured, LangExtract-anchored)
  C1: two INDEPENDENT extractions with different personas
      (A: normative-complete; B: permissive-adversarial)
  C2: clause coverage registry — every policy clause must be accounted
      for by an anchored element; uncovered clauses trigger one targeted
      re-extraction
  C3: mutual review of disagreements — each element present in one theory
      but absent in the other is challenged against the ORIGINAL clause;
      the reviewer must cite decisive source words
  C4: repaired union theory with provenance of every change

All elements carry byte-exact source spans (verified). Elements that fail
span verification are dropped with UNANCHORED status (never silently kept).
"""
from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.trace_parser import Trace, parse_trace, split_policy_clauses
from common.langextract_zai import run_langextract, extractions_to_records
from common.zai_client import chat, extract_json

HERE = Path(__file__).resolve().parent
RESULTS = HERE.parent / "results" / "arch_c"

PERSONA_A = (
    "Извлеки из текста ВСЕ нормативные элементы политики агента: обязанности "
    "(agent must), запреты (agent must not / prohibited), разрешения (may / can), "
    "условия применения (if / when / only if), исключения (unless / except), "
    "пороговые значения (свыше/более N), область действия (scope: для каких операций "
    "или сущностей), временные и порядковые ограничения (before / after / only once). "
    "Для каждого элемента скопируй точный фрагмент исходного текста. Класс элемента "
    "обязателен: обязанность|запрет|разрешение|условие|исключение|порог|область|время. "
    "В атрибуте action укажи затрагиваемое действие (refund, block, cancel, ...)."
)

PERSONA_B = (
    "Ты — адверсарный экстрактор: найди все фрагменты политики, которые ОГРАНИЧИВАЮТ "
    "применимость строгих правил — исключения (unless, except, кроме случаев), "
    "смягчающие условия (if already, only if, provided that), пороги применимости "
    "(свыше N, до N), случаи когда действие РАЗРЕШЕНО или НЕ требует дополнительного "
    "подтверждения. Также извлеки строгие запреты и обязанности, но главное — всё, "
    "что может оправдать действие агента. Копируй точные фрагменты исходного текста. "
    "Классы: обязанность|запрет|разрешение|условие|исключение|порог|область|время."
)

# Example pair teaching the exception class with anchors
from langextract.core import data as lx_data

LX_EXAMPLES_A = [
    lx_data.ExampleData(
        text=(
            "Правила обработки возвратов.\n"
            "Возврат средств запрещён без проверки личности, кроме случаев, когда "
            "клиент уже прошёл проверку в текущем обращении.\n"
            "Для возвратов свыше 10 000 рублей требуется подтверждение руководителя."
        ),
        extractions=[
            lx_data.Extraction(
                extraction_class="запрет",
                extraction_text="Возврат средств запрещён без проверки личности",
                attributes={"action": "refund"},
            ),
            lx_data.Extraction(
                extraction_class="исключение",
                extraction_text="кроме случаев, когда клиент уже прошёл проверку в текущем обращении",
                attributes={"action": "refund"},
            ),
            lx_data.Extraction(
                extraction_class="условие",
                extraction_text="Для возвратов свыше 10 000 рублей требуется подтверждение руководителя",
                attributes={"action": "refund"},
            ),
            lx_data.Extraction(
                extraction_class="порог",
                extraction_text="свыше 10 000 рублей",
                attributes={"action": "refund"},
            ),
        ],
    )
]


def extract_theory(policy_text: str, persona: str, examples, tag_prefix: str) -> tuple[list[dict], int]:
    """Run LangExtract with a persona; verify all spans byte-exact."""
    result, n_calls = run_langextract(
        policy_text,
        prompt_description=persona,
        examples=examples,
        max_char_buffer=2000,
        tag_prefix=tag_prefix,
    )
    recs = extractions_to_records(result, policy_text)
    # keep only span-verified elements
    verified = []
    for r in recs:
        if r.get("span_exact"):
            verified.append(r)
        else:
            verified.append({**r, "dropped_unanchored": True})
    return verified, n_calls


def clause_coverage(clauses: list[dict], elements: list[dict]) -> dict:
    """Coverage over NORMATIVE clauses (non-policy lines accounted separately)."""
    anchored = [e for e in elements if not e.get("dropped_unanchored") and e.get("start") is not None]
    registry = []
    n_norm = n_norm_cov = n_nonpol = 0
    for c in clauses:
        covered = [e for e in anchored if e["start"] < c["end"] and e["end"] > c["start"]]
        kind = c.get("clause_kind", "normative")
        if kind == "non_policy":
            n_nonpol += 1
        else:
            n_norm += 1
            n_norm_cov += bool(covered)
        registry.append(
            {
                "clause_start": c["start"],
                "clause_end": c["end"],
                "clause_text": c["text"][:120],
                "clause_kind": kind,
                "covered": bool(covered),
                "covering_classes": [e["class"] for e in covered],
            }
        )
    return {
        "n_clauses": len(registry),
        "n_covered": sum(1 for r in registry if r["covered"]),
        "n_normative": n_norm,
        "n_normative_covered": n_norm_cov,
        "normative_coverage": (n_norm_cov / n_norm) if n_norm else 0.0,
        "n_non_policy": n_nonpol,
        "registry": registry,
    }


def _clause_for(clauses, policy_text: str, start: int, end: int) -> str:
    """Full SENTENCE context containing [start, end): extend the clause line
    to sentence boundaries (line-wrapped sentences must not be split)."""
    # containing clause
    base = None
    for c in clauses:
        if start < c["end"] and end > c["start"]:
            base = c
            break
    if base is None:
        return policy_text[max(0, start - 200) : end + 200]
    # extend backward to the previous sentence end or paragraph start
    s = base["start"]
    while s > 0:
        prev = policy_text[max(0, s - 200) : s]
        m = None
        for m in re.finditer(r"[.!?]\s", prev):
            pass
        if m:
            s = max(0, s - 200) + m.end()
            break
        s = max(0, s - 200)
        if s == 0:
            break
    # extend forward to the next sentence end
    e = base["end"]
    while e < len(policy_text):
        nxt = policy_text[e : e + 300]
        m = re.search(r"[.!?](\s|$)", nxt)
        if m:
            e = e + m.end()
            break
        e += 300
    return policy_text[s:e].strip()


def find_disagreements(theory_a: list[dict], theory_b: list[dict], clauses: list[dict],
                       policy_text: str = "") -> list[dict]:
    """Elements of A not matched by any anchored element of B (span-overlap
    with same 'hard' class) and vice versa. Restrict to normative classes."""
    HARD = {"запрет", "обязанность", "исключение", "условие", "порог"}
    a_el = [e for e in theory_a if not e.get("dropped_unanchored") and e.get("start") is not None and e["class"] in HARD]
    b_el = [e for e in theory_b if not e.get("dropped_unanchored") and e.get("start") is not None and e["class"] in HARD]
    disagreements = []

    def _clause_for_se(start, end):
        return _clause_for(clauses, policy_text, start, end) if policy_text else (
            next((c["text"] for c in clauses if start < c["end"] and end > c["start"]), "")
        )

    for e in a_el:
        match = [x for x in b_el if x["start"] < e["end"] and x["end"] > e["start"]]
        if not match:
            disagreements.append(
                {
                    "side": "A_only",
                    "element": {k: e[k] for k in ("class", "text", "start", "end")},
                    "clause": _clause_for_se(e["start"], e["end"])[:400],
                }
            )
    for e in b_el:
        match = [x for x in a_el if x["start"] < e["end"] and x["end"] > e["start"]]
        if not match:
            disagreements.append(
                {
                    "side": "B_only",
                    "element": {k: e[k] for k in ("class", "text", "start", "end")},
                    "clause": _clause_for_se(e["start"], e["end"])[:400],
                }
            )
    return disagreements


REVIEW_SYS = """Ты — арбитр смысловых теорий политики. Тебе дают:
- ОРИГИНАЛЬНУЮ клаузу политики (полный текст),
- один смысловой элемент, который извлечён только первой теорией (или только второй),
- вопрос: является ли этот элемент реальным нормативным содержанием этой клаузы?

Реши: element_faithful (элемент действительно выражен в клаузе), element_invented
(клауза этого не утверждает), или ambiguous (текст допускает оба чтения).
Обязательно процитируй решающие слова оригинала (decisive_quote), подтверждающие
твоё решение. Не решай по общему смыслу — только по точным словам.

Ответ строго JSON: {"verdict": "element_faithful|element_invented|ambiguous",
"decisive_quote": "...", "reason": "..."}"""


def review_disagreements(disagreements: list[dict], tag_prefix: str, workers: int = 2) -> list[dict]:
    """LLM arbitration of each disagreement against the ORIGINAL clause."""
    import concurrent.futures

    out = []

    def one(d):
        user = (
            "ОРИГИНАЛЬНАЯ КЛАУЗА ПОЛИТИКИ:\n" + d["clause"]
            + "\n\nЭЛЕМЕНТ ТЕОРИИ (side=" + d["side"] + "):\n"
            + f"class={d['element']['class']}, text={d['element']['text']}"
            + "\n\nЕсть ли этот элемент в оригинале? Ответь JSON."
        )
        resp = chat(user=user, system=REVIEW_SYS, thinking=True, tag=f"{tag_prefix}/rev")
        rec = {**d, "review_ok": resp.ok, "review_error": resp.error}
        if resp.ok:
            data = extract_json(resp.content)
            if data and str(data.get("verdict", "")).lower() in (
                "element_faithful", "element_invented", "ambiguous"
            ):
                rec["verdict"] = str(data["verdict"]).lower()
                rec["decisive_quote"] = data.get("decisive_quote", "")
                rec["reason"] = data.get("reason", "")
                # verify the decisive quote against the clause
                from arch_b.fact_ledger import locate_quote
                loc = locate_quote(d["clause"], rec["decisive_quote"])
                rec["decisive_quote_found"] = loc["found"]
            else:
                rec["review_ok"] = False
                rec["review_error"] = "bad-json"
        return rec

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        for rec in ex.map(one, disagreements):
            out.append(rec)
    return out


def repair_theory(theory_a, theory_b, reviews) -> dict:
    """Union theory after arbitration:
    - A_only elements with verdict element_faithful -> keep (B missed it)
    - A_only with element_invented -> drop (A hallucinated)
    - B_only faithful -> keep (A missed it)
    - ambiguous -> keep with ambiguity flag (both readings allowed)
    - unreviewed (call failed) -> keep with unreviewed flag (conservative)
    """
    keep, dropped, ambiguous, unreviewed = [], [], [], []
    for r in reviews:
        el = r["element"]
        v = r.get("verdict")
        entry = {**el, "side": r["side"], "verdict": v}
        if not r.get("review_ok"):
            entry["flag"] = "unreviewed"
            unreviewed.append(entry)
        elif v == "element_faithful":
            entry["flag"] = "kept_after_review"
            keep.append(entry)
        elif v == "element_invented":
            entry["flag"] = "dropped_invented"
            dropped.append(entry)
        else:
            entry["flag"] = "ambiguous_both_readings"
            ambiguous.append(entry)
    return {
        "kept": keep,
        "dropped_invented": dropped,
        "ambiguous": ambiguous,
        "unreviewed": unreviewed,
    }
