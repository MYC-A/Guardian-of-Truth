"""EN-2: F5 single-round inference orchestrator (Event Normalization
Generalization phase, directive §11 pre-registered arms).

Stages (all idempotent: per-case output files are skipped when present):
  frontend <suite>  - LLM_SG extraction (frozen prompts, module-swap)
  hygiene <suite>   - deterministic candidate hygiene
  bnorm <suite>     - LLM boundary normalizer (frozen prompts; writes into
                      the SAME W1_BNORM_383f5df9/LLM_SG dir as the frozen
                      chain, new per-case files only)
  arm <name> <suite> - relation-stack arms via BYTE-VERBATIM exec-replay of
                      the frozen w1_pipe3.py main() loop with a swapped
                      build_nodes_v3:
                      v10      - frozen v10 build_nodes_v3
                      v11      - v10 + H.3 POS-anchored signature (SigPatch
                                 scoped to node build; D4-promoted)
                      oracleA  - gold nodes (perfect sanitation+identity)
                      oracleB  - A-layer sanitation + GOLD identity clustering
                      modular  - A-layer sanitation + H-and-F identity
                                 clustering (needs f5_modular_decisions.json
                                 from en_f5_identity.py)
  nodes <name> <suite> - node builds only (for CF twins)
  smoke             - faithfulness check: replay v10 loop on one dev case,
                      diff against the saved W1_DOWN10 output

Suites: f5 (20 sealed cases), f5r (6 renamed), cf (5 twin pairs, sides
as cases, no tools / no relation stack).

The replay executes the EXACT source text of the frozen loop (extracted
from w1_pipe3.py between 'for cid_, case in gold.items():' and the final
print) with namespace = module globals + {gold, outdir, arm, ask, rer,
client, build_nodes_v3}. No frozen file is modified.

Run (server): /workspace/guardian/venv/bin/python en_f5_run.py <cmd> ...
"""
from __future__ import annotations

import json
import sys
import textwrap
import time
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).parent
IE = HERE.parent / "event_ie_frontends_v1"
W1 = HERE.parent / "step1_working_v1"
sys.path[:0] = [str(W1), str(IE), str(HERE)]

import w1_pipe3 as v10  # noqa: E402  (frozen v10 module)
from pl_common import Mistral  # noqa: E402

ARMDIR = HERE / "outputs" / "arms"

SUITES = {
    "f5": IE / "frozen" / "level_f5_cases.json",
    "f5r": IE / "frozen" / "level_f5r_cases.json",
}


def load_suite(name: str) -> dict[str, dict]:
    if name in SUITES:
        return {c["case_id"]: c for c in json.loads(
            SUITES[name].read_text(encoding="utf-8"))}
    if name == "cf":
        tw = json.loads((HERE / "f5_frozen" / "f5_cf_twins.json")
                        .read_text(encoding="utf-8"))["twins"]
        out = {}
        for t in tw:
            for side in ("a", "b"):
                cid = f"{t['twin_id']}_{side}"
                out[cid] = {"case_id": cid, "domain": "cf",
                            "family": t["mechanism"],
                            "policy": t[side]["policy"], "tools": [],
                            "mentions": [], "sentences": [],
                            "canonical_events": [], "entities": [],
                            "arguments": [], "semantic_links": [],
                            "normative_edges": [],
                            "expected": t[side]["expected"],
                            "focus": t[side]["focus"]}
        return out
    raise SystemExit(f"unknown suite {name}")


# ---------------------------------------------------------------- stages
def stage_frontend(suite: str) -> None:
    import lf_llm_frontends as fe
    cases = list(load_suite(suite).values())
    fe.load_suite = lambda which: cases
    fe.run_llm_sg("original")


def stage_hygiene(suite: str) -> None:
    import w1_hygiene as hyg
    cases = list(load_suite(suite).values())
    hyg.load_suite = lambda: cases
    old = sys.argv[:]
    sys.argv[:] = ["w1_hygiene.py", "LLM_SG"]
    try:
        hyg.main()
    finally:
        sys.argv[:] = old


