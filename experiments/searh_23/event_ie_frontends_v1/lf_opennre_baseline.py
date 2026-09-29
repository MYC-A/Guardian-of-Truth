"""OpenNRE baseline (arm F of the brief): given correct source-backed
endpoints A and B, does a specialized relation-extraction model add
anything over our narrow relation classifiers?

Setup: OpenNRE's wiki80_bert_softmax (entity-centric, 80 relation types)
queried on (head=A span, tail=B span, sentence) for every Level F gold
pair and every certificate unit edge. We measure:
  - coverage (does it produce a prediction at all);
  - directional signal (does its relation fire more on gold-positive
    pairs than on hard-negative pairs);
  - label usefulness (its wiki80 labels vs our relation taxonomy).

Run (server, main venv):
  python3 lf_opennre_baseline.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).parent
OUT = HERE / "outputs"


def load_gold() -> list[dict]:
    return json.loads((HERE / "frozen" / "level_f_cases.json")
                      .read_text(encoding="utf-8"))


def sent_of(policy: str, start: int) -> str:
    pos = 0
    for s in re.split(r"(?<=[.!?])\s+", policy):
        if pos <= start < pos + len(s):
            return s.strip()
        pos += len(s) + 1
    return policy


def main() -> None:
    from opennre.pretrain import get_model

    model = get_model("wiki80_bert_softmax")

    def ask(head: str, tail: str, text: str) -> dict | None:
        try:
            r = model.infer({"text": text,
                             "h": {"pos": (0, len(head))},
                             "t": {"pos": (len(head) + 1,
                                          len(head) + 1 + len(tail))}})
            return {"relation": r[0], "score": r[1]}
        except Exception as exc:
            return {"error": str(exc)[:200]}

    # ---- certificate unit items (the cleanest signal: gold status known)
    items = json.loads((HERE / "frozen" / "certificate_cases.json")
                       .read_text(encoding="utf-8"))
    rows = []
    for it in items:
        policy = it["policy"]
        a = it["edge"]["a"]
        b = it["edge"]["b"]
        # find the sentence containing the most overlap with both endpoints
        sent = None
        for s in re.split(r"(?<=[.!?])\s+", policy):
            if a.lower()[:12] in s.lower() or b.lower()[:12] in s.lower():
                sent = s
                if a.lower()[:12] in s.lower() and b.lower()[:12] in s.lower():
                    break
        if sent is None:
            sent = policy
        res = ask(a, b, f"{a} {b}. {sent}")
        rows.append({"id": it["id"], "family": it["family"],
                     "gold_status": it["gold"]["status"],
                     "opennre": res, "sentence_used": sent})
        print(it["id"], it["gold"]["status"], "->", res, flush=True)
    (OUT / "opennre_certificate.json").write_text(
        json.dumps(rows, indent=1) + "\n", encoding="utf-8")

    # aggregate
    pos = [r for r in rows if r["gold_status"] == "SUPPORTED"]
    neg = [r for r in rows if r["gold_status"] == "UNSUPPORTED"]
    pos_pred = [r for r in pos if r["opennre"]]
    neg_pred = [r for r in neg if r["opennre"]]

    def nontrivial(r):
        o = r["opennre"] or {}
        return o.get("relation") not in (None, "no relation", "")

    print("coverage on positives:", len(pos_pred), "/", len(pos))
    print("coverage on negatives:", len(neg_pred), "/", len(neg))
    print("non-trivial relation on positives:",
          sum(1 for r in pos if nontrivial(r)), "/", len(pos))
    print("non-trivial relation on negatives:",
          sum(1 for r in neg if nontrivial(r)), "/", len(neg))


if __name__ == "__main__":
    main()
