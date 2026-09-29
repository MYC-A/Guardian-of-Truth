"""F6 relation-stack replay — frozen v10 loop over F6 node builders.

Byte-verbatim exec-replay of the frozen w1_pipe3.py main() per-case
loop (identical mechanism to en_f5_run.py; smoke-verified there), with
swapped node builders. The frozen source is never modified.

Builders (directive section 17 oracles):
  gold    - Oracle 1: gold mentions -> one node per canonical event
  raw     - Oracle 3: raw LLM grounded mentions -> one node per mention
            (recall-oriented, source-faithful, NO merging - directive 20)
  goldid  - Oracle 2: raw LLM mentions + GOLD identity clustering
            (overlap-labeled: nodes whose best-overlap gold cid coincide
             merge; unmatched stay singletons)
  v10     - the NLP-first chain on F6 (LLM_SG frontend + hygiene + bnorm
            + frozen build_nodes_v3) for the direct comparison

Infra adaptations (documented, not pipeline changes): CrossEncoder on
CPU with the local HF cache; Mistral credentials from the local env.

Run: python3 en_f6_stack.py <builder> [suite]
"""
from __future__ import annotations

import json
import os
import sys
import textwrap
import time
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).parent

# credentials BEFORE importing the frozen chain (oc_common falls back
# to os.environ; nothing is printed)
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
from pl_common import Mistral  # noqa: E402

RAW = HERE / "outputs" / "raw"
OUTD = HERE / "outputs" / "stack"
SUITES = {
    "f6": IE / "frozen" / "level_f6_cases.json",
    "f6r": IE / "frozen" / "level_f6r_cases.json",
}
CE_CACHE = "/home/z/my-project/hf_cache"

SEM_TO_TYPE = {"ACTION": "EVENT", "CHECK": "CHECK",
               "STATE": "STATE_OR_FACET", "RECORD": "EVENT",
               "COMMUNICATION": "EVENT",
               "REFERENCE_TO_EVENT": "EVENT_REFERENCE", "OTHER": "ENTITY"}


def load_suite(name: str) -> dict[str, dict]:
    return {c["case_id"]: c for c in json.loads(
        SUITES[name].read_text(encoding="utf-8"))}


def _role_of(types: list[str]) -> str:
    t = max(set(types), key=types.count)
    return v10.TYPE_TO_ROLE.get(t, "UNKNOWN")


# ----------------------------------------------------------------- loop
_LOOP_SRC: str | None = None


def loop_source() -> str:
    global _LOOP_SRC
    if _LOOP_SRC is None:
        src = Path(v10.__file__).read_text(encoding="utf-8")
        lines = src.split("\n")
        start = next(i for i, l in enumerate(lines)
                     if l == "    for cid_, case in gold.items():")
        end = next(i for i, l in enumerate(lines)
                   if l.startswith('    print("W1 DOWN10"'))
        assert start < end, "loop extraction failed"
        _LOOP_SRC = textwrap.dedent("\n".join(lines[start:end]))
    return _LOOP_SRC


def _ask(client):
    def ask(system, user, max_tokens=600):
        for _ in range(4):
            try:
                r = client.ask(system, user, max_tokens=max_tokens)
                parsed, _err = Mistral.parse_json(r["raw"])
                if parsed:
                    return parsed
            except Exception:
                time.sleep(3)
        return {}
    return ask


def run_arm(arm_name: str, suite: str, build_fn, subdir: str) -> None:
    from sentence_transformers import CrossEncoder
    gold = load_suite(suite)
    rer = CrossEncoder("BAAI/bge-reranker-base", device="cpu",
                       max_length=512, cache_folder=CE_CACHE)
    client = Mistral(model="ministral-14b-latest",
                     cache_dir=OUTD / "_cache")
    outdir = OUTD / subdir
    outdir.mkdir(parents=True, exist_ok=True)
    ns = dict(vars(v10))
    ns.update({"gold": gold, "arm": "LLM_SG", "outdir": outdir,
               "build_nodes_v3": build_fn, "rer": rer, "client": client,
               "ask": _ask(client)})
    exec(compile(loop_source(), "<w1_pipe3_main_loop>", "exec"), ns)
    print(f"[stack:{arm_name}:{suite}] done -> {outdir}", flush=True)


