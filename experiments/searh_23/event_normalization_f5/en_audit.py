"""v10 AUDIT — mechanism decomposition (directive §19, §3, §25).

Part 1 (node level, ZERO LLM): re-run build_nodes with toggles separating
  A = candidate sanitation / mention normalization (hygiene, bnorm survivors,
      form variants, spawning, junk filters, orphan-fragment drop, span-dedup)
  B = event identity (frontend-relation unions, deontic-subject attachment,
      deterministic consolidation)
Faithfulness check: toggles-off must reproduce saved W1_DOWN10 nodes exactly.

Part 2 (edge level, ZERO LLM): replay saved pair logs with relation guards
  toggled (C-part): per-guard FP-removed / FN-created + edge P/R deltas.

Part 3: same-action pair suppression cost (gold-mapping analysis).

Run (server): /workspace/guardian/venv/bin/python en_audit.py
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).parent
W1 = HERE.parent / "step1_working_v1"
IE = W1.parent / "event_ie_frontends_v1"
sys.path.insert(0, str(W1))
sys.path.insert(0, str(IE))

import w1_pipe3 as v10  # noqa: E402  (frozen v10 module)
from en_common import (load_gold, node_label, node_cluster_metrics,  # noqa
                       cluster_scores, node_clusters_as_sets,
                       gold_clusters_as_sets, mention_labels)

OUTD = HERE / "outputs"
AUP = OUTD / "audit"
AUP.mkdir(parents=True, exist_ok=True)


# ------------------------------------------------ Part 1: toggled node build
def build_nodes_toggle(arm, case, skip_unions=False, skip_consolidation=False,
                       skip_deontic_attach=False, skip_orphan_drop=False):
    """Faithful re-implementation of w1_pipe3.build_nodes_v3 with toggles.
    All logic copied verbatim from the frozen module; toggles only skip the
    identity (B) steps."""
    policy = case["policy"]
    cid = case["case_id"]
    orig = {c["cid_local"]: c for c in v10._load(IE / "outputs" / arm /
                                                 f"{cid}.json")}
    hyg = {c["cid_local"]: c for c in v10._load(v10.OUT / "W1_HYG" / arm /
                                                f"{cid}.json")}
    bn = []
    for d in reversed(v10.BNORM_DIRS):
        f = d / arm / f"{cid}.json"
        if f.exists():
            bn = v10._load(f)
            break
    survivors, spawned = {}, []
    for c in bn:
        if c.get("bnorm_decision") == "DROP":
            continue
        root = c["cid_local"].split("_b")[0]
        base = c.get("span") or ""
        dec = c.get("bnorm_decision") or "KEEP"
        o = orig.get(root) or hyg.get(root) or {}
        orig_span = o.get("span")
        embeds_foreign = False
        if orig_span and orig_span != base and dec != "SPLIT":
            for sp in v10._spawn_trailing(policy, orig_span):
                spawned.append(sp)
            if v10._spawn_trailing(policy, orig_span):
                embeds_foreign = True
        for sp in v10._spawn_trailing(policy, base) if base != orig_span \
                else []:
            spawned.append(sp)
        variants = v10._grounded_forms(policy, base,
                                       None if embeds_foreign else orig_span,
                                       dec)
        if not variants:
            continue
        rels = v10._harvest_relations(orig, hyg, root, base) or \
            (c.get("relations") or [])
        survivors[c["cid_local"]] = {
            "cid_local": c["cid_local"], "root": root,
            "span": variants[0], "forms": variants,
            "type": c.get("type") or o.get("type") or "UNKNOWN",
            "relations": rels,
            "start": policy.find(variants[0]),
            "arguments": [g for g in (c.get("arguments") or
                                      o.get("arguments") or [])
                          if isinstance(g.get("span"), str)]}
    existing_spans = {s["span"] for s in survivors.values()}
    for i, sp in enumerate(spawned):
        if sp["span"] in existing_spans:
            continue
        base = sp["span"]
        variants = v10._grounded_forms(policy, base, None, "KEEP")
        if not variants:
            continue
        survivors[f"spawn_{i}"] = {
            "cid_local": f"spawn_{i}", "root": f"spawn_{i}",
            "span": variants[0], "forms": variants,
            "type": sp["type"], "relations": [],
            "start": policy.find(variants[0]), "arguments": []}
    # b1 keep-override
    present_roots = {s["root"] for s in survivors.values()}
    for k, c in hyg.items():
        if k in present_roots or any(sk.startswith(k + "_b")
                                     for sk in survivors):
            continue
        span = c.get("span") or ""
        if not span or c.get("type") not in ("STATE_OR_FACET", "CHECK",
                                             "UNKNOWN"):
            continue
        if not v10.COPULA_ANY.search(span) or re.search(r"\bmust\b|\bshould\b",
                                                        span, re.I):
            continue
        if len(v10.COPULA_ANY.findall(span)) >= 2:
            continue
        if not v10._in_policy(policy, span):
            continue
        base = span
        if v10.COPULA_START.match(span.strip()):
            ext = v10.subject_extend(policy, span)
            if ext:
                base = ext
        variants = v10._grounded_forms(policy, base, None, "KEEP")
        survivors[k] = {"cid_local": k, "root": k, "span": variants[0],
                        "forms": variants,
                        "type": c.get("type"),
                        "relations": c.get("relations") or [],
                        "start": policy.find(variants[0]),
                        "arguments": c.get("arguments") or []}
    # junk filters
    kept, deontic_killed = {}, []
    for k, s in survivors.items():
        if s["type"] not in v10.EVENTLIKE:
            continue
        forms = s["forms"]
        if v10.MODAL_COPULA_START.match(s["span"].strip()):
            continue
        if all(len(f.split()) <= 2 and re.match(r"^[a-z]+ed$", f.strip(),
                                                re.I) for f in forms):
            continue
        if any(v10.DEONTIC_ADJ.search(f) for f in forms):
            m = re.match(r"^(.{2,60}?)\s+(is|are|was|were)\b", s["span"],
                         re.I)
            if m:
                deontic_killed.append((m.group(1).strip(), s["span"]))
            continue
        if any(v10.TAXONOMY_PRED.search(f) or v10.IDENTITY_NEG.search(f)
               for f in forms):
            continue
        if any(v10.ARTIFACT_SUBJ.match(f) and v10.COMM_VERB.search(f)
               for f in forms):
            continue
        kept[k] = s
    if not skip_deontic_attach:
        for subj, clause in deontic_killed:
            if not v10._in_policy(policy, subj):
                continue
            for k, s in kept.items():
                if v10.compatible_nodes([subj], s["forms"] or [s["span"]]):
                    for extra in (subj, clause):
                        if extra not in s["forms"] and \
                                v10._in_policy(policy, extra):
                            s["forms"].append(extra)
                    break
    by_span = defaultdict(list)
    for k, s in kept.items():
        by_span[s["span"]].append(k)
    for span, keys in by_span.items():
        if len(keys) > 1:
            main = keys[0]
            for other in keys[1:]:
                kept[main]["forms"] = list(dict.fromkeys(
                    kept[main]["forms"] + kept[other]["forms"]))
                kept[main]["relations"] = list(
                    {json.dumps(r, sort_keys=True): r for r in
                     kept[main]["relations"] + kept[other]["relations"]}
                    .values())
                kept[main]["arguments"] = kept[main]["arguments"] + \
                    kept[other]["arguments"]
                del kept[other]
    # orphan-fragment drop (A: fragment sanitation)
    if not skip_orphan_drop:
        spans_all = [s["span"] for s in kept.values()]
        for k, s in list(kept.items()):
            if s["type"] in ("EVENT_REFERENCE", "CHECK", "ENTITY",
                             "ARTIFACT") and not s["relations"]:
                for other in spans_all:
                    if other != s["span"] and s["span"] in other:
                        del kept[k]
                        break
    # B: frontend-relation unions (identity)
    parent = {k: k for k in kept}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x, y):
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[ry] = rx

    if not skip_unions:
        for k, s in kept.items():
            for r in s["relations"]:
                if r.get("type") in ("SAME_EVENT", "REFERENCE_OF") \
                        and r.get("to") in parent:
                    tgt = kept.get(r["to"])
                    if tgt and (re.search(r"\bagain\b", s["span"], re.I)
                                or re.search(r"\bagain\b", tgt["span"],
                                             re.I)):
                        continue
                    if not v10.compatible_nodes(
                            s["forms"] or [s["span"]],
                            tgt["forms"] or [tgt["span"]]):
                        continue
                    union(k, r["to"])
    groups = defaultdict(list)
    for k, s in kept.items():
        groups[find(k)].append(s)
    nodes = []
    for i, (root, members) in enumerate(sorted(
            groups.items(),
            key=lambda kv: min(m["start"] if m["start"] >= 0 else 10 ** 6
                               for m in kv[1]))):
        ms = sorted(members, key=lambda m: m["start"]
                    if m["start"] >= 0 else 10 ** 6)
        forms = []
        for m in ms:
            for f in m["forms"]:
                if f not in forms:
                    forms.append(f)
        types = [m["type"] for m in ms]
        nodes.append({
            "node_id": f"N{i+1:02d}",
            "members": [m["cid_local"] for m in ms],
            "span": forms[0], "start": ms[0]["start"],
            "type": max(set(types), key=types.count),
            "role": v10.TYPE_TO_ROLE.get(max(set(types), key=types.count),
                                         "UNKNOWN"),
            "member_spans": forms,
            "arguments": [a for m in ms for a in m["arguments"]]})
    if skip_consolidation:
        return nodes
    return v10.consolidate_nodes(nodes, policy)


# ------------------------------------------------------- Part 1 runner
def part1():
    configs = {
        "A_only": dict(skip_unions=True, skip_consolidation=True,
                       skip_deontic_attach=True),
        "A_plus_B": dict(),  # full v10 node build
    }
    report = {}
    for suite in ("main", "f2", "f3", "f4"):
        gold = load_gold(suite)
        for cname, cfg in configs.items():
            rows, faithful = [], True
            for cid_, case in gold.items():
                nodes = build_nodes_toggle("LLM_SG", case, **cfg)
                m = node_cluster_metrics(case, nodes)
                cl = cluster_scores(node_clusters_as_sets(case, nodes),
                                    gold_clusters_as_sets(case))
                m.update(cl)
                # faithfulness check vs saved v10 nodes (A_plus_B only)
                if cname == "A_plus_B":
                    saved = json.loads(
                        (W1 / "outputs" / "W1_DOWN10_LLM_SG" /
                         f"{cid_}.json").read_text())["nodes"] \
                        if (W1 / "outputs" / "W1_DOWN10_LLM_SG" /
                            f"{cid_}.json").exists() else None
                    if saved is not None:
                        got = sorted(
                            (n["span"], tuple(sorted(n["member_spans"])))
                            for n in nodes)
                        exp = sorted(
                            (n["span"], tuple(sorted(n["member_spans"])))
                            for n in saved)
                        if got != exp:
                            faithful = False
                            rows.append({"case": cid_,
                                         "faithful": False,
                                         "diff": [g for g in got
                                                  if g not in exp][:3]})
                rows.append({"case": cid_, **m})
            numeric = {k for k in rows[0]
                       if k not in ("case", "diff", "examples")
                       and isinstance(rows[0].get(k), (int, float))}
            agg = {}
            for k in sorted(numeric):
                if isinstance(rows[0].get(k), float):
                    agg[k] = round(
                        sum(r.get(k, 0) for r in rows) / max(1, len(gold)), 4)
                else:
                    agg[k] = sum(r.get(k, 0) for r in rows)
            report[f"{suite}:{cname}"] = {
                "aggregate": agg, "per_case": rows,
                "faithful": faithful if cname == "A_plus_B" else None}
            print(f"[part1] {suite} {cname}: cluster_recall="
                  f"{agg.get('cluster_recall')} node_precision="
                  f"{agg.get('node_precision')} conll={agg.get('conll_f')}"
                  f" faithful={report[f'{suite}:{cname}']['faithful']}")
    (AUP / "part1_node_ab.json").write_text(json.dumps(report, indent=1))
    return report


# ------------------------------------------------------- Part 2 guard replay
GATES = ["no_trigger_connective", "object_containment_gate",
         "cross_sentence_gate", "coordination_gate"]


def gold_edge_set(case):
    return {(e["from_cid"], e["to_cid"]): set(e["acceptable"])
            for e in case["normative_edges"]}


def replay_case(case, data, disable=frozenset()):
    """Re-derive licensed edges from the saved pair log with gates toggled.

    A pair becomes licensed iff it originally reached judge-YES stage
    (judge q3==YES, q1/q2 in evidence, not SEMANTIC_LINK) and no ACTIVE
    gate killed it. Revived pairs use the judge's q4/q5 (pre-override)."""
    nodes = {n["node_id"]: n for n in data.get("nodes", [])}
    licensed_edges = []
    killed = []
    for rec in data.get("pairs", []):
        stage = rec.get("stage")
        if stage in ("ce_band",):
            continue
        judge = rec.get("judge") or {}
        q3 = judge.get("q3_relation_between_these_two")
        q1ok = q2ok = False
        if stage in ("judge", "licensed"):
            q1ok = q2ok = True  # gate notes imply these already passed
        if stage == "licensed":
            licensed_edges.append(rec)
            continue
        note = rec.get("judge_note") or ""
        if note in ("verifier_q3_no", "verifier_q1q2_not_in_evidence",
                    "semantic_link_routing"):
            continue  # judge itself said no
        if note == "no_trigger_connective":
            if "no_trigger_connective" in disable:
                licensed_edges.append(rec)
            else:
                killed.append((rec, "no_trigger_connective"))
            continue
        if note == "object_containment_gate":
            if "object_containment_gate" in disable:
                licensed_edges.append(rec)
            else:
                killed.append((rec, "object_containment_gate"))
            continue
        if note == "cross_sentence_gate":
            if "cross_sentence_gate" in disable:
                licensed_edges.append(rec)
            else:
                killed.append((rec, "cross_sentence_gate"))
            continue
        if note == "coordination_gate":
            if "coordination_gate" in disable:
                licensed_edges.append(rec)
            else:
                killed.append((rec, "coordination_gate"))
            continue
        # verify-stage rejects (UNSUPPORTED etc.) stay dead
        continue
    return licensed_edges, killed


