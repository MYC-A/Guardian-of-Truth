"""Exploratory head-anchored clause boundaries; never reads test gold.

Unlike the old min/max hull, this preserves separate source chunks and
selects ONLY the contiguous chunk containing the predicate as primary span.
Other predicate clauses and temporal/precondition obliques are excluded.
Punctuation boundaries are a conservative source constraint, not a claim
that abbreviations have been semantically resolved.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent / "policy_licensing_v1"))
from pl_frontend import analyse_case, CLAUSE_DEPS, SUBORDINATORS, np_candidates

OUT = HERE / "outputs"
CLAUSE_CHILDREN = {"advcl", "acl", "ccomp", "xcomp", "conj", "parataxis"}


def source_region(policy: str, anchor: int) -> tuple[int,int]:
    cuts = [0] + [m.end() for m in re.finditer(r"[.!?]\s+(?=[A-Z])", policy)] + [len(policy)]
    return next((a,b) for a,b in zip(cuts,cuts[1:]) if a <= anchor < b)


def anchored_span(policy, sentence, head, source_bounds=None):
    by_id = {w.id: w for w in sentence.words}
    children = {i: [w for w in sentence.words if w.head == i] for i in by_id}
    lo, hi = source_bounds or source_region(policy, head.start_char)
    excluded, kept = [], []

    def visit(word):
        if not (lo <= word.start_char and word.end_char <= hi):
            excluded.append({"id": word.id, "reason": "source_terminal"})
            return
        if word.id != head.id:
            dep = word.deprel.split(":")[0]
            clausal = dep in CLAUSE_CHILDREN and (
                word.upos in {"VERB", "AUX"} or any(c.deprel == "cop" for c in children[word.id]))
            gate = dep in {"obl", "nmod"} and any(
                c.deprel in {"case", "mark", "advmod"} and c.lemma in SUBORDINATORS
                for c in children[word.id])
            if clausal or gate:
                excluded.append({"id": word.id, "reason": "other_clause" if clausal else "gate_oblique"})
                return
        kept.append(word)
        for child in children[word.id]:
            visit(child)

    visit(head)
    kept.sort(key=lambda w: w.id)
    runs = []
    for word in kept:
        if not runs or word.id != runs[-1][-1].id+1:
            runs.append([])
        runs[-1].append(word)
    chunks = []
    primary = None
    for run in runs:
        while len(run)>1 and run[0].upos in {"PUNCT", "CCONJ"}:
            run.pop(0)
        while len(run)>1 and run[-1].upos in {"PUNCT", "CCONJ"}:
            run.pop()
        if not run:
            continue
        start,end = run[0].start_char,run[-1].end_char
        chunk = {"start": start,"end": end,"text": policy[start:end]}
        chunks.append(chunk)
        if any(w.id == head.id for w in run):
            primary = chunk
    if primary is None:
        return None
    return {"span": primary["text"], "start": primary["start"], "end": primary["end"],
            "source_chunks": chunks, "predicate_start": head.start_char,
            "predicate_end": head.end_char, "predicate_text": head.text,
            "predicate_lemma": head.lemma, "excluded_roots": excluded,
            "noncontiguous": len(chunks)>1}


def extract(nlp, policy):
    candidates = []
    for sentence in nlp(policy).sentences:
        for word in sentence.words:
            dep = word.deprel.split(":")[0]
            cop = any(c.head == word.id and c.deprel == "cop" for c in sentence.words)
            if dep not in CLAUSE_DEPS or (word.upos != "VERB" and not cop):
                continue
            span = anchored_span(policy,sentence,word)
            if span is None or not span["span"].strip():
                continue
            marks = [c.lemma for c in sentence.words if c.head == word.id
                     and c.lemma in SUBORDINATORS and c.deprel in {"mark","case","advmod"}]
            candidates.append({**span, "verb": word.lemma, "is_np": False,
                               "dep": dep, "mark": marks[0] if marks else None})
            # Keep the old NP proposal arm unchanged. It is NOT accepted as
            # an event by this boundary mechanism; eventness is separate.
            candidates.extend(np_candidates(policy,sentence,sentence.words,word))
    seen = {}
    for c in candidates:
        key = c["start"],c["end"]
        if key not in seen or (seen[key].get("is_np") and not c.get("is_np")):
            seen[key] = c
    return list(seen.values())


def run():
    import stanza
    nlp = stanza.Pipeline("en",processors="tokenize,pos,lemma,depparse",verbose=False,use_gpu=True)
    inputs = json.loads((HERE/"frozen/boundary_inputs.json").read_text(encoding="utf-8"))
    dest = OUT/"E6_BOUNDARIES"; dest.mkdir(exist_ok=True)
    for row in inputs:
        path = dest/f"{row['id']}.json"
        if path.exists():
            continue
        data = {"id":row["id"],"policy":row["policy"],
                "A_old":analyse_case(nlp,{"policy":row["policy"]}),
                "B_anchored":extract(nlp,row["policy"])}
        path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        print(row["id"],len(data["A_old"]),len(data["B_anchored"]),flush=True)


def score():
    gold = json.loads((HERE/"frozen/boundary_gold.json").read_text(encoding="utf-8"))
    result = {}
    for arm in ("A_old","B_anchored"):
        total = {"cores":0,"covered":0,"clean_covered":0,"multi_core_candidates":0,"candidates":0,"cross_sentence_candidates":0}
        cases = {}
        for cid,cores in gold.items():
            data = json.loads((OUT/"E6_BOUNDARIES"/f"{cid}.json").read_text(encoding="utf-8"))
            spans = [c for c in data[arm] if not c.get("is_np")]
            coverage = []
            for core in cores:
                containing = [c for c in spans if c["start"]<=core["start"] and core["end"]<=c["end"]]
                clean = [c for c in containing if not any(
                    other!=core and max(c["start"],other["start"])<min(c["end"],other["end"])
                    for other in cores)]
                coverage.append({"core":core["text"],"covered":bool(containing),"clean":bool(clean)})
            multi = [c["span"] for c in spans if sum(
                max(c["start"],core["start"])<min(c["end"],core["end"]) for core in cores)>1]
            cross = [c["span"] for c in spans if re.search(r"[.!?]\s+[A-Z]",c["span"])]
            total["cores"]+=len(cores); total["covered"]+=sum(x["covered"] for x in coverage)
            total["clean_covered"]+=sum(x["clean"] for x in coverage)
            total["multi_core_candidates"]+=len(multi); total["candidates"]+=len(spans)
            total["cross_sentence_candidates"]+=len(cross)
            cases[cid]={"coverage":coverage,"mixed":multi,"cross_sentence":cross}
        result[arm]={"total":total,"cases":cases}
    (OUT/"E6_score.json").write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
    for arm,data in result.items(): print(arm,data["total"])


if __name__ == "__main__":
    ap=argparse.ArgumentParser(); ap.add_argument("phase",choices=("run","score"))
    {"run":run,"score":score}[ap.parse_args().phase]()
