"""H.3 / H.4 as ablation arms — node-level (zero LLM).

H.3: POS-anchored subject/verb split for determiner-subject SVO states
     ('the wind sensor reads calm'): use stanza POS to find the first
     verb in the span; action lemma = verb lemma; subject/args split at
     the verb. Replaces the last-token-head heuristic for
     determiner-initial spans. Old heuristic stays as fallback when no
     verb is found.

H.4a: artifact head nouns detected by derivational morphology
     (deverbal -tion/-ment/-ing/-ure/-ance/-al/-ery/-ity + the frozen
     list) in the artifact-subject junk filter — extends coverage to
     unseen nouns ('the run count', 'the tally sheet') without a domain
     lexicon.

H.4b: determiner-gerund / deverbal-nominal reference form generates an
     additional stem lemma variant ('the run count' -> 'run'; 'the
     polishing' -> 'polish') so the act node's imperative form can
     anchor to the reference node (fragment-twin merge).

Arms (node build only, evaluated with node/cluster metrics):
  v10      - frozen build_nodes_v3
  v10+H3   - POS-anchored action_signature for determiner-initial spans
  v10+H4   - derivational artifact nouns + gerund/stem variants
  v10+H34  - both

Run: python en_h34_nodes.py
"""
from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).parent
W1 = HERE.parent / "step1_working_v1"
sys.path.insert(0, str(W1))

import w1_pipe3 as v10  # noqa: E402
from en_common import (load_gold, node_label, node_cluster_metrics,  # noqa
                       cluster_scores, node_clusters_as_sets,
                       gold_clusters_as_sets)
from en_audit import build_nodes_toggle  # noqa: E402

OUTD = HERE / "outputs" / "ablations"
OUTD.mkdir(parents=True, exist_ok=True)

DERIV_ARTIFACT = re.compile(
    r"^(?:[a-z]+(?:tion|ment|ing|ure|ance|ence|al|ery|ity|ics|log))$",
    re.I)


def is_artifact_noun(token: str) -> bool:
    t = token.lower().strip(".,;:'\"")
    if t in ("log", "certificate", "note", "record", "report", "master",
             "form", "file", "reading", "document", "tally", "count",
             "roster", "sheet", "ledger", "register", "entry"):
        return True
    if DERIV_ARTIFACT.match(t) and len(t) >= 6:
        # exclude deverbal nouns that are typically EVENTS in policies
        if t.endswith("ing") and len(t) >= 8:
            return False  # 'the cleaning' is an EVENT_REFERENCE, not artifact
        return True
    return False


def artifact_subject_h4(span: str) -> bool:
    """Artifact-subject test with derivational morphology (H.4a)."""
    m = re.match(
        r"^(?:[Tt]he\s+|[Aa]\s+|[Aa]n\s+)?([A-Za-z0-9'\- ]+?)\s+"
        r"(records?|logs?|documents?|confirms?|lists?|states?|certifies?|"
        r"indicates?|shows?|must\s+|should\s+|may\s+|shall\s+|will\s+|"
        r"record\b|log\b|document\b|confirm\b|list\b|state\b|certify\b|"
        r"indicate\b|show\b)", span)
    if not m:
        return False
    subj = m.group(1).strip()
    head = subj.split()[-1] if subj.split() else ""
    return is_artifact_noun(head)


def pos_action_signature(span: str, pos_map: dict) -> tuple:
    """H.3: POS-anchored signature for determiner-initial spans.

    pos_map: token(lower) -> UPOS from stanza over the span. Returns
    (action_lemma, args_set) or None when no verb is present."""
    toks = span.split()
    if not toks:
        return None
    if toks[0].lower() not in ("the", "a", "an", "each", "every",
                               "this", "that"):
        return None
    # find first VERB/AUX (skip leading determiners/adjectives)
    verb_i = None
    for i, t in enumerate(toks):
        if pos_map.get(t.lower()) in ("VERB", "AUX"):
            verb_i = i
            break
    if verb_i is None or verb_i == 0:
        return None
    subj = [t for t in toks[:verb_i]
            if t.lower() not in v10.STOP and t.lower() not in
            ("the", "a", "an", "each", "every", "this", "that")]
    act = v10._norm_lemma(re.sub(r"[^a-z]", "", toks[verb_i].lower()))
    rest = [t for t in toks[verb_i + 1:] if t.lower() not in v10.STOP]
    return act, {v10._norm_lemma(re.sub(r"[^a-z]", "", t.lower()))
                 for t in subj + rest}


def stem_variants(span: str) -> list[str]:
    """H.4b: stem-lemma forms for deverbal reference mentions."""
    s = span.strip()
    out = []
    m = re.match(r"^(?:the|a|an)\s+(.+)$", s, re.I)
    if not m:
        return out
    inner = m.group(1)
    toks = inner.split()
    if len(toks) == 1:
        w = toks[0].lower()
        if w.endswith("ing") and len(w) >= 5:
            stem = w[:-3]
            if len(stem) >= 3 and stem[-1] == stem[-2]:
                stem = stem[:-1]
            if stem and stem not in ("count",):
                out.append(stem)
        elif w.endswith("tion") and len(w) >= 6:
            out.append(w[:-3])  # inspect+ion -> inspect approx
    return [x for x in out if x]


