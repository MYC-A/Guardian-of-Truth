"""Arm C: AMR event candidates and event relations (amrlib BART-large + RBW aligner).

Parses each policy sentence to AMR, aligns nodes to source tokens (RBW
rule-based word aligner; tokens injected as graph metadata), extracts
predicate concepts (events) with aligned source spans, and derives
structural signals from generic AMR relations only:
  event under :condition    -> PRECONDITION_CHECK hypothesis + GATE edge
  event under :concession   -> EVEN_IF edge to parent
  before/after :time concepts -> ORDER_BEFORE edge between the two events
  top-level event           -> OPERATION_EFFECT hypothesis
No domain word lists; only AMR relation types and senses are used.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from oc_common import load_suite, out_dir, write_usage, suffix_for


def split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p for p in parts if p.strip()]


def tokenize(sentence: str):
    out = []
    for m in re.finditer(r"[A-Za-z][A-Za-z0-9'-]*|[0-9]+(?:\.[0-9]+)?", sentence):
        out.append((m.group(0), m.start(), m.end()))
    return out


def align_graph(graph_str: str, sentence: str):
    """Decode, inject tokens/lemmas metadata, run RBW aligner, return graph."""
    import penman
    from amrlib.alignments.rbw_aligner import RBWAligner
    from amrlib.alignments.penman_utils import NoOpModel
    g = penman.decode(graph_str, model=NoOpModel())
    toks = tokenize(sentence)
    if "tokens" not in g.metadata:
        g.metadata["tokens"] = json.dumps([t[0] for t in toks])
        g.metadata["lemmas"] = json.dumps([t[0].lower() for t in toks])
    aligner = RBWAligner.from_penman_w_json(g)
    return aligner.get_penman_graph(), toks


def node_alignments(g, toks):
    """Map node id -> (char_start, char_end) from penman alignment markers."""
    out = {}
    for triple, markers in g.epidata.items():
        for m in markers:
            cls = type(m).__name__
            if "Alignment" not in cls:
                continue
            targets = getattr(m, "targets", None)
            if not targets:
                continue
            idxs = [t for t in targets if isinstance(t, int) and 0 <= t < len(toks)]
            if not idxs:
                continue
            start = toks[min(idxs)][1]
            end = toks[max(idxs)][2]
            out[triple[0]] = (start, end)
    return out


def extract_events(g, toks, sentence, node_tok):
    concept = {}
    for triple in g.triples:
        if triple[1] == ":instance":
            concept[triple[0]] = triple[2]

    events = {n: {"concept": lem} for n, lem in concept.items()
              if re.search(r"-\d\d$", lem)}

    # event-level relations
    rel_triples = [(s, r, t) for s, r, t in g.triples
                   if r in {":condition", ":concession", ":time", ":cause", ":purpose"}]

    order_pairs = []
    for s, r, t in g.triples:
        if r == ":instance" and concept.get(t) in {"before", "after"}:
            args = {rr: tt for ss, rr, tt in g.triples if ss == t and rr in {":op1", ":op2"}}
            e1, e2 = args.get(":op1"), args.get(":op2")
            if e1 in events and e2 in events:
                order_pairs.append((e1, e2) if concept[t] == "before" else (e2, e1))

    incoming = {}
    for s, r, t in rel_triples:
        if t in events:
            incoming.setdefault(t, []).append(r)

    def event_record(node):
        span = None
        if node in node_tok:
            span = sentence[node_tok[node][0]:node_tok[node][1]]
        if not span:  # fallback: concept lemma token
            base = events[node]["concept"].rsplit("-", 1)[0].replace("-", " ").lower()
            for tok, st, en in toks:
                if tok.lower() == base or (len(base) > 4 and tok.lower()[:4] == base[:4]):
                    span = sentence[st:en]
                    break
        rels = incoming.get(node, [])
        if ":condition" in rels:
            role = "PRECONDITION_CHECK"
        else:
            role = "OPERATION_EFFECT"
        return {"concept": events[node]["concept"], "span": span, "node": node,
                "role_hypothesis": role,
                "incoming": rels}

    out_events = [event_record(n) for n in events]
    by_node = {e["node"]: e for e in out_events}

    edges = []
    for s, r, t in rel_triples:
        if s in by_node and t in by_node and by_node[t]["span"] and by_node[s]["span"]:
            if r == ":condition":
                edges.append({"condition_span": by_node[t]["span"],
                              "operation_span": by_node[s]["span"],
                              "relation": "GATE", "source": "amr:condition"})
            elif r == ":concession":
                edges.append({"condition_span": by_node[t]["span"],
                              "operation_span": by_node[s]["span"],
                              "relation": "EVEN_IF", "source": "amr:concession"})
            elif r == ":time":
                edges.append({"condition_span": by_node[t]["span"],
                              "operation_span": by_node[s]["span"],
                              "relation": "ORDER_BEFORE", "source": "amr:time"})
    for e1, e2 in order_pairs:
        a, b = by_node[e1], by_node[e2]
        if a["span"] and b["span"]:
            edges.append({"condition_span": a["span"], "operation_span": b["span"],
                          "relation": "ORDER_BEFORE", "source": "amr:before"})
    # deduplicate edges with identical (cond, op, rel)
    seen = set()
    uniq = []
    for e in edges:
        key = (e["condition_span"], e["operation_span"], e["relation"])
        if key not in seen:
            seen.add(key)
            uniq.append(e)
    return out_events, uniq, concept


def main():
    which = os.environ.get("OC_SUITE", "original")
    arm = os.environ.get("OC_ARM_DIR", "C_amr")
    suite = load_suite(which)
    import amrlib
    stog = amrlib.load_stog_model()
    t0 = time.time()
    outdir = out_dir(arm + suffix_for(which))
    for case in suite:
        path = outdir / f"{case['case_id']}.json"
        if path.is_file():
            continue
        sentences = split_sentences(case["policy"])
        events, edges, graphs_out = [], [], []
        align_ok = 0
        for sent in sentences:
            graph_strs = stog.parse_sents([sent])
            graph_str = graph_strs[0]
            try:
                g, toks = align_graph(graph_str, sent)
                node_tok = node_alignments(g, toks)
                align_ok += 1
            except Exception as exc:  # noqa: BLE001
                import penman
                from amrlib.alignments.penman_utils import NoOpModel
                g = penman.decode(graph_str, model=NoOpModel())
                toks = tokenize(sent)
                node_tok = {}
            evs, eds, concept = extract_events(g, toks, sent, node_tok)
            events.extend(evs)
            edges.extend(eds)
            graphs_out.append(penman.encode(g) if "penman" in dir() else graph_str)
        result = {
            "case_id": case["case_id"],
            "sentences": sentences,
            "aligned_sentences": align_ok,
            "events": events,
            "edges": edges,
        }
        path.write_text(json.dumps(result, ensure_ascii=False, indent=1),
                        encoding="utf-8")
    write_usage(arm + suffix_for(which),
                {"wall_seconds": round(time.time() - t0, 1), "suite": which,
                 "model": "amrlib parse_xfm_bart_large (83.7 SMATCH) + RBW aligner",
                 "device": "cpu"})
    print("C done", which)


if __name__ == "__main__":
    main()
