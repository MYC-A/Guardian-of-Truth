"""Dev calibration for ready-frontend schema phrasings (UIE, GLiNER).

Uses ONLY old Level E dev-pool policies (previous phase, already
analyzed; Level F is untouched). Selects:
  - the UIE schema phrasing variant with the best dev mention recall
  - the GLiNER threshold
Writes outputs/dev_calibration.json. The frozen winner is then hardcoded
in lf_ready_frontends.py BEFORE any Level F inference.
"""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).parent
LE = HERE.parent / "event_frontend_level_e" / "frozen"
OUT = HERE / "outputs"

DEV_CASES = ["e_observatory", "e_seedbank", "e_aquarium", "e_theater",
             "e_orchard"]  # old dev pool families (passive, nominal,
# artifact, check-vs-action, repeated-op occurrences)

VARIANTS = {
    "V1": {
        "EVENT": "action or task to be performed",
        "EVENT_REFERENCE": "reference to an action or task",
        "STATE_OR_FACET": "state or condition of an action",
        "ARTIFACT": "document, report, log or record",
        "CHECK": "verification or checking action",
        "ENTITY": "physical object or participant",
    },
    "V2": {
        "EVENT": "action",
        "EVENT_REFERENCE": "action reference",
        "STATE_OR_FACET": "state",
        "ARTIFACT": "document",
        "CHECK": "verification action",
        "ENTITY": "object",
    },
    "V3": {
        "EVENT": "event",
        "EVENT_REFERENCE": "event reference",
        "STATE_OR_FACET": "state or facet",
        "ARTIFACT": "artifact",
        "CHECK": "check",
        "ENTITY": "entity",
    },
}


def load_dev() -> list[dict]:
    cases = json.loads((LE / "frozen_cases.json").read_text(encoding="utf-8"))
    return [c for c in cases if c["case_id"] in DEV_CASES]


def main() -> None:
    report = {"uie": {}, "gliner": {}}
    dev = load_dev()
    # gold event-like spans for recall measurement (mentions + probes)
    gold_spans = {}
    for c in dev:
        spans = set()
        for mid, span, cid, *_ in [(m["mid"], m["span"], m["cid"])
                                   for m in c["mentions"]]:
            spans.add(span.strip().lower())
        report.setdefault("_dev_gold", {})[c["case_id"]] = len(spans)
        gold_spans[c["case_id"]] = spans

    from paddlenlp import Taskflow
    for name, phrase in VARIANTS.items():
        found, total = 0, 0
        det = {}
        ie = Taskflow("information_extraction", schema=list(phrase.values()),
                      model="uie-base-en", prob_thresh=0.3)
        for c in dev:
            res = ie(c["policy"])[0] or {}
            spans = set()
            for label, items in res.items():
                for it in items:
                    spans.add(it["text"].strip().lower())
            hit = len(spans & gold_spans[c["case_id"]])
            found += hit
            total += len(gold_spans[c["case_id"]])
            det[c["case_id"]] = {"hit": hit,
                                 "gold": len(gold_spans[c["case_id"]]),
                                 "pred": len(spans)}
        report["uiie_fix"] = None
        report["uie"][name] = {"recall": round(found / total, 3) if total
                               else 0.0, "detail": det}
        print("UIE", name, report["uie"][name]["recall"])

    from gliner import GLiNER
    model = GLiNER.from_pretrained("urchade/gliner_base",
                                   cache_dir="/workspace/guardian/hf_cache")
    for thr in (0.3, 0.5):
        found, total, npred = 0, 0, 0
        for c in dev:
            ents = model.predict_entities(c["policy"], list(
                VARIANTS["V1"].values()), threshold=thr)
            spans = {e["text"].strip().lower() for e in ents}
            found += len(spans & gold_spans[c["case_id"]])
            total += len(gold_spans[c["case_id"]])
            npred += len(spans)
        report["gliner"][str(thr)] = {
            "recall": round(found / total, 3) if total else 0.0,
            "pred": npred}
        print("GLINER", thr, report["gliner"][str(thr)])

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "dev_calibration.json").write_text(
        json.dumps(report, indent=1, ensure_ascii=False) + "\n",
        encoding="utf-8")
    print("written dev_calibration.json")


if __name__ == "__main__":
    main()
