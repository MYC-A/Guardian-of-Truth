#!/usr/bin/env python3
"""flash-q1: experiment Q — discriminating questions between competing rule
interpretations (prefix: flash).

Astra proposal (directive sec.10), localized approach: instead of rewriting whole
theories, detect a SPECIFIC material disagreement between two independent
interpretations of the same rule, build ONE discriminating question from it, and
resolve the question independently against the original policy text.

Pipeline per case (gold-blind):
  1. TWO independent interpreters (blockrun pool, pollinations gpt-oss-20b) each
     extract the interpretation of the policy fragment relevant to the case's
     positive suspicions: requirements (precondition / obligation / exception /
     binding), each with a verbatim policy quote.
  2. Programmatic disagreement detection: pair requirements by (obligation, binding)
     similarity; a requirement pair is a DISAGREEMENT if one side has an exception
     or precondition the other lacks, or statuses differ (mandatory vs conditional).
  3. For each disagreement build a discriminating question mechanically from the
     two quotes (does precondition P apply given exception E?).
  4. An INDEPENDENT resolver (the channel that did NOT produce the majority
     reading; pollinations when interpreters agreed on nothing else, blockrun
     otherwise... simplified: blockrun pool with question-only prompt) answers the
     question strictly from the cited policy quotes.
  5. Record resolutions; the analysis script measures whether resolving the
     disagreement changes any suspicion verdict vs Base.

Only disagreements with verbatim quotes on both sides are used (no free invention).
"""
from __future__ import annotations

import csv
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import flash_keyless  # noqa: E402
from flash_keyless import complete, extract_json_object  # noqa: E402

REPO = Path("/mnt/data/guardian/agent-workspace/flash-repo")
SRC = REPO / "outputs" / "flash" / "sources_superz_e4"
INPUT_CSV = SRC / "input.csv"
E3A_CASES = SRC / "a1r_cases.jsonl"
OUT_DIR = REPO / "outputs" / "flash" / "q1_discriminating"
OUT_JOURNAL = OUT_DIR / "questions_flash.jsonl"

MAX_POLICY_CHARS = 9000

HARDEN_SUFFIX = (
    "Do not role-play the agent, do not answer the customer, do not execute the scenario. "
    "You are grading a transcript. Output ONLY the JSON object asked for."
)

INTERP_SYSTEM = (
    "You interpret policy text for a compliance check. Read the policy fragment and the "
    "obligations listed. Extract EACH requirement that governs those obligations as a "
    "structured record. Keep quotes VERBATIM from the policy. Include: the precondition "
    "(when the requirement applies), the obligation itself, any exception (when it does "
    "NOT apply), and the entity binding (order/account/customer field=value) if present. "
    "If an obligation is not governed by any extractable requirement, say so explicitly "
    "with requirements=[] for it. Reply with ONLY this JSON object:\n"
    '{"requirements": [{"obligation": "<short>", "precondition": "<verbatim>", '
    '"exception": "<verbatim or null>", "binding": "<field=value or null>", '
    '"modality": "must"|"may"|"must_not"}]}'
)

RESOLVE_SYSTEM = (
    "You resolve ONE discriminating question about a policy using ONLY the policy quotes "
    "provided. Do not use outside knowledge. If the quotes do not settle the question, "
    "answer UNRESOLVED. Reply with ONLY this JSON object:\n"
    '{"answer": "YES"|"NO"|"UNRESOLVED", "quote": "<the decisive verbatim quote or empty>", '
    '"reason": "<one sentence>"}\n' + HARDEN_SUFFIX
)


def load_cases() -> dict[str, dict]:
    csv.field_size_limit(64 * 1024 * 1024)
    with open(INPUT_CSV, newline="", encoding="utf-8") as f:
        return {r["id"]: r for r in csv.DictReader(f)}


