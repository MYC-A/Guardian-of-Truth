"""F6 ARM A / A2 / B runners — raw LLM extraction on the F6 suite.

Local Mistral API backend (pl_common.Mistral client class copied into
this experiment as f6_mistral.py with identical request semantics:
temperature 0, json_object response format, sha-keyed cache, 429 retry).
NO NLP candidates, NO bnorm output, NO old event candidates are given
to the model (directive section 4).

Outputs (per case, resumable):
  outputs/raw/<model>/<arm>/<case_id>.json
    {"case_id", "arm", "model", "mentions": [raw generated mentions],
     "raw_count", "grounded_count", "hallucinated",
     "latency_s", "usage"}

Programmatic grounding check (directive section 4): every quote is
verified against the policy text; quotes not found verbatim are marked
invalid/hallucinated (kept in the file for measurement, flagged).

Run: python3 en_f6_raw.py A|B [mistral|codestral]
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

from en_f6_prompts import (ARM_A_SYSTEM, ARM_A_USER_TMPL,  # noqa: E402
                           ARM_B_SYSTEM, ARM_B_USER_TMPL, MODELS)
from f6_mistral import Mistral  # noqa: E402

FROZEN = HERE / "f6_frozen"
OUT = HERE / "outputs" / "raw"

SUITES = {
    "f6": FROZEN.parent.parent / "event_ie_frontends_v1" / "frozen" /
          "level_f6_cases.json",
    "f6r": FROZEN.parent.parent / "event_ie_frontends_v1" / "frozen" /
           "level_f6r_cases.json",
}


def load_cases(suite: str) -> list[dict]:
    return json.loads(SUITES[suite].read_text(encoding="utf-8"))


def render_tools(tools: list[dict]) -> str:
    lines = []
    for t in tools:
        lines.append(f"- {t['name']}: {t['description']} "
                     f"input={json.dumps(t.get('input', {}))} "
                     f"output={json.dumps(t.get('output', {}))}")
    return "\n".join(lines)


def find_offset(policy: str, span: str) -> tuple[int, int] | None:
    """Case-sensitive exact match first, then case-insensitive (flagged)."""
    if not span:
        return None
    idx = policy.find(span)
    if idx >= 0:
        return idx, idx + len(span)
    low, s = policy.lower(), span.strip().lower()
    if s:
        idx = low.find(s)
        if idx >= 0:
            return idx, idx + len(s)
    return None


def check_mention(policy: str, m: dict) -> dict:
    """Grounding check for ONE generated mention (directive 4/6)."""
    quote = m.get("quote") or m.get("span") or ""
    off = find_offset(policy, quote)
    m["quote"] = quote
    m["start"], m["end"] = (off if off else (None, None))
    m["exact_verbatim"] = bool(off and policy.find(quote) >= 0)
    m["case_variant"] = bool(off and policy.find(quote) < 0)
    m["grounded"] = off is not None
    args = m.get("arguments") or []
    ok_args = []
    for a in args:
        if not isinstance(a, dict):
            continue
        aq = a.get("quote") or a.get("span") or ""
        aoff = find_offset(policy, aq)
        if aoff:
            ok_args.append({"role": a.get("role", "argument"),
                            "quote": aq, "start": aoff[0], "end": aoff[1]})
    m["arguments"] = ok_args
    m["args_grounded"] = len(ok_args)
    m["args_dropped"] = len(args) - len(ok_args)
    return m


def run_arm(arm: str, model_key: str, suite: str = "f6") -> None:
    assert arm in ("A", "B")
    system = ARM_A_SYSTEM if arm == "A" else ARM_B_SYSTEM
    user_tmpl = ARM_A_USER_TMPL if arm == "A" else ARM_B_USER_TMPL
    model = MODELS[model_key]
    client = Mistral(model=model, cache_dir=OUT / "_cache")
    outdir = OUT / model_key / arm
    outdir.mkdir(parents=True, exist_ok=True)
    cases = load_cases(suite)
    tag = f"[{arm}:{model_key}:{suite}]"
    for case in cases:
        path = outdir / f"{case['case_id']}.json"
        if path.exists():
            continue
        policy = case["policy"]
        user = user_tmpl.format(policy=policy,
                                tools=render_tools(case["tools"]))
        t0 = time.time()
        parsed = {}
        for _ in range(4):
            try:
                r = client.ask(system, user, max_tokens=2500)
                parsed, _err = Mistral.parse_json(r["raw"])
                if parsed:
                    break
            except Exception:
                time.sleep(3)
        raw_mentions = []
        if isinstance(parsed, dict):
            for m in parsed.get("mentions", []):
                if isinstance(m, dict):
                    raw_mentions.append(m)
        checked = [check_mention(policy, m) for m in raw_mentions]
        rec = {"case_id": case["case_id"], "arm": arm, "model": model,
               "suite": suite, "mentions": checked,
               "raw_count": len(checked),
               "grounded_count": sum(1 for m in checked if m["grounded"]),
               "hallucinated": sum(1 for m in checked if not m["grounded"]),
               "case_variant_quotes": sum(1 for m in checked
                                           if m["case_variant"]),
               "latency_s": round(time.time() - t0, 2),
               "usage": client.usage_total}
        path.write_text(json.dumps(rec, indent=1, ensure_ascii=False) + "\n",
                        encoding="utf-8")
        print(tag, case["case_id"], f"raw={rec['raw_count']} "
              f"grounded={rec['grounded_count']} "
              f"hallu={rec['hallucinated']}", flush=True)
    print(tag, "done", flush=True)


def run_cf_twins(model_key: str, arm: str = "A") -> None:
    """CF twins: no tools (F5 convention), both arms A and B prompts."""
    tw = json.loads((FROZEN / "f6_cf_twins.json").read_text())["twins"]
    client = Mistral(model=MODELS[model_key], cache_dir=OUT / "_cache")
    for arm_i in ([arm] if arm != "AB" else ["A", "B"]):
        system = ARM_A_SYSTEM if arm_i == "A" else ARM_B_SYSTEM
        outdir = OUT / model_key / arm_i
        outdir.mkdir(parents=True, exist_ok=True)
        for t in tw:
            for side in ("a", "b"):
                cid = f"{t['twin_id']}_{side}"
                path = outdir / f"{cid}.json"
                if path.exists():
                    continue
                policy = t[side]["policy"]
                user = ARM_A_USER_TMPL.format(
                    policy=policy,
                    tools="(none - extract from the policy text alone)")
                parsed = {}
                for _ in range(4):
                    try:
                        r = client.ask(system, user, max_tokens=1500)
                        parsed, _err = Mistral.parse_json(r["raw"])
                        if parsed:
                            break
                    except Exception:
                        time.sleep(3)
                raw_mentions = [m for m in (parsed or {}).get("mentions", [])
                                if isinstance(m, dict)] if isinstance(parsed, dict) else []
                checked = [check_mention(policy, m) for m in raw_mentions]
                rec = {"case_id": cid, "arm": arm_i,
                       "model": MODELS[model_key], "suite": "cf",
                       "twin_id": t["twin_id"], "side": side,
                       "focus": t[side]["focus"],
                       "expected": t[side]["expected"],
                       "mentions": checked,
                       "raw_count": len(checked),
                       "grounded_count": sum(1 for m in checked
                                             if m["grounded"]),
                       "hallucinated": sum(1 for m in checked
                                           if not m["grounded"])}
                path.write_text(json.dumps(rec, indent=1,
                                           ensure_ascii=False) + "\n",
                                encoding="utf-8")
                print(f"[cf:{arm_i}:{model_key}]", cid,
                      f"raw={rec['raw_count']}", flush=True)


if __name__ == "__main__":
    arm = sys.argv[1] if len(sys.argv) > 1 else "A"
    model_key = sys.argv[2] if len(sys.argv) > 2 else "mistral"
    if arm == "cf":
        run_cf_twins(model_key)
    elif arm == "cfAB":
        run_cf_twins(model_key, "AB")
    else:
        suite = sys.argv[3] if len(sys.argv) > 3 else "f6"
        run_arm(arm, model_key, suite)
