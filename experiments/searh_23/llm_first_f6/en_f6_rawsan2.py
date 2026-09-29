"""F6 rawsan arm — RAW LLM mentions as the candidate source for the FULL
frozen sanitation chain (hygiene -> bnorm -> v10 build_nodes_v3 ->
frozen relation stack).

Architecture: exactly the directive section 0 pipeline with the NLP
candidate generator swapped for the raw LLM extractor. NO new
mechanisms: the raw grounded mentions are written in the LLM_SG
candidate schema, and every downstream stage is the frozen module.

This isolates Q12: is the sanitation/consolidation layer still needed
(and still sufficient) when the candidate source becomes the raw LLM?

Run: python3 en_f6_rawsan.py <stage>   (stages: write, hygiene, bnorm, stack)
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).parent
_env = Path("/home/z/my-project/guardian-access/mistral.env")
if _env.is_file() and not os.environ.get("MISTRAL_API_KEY"):
    for line in _env.read_text().splitlines():
        line = line.strip()
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip("\"'"))
os.environ.setdefault("HF_HOME", "/home/z/my-project/hf_cache")

IE = HERE.parent / "event_ie_frontends_v1"
W1 = HERE.parent / "step1_working_v1"
sys.path[:0] = [str(W1), str(IE), str(HERE)]

RAW = HERE / "outputs" / "raw"
ARM = "RAWA2"

# F6 sem taxonomy -> the frozen pipeline type vocabulary the v10
# sanitation/filters are calibrated on
SEM_TO_TYPE = {"ACTION": "EVENT", "CHECK": "CHECK",
               "STATE": "STATE_OR_FACET", "RECORD": "EVENT",
               "COMMUNICATION": "EVENT",
               "REFERENCE_TO_EVENT": "EVENT_REFERENCE", "OTHER": "ENTITY"}


def load_cases() -> list[dict]:
    return json.loads((IE / "frozen" / "level_f6_cases.json")
                      .read_text(encoding="utf-8"))


def stage_write() -> None:
    """Raw grounded mentions -> LLM_SG candidate schema files."""
    dst = IE / "outputs" / ARM
    dst.mkdir(parents=True, exist_ok=True)
    for case in load_cases():
        f = RAW / "codestral" / "A" / f"{case['case_id']}.json"
        data = json.loads(f.read_text(encoding="utf-8"))
        cands = []
        for i, m in enumerate(data["mentions"], start=1):
            if not m.get("grounded"):
                continue
            cands.append({
                "cid_local": f"c{i:02d}",
                "span": m["quote"],
                "start": m["start"], "end": m["end"],
                "type": SEM_TO_TYPE.get(m.get("type", "OTHER"), "EVENT"),
                "predicate": m.get("predicate"),
                "arguments": [{"role": a["role"], "span": a["quote"],
                               "start": a["start"], "end": a["end"]}
                              for a in (m.get("arguments") or [])],
                "relations": [], "grounded_tools": [],
                "provenance": "offsets"})
        (dst / f"{case['case_id']}.json").write_text(
            json.dumps({"case_id": case["case_id"], "arm": ARM,
                        "candidates": cands}, indent=1) + "\n",
            encoding="utf-8")
        print(case["case_id"], len(cands), flush=True)


def stage_hygiene() -> None:
    import w1_hygiene as hyg
    hyg.load_suite = load_cases
    old = sys.argv[:]
    sys.argv[:] = ["w1_hygiene.py", ARM]
    try:
        hyg.main()
    finally:
        sys.argv[:] = old


def stage_bnorm() -> None:
    import w1_bnorm as bn
    bn.load_suite = load_cases
    old = sys.argv[:]
    sys.argv[:] = ["w1_bnorm.py", ARM]
    try:
        bn.main()
    finally:
        sys.argv[:] = old


def stage_stack() -> None:
    import en_f6_stack as st

    def build(arm_: str, case: dict) -> list[dict]:
        return st.v10.build_nodes_v3(ARM, case)
    st.run_arm("rawsan2", "f6", build, "f6_rawsan2")


if __name__ == "__main__":
    stage = sys.argv[1] if len(sys.argv) > 1 else "write"
    {"write": stage_write, "hygiene": stage_hygiene,
     "bnorm": stage_bnorm, "stack": stage_stack}[stage]()
