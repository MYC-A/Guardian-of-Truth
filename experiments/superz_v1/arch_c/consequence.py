"""C3 — consequence checking of the formalized theory.

Experimental mode requested by the user: after mutual criticism, build
CONTROL SITUATIONS in which the theories diverge, or which are grounded in
independently discovered semantic facets of the original. For each control
situation we check TWO things SEPARATELY:

  1. FORMAL side: what does the FORMALIZED theory output? The rule element
     is formalized into the same typed template used everywhere (arch_d
     machinery), the situation's world facts act as the observable fields,
     and the local resolver + Clingo compute the verdict. Clingo here only
     computes the consequences of THIS specific formalization — it is NEVER
     a judge of natural-language interpretation (user directive).
  2. CORRESPONDENCE side: does the control situation correspond to the
     original rule? An LLM judges the situation against the ORIGINAL clause
     text (decisive quote verified), independently of any formalization.

Control situations come in CONSTRUCTED PAIRS: ok (agent complies) and err
(agent violates) — so both correct theories (should pass both) and erroneous
formalizations (fail one side) are tested. Ground truth is by construction.

Flagging logic (theory level, fed back to case checking):
  - formal wrong on a situation AND correspondence right on the same
    situation -> the element's FORMALIZATION diverges from the natural
    reading -> element flagged unreliable (strict C3 downgrades CONFIRMED
    verdicts resting on it; lenient C3 keeps them and reports only).
  - correspondence wrong or unclear -> the situation itself is ambiguous
    -> excluded from flagging (never flags an element on a bad test).
  - both wrong -> situation construction issue -> recorded, no flag.

Nothing here uses Clingo to adjudicate natural-language meaning; the
semantic verdict always comes from the correspondence check against the
original text.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.trace_parser import Trace, ToolEvent, Segment
from common.zai_client import chat, extract_json, PROVIDER_MISTRAL, PROVIDER_ZAI
from arch_b.fact_ledger import locate_quote
from arch_d.hypothesis_check import (
    resolve_condition, resolve_exception, build_asp, solve,
)

HERE = Path(__file__).resolve().parent
RESULTS = HERE.parent / "results"
OUT = RESULTS / "arch_c_conseq"
FACETS = RESULTS / "arch_c_facets"
MUTUAL = RESULTS / "arch_c_mutual"

SITUATION_GEN_SYS = """Ты — конструктор контрольных ситуаций для проверки формализации правила
политики. Тебе дают ПРАВИЛО (точная цитата из политики) и полный текст политики
для контекста. Создай ПАРУ контрольных ситуаций:

1. ok_situation — агент действует СОГЛАСНО правилу (нарушения нет);
2. err_situation — агент НАРУШАЕТ именно это правило.

Каждая ситуация содержит:
- agent_statement: что агент говорит/пишет пользователю (1-2 предложения; включи
  ключевую деталь — число, статус, флаг, — по которой можно проверить правило);
- agent_action: какое действие совершено (имя инструмента + суть, или "только заявление");
- world_facts: JSON-объект наблюдаемых фактов мира (поля вида сумма, статус,
  флаг, результат вызова инструмента) — ровно enough для проверки по этому правилу.

Требования:
- ситуации конкретные и реалистичные (стиль tau-bench: банк/авиалиния/ритейл/телеком);
- ok и err различаются ТОЛЬКО аспектом, релевантным правилу;
- err_situation нарушает ИМЕННО это правило, не любое другое;
- world_facts — плоский JSON со строковыми/числовыми значениями.

Ответ строго JSON одной строкой (переносы в строках замени пробелами):
{"ok_situation": {"agent_statement": "...", "agent_action": "...", "world_facts": {...}},
 "err_situation": {"agent_statement": "...", "agent_action": "...", "world_facts": {...}}}"""

CORRESPONDENCE_SYS = """Ты — независимый проверяющий. Тебе дают:
- ОРИГИНАЛЬНУЮ клаузу политики (точный текст),
- КОНТРОЛЬНУЮ СИТУАЦИЮ: заявление агента, действие и наблюдаемые факты мира.

Вопрос: соответствует ли ситуация исходному правилу — нарушает ли действие
агента ЭТУ клаузу? Решай ТОЛЬКО по точным словам оригинала, не по здравому
смыслу. Обязательно процитируй решающие слова (decisive_quote).