def edge_label_case(case, rec, nodes):
    u = nodes.get(rec.get("u"))
    v = nodes.get(rec.get("v"))
    if u is None or v is None:
        return None, None
    return node_label(case, u), node_label(case, v)


def score_edges(case, recs, nodes):
    """Strict edge scoring over replay-licensed records (approximation:
    direction from rec or judge q4; type from judge q5)."""
    gold = gold_edge_set(case)
    hits, extra, wrong_dir, dup = set(), 0, 0, 0
    for rec in recs:
        lu, lv = edge_label_case(case, rec, nodes)
        d = rec.get("direction")
        if d is None:
            judge = rec.get("judge") or {}
            q4 = judge.get("q4_direction")
            d = q4 if q4 in ("A_TO_B", "B_TO_A") else "UNKNOWN"
        if d == "B_TO_A":
            la, lb = lv, lu
        elif d == "A_TO_B":
            la, lb = lu, lv
        else:
            extra += 1
            continue
        if la in (None, "JUNK", "MIXED", "NON_EVENT") or \
                lb in (None, "JUNK", "MIXED", "NON_EVENT"):
            extra += 1
            continue
        if (la, lb) in gold:
            if (la, lb) in hits:
                dup += 1
            else:
                hits.add((la, lb))
        else:
            if (lb, la) in gold:
                wrong_dir += 1
            else:
                extra += 1
    g = len(gold)
    P = len(hits) / max(1, len(hits) + extra + wrong_dir + dup)
    R = len(hits) / max(1, g)
    return {"correct": len(hits), "extra": extra, "wrong_dir": wrong_dir,
            "dup": dup, "gold": g, "P": round(P, 3), "R": round(R, 3),
            "exact": len(hits) == g and extra + wrong_dir + dup == 0}