def stage_bnorm(suite: str) -> None:
    import w1_bnorm as bn
    cases = list(load_suite(suite).values())
    bn.load_suite = lambda: cases
    old = sys.argv[:]
    sys.argv[:] = ["w1_bnorm.py", "LLM_SG"]
    try:
        bn.main()
    finally:
        sys.argv[:] = old


# ---------------------------------------------------- relation-stack replay
_LOOP_SRC: str | None = None


def loop_source() -> str:
    """Extract the frozen per-case loop from w1_pipe3.py main(), dedented.

    Byte-verbatim reuse: the extracted text is executed as-is (see run_arm).
    """
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


def run_arm(arm_name: str, suite: str, build_fn, outdir: Path) -> None:
    from sentence_transformers import CrossEncoder
    gold = load_suite(suite)
    rer = CrossEncoder("BAAI/bge-reranker-base", device="cuda",
                       max_length=512,
                       cache_folder="/workspace/guardian/hf_cache")
    client = Mistral(model="ministral-14b-latest",
                     cache_dir=v10.OUT / "_cache")
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    ns = dict(vars(v10))
    ns.update({"gold": gold, "arm": "LLM_SG", "outdir": outdir,
               "build_nodes_v3": build_fn, "rer": rer, "client": client,
               "ask": _ask(client)})
    exec(compile(loop_source(), "<w1_pipe3_main_loop>", "exec"), ns)
    print(f"[arm:{arm_name}:{suite}] done -> {outdir}", flush=True)


# ---------------------------------------------------------------- builders
def _role_of(types: list[str]) -> str:
    t = max(set(types), key=types.count)
    return v10.TYPE_TO_ROLE.get(t, "UNKNOWN")


def build_v10(arm: str, case: dict) -> list[dict]:
    return v10.build_nodes_v3("LLM_SG", case)


def f5_pos_maps(suite: str) -> dict:
    cache = HERE / "outputs" / f"_pos_maps_{suite}.json"
    if cache.exists():
        return json.loads(cache.read_text())
    import stanza
    nlp = stanza.Pipeline("en", processors="tokenize,pos", verbose=False,
                          use_gpu=True)
    maps = {}
    for cid, case in load_suite(suite).items():
        doc = nlp(case["policy"])
        pm: dict[str, str] = {}
        for s in doc.sentences:
            for w in s.words:
                pm.setdefault(w.text.lower(), w.upos)
        maps[cid] = pm
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(maps))
    return maps


def build_v11_factory(suite: str):
    from en_h34_nodes import pos_action_signature
    maps = f5_pos_maps(suite)

    def build_v11(arm: str, case: dict) -> list[dict]:
        pm = maps.get(case["case_id"])
        orig = v10.action_signature

        class P:
            def __call__(self, span):
                got = pos_action_signature(span, pm)
                if got is not None:
                    return got
                return orig(span)

        v10.action_signature = P()
        try:
            return v10.build_nodes_v3("LLM_SG", case)
        finally:
            v10.action_signature = orig
    return build_v11


def build_gold_nodes(arm: str, case: dict) -> list[dict]:
    """Oracle A: one node per gold canonical event (all its gold mentions
    as members). Perfect sanitation AND perfect identity."""
    groups: dict[str, list] = defaultdict(list)
    for m in case["mentions"]:
        if m.get("cid"):
            groups[m["cid"]].append(m)
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


def _alayer(case: dict) -> list[dict]:
    from en_audit import build_nodes_toggle
    return build_nodes_toggle("LLM_SG", case, skip_unions=True,
                              skip_consolidation=True,
                              skip_deontic_attach=True)