# ------------------------------------------------------- patched builders
def build_pos_maps(cases: dict) -> dict:
    """stanza POS map per case (token-lower -> UPOS)."""
    import stanza
    cache = OUTD / "_pos_cache.json"
    if cache.exists():
        return json.loads(cache.read_text())
    nlp = stanza.Pipeline("en", processors="tokenize,pos", verbose=False,
                          use_gpu=True)
    maps = {}
    for cid_, case in cases.items():
        doc = nlp(case["policy"])
        pm = {}
        for s in doc.sentences:
            for w in s.words:
                pm.setdefault(w.text.lower(), w.upos)
        maps[cid_] = pm
    cache.write_text(json.dumps(maps))
    return maps


def patched_action_signature(span: str, pos_map: dict | None):
    """v10 signature with H.3 patch for determiner-initial spans."""
    if pos_map is not None:
        got = pos_action_signature(span, pos_map)
        if got is not None:
            return got
    return v10.action_signature(span)


def build_nodes_h34(case, pos_map, use_h3=False, use_h4=False):
    """v10 node build with H.3/H.4 toggles. Copies the frozen logic and
    patches only the specified mechanisms."""
    # monkey-patch the two functions used inside build_nodes_v3's
    # closure graph (action_signature via compatible_nodes /
    # consolidate_nodes; artifact filter is inline in the junk stage).
    orig_sig = v10.action_signature
    orig_artifact = v10.ARTIFACT_SUBJ

    class SigPatch:
        def __init__(self, pm):
            self.pm = pm

        def __call__(self, span):
            if self.pm is not None:
                got = pos_action_signature(span, self.pm)
                if got is not None:
                    return got
            return orig_sig(span)

    if use_h3:
        v10.action_signature = SigPatch(pos_map)
    # H.4a: widen the artifact-subject regex via an additional check —
    # monkey-patch ARTIFACT_SUBJ.match is not enough; instead we filter
    # post-hoc in a wrapper around the junk stage by re-running the
    # filter with artifact_subject_h4 on survivors.
    nodes = build_nodes_toggle("LLM_SG", case)
    if use_h3:
        v10.action_signature = orig_sig
    if use_h4:
        # H.4a: drop nodes whose span is an artifact-subject recording
        # sentence under the DERIVATIONAL test (v10's frozen list missed
        # e.g. 'the run count is logged')
        keep = []
        for n in nodes:
            span = n.get("span", "")
            if artifact_subject_h4(span) and v10.COMM_VERB.search(span):
                continue  # derivational artifact-subject junk
            keep.append(n)
        # H.4b: add stem-lemma member forms for determiner-deverbal refs
        # (only when the stem occurs as a standalone word in the policy —
        # the form must remain locatable for certificates)
        for n in keep:
            for f in list(n.get("member_spans") or []):
                for sv in stem_variants(f):
                    if sv in (n.get("member_spans") or []):
                        continue
                    if re.search(rf"\b{re.escape(sv)}\b",
                                 case["policy"], re.I):
                        n["member_spans"].append(sv)
        nodes = keep
    return nodes


def main():
    suites = ("main", "f2", "f3", "f4")
    all_cases = {}
    for suite in suites:
        for cid_, case in load_gold(suite).items():
            all_cases[f"{suite}:{cid_}"] = case
    print("[h34] computing POS maps (stanza) ...")
    pos_maps_by_case = build_pos_maps(all_cases)

    arms = {
        "v10": dict(use_h3=False, use_h4=False),
        "v10+H3": dict(use_h3=True, use_h4=False),
        "v10+H4": dict(use_h3=False, use_h4=True),
        "v10+H34": dict(use_h3=True, use_h4=True),
    }
    out = {}
    for suite in suites:
        gold = load_gold(suite)
        out[suite] = {}
        for aname, cfg in arms.items():
            rows = []
            for cid_, case in gold.items():
                pm = pos_maps_by_case.get(f"{suite}:{cid_}")
                nodes = build_nodes_h34(case, pm, **cfg)
                m = node_cluster_metrics(case, nodes)
                m.update(cluster_scores(node_clusters_as_sets(case, nodes),
                                        gold_clusters_as_sets(case)))
                rows.append({"case": cid_, **m})
            numeric = {k for k in rows[0]
                       if k not in ("case", "diff", "examples")
                       and isinstance(rows[0].get(k), (int, float))}
            agg = {}
            for k in sorted(numeric):
                if isinstance(rows[0].get(k), float):
                    agg[k] = round(sum(r.get(k, 0) for r in rows) /
                                   max(1, len(gold)), 4)
                else:
                    agg[k] = sum(r.get(k, 0) for r in rows)
            out[suite][aname] = {"aggregate": agg, "per_case": rows}
            print(f"[{suite}] {aname}: recall={agg.get('cluster_recall')} "
                  f"prec={agg.get('node_precision')} "
                  f"conll={agg.get('conll_f')} "
                  f"junk={agg.get('junk_or_unlabeled_nodes')} "
                  f"splits={agg.get('false_split_cids')}")
    (OUTD / "h34_nodes.json").write_text(json.dumps(out, indent=1))
    print("saved ->", OUTD / "h34_nodes.json")


if __name__ == "__main__":
    main()
