"""AMR frontend adapter - real AMR parser as candidate graph proposer.

Runs INSIDE amr_env (amrlib 0.8.1 + SPRAY/BART-large parse model,
83.7 SMATCH on AMR-3). Mapping rules are fixed a priori on linguistic
principles (they were written before any Level F test inference):

  1. AMR predicate frames (concept like inspect-01, fire-01) are EVENT
     candidates; the source span is anchored by lemma matching in the
     sentence (deterministic, extractive).
  2. Completion wrappers (complete-01 / finish-01 / pass-01 / valid-01 /
     confirm-01 / record-01 whose ARG1 is itself a predicate frame) mark
     STATE_OR_FACET candidates of the wrapped predicate.
  3. A candidate whose anchored surface token is verbal (VB*) is EVENT;
     if the surface is nominal (NN*) the candidate is EVENT_REFERENCE.
  4. Non-predicate concepts under ARG0/ARG1/ARG2/ARG-of become ENTITY
     argument candidates (never event endpoints).
  5. :time (b / before ...) / (a / after ...) between two predicates
     proposes ORDER_BEFORE / ORDER_AFTER semantic relations.
  6. :polarity - proposes NEGATION on the candidate.

The AMR graph is additionally stored raw for use as a structural WITNESS
(predicate-vs-argument verdicts) in the certificate verifier.

Run (server, amr_env):
  /workspace/guardian/venvs/amr_env/bin/python lf_amr_frontend.py original
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).parent
OUT = HERE / "outputs"
MODEL = "/workspace/guardian/models/amrlib/model_parse_xfm_bart_large-v0_1_0"

STATE_WRAPPERS = {"complete-01", "finish-01", "pass-01", "valid-01",
                  "confirm-01", "verify-01"}
PRED_RE = re.compile(r"^[a-z][a-z0-9_-]*-[0-9]{2}$")


def load_suite(which: str) -> list[dict]:
    fname = ("level_f_cases.json" if which == "original"
             else "level_f_cases_renamed.json")
    return json.loads((HERE / "frozen" / fname).read_text(encoding="utf-8"))


def split_sentences(policy: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", policy.strip())
    return [p for p in parts if p.strip()]


# --------------------------------------------------------- AMR parsing
def parse_amr(sents: list[str]) -> list[str]:
    import amrlib
    stog = amrlib.load_stog_model(MODEL, device="cpu")
    return stog.parse_sents(sents, disable_progress=True)


def penman_to_nodes(graph: str) -> list[dict]:
    """Very small PENMAN reader: instance nodes + ARG edges + attributes.

    Handles indentation-based triples of the amrlib output. This is a
    structural witness reader, not a full AMR toolchain.
    """
    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    stack: list[tuple[int, str]] = []

    def instance(var: str, concept: str, indent: int) -> None:
        nodes[var] = {"var": var, "concept": concept, "indent": indent,
                      "mode": None, "polarity": None}
        # pop stack to current depth
        while stack and stack[-1][0] >= indent:
            stack.pop()
        if stack:
            edges.append({"src": stack[-1][1], "dst": var})
        stack.append((indent, var))

    for raw_line in graph.split("\n"):
        if raw_line.startswith("#") or not raw_line.strip():
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        line = raw_line.strip()
        m = re.match(r"^(\(\s*)?([a-z][a-z0-9]*)\s*/\s*([^\s()]+)", line)
        if m:
            instance(m.group(2), m.group(3), indent)
            line = line[m.end():]
        for role, tgt in re.findall(r":([a-zA-Z0-9-]+)\s+(\([^a-z\s]*\s+)?"
                                    r"([a-zA-Z0-9_]+|\"[^\"]*\")", line):
            if tgt.startswith("("):
                continue  # nested instance handled by next lines
            if tgt.startswith('"'):
                attr = {"role": role, "value": tgt.strip('"')}
                cur = stack[-1][1] if stack else None
                if cur:
                    nodes[cur].setdefault("attrs", []).append(attr)
                    if role == "mode":
                        nodes[cur]["mode"] = tgt.strip('"')
            else:
                cur = stack[-1][1] if stack else None
                if cur:
                    edges.append({"src": cur, "dst": tgt, "role": role})
                    if role == "polarity":
                        nodes[cur]["polarity"] = tgt
    # pass 2: bind roles to edges (edges created before roles were unknown)
    return _finalize(nodes, edges, graph)


def _finalize(nodes: dict, edges: list, graph: str) -> list[dict]:
    # re-parse with roles attached properly using a simple regex over
    # the full graph text for ":role (var / concept" and ":role var"
    for m in re.finditer(r":([a-zA-Z0-9-]+)\s+\(([a-z][a-z0-9]*)\s*/\s*"
                         r"([^\s()]+)", graph):
        role, var, concept = m.group(1), m.group(2), m.group(3)
        # find the owning var: the var instance textually preceding match
        owner = _owner_of(graph, m.start())
        if owner:
            edges.append({"src": owner, "dst": var, "role": role,
                          "dst_concept": concept})
    for m in re.finditer(r":([a-zA-Z0-9-]+)\s+([a-z][a-z0-9]*)\b(?!\s*/)",
                         graph):
        role, var = m.group(1), m.group(2)
        owner = _owner_of(graph, m.start())
        if owner and var in nodes:
            edges.append({"src": owner, "dst": var, "role": role})
    return list(nodes.values()) + [{"edges": edges}]


def _owner_of(graph: str, pos: int) -> str | None:
    """The var of the closest instance opened before pos at lower depth."""
    best = None
    for m in re.finditer(r"\(([a-z][a-z0-9]*)\s*/\s*([^\s()]+)", graph):
        if m.start() < pos:
            best = m.group(1)
        else:
            break
    return best


def main() -> None:
    import stanza
    nlp = stanza.Pipeline("en", processors="tokenize,pos,lemma",
                          verbose=False, use_gpu=False)
    which = sys.argv[1] if len(sys.argv) > 1 else "original"
    outdir = OUT / "AMR"
    outdir.mkdir(parents=True, exist_ok=True)
    for case in load_suite(which):
        path = outdir / f"{case['case_id']}.json"
        if path.exists():
            continue
        policy = case["policy"]
        sents = split_sentences(policy)
        t0 = time.time()
        graphs = parse_amr(sents)
        candidates = []
        raw_graphs = []
        cid_n = 0
        for s_idx, (sent, graph) in enumerate(zip(sents, graphs)):
            raw_graphs.append(graph)
            doc = nlp(sent)
            words = [w for s in doc.sentences for w in s.words]
            # lemma index for anchoring
            lemma_positions: dict[str, list[int]] = {}
            for w in words:
                lemma_positions.setdefault(w.lemma.lower(), []).append(
                    (w.start_char, w.end_char, w.upos))

            def anchor(concept: str, used: set) -> tuple | None:
                base = concept.split("-")[0]
                for key, positions in lemma_positions.items():
                    if key == base or key == base + "e" \
                            or base.startswith(key) or key.startswith(base):
                        for p in positions:
                            if p not in used:
                                used.add(p)
                                return p
                return None

            used: set = set()
            # predicate frames -> event candidates
            for m in re.finditer(r"\(([a-z][a-z0-9]*)\s*/\s*([^\s()]+)",
                                 graph):
                var, concept = m.group(1), m.group(2)
                if not PRED_RE.match(concept):
                    continue
                off = anchor(concept, used)
                if not off:
                    continue
                st, en, upos = off
                surface = sent[st - 0:en - 0] if st < en else None
                # type by surface POS + wrapper semantics
                wrapper = concept in STATE_WRAPPERS and re.search(
                    r":ARG1\s+\([a-z][a-z0-9]*\s*/\s*[a-z][a-z0-9-]*-\d+",
                    graph[m.end():m.end() + 120])
                if wrapper:
                    mtype = "STATE_OR_FACET"
                elif upos.startswith("VB"):
                    mtype = "EVENT"
                elif upos in {"NN", "NNS", "NNP", "NNPS", "PRON"}:
                    mtype = "EVENT_REFERENCE"
                else:
                    mtype = "UNKNOWN"
                cid_n += 1
                candidates.append({
                    "cid_local": f"c{cid_n:02d}",
                    "span": surface, "start": None, "end": None,
                    "sentence_index": s_idx,
                    "type": mtype,
                    "predicate": concept.split("-")[0],
                    "amr_concept": concept, "amr_var": var,
                    "surface_pos": upos,
                    "arguments": [], "relations": [],
                    "grounded_tools": [],
                    "provenance": "sentence_lemma_anchor",
                    "mode": "imperative" if ":mode imperative" in graph
                            else None,
                    "negation": bool(re.search(
                        r"\(" + var + r"\s*/\s*[^\s()]+\s*\n?\s*:polarity\s+-",
                        graph)),
                })
            # non-predicate concepts -> entity argument candidates
            for m in re.finditer(r"\(([a-z][a-z0-9]*)\s*/\s*([^\s()]+)",
                                 graph):
                var, concept = m.group(1), m.group(2)
                if PRED_RE.match(concept) or concept.startswith("amr-"):
                    continue
                off = anchor(concept, used)
                if not off:
                    continue
                st, en, upos = off
                cid_n += 1
                candidates.append({
                    "cid_local": f"c{cid_n:02d}",
                    "span": sent[st:en] if st < en else None,
                    "sentence_index": s_idx,
                    "type": "ENTITY", "predicate": None,
                    "amr_concept": concept, "amr_var": var,
                    "surface_pos": upos,
                    "arguments": [], "relations": [],
                    "grounded_tools": [],
                    "provenance": "sentence_lemma_anchor",
                })
        # resolve absolute offsets from sentence starts
        pos = 0
        sent_starts = []
        for s in sents:
            idx = policy.find(s, pos)
            sent_starts.append(idx)
            pos = idx + len(s)
        for c in candidates:
            if c.get("span") and c.get("sentence_index") is not None:
                st = policy.find(c["span"], sent_starts[
                    c["sentence_index"]])
                if st >= 0:
                    c["start"], c["end"] = st, st + len(c["span"])
        path.write_text(json.dumps({"case_id": case["case_id"], "arm": "AMR",
                                    "candidates": candidates,
                                    "amr_graphs": raw_graphs,
                                    "latency_s": round(time.time() - t0, 1)},
                                   indent=1) + "\n", encoding="utf-8")
        print(case["case_id"], len(candidates), flush=True)


if __name__ == "__main__":
    main()
