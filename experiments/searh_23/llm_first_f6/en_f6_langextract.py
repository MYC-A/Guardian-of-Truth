"""F6 ARM 14 — LangExtract as an auxiliary extractive mechanism.

Directive section 14 asks whether LangExtract helps: recall, exact-
source grounding, recovery of missed passive/nominalized/nested
mentions - NOT to assume it is better than the raw LLM.

Honest scope: on F6 the raw extractor already has coverage 1.0
(mistral) / .992 (codestral) with 0 hallucinated quotes, so there is
almost nothing to RECOVER; the meaningful comparison is LangExtract
as a PRIMARY extractor (with its built-in span alignment) vs the raw
arm on the same cases.

Backend: LangExtract OpenAILanguageModel pointed at the Mistral API
(OpenAI-compatible endpoint), model ministral-14b-latest, the same
model as ARM A - so the comparison isolates the extractive machinery
(prompting style + built-in alignment), not the model.

Run: python3 en_f6_langextract.py [n_cases]
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).parent
_env = Path("/home/z/my-project/guardian-access/mistral.env")
KEY = None
if _env.is_file():
    for line in _env.read_text().splitlines():
        line = line.strip()
        if line.startswith("export "):
            line = line[7:].strip()
        if line.startswith("MISTRAL_API_KEY="):
            KEY = line.split("=", 1)[1].strip().strip("\"'")

IE = HERE.parent / "event_ie_frontends_v1"
RAW = HERE / "outputs" / "raw"
OUT = HERE / "outputs" / "langextract"
OUT.mkdir(parents=True, exist_ok=True)

import langextract as lx  # noqa: E402
from langextract.providers.openai import OpenAILanguageModel  # noqa: E402

PROMPT_HINT = (
    "Extract every policy-relevant semantic mention from workplace "
    "policies: actions to perform, checks or verifications, states of "
    "affairs, recordings of events, communications, and references to "
    "earlier events. Extract only text present verbatim in the source. "
    "Extraction classes: ACTION, CHECK, STATE, RECORD, COMMUNICATION, "
    "REFERENCE_TO_EVENT.")

EXAMPLE = lx.data.ExampleData(
    text=("Inspect the sluice gate before operating it. Once it has "
          "been inspected, operating is permitted. Verify that the "
          "inspection is logged."),
    extractions=[
        lx.data.Extraction(extraction_class="CHECK",
                           extraction_text="Inspect the sluice gate"),
        lx.data.Extraction(extraction_class="STATE",
                           extraction_text="it has been inspected"),
        lx.data.Extraction(extraction_class="ACTION",
                           extraction_text="operating is permitted"),
        lx.data.Extraction(extraction_class="CHECK",
                           extraction_text="Verify that the inspection "
                                           "is logged"),
        lx.data.Extraction(extraction_class="RECORD",
                           extraction_text="the inspection is logged"),
        lx.data.Extraction(extraction_class="REFERENCE_TO_EVENT",
                           extraction_text="the inspection"),
    ])


def iou(a, b):
    inter = max(0, min(a["end"], b["end"]) - max(a["start"], b["start"]))
    if inter == 0:
        return 0.0
    union = max(a["end"], b["end"]) - min(a["start"], b["start"])
    return inter / max(1, union)


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 8
    cases = json.loads((IE / "frozen" / "level_f6_cases.json")
                       .read_text(encoding="utf-8"))[:n]
    model = OpenAILanguageModel(model_id="ministral-14b-latest",
                                api_key=KEY,
                                base_url="https://api.mistral.ai/v1",
                                temperature=0.0, max_workers=1)
    rows = []
    tot = dict(pred=0, gold=0, covered=0, exact=0, junk=0, aligned=0)
    for case in cases:
        cid = case["case_id"]
        out_path = OUT / f"{cid}.json"
        if out_path.exists():
            res = json.loads(out_path.read_text(encoding="utf-8"))
        else:
            t0 = time.time()
            try:
                doc = lx.extract(case["policy"],
                                 prompt_description=PROMPT_HINT,
                                 examples=[EXAMPLE], model=model,
                                 show_progress=False,
                                 extraction_passes=1)
                res = getattr(doc, "extractions", [])
            except Exception as exc:
                res = []
                print(cid, "ERROR", str(exc)[:120])
            mentions = []
            for i, ex in enumerate(res):
                iv = getattr(ex, "char_interval", None)
                s0 = getattr(iv, "start_pos", None) if iv is not None else None
                s1 = getattr(iv, "end_pos", None) if iv is not None else None
                mentions.append({
                    "quote": getattr(ex, "extraction_text", ""),
                    "class": getattr(ex, "extraction_class", ""),
                    "start": s0, "end": s1,
                    "alignment": str(getattr(ex, "alignment_status", ""))})
            res = {"case_id": cid, "mentions": mentions,
                   "latency_s": round(time.time() - t0, 2)}
            out_path.write_text(json.dumps(res, indent=1,
                                           ensure_ascii=False) + "\n",
                                encoding="utf-8")
        pred = [m for m in res["mentions"] if m.get("start") is not None]
        goldm = [m for m in case["mentions"] if m.get("cid")]
        gspans = {m["span"] for m in goldm}
        pspans = {m["quote"] for m in pred}
        covered = sum(1 for g in goldm
                      if any(iou({"start": p["start"], "end": p["end"]},
                                 g) > 0 for p in pred))
        exact = len(gspans & pspans)
        junk = sum(1 for p in pred
                   if not any(iou({"start": p["start"], "end": p["end"]},
                                  g) > 0 for g in goldm))
        aligned = sum(1 for p in pred
                      if case["policy"][p["start"]:p["end"]] == p["quote"])
        tot["pred"] += len(pred)
        tot["gold"] += len(goldm)
        tot["covered"] += covered
        tot["exact"] += exact
        tot["junk"] += junk
        tot["aligned"] += aligned
        rows.append({"case_id": cid, "n_pred": len(pred),
                     "coverage": covered, "exact": exact, "junk": junk,
                     "aligned": aligned})
        print(cid, len(pred), "cov", covered, "exact", exact, flush=True)
    # compare with raw ARM A on the same cases
    comp = []
    for case in cases:
        cid = case["case_id"]
        f = RAW / "mistral" / "A" / f"{cid}.json"
        d = json.loads(f.read_text(encoding="utf-8"))
        pred = [m for m in d["mentions"] if m.get("grounded")]
        goldm = [m for m in case["mentions"] if m.get("cid")]
        covered = sum(1 for g in goldm
                      if any(iou({"start": p["start"], "end": p["end"]},
                                 g) > 0 for p in pred))
        comp.append(covered)
    out = {"n_cases": len(rows),
           "langextract": {"pred": tot["pred"], "gold": tot["gold"],
                           "coverage": round(tot["covered"] /
                                             max(1, tot["gold"]), 3),
                           "exact": tot["exact"],
                           "junk": tot["junk"],
                           "span_alignment_ok": tot["aligned"]},
           "raw_arm_a_coverage_on_same": round(
               sum(comp) / max(1, tot["gold"]), 3),
           "per_case": rows}
    (OUT / "langextract_summary.json").write_text(
        json.dumps(out, indent=1, ensure_ascii=False) + "\n",
        encoding="utf-8")
    print(json.dumps({k: v for k, v in out.items() if k != "per_case"},
                     indent=1))


if __name__ == "__main__":
    main()
