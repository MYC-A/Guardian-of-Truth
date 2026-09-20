"""Architecture B - mutual verification of suspicions (source-grounded).

B1 = A1_citations output (suspicion list with policy_quote + response_fragment).
B2 = deterministic grounding + mechanical cross-check:
     - anchor verification of policy_quote in prompt (spans.locate)
     - stale-fact detection: if suspicion claims a wrong VALUE for entity E field F,
       and a LATER tool response shows F for E equal to the response's value,
       the suspicion is REFUTED_STALE (successor-fact wins).
B3 = LLM cross-review of surviving suspicions: must cite a verbatim conversation
     quote as refutation ground; refutation accepted only if quote anchors.
Suspicion statuses: supported / refuted / unresolved (unknown never cancels).
Case label: 1 if >=1 surviving (supported or unresolved) suspicion.
"""
import sys, json, re
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.io_utils import load_dataset, run_llm, prf, save_result, extract_json, SYSTEM_PROMPT
from common.spans import locate
from common import timeline as T
from arch_a_judge import build_context, P_A1


# ---------------- B2 mechanical checks ----------------

def _flatten_payload(obj, prefix=""):
    """Yield (path, value, scalar_text) for JSON-ish payloads incl. scalars."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _flatten_payload(v, f"{prefix}.{k}" if prefix else str(k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _flatten_payload(v, prefix)
    else:
        yield (prefix, obj, str(obj))


def _numbers_in(text):
    return set(re.findall(r"(?<![\w.])(\d+(?:[.,]\d+)?)(?![\w])", str(text)))


def stale_fact_check(row, suspicion):
    """If suspicion is about a value reported for an entity, and a LATER tool
    response of the same tool/domain shows a different value that matches the
    final response's value -> refuted_stale. Returns status."""
    resp = row["response"]
    resp_nums = _numbers_in(resp)
    frag = suspicion.get("response_fragment") or ""
    frag_nums = _numbers_in(frag)
    if not frag_nums:
        return "unresolved"
    # numbers cited by the suspicion as 'true' evidence (from its policy_quote
    # or description) that contradict the response
    ev = (suspicion.get("policy_quote") or "") + " " + (suspicion.get("description") or "")
    ev_nums = _numbers_in(ev) - frag_nums
    if not ev_nums:
        return "unresolved"
    events = T.parse_prompt(row["prompt"])
    resp_evs = T.tool_responses(events)
    # find any later tool response whose value set contains the response's numbers
    # AND shares no number with the evidence numbers
    for i, e in enumerate(resp_evs):
        payloads = []
        if e.payload is not None:
            payloads = [v for _, v, _ in _flatten_payload(e.payload)]
        else:
            payloads = [e.payload_raw or ""]
        vals = set()
        for p in payloads:
            vals |= _numbers_in(p)
        if not vals:
            continue
        # successor check: response numbers come from a LATER read, evidence numbers absent
        if (vals & frag_nums) and ev_nums and not (vals & ev_nums):
            # require the evidence numbers to appear in an EARLIER tool response
            for j in range(i):
                e2 = resp_evs[j]
                vals2 = set()
                if e2.payload is not None:
                    vals2 = {v for _, v, _ in _flatten_payload(e2.payload)}
                else:
                    vals2 = _numbers_in(e2.payload_raw or "")
                if vals2 & ev_nums:
                    return "refuted_stale"
    return "unresolved"


def b2_check(row, suspicions):
    out = []
    for s in suspicions:
        s2 = dict(s)
        anch = locate(s.get("policy_quote") or "", row["prompt"])
        s2["anchor"] = anch
        if anch["status"] == "unanchored":
            s2["status"] = "unanchored"
        else:
            s2["status"] = stale_fact_check(row, s)
        out.append(s2)
    return out


# ---------------- B3 LLM cross-review ----------------

P_B3 = """You are a skeptical SECOND-OPINION reviewer of an AI agent audit.
A first reviewer produced suspicions of errors. Your job: verify the EVIDENCE BASE of each
suspicion against the conversation. Cancel a suspicion ONLY if the conversation contains
concrete information that makes it wrong: a later tool result for the same entity/field,
an applicable exception in the policy, a different entity, or an event the reviewer missed.
Do NOT cancel just because the action seems plausible.
For every suspicion you CANCEL, provide refuting_quote: an EXACT verbatim fragment of the
conversation that proves the suspicion wrong. If you cannot quote proof, leave the suspicion.
Answer with JSON:
{"suspicions": [{"description": "...", "verdict": "supported|refuted", "refuting_quote": "..."}]}
Keep all original suspicions in the list, with your verdicts.
"""