def _merge_group(nodes: list[dict], policy: str) -> dict:
    ms = sorted(nodes, key=lambda n: n.get("start") or 10 ** 6)
    forms: list[str] = []
    for n in ms:
        for f in (n.get("member_spans") or [n["span"]]):
            if f not in forms:
                forms.append(f)
    types = [n.get("type") or "UNKNOWN" for n in ms]
    return {"node_id": "",  # assigned by caller
            "members": [m for n in ms for m in n["members"]],
            "span": forms[0], "start": ms[0].get("start"),
            "type": max(set(types), key=types.count),
            "role": _role_of(types),
            "member_spans": forms,
            "arguments": [a for n in ms for a in (n.get("arguments")
                                                  or [])]}


def build_oracle_b_factory():
    """Oracle B: A-layer sanitation nodes + GOLD identity clustering
    (nodes whose gold label is the same cid merge; junk/unlabeled stay
    singletons)."""
    from en_common import node_label

    def build(arm: str, case: dict) -> list[dict]:
        policy = case["policy"]
        al = _alayer(case)
        groups: dict[str, list] = defaultdict(list)
        for n in al:
            lab = node_label(case, n)
            if lab and lab not in ("MIXED", "NON_EVENT"):
                groups[lab].append(n)
            else:
                groups[f"__sing_{n['node_id']}"].append(n)
        out = []
        ordered = sorted(
            groups.items(),
            key=lambda kv: min(n.get("start") or 10 ** 6
                               for n in kv[1]))
        for i, (_k, ns_) in enumerate(ordered):
            g = _merge_group(ns_, policy)
            g["node_id"] = f"N{i+1:02d}"
            out.append(g)
        return out
    return build


def build_modular_factory():
    """Modular architecture: A-layer sanitation + H-and-F identity
    clustering (veto = union-find over direct SAME_EVENT decisions only).
    Decisions come from en_f5_identity.py (H pre-filter, else F4way judge,
    AMBIGUOUS = no merge) over A-layer candidate pairs."""
    dec_path = HERE / "outputs" / "identity" / "f5_modular_decisions.json"
    if not dec_path.exists():
        raise SystemExit("f5_modular_decisions.json missing - run "
                         "en_f5_identity.py first")
    decisions = json.loads(dec_path.read_text(encoding="utf-8"))

    def build(arm: str, case: dict) -> list[dict]:
        policy = case["policy"]
        al = _alayer(case)
        parent = {n["node_id"]: n["node_id"] for n in al}

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(a, b):
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[rb] = ra

        by_span: dict[str, str] = {}
        for n in al:
            for f in (n.get("member_spans") or [n["span"]]):
                by_span.setdefault(f, n["node_id"])
        for d in decisions.get(case["case_id"], []):
            if d.get("label") != "SAME_EVENT":
                continue
            ia, ib = by_span.get(d.get("a")), by_span.get(d.get("b"))
            if ia and ib and ia != ib:
                union(ia, ib)
        groups: dict[str, list] = defaultdict(list)
        for n in al:
            groups[find(n["node_id"])].append(n)
        out = []
        ordered = sorted(
            groups.items(),
            key=lambda kv: min(n.get("start") or 10 ** 6
                               for n in kv[1]))
        for i, (_k, ns_) in enumerate(ordered):
            g = _merge_group(ns_, policy)
            g["node_id"] = f"N{i+1:02d}"
            out.append(g)
        return out
    return build


ARMS = {
    "v10": lambda suite: build_v10,
    "v11": lambda suite: build_v11_factory(suite),
    "oracleA": lambda suite: build_gold_nodes,
    "oracleB": lambda suite: build_oracle_b_factory(),
    "modular": lambda suite: build_modular_factory(),
}


# ---------------------------------------------------------------- commands
def cmd_arm(name: str, suite: str) -> None:
    if name not in ARMS:
        raise SystemExit(f"unknown arm {name}; have {sorted(ARMS)}")
    build_fn = ARMS[name](suite)
    outdir = ARMDIR / f"{suite}_{name}"
    run_arm(name, suite, build_fn, outdir)