Вердикты: violation (действие нарушает клаузу), compliant (не нарушает),
unclear (данных недостаточно или текст двусмыслен).

Ответ строго JSON одной строкой:
{"verdict": "violation|compliant|unclear", "decisive_quote": "...", "reason": "..."}"""

FORMALIZE_SITU_SYS = """You convert ONE policy rule into a typed, checkable template for a CONTROL
SITUATION (a synthetic tau-bench-like scenario).

You receive:
- POLICY (full text),
- the RULE (exact quote of one normative element),
- the SITUATION: agent statement, agent action, and WORLD FACTS (the only
  observable fields).

Return strictly JSON:
{
 "hypothesis": "<one sentence: what violation would look like here>",
 "trigger": {"kind": "statement", "tool": null,
             "match_response_fragment": "<exact fragment of agent_statement>"},
 "conditions": [
   {"id": "c1", "desc": "...", "kind": "numeric|flag|absence|temporal|claim_match",
    "evidence": {"tool": "world", "field": "<a WORLD FACTS key>",
                 "entity_ref": null,
                 "op": ">|<|>=|<=|==|!=", "value": <number or string>},
    "required": true}
 ],
 "exceptions": [
   {"id": "e1", "desc": "...", "evidence": {"tool": "world", "field": "<a WORLD FACTS key>",
                 "present_value": "<value that means the exception applies>"}}
 ]
}

Rules:
- BINDING IS MANDATORY: every condition/exception must use a field that
  EXISTS in WORLD FACTS. If nothing relevant is observable, set
  "unverifiable": true and explain in "unverifiable_reason".
- The template must express THE RULE (when the rule is violated), so that:
  err_situation -> all conditions hold and no exception applies,
  ok_situation -> some condition fails or an exception applies (ideally).
