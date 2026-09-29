"""W1 cert replay: reconstruct extractor requests for failing pairs and
read the cached LLM answers (no new LLM calls).

Run: python3 w1_replay.py <case_id> <u_node> <v_node>
"""
from __future__ import annotations

import glob
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).parent
IE = HERE.parent / "event_ie_frontends_v1"
PL = HERE.parent / "policy_licensing_v1"
sys.path[:0] = [str(PL), str(IE), str(HERE)]
from w1_pipeline import (E3_EXT_SYSTEM_V2, E3_JUDGE_SYSTEM_V2,  # noqa: E402
                          build_nodes, node_view, e3_ext_user_v2,
                          e3_judge_user_v2)
from lf_certificate import sanitize_quote  # noqa: E402

OUT = HERE / "outputs"
MODEL = "ministral-14b-latest"


def cache_get(system: str, user: str, mt: int) -> dict | None:
    blob = json.dumps({"m": MODEL, "s": system, "u": user, "t": mt},
                      ensure_ascii=False, sort_keys=True)
    key = hashlib.sha256(blob.encode()).hexdigest()
    f = OUT / "_cache" / f"{key}.json"
    if f.is_file():
        return json.loads(f.read_text(encoding="utf-8"))
    return None


def main() -> None:
    cid, uid, vid = sys.argv[1], sys.argv[2], sys.argv[3]
    suite = "level_f2_cases.json"
    case = next(c for c in json.loads(
        (IE / "frozen" / suite).read_text(encoding="utf-8"))
        if c["case_id"] == cid)
    data = json.loads((OUT / "W1_DOWN_LLM_SG" / f"{cid}.json")
                      .read_text(encoding="utf-8"))
    # rebuild nodes exactly as the pipeline did (bnorm candidates)
    nodes = build_nodes("LLM_SG", case)
    by_id = {n["node_id"]: n for n in nodes}
    na, nb = by_id[uid], by_id[vid]
    # governed tools are needed only for tool_text in CE, not in ext prompt
    ev_a, ev_b = node_view(case, na), node_view(case, nb)
    print("ENDPOINT A forms:", ev_a["all_forms"], "type:", ev_a.get("type"))
    print("ENDPOINT B forms:", ev_b["all_forms"], "type:", ev_b.get("type"))
    user = e3_ext_user_v2(case["policy"], ev_a, ev_b)
    r = cache_get(E3_EXT_SYSTEM_V2, user, 500)
    print("\nPOLICY:\n", case["policy"], "\n")
    print("=== EXTRACTOR ANSWER ===")
    print(r["raw"] if r else "CACHE MISS")
    if r:
        import re
        m = re.search(r"\{.*\}", r["raw"], re.S)
        cert = json.loads(m.group(0)) if m else {}
        rel = sanitize_quote(cert.get("relation_text"))
        ev = sanitize_quote(cert.get("relation_text"))
        juser = e3_judge_user_v2(ev, ev_a, ev_b)
        jr = cache_get(E3_JUDGE_SYSTEM_V2, juser, 400)
        print("\n=== JUDGE ANSWER ===")
        print(jr["raw"] if jr else "CACHE MISS / not reached")


if __name__ == "__main__":
    main()
