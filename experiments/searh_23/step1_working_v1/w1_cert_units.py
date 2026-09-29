"""W1 certificate units with E3v2 prompts (mechanism dev-set regression).

Re-runs the 22 frozen adversarial certificate items with the v2 prompts
(anchor-set verification + SEMANTIC_LINK routing) so that prompt changes
are checked against the adversarial discipline before any downstream.

Run: python3 w1_cert_units.py          (writes outputs/W1_CERT_E3V2/)
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).parent
IE = HERE.parent / "event_ie_frontends_v1"
PL = HERE.parent / "policy_licensing_v1"
sys.path[:0] = [str(PL), str(HERE)]
from pl_common import Mistral  # noqa: E402
from lf_certificate import sanitize_quote, span_in  # noqa: E402
from w1_pipeline import (E3_EXT_SYSTEM_V2, E3_JUDGE_SYSTEM_V2,  # noqa: E402
                         e3_ext_user_v2, e3_judge_user_v2,
                         verify_certificate_v2)

OUT = HERE / "outputs"


def load_cert_items() -> list[dict]:
    return json.loads((IE / "frozen" / "certificate_cases.json")
                      .read_text(encoding="utf-8"))


def _ask(client, system: str, user: str, mt: int = 500) -> dict:
    for _ in range(4):
        try:
            r = client.ask(system, user, max_tokens=mt)
            parsed, _err = Mistral.parse_json(r["raw"])
            if parsed:
                return parsed
        except Exception:
            time.sleep(3)
    return {}


def main() -> None:
    client = Mistral(model="ministral-14b-latest", cache_dir=OUT / "_cache")
    outdir = OUT / "W1_CERT_E3V2"
    outdir.mkdir(parents=True, exist_ok=True)
    ok = {"SUPPORTED": 0, "UNSUPPORTED": 0, "UNKNOWN": 0}
    for it in load_cert_items():
        path = outdir / f"{it['id']}.json"
        if path.exists():
            r = json.loads(path.read_text(encoding="utf-8"))
            ok[r.get("verdict", "?")] = ok.get(r.get("verdict", "?"), 0) + 1
            continue
        policy = it["policy"]
        a = {"source_span": it["edge"]["a"], "type": "UNKNOWN",
             "all_forms": [it["edge"]["a"]], "arguments": []}
        b = {"source_span": it["edge"]["b"], "type": "UNKNOWN",
             "all_forms": [it["edge"]["b"]], "arguments": []}
        rec = {"id": it["id"], "family": it["family"],
               "expected": it.get("expected_status")}
        t0 = time.time()
        cert = _ask(client, E3_EXT_SYSTEM_V2, e3_ext_user_v2(policy, a, b))
        rec["certificate"] = cert
        v = verify_certificate_v2(policy, cert, a, b)
        rec["deterministic"] = v
        if v["verdict"] == "SUPPORTED":
            ev = sanitize_quote(cert.get("relation_text"))
            judge = _ask(client, E3_JUDGE_SYSTEM_V2,
                         e3_judge_user_v2(ev, a, b))
            rec["endpoint_verifier"] = judge
            q1 = sanitize_quote(judge.get("q1_where_is_a"))
            q2 = sanitize_quote(judge.get("q2_where_is_b"))
            if judge.get("q3_relation_between_these_two") != "YES":
                rec["verdict"] = "UNSUPPORTED"
                rec["reason"] = "verifier_q3_no"
            elif not (q1 and span_in(ev, q1) is not None
                      and q2 and span_in(ev, q2) is not None):
                rec["verdict"] = "UNKNOWN"
                rec["reason"] = "verifier_q1q2_not_verbatim"
            elif judge.get("q5_relation_type") == "SEMANTIC_LINK":
                rec["verdict"] = "UNSUPPORTED"
                rec["reason"] = "semantic_link_routing"
            else:
                rec["verdict"] = "SUPPORTED"
                rec["direction"] = judge.get("q4_direction", "UNKNOWN")
                rec["relation_type"] = judge.get("q5_relation_type",
                                                 "UNKNOWN")
        else:
            rec["verdict"] = v["verdict"]
            rec["reason"] = v.get("reason")
        rec["latency_s"] = round(time.time() - t0, 2)
        path.write_text(json.dumps(rec, indent=1, ensure_ascii=False) + "\n",
                        encoding="utf-8")
        ok[rec["verdict"]] = ok.get(rec["verdict"], 0) + 1
        print(it["id"], rec.get("verdict"), rec.get("reason", ""),
              flush=True)
    # accuracy vs expected
    items = load_cert_items()
    correct = 0
    for it in items:
        f = outdir / f"{it['id']}.json"
        if f.exists():
            r = json.loads(f.read_text(encoding="utf-8"))
            exp = it.get("expected_status")
            got = r.get("verdict")
            # direction-sensitive positives: expected SUPPORTED + direction
            if exp == got:
                if exp == "SUPPORTED" and it.get("expected_direction"):
                    if r.get("direction") == it["expected_direction"]:
                        correct += 1
                else:
                    correct += 1
    print("verdict distribution:", ok)
    print(f"status accuracy: {correct}/{len(items)}")


if __name__ == "__main__":
    main()