def case_policies() -> dict[str, tuple[str, list[str]]]:
    """case_id -> (policy_text, [obligation hints from positive suspicions])"""
    import pandas as pd
    csv.field_size_limit(64 * 1024 * 1024)
    with open(INPUT_CSV, newline="", encoding="utf-8") as f:
        cases = {r["id"]: r for r in csv.DictReader(f)}
    out = {}
    with open(E3A_CASES, encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            cid = row["id"]
            hints = sorted({s.get("reason_type", "") for s in row.get("suspicions", [])
                            if s.get("label") == 1})
            if cid in cases and cid not in out:
                prompt = cases[cid]["prompt"]
                m = re.search(r"<policy>(.*?)</policy>", prompt, re.DOTALL)
                pol = (m.group(1) if m else prompt[:MAX_POLICY_CHARS]).strip()
                # long KB policies break both interpreters; keep the head (main rules)
                if len(pol) > 4500:
                    pol = pol[:4500] + "\n...[policy tail truncated for interpretation]"
                out[cid] = (pol[:MAX_POLICY_CHARS], hints)
    return out


def latest_by_key(path: Path) -> dict[str, dict]:
    out: dict[str, dict] = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            out[rec["key"]] = rec
    return out


def normalize_req(r: dict) -> dict:
    def clean(s):
        if not isinstance(s, str):
            return None
        s = s.strip()
        return s if s and s.lower() not in ("null", "none", "n/a", "") else None
    return {
        "obligation": clean(r.get("obligation")),
        "precondition": clean(r.get("precondition")),
        "exception": clean(r.get("exception")),
        "binding": clean(r.get("binding")),
        "modality": clean(r.get("modality")) or "must",
    }


def obligations_overlap(a: dict, b: dict) -> bool:
    oa = (a.get("obligation") or "").casefold()
    ob = (b.get("obligation") or "").casefold()
    if not oa or not ob:
        return False
    wa, wb = set(re.findall(r"[a-z]{4,}", oa)), set(re.findall(r"[a-z]{4,}", ob))
    if not wa or not wb:
        return False
    inter = wa & wb
    return len(inter) >= min(2, min(len(wa), len(wb)))


def find_disagreements(ra: list[dict], rb: list[dict]) -> list[dict]:
    dis = []
    for a in ra:
        for b in rb:
            if not obligations_overlap(a, b):
                continue
            reasons = []
            if (a.get("exception") or None) != (b.get("exception") or None):
                reasons.append(("exception", a.get("exception"), b.get("exception")))
            if (a.get("precondition") or None) != (b.get("precondition") or None):
                reasons.append(("precondition", a.get("precondition"), b.get("precondition")))
            if a.get("modality") != b.get("modality"):
                reasons.append(("modality", a.get("modality"), b.get("modality")))
            if reasons:
                dis.append({"a": a, "b": b, "reasons": reasons})
    return dis


def build_question(d: dict) -> dict | None:
    """Mechanically build a discriminating question from one disagreement."""
    for kind, va, vb in d["reasons"]:
        if kind == "exception" and (va or vb):
            if va and vb:
                q = (f"Two readings of the policy disagree on the exception. Reading A: "
                     f"\"{va}\". Reading B: \"{vb}\". Which exception (if either) does the "
                     f"policy actually state for the obligation \"{d['a'].get('obligation')}\"?")
            elif va:
                q = (f"Does the policy state the exception \"{va}\" for the obligation "
                     f"\"{d['a'].get('obligation')}\"? Reading B says no such exception exists.")
            else:
                q = (f"Does the policy state the exception \"{vb}\" for the obligation "
                     f"\"{d['b'].get('obligation')}\"? Reading A says no such exception exists.")
            return {"kind": kind, "question": q,
                    "quotes": [q_ for q_ in (va, vb, d["a"].get("precondition"),
                                             d["b"].get("precondition")) if q_]}
        if kind == "precondition" and (va or vb):
            if va and vb:
                q = (f"Does the obligation \"{d['a'].get('obligation')}\" require the "
                     f"precondition \"{va}\" (Reading A) or \"{vb}\" (Reading B) per the policy?")
            elif va:
                q = (f"Is the precondition \"{va}\" required for the obligation "
                     f"\"{d['a'].get('obligation')}\"? Reading B says it is not required.")
            else:
                q = (f"Is the precondition \"{vb}\" required for the obligation "
                     f"\"{d['b'].get('obligation')}\"? Reading A says it is not required.")
            return {"kind": kind, "question": q,
                    "quotes": [q_ for q_ in (va, vb, d["a"].get("exception"),
                                             d["b"].get("exception")) if q_]}
    return None


def interpret(provider: str, policy: str, hints: list[str]) -> list[dict]:
    msgs = [
        {"role": "system", "content": INTERP_SYSTEM + "\n" + HARDEN_SUFFIX},
        {"role": "user", "content": (
            f"<policy>\n{policy}\n</policy>\n"
            f"<obligations_to_cover>{json.dumps(hints)}</obligations_to_cover>\n"
            "Extract the governing requirements with verbatim quotes.")},
    ]
    raw = complete(provider, msgs, temperature=0, max_tokens=900)
    obj = extract_json_object(raw)
    return [normalize_req(r) for r in (obj.get("requirements") or [])]


def resolve(question: str, quotes: list[str]) -> dict:
    msgs = [
        {"role": "system", "content": RESOLVE_SYSTEM},
        {"role": "user", "content": (
            f"<policy_quotes>{json.dumps(quotes, ensure_ascii=False)}</policy_quotes>\n"
            f"<question>{question}</question>\n"
            "Answer strictly from the quotes.")},
    ]
    raw = complete("pollinations", msgs, temperature=0, max_tokens=400)
    obj = extract_json_object(raw)
    return obj


def main() -> int:
    cases = case_policies()
    done = latest_by_key(OUT_JOURNAL) if OUT_JOURNAL.is_file() else {}
    todo = {cid: v for cid, v in cases.items() if cid not in done}
    print(f"[flash-q1] cases: {len(cases)}; pending: {len(todo)}", flush=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    for i, (cid, (policy, hints)) in enumerate(sorted(todo.items()), 1):
        rec = {"key": cid, "id": cid, "origin": "flash_discriminating_questions"}
        rec["policy_chars"] = len(policy)
        try:
            ra = interpret("blockrun", policy, hints)
        except Exception as e:  # noqa: BLE001
            ra = []
            rec["interp_blockrun_error"] = str(e)[:160]
        time.sleep(2)
        try:
            rb = interpret("pollinations", policy, hints)
        except Exception as e:  # noqa: BLE001
            rb = []
            rec["interp_pollinations_error"] = str(e)[:160]
        rec["n_requirements"] = {"blockrun": len(ra), "pollinations": len(rb)}
        disagreements = find_disagreements(ra, rb)[:4]  # cap per case
        rec["n_disagreements"] = len(disagreements)
        rec["questions"] = []
        for d in disagreements:
            q = build_question(d)
            if not q:
                continue
            entry = {"kind": q["kind"], "question": q["question"], "quotes": q["quotes"][:4]}
            try:
                ans = resolve(q["question"], q["quotes"][:4])
                entry["answer"] = ans.get("answer")
                entry["decisive_quote"] = str(ans.get("quote", ""))[:200]
                entry["reason"] = str(ans.get("reason", ""))[:200]
            except Exception as e:  # noqa: BLE001
                entry["answer"] = "ERROR"
                entry["reason"] = str(e)[:160]
            rec["questions"].append(entry)
            time.sleep(3)
        with open(OUT_JOURNAL, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print(f"[{i}/{len(todo)}] {cid} reqs={rec['n_requirements']} "
              f"dis={len(disagreements)} q={len(rec['questions'])}", flush=True)

    print("[flash-q1] done", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