def b3_review(row, suspicions):
    ctx = build_context(row)
    sus_text = json.dumps([{"description": s.get("description", ""),
                            "policy_quote": s.get("policy_quote", ""),
                            "response_fragment": s.get("response_fragment", "")}
                           for s in suspicions], ensure_ascii=False, indent=1)
    prompt = (P_B3 + "\n\nSUSPICIONS:\n" + sus_text + "\n\n" + ctx)
    out = run_llm([{"id": row["id"], "system": SYSTEM_PROMPT, "prompt": prompt}], concurrency=1)
    j = extract_json(out.get(row["id"]))
    if not j or not isinstance(j, dict) or "suspicions" not in j:
        return None
    # accept refutation only if refuting_quote anchors
    verdicts = []
    for s in j.get("suspicions", []):
        v = dict(s)
        if str(s.get("verdict", "")).lower() == "refuted":
            q = s.get("refuting_quote") or ""
            anch = locate(q, row["prompt"])
            v["refuting_anchor"] = anch
            v["verdict"] = "refuted" if anch["status"] != "unanchored" else "unresolved"
        else:
            v["verdict"] = "supported"
        verdicts.append(v)
    return verdicts


def run_b(dataset, limit=None, use_b3=True, source="arch_a_a1_citations", out_suffix=""):
    """Full B pipeline over a dataset, reusing A1 suspicions (B1)."""
    rows = load_dataset(dataset)
    if limit:
        rows = rows[:limit]
    a1 = json.loads((Path(__file__).resolve().parent.parent.parent / "outputs" / "agentz" /
                     f"{source}_{dataset}.json").read_text())
    preds_b1, preds_b2, preds_b3 = {}, {}, {}
    details = {}
    for r in rows:
        d1 = a1["details"].get(r["id"], {})
        j = d1.get("json")
        suspicions = (j.get("errors") if isinstance(j, dict) else None) or []
        golds_ok = True
        # B1 label
        preds_b1[r["id"]] = 1 if suspicions else 0
        # B2
        s2 = b2_check(r, suspicions)
        surv2 = [s for s in s2 if s["status"] != "refuted_stale"]
        preds_b2[r["id"]] = 1 if surv2 else 0
        det = {"b1": suspicions, "b2": [{k: s[k] for k in ("description", "status", "anchor") if k in s} for s in s2]}
        # B3
        if use_b3 and surv2:
            v3 = b3_review(r, surv2)
            if v3 is None:
                preds_b3[r["id"]] = preds_b2[r["id"]]
                det["b3"] = "no_parse"
            else:
                refuted = {i for i, v in enumerate(v3) if v.get("verdict") == "refuted"}
                surv3 = [s for i, s in enumerate(surv2) if i not in refuted]
                preds_b3[r["id"]] = 1 if surv3 else 0
                det["b3"] = v3
        else:
            preds_b3[r["id"]] = preds_b2[r["id"]]
            det["b3"] = "skipped"
        details[r["id"]] = det
    golds = {r["id"]: r["gold"] for r in rows}
    out = {"dataset": dataset,
           "metrics_b1": prf(preds_b1, golds),
           "metrics_b2": prf(preds_b2, golds),
           "metrics_b3": prf(preds_b3, golds),
           "preds_b2": preds_b2, "preds_b3": preds_b3, "details": details}
    save_result(f"arch_b_{dataset}{out_suffix}.json", out)
    print(f"B/{dataset}: B1={out['metrics_b1']}")
    print(f"          B2={out['metrics_b2']}")
    print(f"          B3={out['metrics_b3']}")


if __name__ == "__main__":
    ds = sys.argv[1] if len(sys.argv) > 1 else "public46"
    limit = None
    if len(sys.argv) > 2 and sys.argv[2].isdigit():
        limit = int(sys.argv[2])
    nb3 = "--no-b3" in sys.argv
    suffix = ""
    if "--suffix" in sys.argv:
        suffix = sys.argv[sys.argv.index("--suffix") + 1]
    src = "arch_a_a1_citations"
    if "--source" in sys.argv:
        src = sys.argv[sys.argv.index("--source") + 1]
    run_b(ds, limit, use_b3=not nb3, source=src, out_suffix=suffix)
