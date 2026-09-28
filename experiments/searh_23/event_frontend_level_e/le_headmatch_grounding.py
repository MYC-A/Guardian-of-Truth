"""Generic predicate-to-tool-description head agreement after CE ranking.

For a rescued leading command, a unique match between the lemma of its first
word and the lemma of the first word in one tool description overrides the
reranker's top choice. Ties and absent matches preserve the original choice.
No policy domain, tool identifier or business verb is encoded here.
"""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).parent
OUT = HERE / "outputs"


def main():
    import stanza
    nlp = stanza.Pipeline("en", processors="tokenize,pos,lemma", verbose=False, use_gpu=True)
    cases = {c["case_id"]: c for c in json.loads((HERE / "frozen" / "frozen_cases.json").read_text(encoding="utf-8"))}
    dest = OUT / "FRONTEND_imperative_headmatch"
    dest.mkdir(parents=True, exist_ok=True)
    changes = []

    def first_lemma(text):
        doc = nlp(text)
        if not doc.sentences or not doc.sentences[0].words:
            return ""
        w = doc.sentences[0].words[0]
        return (w.lemma or w.text).lower()

    for p in sorted((OUT / "FRONTEND_imperative_regrounded").glob("e_*.json")):
        data = json.loads(p.read_text(encoding="utf-8"))
        tools = cases[data["case_id"]]["tools"]
        heads = {t["name"]: first_lemma(t["description"]) for t in tools}
        for ev in data["events"]:
            if ev.get("dep") != "rescue_imperative":
                continue
            action_head = first_lemma(ev["span"])
            matches = [t for t in tools if heads[t["name"]] == action_head]
            if len(matches) == 1:
                old = ev["governed_tools"]
                ev["governed_tools"] = [matches[0]["name"]]
                ev["tool_head_match"] = True
                if old != ev["governed_tools"]:
                    changes.append({"case_id": data["case_id"], "span": ev["span"],
                                    "from": old, "to": ev["governed_tools"]})
            else:
                ev["tool_head_match"] = False
        (dest / p.name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT / "headmatch_changes.json").write_text(json.dumps(changes, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(changes, indent=2))


if __name__ == "__main__":
    main()