def part2():
    out = {}
    for suite, arm_dir in (("main", "W1_DOWN10_LLM_SG"),
                           ("f2", "W1_DOWN10_LLM_SG"),
                           ("f4", "W1_DOWN10_LLM_SG"),
                           ("f3", "W1_DOWN8_LLM_SG")):
        gold = load_gold(suite)
        prefix_counts = Counter()
        per_case = {}
        totals = {"base": Counter(), "all_gates_off": Counter()}
        guard_fp_fn = {g: {"gold_edges_killed": 0, "nongold_killed": 0}
                       for g in GATES}
        for cid_, case in gold.items():
            p = W1 / "outputs" / arm_dir / f"{cid_}.json"
            if not p.exists():
                continue
            data = json.loads(p.read_text())
            nodes = {n["node_id"]: n for n in data.get("nodes", [])}
            # base replay fidelity: must reproduce saved edges
            base_rec, killed = replay_case(case, data)
            saved_edges = [
                {"u": e["u"], "v": e["v"], "direction": e.get("direction")}
                for e in data.get("edges", [])]
            base_rec_ids = sorted((r["u"], r["v"]) for r in base_rec)
            saved_ids = sorted((e["u"], e["v"]) for e in saved_edges)
            # licensed edges in the saved file may differ from pair-log
            # 'licensed' stage only via consolidation drops (post-hoc);
            # count both
            prefix_counts[f"saved_edges_{len(saved_ids)}"] += 1
            prefix_counts[f"replayed_licensed_{len(base_rec_ids)}"] += 1
            base_score = score_edges(case, base_rec, nodes)
            totals["base"]["correct"] += base_score["correct"]
            totals["base"]["extra"] += base_score["extra"]
            totals["base"]["gold"] += base_score["gold"]
            # per-guard attribution
            for rec, gate in killed:
                lu, lv = edge_label_case(case, rec, nodes)
                d = rec.get("direction") or \
                    (rec.get("judge") or {}).get("q4_direction")
                if d == "B_TO_A":
                    la, lb = lv, lu
                else:
                    la, lb = lu, lv
                gold = gold_edge_set(case)
                if (la, lb) in gold or (lb, la) in gold:
                    guard_fp_fn[gate]["gold_edges_killed"] += 1
                else:
                    guard_fp_fn[gate]["nongold_killed"] += 1
            # all gates off
            all_off, _ = replay_case(case, data, disable=frozenset(GATES))
            off_score = score_edges(case, all_off, nodes)
            totals["all_gates_off"]["correct"] += off_score["correct"]
            totals["all_gates_off"]["extra"] += off_score["extra"]
            totals["all_gates_off"]["gold"] += off_score["gold"]
            per_case[cid_] = {"base": base_score, "gates_off": off_score,
                              "killed_pairs": [
                                  {"u": r.get("u"), "v": r.get("v"),
                                   "gate": g,
                                   "u_span": r.get("u_span"),
                                   "v_span": r.get("v_span")}
                                  for r, g in killed]}
        for k in ("base", "all_gates_off"):
            c = totals[k]
            c["P"] = round(c["correct"] /
                           max(1, c["correct"] + c["extra"] +
                               c.get("wrong_dir", 0) + c.get("dup", 0)), 3)
            c["R"] = round(c["correct"] / max(1, c["gold"]), 3)
        out[suite] = {"totals": dict(totals), "guard_fp_fn": guard_fp_fn,
                      "per_case": per_case}
        print(f"[part2] {suite}: base P={totals['base']['P']} "
              f"R={totals['base']['R']}; gates-off "
              f"P={totals['all_gates_off']['P']} "
              f"R={totals['all_gates_off']['R']}; guard attribution "
              f"{guard_fp_fn}")
    (AUP / "part2_guard_replay.json").write_text(json.dumps(out, indent=1))
    return out