- Do NOT invent fields or conditions the rule does not state.
"""


# ---------------------------------------------------------------- situations

def select_rules(policy_hash: str, policy_text: str, max_rules: int = 3) -> list[dict]:
    """Rules for control situations:
    (a) elements criticized in mutual review (divergences, drops, challenges,
        modality conflicts) — where theories actually diverged;
    (b) facets discovered independently that the C0 theory did NOT capture
        (theory-vs-independent-discovery divergence)."""
    from arch_c.theory_case import load_variant_theory
    from arch_c.mutual_review import criticism_items
    from common.trace_parser import split_policy_clauses

    clauses = split_policy_clauses(policy_text)
    items = criticism_items(policy_hash, policy_text, clauses)
    c0 = load_variant_theory(policy_hash, "C0")
    c2 = load_variant_theory(policy_hash, "C2")

    rules = []
    seen_spans = set()

    def _span_seen(s, e):
        return any(abs(s - s2) < 30 and abs(e - e2) < 30 for s2, e2 in seen_spans)

    # (a) criticized elements
    for it in items:
        els = []
        if it["kind"] == "span_disagreement":
            els = [it["element"]]
        else:
            els = [it["element_a"], it["element_b"]]
        for el in els:
            if _span_seen(el["start"], el["end"]):
                continue
            # only elements that SURVIVE into C2 can be flagged; dropped ones
            # are already gone — but test them too (restoration evidence)
            in_c2 = any(e["start"] == el["start"] and e["end"] == el["end"]
                        for e in c2)
            rules.append({
                "source": "divergence",
                "clause": it["clause"],
                "element": {k: el[k] for k in ("class", "text", "start", "end")},
                "in_c2": in_c2,
            })
            seen_spans.add((el["start"], el["end"]))

    # (b) independent facets missed by C0 (theory-independence divergence)
    fdir = FACETS / policy_hash
    if (fdir / "facets_union.json").exists():
        facets = json.loads((fdir / "facets_union.json").read_text())
    elif (fdir / f"facets_{PROVIDER_MISTRAL}.json").exists():
        facets = json.loads((fdir / f"facets_{PROVIDER_MISTRAL}.json").read_text())
    else:
        facets = []
    aud_f = fdir / f"audit_C0_{PROVIDER_MISTRAL}.json"
    if aud_f.exists():
        audits = json.loads(aud_f.read_text())
        missed = [a for a in audits if not a.get("captured")]
        missed_idx = {a["facet"] for a in missed}
        for i, fc in enumerate(facets):
            if i not in missed_idx or fc["type"] not in (
                    "модальность", "исключение", "условие", "порог", "время", "область"):
                continue
            # find the sentence containing the facet quote
            loc = locate_quote(policy_text, fc["quote"])
            if not loc.get("found"):
                continue
            mid = (loc.get("start") or 0)
            if _span_seen(mid, mid + len(fc["quote"])):
                continue
            # attach to the nearest C2 element if any (else standalone rule)
            near = None
            for e in c2:
                if abs(e["start"] - mid) < 200:
                    near = e
                    break
            rules.append({
                "source": "independent_facet",
                "clause": fc["quote"],
                "facet_type": fc["type"],
                "element": ({k: near[k] for k in ("class", "text", "start", "end")}
                            if near else None),
                "in_c2": near is not None,
            })
            seen_spans.add((mid, mid + len(fc["quote"])))
    return rules[:max_rules]


def _extract_situation_objects(content: str) -> dict | None:
    """Robust extraction of ok_situation/err_situation objects even when the
    OUTER json is malformed (unescaped chars): balanced-scan each key's
    object separately."""
    import re as _re

    def _balanced(text: str, start: int) -> str | None:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    return text[start : i + 1]
        return None

    out = {}
    for key in ("ok_situation", "err_situation"):
        m = _re.search(rf'"{key}"\s*:\s*\{{', content)
        if not m:
            return None
        frag = _balanced(content, m.end() - 1)
        if not frag:
            return None
        obj = None
        for cleaner in (
            lambda s: s,
            # strip trailing commas
            lambda s: _re.sub(r",\s*([}\]])", r"\1", s),
            # strip JS-style // comments (models sometimes add them):
            # cut //..EOL when not inside a quoted string
            lambda s: _strip_line_comments(s),
            lambda s: _strip_line_comments(_re.sub(r",\s*([}\]])", r"\1", s)),
        ):
            try:
                obj = json.loads(cleaner(frag))
                break
            except json.JSONDecodeError:
                continue
        if not isinstance(obj, dict) or not obj.get("agent_statement"):
            return None
        out[key] = obj
    return out


def _strip_line_comments(s: str) -> str:
    import re as _re
    lines = []
    for line in s.split("\n"):
        in_str = False
        cut = None
        i = 0
        while i < len(line) - 1:
            if line[i] == '"' and (i == 0 or line[i - 1] != "\\"):
                in_str = not in_str
            elif not in_str and line[i] == "/" and line[i + 1] == "/":
                cut = i
                break
            i += 1
        lines.append(line if cut is None else line[:cut].rstrip())
    return "\n".join(lines)


def generate_pair(rule: dict, policy_text: str, provider: str, tag: str) -> dict | None:
    user = (
        "ПОЛИТИКА (полный текст):\n" + policy_text
        + "\n\nПРАВИЛО (точная цитата):\n" + rule["clause"][:600]
        + "\n\nСоздай пару контрольных ситуаций. JSON одной строкой."
    )
    resp = chat(user=user, system=SITUATION_GEN_SYS, thinking=False,
                provider=provider, tag=tag, max_retries=2)
    if not resp.ok:
        return None
    data = extract_json(resp.content)
    if isinstance(data, dict) and "ok_situation" in data and "err_situation" in data:
        pair = data
    else:
        pair = _extract_situation_objects(resp.content)
    if not pair:
        return None
    for k in ("ok_situation", "err_situation"):
        s = pair[k]
        if not isinstance(s, dict) or not s.get("agent_statement"):
            return None
        s.setdefault("world_facts", {})
    return pair


# ------------------------------------------------------- formal side (reused)

def _situation_trace(agent_statement: str, world_facts: dict) -> Trace:
    """Synthetic Trace: one RESPONSE segment (the agent statement) + one
    'world' TOOL_RESPONSE event carrying the observable facts. resolve_*
    functions from arch_d work on it unchanged."""
    seg = Segment(kind="RESPONSE", turn=None, start=0, end=len(agent_statement),
                  marker_start=0, text=agent_statement, idx=0)
    payload = json.dumps(world_facts, ensure_ascii=False)
    ev = ToolEvent(kind="RESPONSE", tool="world", raw_payload=payload,
                   payload=world_facts, seg_idx=0, abs_start=0, abs_end=len(payload),
                   seq=1)
    return Trace(full_text=agent_statement, prompt_text="", response_text=agent_statement,
                 segments=[seg], tool_events=[ev])


def formalize_rule_for_situation(rule: dict, situation: dict, policy_text: str,
                                 provider: str, tag: str) -> dict | None:
    facts = situation.get("world_facts", {})
    fields = ", ".join(f"{k} ({type(v).__name__})" for k, v in facts.items()) or "(none)"
    user = (
        "POLICY:\n" + policy_text
        + "\n\nRULE (exact quote of the normative element):\n" + rule["clause"][:600]
        + "\n\nWORLD FACTS (the ONLY observable fields; tool name is 'world'):\n- world: "
        + fields
        + "\n\nSITUATION:\nagent statement: " + situation["agent_statement"]
        + "\nagent action: " + str(situation.get("agent_action", ""))
        + "\n\nWorld facts JSON:\n" + json.dumps(facts, ensure_ascii=False)
        + "\n\nConvert the RULE into the typed template for this situation. "
        "Output strictly the JSON."
    )
    resp = chat(user=user, system=FORMALIZE_SITU_SYS, thinking=False,
                provider=provider, tag=tag, max_retries=2)
    if not resp.ok:
        return None
    data = extract_json(resp.content)
    if not data or "conditions" not in data:
        return None
    return data


def check_situation(hyp: dict, situation: dict) -> dict:
    """Resolve the formalized rule on the control situation (local resolver
    + Clingo cross-check). Same verdict semantics as arch_d."""
    trace = _situation_trace(situation["agent_statement"],
                             situation.get("world_facts", {}))
    trig = hyp.get("trigger", {})
    frag = trig.get("match_response_fragment", "")
    trigger_observed = bool(frag) and locate_quote(trace.response_segment.text, frag)["found"]
    cond_results = [resolve_condition(c, trace, {}) for c in hyp.get("conditions", [])]
    exc_results = [resolve_exception(e, trace, {}) for e in hyp.get("exceptions", [])]

    if not trigger_observed:
        verdict = "REFUTED_NO_TRIGGER"
    elif any(c["status"] == "failed" for c in cond_results):
        verdict = "REFUTED_CONDITION_FAILS"
    elif any(e["status"] == "applies" for e in exc_results):
        verdict = "REFUTED_EXCEPTION_APPLIES"
    elif any(c["status"] == "unknown" for c in cond_results) or any(
        e["status"] == "unknown" for e in exc_results
    ):
        verdict = "UNRESOLVED_UNKNOWN_PREMISE"
    else:
        verdict = "CONFIRMED"

    if verdict == "CONFIRMED" and trig.get("kind") == "statement":
        if not any(c.get("kind") == "claim_match" for c in hyp.get("conditions", [])):
            # situations provide full observability; claim_link guard relaxed
            pass

    asp = build_asp(hyp, cond_results, exc_results) if trigger_observed else (
        build_asp({}, [], []) + "\n:- trigger_observed.")
    asp_res = solve(asp)
    return {
        "trigger_observed": trigger_observed,
        "conditions": cond_results,
        "exceptions": exc_results,
        "verdict": verdict,
        "asp_ok": asp_res.get("ok"),
    }


# ------------------------------------------------- correspondence side (LLM)

def check_correspondence(rule_clause: str, situation: dict, provider: str,
                         tag: str) -> dict:
    user = (
        "ОРИГИНАЛЬНАЯ КЛАУЗА ПОЛИТИКИ:\n" + rule_clause[:600]
        + "\n\nКОНТРОЛЬНАЯ СИТУАЦИЯ:\nзаявление агента: " + situation["agent_statement"]
        + "\nдействие агента: " + str(situation.get("agent_action", ""))
        + "\nнаблюдаемые факты:\n" + json.dumps(situation.get("world_facts", {}),
                                                ensure_ascii=False)
        + "\n\nНарушает ли действие агента эту клаузу? JSON одной строкой."
    )
    resp = chat(user=user, system=CORRESPONDENCE_SYS, thinking=False,
                provider=provider, tag=tag, max_retries=2)
    rec = {"provider": provider, "ok": resp.ok, "error": (resp.error or "")[:150]}
    if resp.ok:
        import re as _re
        data = extract_json(resp.content)
        if not (isinstance(data, dict) and data.get("verdict")):
            m = _re.search(r'"verdict"\s*:\s*"(violation|compliant|unclear)"', resp.content)
            if not m:
                rec["ok"] = False
                rec["error"] = "bad-json"
                return rec
            data = {"verdict": m.group(1)}
        v = str(data.get("verdict", "")).lower()
        if v not in ("violation", "compliant", "unclear"):
            rec["ok"] = False
            rec["error"] = "bad-verdict"
            return rec
        rec["verdict"] = v
        rec["decisive_quote"] = str(data.get("decisive_quote", ""))
        rec["reason"] = str(data.get("reason", ""))[:300]
        rec["quote_found"] = locate_quote(rule_clause, rec["decisive_quote"])["found"]
    return rec


# ------------------------------------------------------------------- runner

def run(provider: str = PROVIDER_MISTRAL, max_seconds: float = 900,
        max_rules: int = 3) -> None:
    """Generate control pairs, run both sides, aggregate flags."""
    import hashlib
    import time
    from common.trace_parser import parse_trace

    data_f = HERE.parent / "data" / "synth_pairs" / "synth_pairs_v1.jsonl"
    pol_by_hash = {}
    for line in data_f.open(encoding="utf-8"):
        r = json.loads(line)
        t = parse_trace(r["prompt"], r["response"])
        h = hashlib.sha256(t.policy_text.encode()).hexdigest()[:10]
        if h not in pol_by_hash:
            pol_by_hash[h] = (t.policy_text, r.get("domain", ""))

    t0 = time.time()
    for h in sorted(pol_by_hash):
        pol, domain = pol_by_hash[h]
        out_dir = OUT / h
        out_dir.mkdir(parents=True, exist_ok=True)
        rules = select_rules(h, pol, max_rules=max_rules)
        print(f"=== {h} ({domain}): {len(rules)} rules selected for consequences", flush=True)
        for ri, rule in enumerate(rules):
            pair_f = out_dir / f"rule{ri:02d}_pair.json"
            pair = None
            if pair_f.exists():
                blob = json.loads(pair_f.read_text())
                pair = blob.get("pair") if isinstance(blob, dict) else None
            def _usable(p):
                return isinstance(p, dict) and "ok_situation" in p and "err_situation" in p
            if not _usable(pair):
                # one regeneration attempt for failed/partial pairs
                retry_f = out_dir / f"rule{ri:02d}_retry.json"
                if retry_f.exists():
                    continue  # already retried once; keep the failure on record
                if time.time() - t0 > max_seconds:
                    print("[conseq] time budget reached", flush=True)
                    return
                retry_f.write_text(json.dumps({"regenerated": True}, indent=1))
                pair = generate_pair(rule, pol, provider, tag=f"CQ/{h}/r{ri}r")
                if _usable(pair):
                    pair_f.write_text(json.dumps(
                        {"rule": rule, "pair": pair}, ensure_ascii=False, indent=1))
            if not _usable(pair):
                continue
            for side, is_err in (("ok", False), ("err", True)):
                sf = out_dir / f"rule{ri:02d}_{side}_{provider}.json"
                if sf.exists():
                    continue
                if time.time() - t0 > max_seconds:
                    print("[conseq] time budget reached", flush=True)
                    return
                sit = pair[f"{side}_situation"]
                hyp = formalize_rule_for_situation(rule, sit, pol, provider,
                                                   tag=f"CQ/{h}/r{ri}/{side}")
                rec = {"rule": rule, "side": side, "is_err": is_err,
                       "situation": sit}
                if hyp is None:
                    rec["status"] = "FORMALIZE_FAILED"
                else:
                    rec["formal"] = check_situation(hyp, sit)
                corr = check_correspondence(rule["clause"], sit, provider,
                                            tag=f"CQ/{h}/r{ri}/{side}/corr")
                rec["correspondence"] = corr
                sf.write_text(json.dumps(rec, ensure_ascii=False, indent=1))
                fv = (rec.get("formal") or {}).get("verdict")
                cv = (corr.get("verdict") if corr.get("ok") else None)
                print(f"  r{ri} {side}: formal={fv} corr={cv} "
                      f"(constructed={'violation' if is_err else 'compliant'})", flush=True)
        # aggregate flags for this policy
        _aggregate_flags(h)


def _aggregate_flags(policy_hash: str) -> None:
    """element_key -> reliability. Key format matches theory_case.check_case:
    f"{start}:{end}:{class}" of the C2-theory element."""
    from arch_c.theory_case import load_variant_theory
    pol_dir = OUT / policy_hash
    c2 = load_variant_theory(policy_hash, "C2")
    # map (start,end) -> key in C2 (class may have been corrected)
    key_by_span = {e["start"]: f"{e['start']}:{e['end']}:{e['class']}" for e in c2}

    per_element: dict[str, dict] = {}
    for f in sorted(pol_dir.glob("rule*_*_*.json")):
        if "_pair" in f.name:
            continue
        try:
            r = json.loads(f.read_text())
        except json.JSONDecodeError:
            continue
        if not isinstance(r, dict) or "is_err" not in r:
            continue
        rule = r.get("rule") or {}
        el = rule.get("element")
        if not el:
            continue
        key = key_by_span.get(el["start"])
        formal = (r.get("formal") or {})
        corr = (r.get("correspondence") or {})
        # formal correctness on this situation
        formal_v = formal.get("verdict")
        formal_says_violation = formal_v == "CONFIRMED"
        formal_definitive = formal_v in ("CONFIRMED", "REFUTED_CONDITION_FAILS",
                                         "REFUTED_EXCEPTION_APPLIES")
        formal_correct = formal_definitive and (formal_says_violation == r["is_err"])
        # correspondence correctness
        corr_v = corr.get("verdict") if corr.get("ok") else None
        corr_says_violation = corr_v == "violation"
        corr_correct = corr_v in ("violation", "compliant") and (
            corr_says_violation == r["is_err"])
        entry = per_element.setdefault(key or f"{el['start']}:{el['end']}:{el['class']}", {
            "n_situations": 0, "formal_correct": 0, "formal_definitive": 0,
            "corr_correct": 0, "corr_definitive": 0, "mismatches": []})
        entry["n_situations"] += 1
        entry["formal_correct"] += bool(formal_correct)
        entry["formal_definitive"] += bool(formal_definitive)
        entry["corr_correct"] += bool(corr_correct)
        entry["corr_definitive"] += corr_v in ("violation", "compliant")
        if formal_definitive and corr_v in ("violation", "compliant"):
            if not formal_correct and corr_correct:
                entry["mismatches"].append({
                    "side": r["side"], "formal": formal_v,
                    "corr": corr_v, "constructed": "violation" if r["is_err"] else "compliant"})
    flags = {}
    for key, e in per_element.items():
        has_mismatch = bool(e["mismatches"])
        if has_mismatch:
            reliable, state = False, "unreliable_mismatch"
        elif e["formal_definitive"] > 0:
            reliable, state = True, "tested_ok"
        else:
            # no definitive formal check and no mismatch: situation problems
            # (FORMALIZE_FAILED / ambiguous correspondence) — NOT evidence
            # against the element; must not downgrade anything
            reliable, state = None, "untested"
        flags[key] = {
            "reliable": reliable,
            "state": state,
            "n_situations": e["n_situations"],
            "formal_correct": e["formal_correct"],
            "formal_definitive": e["formal_definitive"],
            "corr_correct": e["corr_correct"],
            "corr_definitive": e["corr_definitive"],
            "mismatches": e["mismatches"],
        }
    (pol_dir / "flags.json").write_text(json.dumps(flags, ensure_ascii=False, indent=1))
    n_bad = sum(1 for v in flags.values() if v["reliable"] is False)
    n_untested = sum(1 for v in flags.values() if v["reliable"] is None)
    print(f"  flags: {len(flags)} elements, {n_bad} unreliable, {n_untested} untested", flush=True)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", default=PROVIDER_MISTRAL)
    ap.add_argument("--max-seconds", type=float, default=900)
    ap.add_argument("--max-rules", type=int, default=3)
    ap.add_argument("--aggregate-only", action="store_true")
    args = ap.parse_args()
    if args.aggregate_only:
        import hashlib
        from common.trace_parser import parse_trace
        data_f = HERE.parent / "data" / "synth_pairs" / "synth_pairs_v1.jsonl"
        for line in data_f.open(encoding="utf-8"):
            r = json.loads(line)
            t = parse_trace(r["prompt"], r["response"])
            h = hashlib.sha256(t.policy_text.encode()).hexdigest()[:10]
            _aggregate_flags(h)
    else:
        run(provider=args.provider, max_seconds=args.max_seconds,
            max_rules=args.max_rules)
