"""F6 v10-chain staging — NLP-first frontend baseline on F6.

Stages (all resumable, frozen modules monkey-patched ONLY at the
load_suite boundary, exactly like en_f5_run.py did for F5):
  frontend - LLM_SG extraction (frozen prompts, lf_llm_frontends)
  hygiene  - deterministic candidate hygiene (w1_hygiene)
  bnorm    - LLM boundary normalizer (frozen prompts, w1_bnorm)
  stack    - the frozen v10 loop replay with build_nodes_v3 (en_f6_stack)

Run: python3 en_f6_v10chain.py <stage> [suite]
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

SUITES = {
    "f6": IE / "frozen" / "level_f6_cases.json",
    "f6r": IE / "frozen" / "level_f6r_cases.json",
}


def load_suite(name: str) -> list[dict]:
    return list(json.loads(SUITES[name].read_text(encoding="utf-8")))


def stage_frontend(suite: str) -> None:
    import lf_llm_frontends as fe
    cases = load_suite(suite)
    fe.load_suite = lambda which: cases
    fe.run_llm_sg("original")


def stage_hygiene(suite: str) -> None:
    import w1_hygiene as hyg
    cases = load_suite(suite)
    hyg.load_suite = lambda: cases
    old = sys.argv[:]
    sys.argv[:] = ["w1_hygiene.py", "LLM_SG"]
    try:
        hyg.main()
    finally:
        sys.argv[:] = old


def stage_bnorm(suite: str) -> None:
    import w1_bnorm as bn
    cases = load_suite(suite)
    bn.load_suite = lambda: cases
    old = sys.argv[:]
    sys.argv[:] = ["w1_bnorm.py", "LLM_SG"]
    try:
        bn.main()
    finally:
        sys.argv[:] = old


def stage_stack(suite: str) -> None:
    import en_f6_stack as st
    st.run_arm("v10", suite, st.build_v10, f"{suite}_v10")


if __name__ == "__main__":
    stage = sys.argv[1] if len(sys.argv) > 1 else "frontend"
    suite = sys.argv[2] if len(sys.argv) > 2 else "f6"
    {"frontend": stage_frontend, "hygiene": stage_hygiene,
     "bnorm": stage_bnorm, "stack": stage_stack}[stage](suite)