# ------------------------------------------- Part 3 suppression cost (B)
def part3():
    """Same-action pair suppression: predicted node pairs (u,v) with
    compatible_nodes(u,v) are never proposed. Cost = gold edges whose
    endpoints map to such pairs. Also: shared-form / self-loop gates."""
    out = {}
    for suite, arm_dir in (("main", "W1_DOWN10_LLM_SG"),
                           ("f2", "W1_DOWN10_LLM_SG"),
                           ("f4", "W1_DOWN10_LLM_SG"),
                           ("f3", "W1_DOWN8_LLM_SG")):
        gold = load_gold(suite)
        sup = {"suppressed_pairs": 0, "suppressed_gold_edges": 0,
               "suppressed_nongold_pairs": 0, "examples": []}
        for cid_, case in gold.items():
            p = W1 / "outputs" / arm_dir / f"{cid_}.json"
            if not p.exists():
                continue
            data = json.loads(p.read_text())
            nodes = data.get("nodes", [])
            labels = {n["node_id"]: node_label(case, n) for n in nodes}
            gold = gold_edge_set(case)
            logged = {(r.get("u"), r.get("v")) for r in data.get("pairs",
                                                                 [])}
            for i in range(len(nodes)):
                for j in range(i + 1, len(nodes)):
                    ni, nj = nodes[i], nodes[j]
                    if (ni["node_id"], nj["node_id"]) in logged:
                        continue
                    if set(ni.get("members", [])) & \
                            set(nj.get("members", [])):
                        continue
                    if set(ni.get("member_spans", [])) & \
                            set(nj.get("member_spans", [])):
                        continue
                    if not v10.compatible_nodes(
                            ni.get("member_spans") or [ni["span"]],
                            nj.get("member_spans") or [nj["span"]]):
                        continue
                    sup["suppressed_pairs"] += 1
                    la, lb = labels[ni["node_id"]], labels[nj["node_id"]]
                    if (la, lb) in gold or (lb, la) in gold:
                        sup["suppressed_gold_edges"] += 1
                        if len(sup["examples"]) < 12:
                            sup["examples"].append(
                                {"case": cid_, "u": ni["span"],
                                 "v": nj["span"], "labels": [la, lb]})
                    else:
                        sup["suppressed_nongold_pairs"] += 1
        out[suite] = sup
        print(f"[part3] {suite}: {sup}")
    (AUP / "part3_suppression.json").write_text(json.dumps(out, indent=1))
    return out


if __name__ == "__main__":
    part1()
    part2()
    part3()
    print("audit complete ->", AUP)
