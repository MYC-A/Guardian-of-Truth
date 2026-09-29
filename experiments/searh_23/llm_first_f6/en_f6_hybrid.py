"""F6 hybrid arm — raw LLM mentions + FROZEN deterministic span hygiene
+ FROZEN deterministic identity (compatible_nodes) -> frozen stack.

COMPOSITION DISCIPLINE (honesty note): every mechanism here is a
pre-existing frozen component (w1_hygiene's LEADING_CONNECTIVES strip;
w1_pipe3's compatible_nodes predicate; the frozen relation stack). The
COMPOSITION was motivated post-hoc by diagnosing oracle2/oracle3
failures on F6 (leading-connective spans and unmerged duplicates damage
the stack) - it is labeled post-hoc in the report and requires F7
confirmation, per the anti-leakage directive section 18.

Run: python3 en_f6_hybrid.py [mistral|codestral] [A|B]
"""
from __future__ import annotations

import json
import os
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).parent
_env = Path("/home/z/my-project/guardian-access/mistral.env")
if _env.is_file() and not os.environ.get("MISTRAL_API_KEY"):
    for line in _env.read_text().splitlines():
        line = line.strip()
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip("\"'"))
os.environ.setdefault("HF_HOME", "/home/z/my-project/hf_cache")

W1 = HERE.parent / "step1_working_v1"
IE = HERE.parent / "event_ie_frontends_v1"
sys.path[:0] = [str(W1), str(IE), str(HERE)]

import w1_pipe3 as v10  # noqa: E402
import en_f6_stack as st  # noqa: E402

RAW = HERE / "outputs" / "raw"

# frozen regex from w1_hygiene (byte-identical semantics)
LEADING_CONNECTIVES = v10.re.compile(
    r"^(only\s+(when|if|after|before)|after|before|when|if|unless|until|"
    r"provided\s+that|once|while)\b[\s,]+", v10.re.I)


def strip_leading(policy: str, span: str, start: int):
    """Apply the frozen hygiene connective strip to one raw span."""
    s = span
    off = start
    for _ in range(3):
        m = LEADING_CONNECTIVES.match(s)
        if not m:
            break
        cut = m.end()
        # re-anchor: skip the stripped prefix at the original offset
        off += len(s[:cut])
        s = s[cut:].lstrip()
    if not s or s not in policy[off:off + len(s)]:
        # fall back to case-insensitive re-find
        idx = policy.find(s)
        if idx >= 0:
            off = idx
        else:
            return None
    return s, off


def build_hybrid(model_key: str, arm: str):
    def build(arm_: str, case: dict) -> list[dict]:
        nodes = st._raw_nodes(case, model_key, arm)
        # 1) frozen hygiene: strip leading connectives
        cleaned = []
        for n in nodes:
            r = strip_leading(case["policy"], n["span"], n["start"])
            if r:
                n["span"], n["start"] = r
                n["end"] = n["start"] + len(n["span"])
                n["member_spans"] = [n["span"]]
            cleaned.append(n)
        # 2) frozen deterministic identity: compatible_nodes merging
        parent = {n["node_id"]: n["node_id"] for n in cleaned}

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        for i in range(len(cleaned)):
            for j in range(i + 1, len(cleaned)):
                a, b = cleaned[i], cleaned[j]
                if v10.compatible_nodes(
                        a.get("member_spans") or [a["span"]],
                        b.get("member_spans") or [b["span"]]):
                    ra = case["policy"].find(a["span"])
                    rb = case["policy"].find(b["span"])
                    if ra >= 0 and rb >= 0:
                        # same-event facets: merge positionally
                        parent[find(b["node_id"])] = find(a["node_id"])
        groups: dict[str, list] = defaultdict(list)
        for n in cleaned:
            groups[find(n["node_id"])].append(n)
        out = []
        ordered = sorted(groups.items(),
                         key=lambda kv: min(n["start"] for n in kv[1]))
        for i, (_k, ns_) in enumerate(ordered):
            ms = sorted(ns_, key=lambda n: n["start"])
            forms = []
            for n in ms:
                for f_ in (n.get("member_spans") or [n["span"]]):
                    if f_ not in forms:
                        forms.append(f_)
            types = [n["type"] for n in ms]
            out.append({"node_id": f"N{i+1:02d}",
                        "members": [m for n in ms for m in n["members"]],
                        "span": forms[0], "start": ms[0]["start"],
                        "end": ms[-1]["end"],
                        "type": max(set(types), key=types.count),
                        "role": st._role_of(types),
                        "member_spans": forms,
                        "arguments": [a for n in ms
                                      for a in (n.get("arguments") or [])]})
        return out
    return build


if __name__ == "__main__":
    model_key = sys.argv[1] if len(sys.argv) > 1 else "mistral"
    arm = sys.argv[2] if len(sys.argv) > 2 else "A"
    st.run_arm(f"hyb_{model_key}{arm}", "f6",
               build_hybrid(model_key, arm), f"f6_hyb_{model_key}{arm}")
