"""Architecture A - direct LLM-judge baseline (control neural variant).

Variants:
  a0_direct     : full context -> binary 0/1
  a1_citations  : full context -> list of concrete errors, each with a source
                  quote (verified via spans.locate); label 1 iff >=1 verified-ish error
GLM-API is used as the judge (documented; NOT a local model).
"""
import sys, json, re
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.io_utils import load_dataset, run_llm, prf, save_result, extract_json, SYSTEM_PROMPT
from common.spans import locate

MAX_CONTEXT = 100_000   # chars; simple truncation strategy (head+tail)


def build_context(row, max_chars=MAX_CONTEXT):
    text = f"FULL CONVERSATION HISTORY (prompt):\n{row['prompt']}\n\nFINAL AGENT RESPONSE TO AUDIT:\n{row['response']}"
    if len(text) <= max_chars:
        return text
    head, tail = int(max_chars * 0.6), int(max_chars * 0.4)
    return text[:head] + "\n\n[...TRUNCATED MIDDLE...]\n\n" + text[-tail:]


P_A0 = """You are auditing an AI customer-service agent. Decide whether the FINAL RESPONSE
contains a contextual error: a statement contradicting the conversation/policy, an
unsupported (ungrounded) claim, a wrong entity/value, a wrong or policy-violating action,
a wrong tool call or wrong arguments. Correct paraphrasing, formatting or rounding is NOT an error.
Answer with exactly one JSON object: {"label": 0} or {"label": 1}
1 means: the final response has such an error.
"""

P_A1 = """You are auditing an AI customer-service agent. Find contextual errors in the FINAL RESPONSE:
statements contradicting the conversation/policy, unsupported claims, wrong entity/value,
wrong or policy-violating actions, wrong tool calls or arguments.
For EACH suspected error output: the error description, the exact verbatim quote from the
conversation that the error contradicts or violates (copy-paste exact text, may be shorter
than 200 chars), and the exact verbatim fragment of the final response that is wrong.
If there are no errors, return an empty list.
Answer with exactly one JSON object:
{"errors": [{"description": "...", "policy_quote": "...", "response_fragment": "..."}]}
"""

R_A1 = """You are auditing an AI customer-service agent. Below are suspected errors found by a
first reviewer. For EACH suspicion, check the conversation: is the cited policy_quote really
present in the conversation? Does it really contradict the final response fragment, or is there
later/more specific information (fresh tool results, exceptions, other entities) that makes the
suspicion wrong? Remove suspicions based on outdated or misattributed evidence.
Answer with JSON: {"errors": [ ... surviving suspicions in the same format ... ]}
"""


def run(dataset, variant, limit=None):
    rows = load_dataset(dataset)
    if limit:
        rows = rows[:limit]
    tasks = []
    for r in rows:
        ctx = build_context(r)
        if variant == "a0_direct":
            tasks.append({"id": r["id"], "system": SYSTEM_PROMPT, "prompt": P_A0 + "\n\n" + ctx})
        else:
            tasks.append({"id": r["id"], "system": SYSTEM_PROMPT, "prompt": P_A1 + "\n\n" + ctx})
    res = run_llm(tasks, concurrency=3)
    preds, details = {}, {}
    for r in rows:
        out = res.get(r["id"])
        if variant == "a0_direct":
            j = extract_json(out)
            preds[r["id"]] = int(j["label"]) if j and j.get("label") in (0, 1) else None
            details[r["id"]] = {"raw": out, "json": j}
        else:
            j = extract_json(out)
            errs = j.get("errors") if isinstance(j, dict) else None
            if errs is None:
                preds[r["id"]] = None
                details[r["id"]] = {"raw": out, "json": j, "verified": []}
                continue
            verified = []
            for e in errs[:6]:
                q = e.get("policy_quote") or ""
                anch = locate(q, r["prompt"])
                e2 = dict(e)
                e2["anchor"] = anch
                verified.append(e2)
            preds[r["id"]] = 1 if verified else 0
            details[r["id"]] = {"json": j, "verified": verified}
    golds = {r["id"]: r["gold"] for r in rows}
    m = prf(preds, golds)
    save_result(f"arch_a_{variant}_{dataset}.json",
                {"variant": variant, "dataset": dataset, "metrics": m,
                 "preds": preds, "details": details})
    print(f"A/{variant}/{dataset}: {m}")


if __name__ == "__main__":
    ds = sys.argv[1] if len(sys.argv) > 1 else "synth-dev"
    variant = sys.argv[2] if len(sys.argv) > 2 else "a0_direct"
    limit = int(sys.argv[3]) if len(sys.argv) > 3 else None
    run(ds, variant, limit)