def cmd_nodes(name: str, suite: str) -> None:
    if name not in ARMS:
        raise SystemExit(f"unknown arm {name}")
    build_fn = ARMS[name](suite)
    outdir = HERE / "outputs" / f"nodes_{suite}"
    outdir.mkdir(parents=True, exist_ok=True)
    out = {}
    for cid, case in load_suite(suite).items():
        out[cid] = build_fn("LLM_SG", case)
        print(cid, len(out[cid]), "nodes", flush=True)
    (outdir / f"{name}.json").write_text(json.dumps(out, indent=1))
    print(f"[nodes:{name}:{suite}] -> {outdir / (name + '.json')}")


def cmd_smoke() -> None:
    """Faithfulness: replay the v10 loop on ONE dev case into a temp dir
    and diff against the saved W1_DOWN10 output (nodes/edges/pairs)."""
    from en_common import load_gold
    gold = load_gold("main")
    cid = "f_bottling"
    case = gold[cid]
    saved = json.loads((v10.OUT / "W1_DOWN10_LLM_SG" /
                        f"{cid}.json").read_text(encoding="utf-8"))
    outdir = HERE / "outputs" / "_smoke"
    outdir.mkdir(parents=True, exist_ok=True)
    f = outdir / f"{cid}.json"
    if f.exists():
        f.unlink()
    from sentence_transformers import CrossEncoder
    rer = CrossEncoder("BAAI/bge-reranker-base", device="cuda",
                       max_length=512,
                       cache_folder="/workspace/guardian/hf_cache")
    client = Mistral(model="ministral-14b-latest",
                     cache_dir=v10.OUT / "_cache")
    ns = dict(vars(v10))
    ns.update({"gold": {cid: case}, "arm": "LLM_SG", "outdir": outdir,
               "build_nodes_v3": lambda arm, c: v10.build_nodes_v3(
                   "LLM_SG", c),
               "rer": rer, "client": client, "ask": _ask(client)})
    exec(compile(loop_source(), "<w1_pipe3_main_loop>", "exec"), ns)
    fresh = json.loads(f.read_text(encoding="utf-8"))
    # structural comparison
    def norm_nodes(nodes):
        return [(n["node_id"], n["span"], tuple(n["members"]),
                 tuple(n["member_spans"]), n.get("type"))
                for n in nodes]

    def norm_edges(edges):
        return [(e["u"], e["v"], e.get("relation"), e.get("direction"))
                for e in edges]

    ok_nodes = norm_nodes(saved["nodes"]) == norm_nodes(fresh["nodes"])
    ok_edges = norm_edges(saved["edges"]) == norm_edges(fresh["edges"])
    ok_pairs = len(saved.get("pairs", [])) == len(fresh.get("pairs", []))
    print(f"[smoke] nodes_equal={ok_nodes} edges_equal={ok_edges} "
          f"pairs_len_equal={ok_pairs} "
          f"(saved {len(saved['nodes'])}n/{len(saved['edges'])}e/"
          f"{len(saved.get('pairs', []))}p vs fresh "
          f"{len(fresh['nodes'])}n/{len(fresh['edges'])}e/"
          f"{len(fresh.get('pairs', []))}p)")
    if not (ok_nodes and ok_edges):
        print("[smoke] DETAIL saved-edges:", norm_edges(saved["edges"]))
        print("[smoke] DETAIL fresh-edges:", norm_edges(fresh["edges"]))
        raise SystemExit("smoke FAILED - replay is not faithful")
    print("[smoke] PASS - exec-replay is faithful to the frozen v10 loop")


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(1)
    cmd = sys.argv[1]
    if cmd == "frontend":
        stage_frontend(sys.argv[2])
    elif cmd == "hygiene":
        stage_hygiene(sys.argv[2])
    elif cmd == "bnorm":
        stage_bnorm(sys.argv[2])
    elif cmd == "arm":
        cmd_arm(sys.argv[2], sys.argv[3])
    elif cmd == "nodes":
        cmd_nodes(sys.argv[2], sys.argv[3])
    elif cmd == "smoke":
        cmd_smoke()
    else:
        raise SystemExit(f"unknown command {cmd}")


if __name__ == "__main__":
    main()
