"""Frozen Level E3 assembly: eventness gate and B3 identity over REAL spans.

Never reads the E3 alignment or gold. It consumes the untouched old F/veto
candidate pairs and preserves UNKNOWN as a singleton/uncertain node.
"""
from __future__ import annotations

import argparse
import json
import sys

HERE = __import__("pathlib").Path(__file__).parent
EC = HERE.parent / "event_canon_v1"
sys.path[:0] = [str(HERE), str(EC)]
from ec_common import load_suite, out_dir, Mistral
from ec_track_b import cluster_to_nodes
from ec_cluster import build_clusters
from le_eventness import SYSTEM_A4, llm_label
from le_identity import SYSTEM_CORE_ID, ask, payload

BASE = "TRACKB_F_pol_veto"
EVENTLIKE = {"EVENT", "EVENT_REFERENCE", "STATE", "UNKNOWN"}


def eventness() -> None:
    client = Mistral(cache_dir=out_dir("_cache"))
    for case in load_suite("original"):
        cid = case["case_id"]
        events = json.loads((out_dir("FRONTEND") / f"{cid}.json").read_text(encoding="utf-8"))["events"]
        for i, p in enumerate(events):
            dst = out_dir("E3_EVENTNESS") / f"{cid}__P{i:02d}.json"
            if dst.exists():
                continue
            policy = case["policy"]
            # Oversized predicted spans can cross sentence boundaries. Keep
            # the full exact span and one adjacent clause as local context.
            lo = max(0, p["span_start"] - 100)
            hi = min(len(policy), p["span_end"] + 100)
            row = {"span": p["span"], "sentence": policy[lo:hi]}
            label, record = llm_label(client, SYSTEM_A4, row, 120)
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text(json.dumps({"case_id": cid, "i": i, "span": p["span"],
                                       "label": label, "record": record}, indent=2) + "\n", encoding="utf-8")
            print(cid, i, label, flush=True)
    print(json.dumps({"calls": client.calls, "usage": client.usage_total}), flush=True)


def corepairs() -> None:
    import stanza
    nlp = stanza.Pipeline("en", processors="tokenize,pos,lemma,depparse", verbose=False, use_gpu=True)
    client = Mistral(cache_dir=out_dir("_cache"))
    for case in load_suite("original"):
        cid = case["case_id"]
        base = json.loads((out_dir(BASE) / f"{cid}.json").read_text(encoding="utf-8"))
        mentions = {m["mid"]: m for m in base["mentions"]}
        for a, b in base["candidates"]:
            dst = out_dir("E3_B3_PAIRS") / f"{cid}__{a}__{b}.json"
            if dst.exists():
                continue
            row = {"id": f"{cid}::{a}::{b}", "policy": case["policy"], "a": mentions[a], "b": mentions[b]}
            content = payload(row, "B3_raw_core", nlp)
            result = ask(client, SYSTEM_CORE_ID, content)
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text(json.dumps({"a": a, "b": b, "input": content, **result},
                                      ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(cid, a, b, result["label"], flush=True)
    print(json.dumps({"calls": client.calls, "usage": client.usage_total}), flush=True)


def assemble() -> None:
    names = ("EVENTNESS_ONLY", "CANON_F", "EVENTNESS_CANON_F", "CANON_B3", "EVENTNESS_CANON_B3")
    for case in load_suite("original"):
        cid = case["case_id"]
        base = json.loads((out_dir(BASE) / f"{cid}.json").read_text(encoding="utf-8"))
        mentions = base["mentions"]
        elabs = {f"P{i:02d}": json.loads((out_dir("E3_EVENTNESS") / f"{cid}__P{i:02d}.json").read_text(encoding="utf-8"))["label"]
                 for i in range(len(mentions))}
        b3 = [json.loads((out_dir("E3_B3_PAIRS") / f"{cid}__{a}__{b}.json").read_text(encoding="utf-8"))
              for a, b in base["candidates"]]
        for name in names:
            dst = out_dir(f"TRACKB_{name}") / f"{cid}.json"
            if name == "CANON_F":
                nodes = base["nodes"]
                pair_src = base["pair_src"]
                subset = mentions
                assignment = base["assign"]
            else:
                gated = name.startswith("EVENTNESS")
                subset = [m for m in mentions if not gated or elabs[m["mid"]] in EVENTLIKE]
                mids = {m["mid"] for m in subset}
                pair_src = (b3 if name.endswith("B3") else base["pair_src"])
                pair_src = [p for p in pair_src if p["a"] in mids and p["b"] in mids]
                if name == "EVENTNESS_ONLY":
                    assignment = {m["mid"]: f"singleton_{m['mid']}" for m in subset}
                else:
                    assignment = build_clusters(pair_src, "veto")
                nodes = cluster_to_nodes(case, subset, assignment)
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text(json.dumps({"case_id": cid, "mentions": subset,
                                       "assign": assignment, "nodes": nodes, "pair_src": pair_src,
                                       "retained_eventness": elabs}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(cid, name, len(nodes), flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("phase", choices=("eventness", "corepairs", "assemble"))
    phase = ap.parse_args().phase
    {"eventness": eventness, "corepairs": corepairs, "assemble": assemble}[phase]()