# -------------------------------------------------------------- builders
def build_gold_nodes(arm: str, case: dict) -> list[dict]:
    """Oracle 1: one node per gold canonical event (all gold mentions of
    that cid as members)."""
    groups: dict[str, list] = defaultdict(list)
    for m in case["mentions"]:
        if m.get("cid"):
            groups[m.get("cid")].append(m)
    nodes = []
    for i, (cid, ms) in enumerate(sorted(
            groups.items(), key=lambda kv: kv[1][0]["start"])):
        forms = [m["span"] for m in ms]
        types = [m["type"] for m in ms]
        nodes.append({"node_id": f"N{i+1:02d}",
                      "members": [m["mid"] for m in ms],
                      "span": forms[0], "start": ms[0]["start"],
                      "type": max(set(types), key=types.count),
                      "role": _role_of(types),
                      "member_spans": forms, "arguments": []})
    return nodes


def _raw_nodes(case: dict, model_key: str, arm: str) -> list[dict]:
    f = RAW / model_key / arm / f"{case['case_id']}.json"
    if not f.exists():
        return []
    data = json.loads(f.read_text(encoding="utf-8"))
    nodes = []
    for i, m in enumerate(data["mentions"]):
        if not m.get("grounded") or m.get("start") is None:
            continue
        sem = m.get("type", "OTHER")
        ptype = SEM_TO_TYPE.get(sem, "EVENT")
        nodes.append({"node_id": f"L{i+1:02d}",
                      "members": [f"l{i+1:02d}"],
                      "span": m["quote"], "start": m["start"],
                      "end": m["end"],
                      "type": ptype, "role": v10.TYPE_TO_ROLE.get(ptype,
                                                                  "UNKNOWN"),
                      "member_spans": [m["quote"]],
                      "arguments": [{"role": a["role"], "span": a["quote"],
                                     "start": a["start"], "end": a["end"]}
                                    for a in (m.get("arguments") or [])]})
    return nodes


def build_raw_factory(model_key: str, arm: str):
    def build(arm_: str, case: dict) -> list[dict]:
        return _raw_nodes(case, model_key, arm)
    return build


def _gold_label_by_overlap(case: dict, node: dict):
    """Best-overlap gold cid for a node span (None if no event overlap)."""
    best, blab = 0.0, None
    for m in case["mentions"]:
        if not m.get("cid"):
            continue
        inter = max(0, min(node["end"], m["end"]) - max(node["start"],
                                                        m["start"]))
        if inter > best:
            best, blab = inter, m["cid"]
    if best == 0.0:
        return None
    # reject overlaps dominated by ENTITY gold spans: require >=1 overlap
    # with an EVENT-like gold mention carrying this cid
    for m in case["mentions"]:
        if m.get("cid") == blab and m["type"] not in ("ENTITY", "ARTIFACT"):
            inter = max(0, min(node["end"], m["end"]) -
                        max(node["start"], m["start"]))
            if inter > 0:
                return blab
    return None


def build_goldid_factory(model_key: str, arm: str):
    """Oracle 2: raw LLM nodes + GOLD identity (same best-overlap gold
    cid -> one merged node; unmatched stay singletons)."""
    def build(arm_: str, case: dict) -> list[dict]:
        nodes = _raw_nodes(case, model_key, arm)
        groups: dict[str, list] = defaultdict(list)
        for n in nodes:
            lab = _gold_label_by_overlap(case, n)
            key = lab if lab else f"__sing_{n['node_id']}"
            groups[key].append(n)
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
                        "type": max(set(types), key=types.count),
                        "role": _role_of(types),
                        "member_spans": forms,
                        "arguments": [a for n in ms
                                      for a in (n.get("arguments") or [])]})
        return out
    return build


def build_v10(arm: str, case: dict) -> list[dict]:
    return v10.build_nodes_v3("LLM_SG", case)


# ------------------------------------------------------------------ main
if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "gold"
    suite = sys.argv[2] if len(sys.argv) > 2 else "f6"
    if which == "gold":
        run_arm("oracle1", suite, build_gold_nodes,
                f"{suite}_oracle1")
    elif which == "raw":
        run_arm("oracle3", suite, build_raw_factory("mistral", "A"),
                f"{suite}_oracle3_mistralA")
    elif which == "rawB":
        run_arm("oracle3B", suite, build_raw_factory("mistral", "B"),
                f"{suite}_oracle3_mistralB")
    elif which == "rawc":
        run_arm("oracle3c", suite, build_raw_factory("codestral", "A"),
                f"{suite}_oracle3_codestralA")
    elif which == "goldid":
        run_arm("oracle2", suite, build_goldid_factory("mistral", "A"),
                f"{suite}_oracle2_mistralA")
    elif which == "v10":
        run_arm("v10", suite, build_v10, f"{suite}_v10")
    else:
        raise SystemExit(f"unknown builder {which}")
