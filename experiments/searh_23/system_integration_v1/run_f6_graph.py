"""Paired F6 RAWSAN relation replay; run once per mode in separate processes.

PYTHONHASHSEED=0 must be set before Python starts. The same frozen F6 raw
extractor/sanitation files, model, prompts and scorer are used in both arms.
The only intended difference is W1_SCOPE_GUARD. Never overwrite archived F6.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
F6 = HERE.parent / "llm_first_f6"
sys.path.insert(0, str(F6))


def main() -> None:
    if len(sys.argv) != 2 or sys.argv[1] not in ("base", "scope"):
        raise SystemExit("usage: run_f6_graph.py {base|scope}")
    if os.environ.get("PYTHONHASHSEED") != "0":
        raise SystemExit("set PYTHONHASHSEED=0 before launching Python")
    mode = sys.argv[1]
    expected = "1" if mode == "scope" else "0"
    if os.environ.get("W1_SCOPE_GUARD") != expected:
        raise SystemExit(f"set W1_SCOPE_GUARD={expected} before launching Python")

    import en_f6_stack as stack
    import en_f6_graph as graph

    # The archived F6 script refers to an older instance. Keep the model,
    # graph loop and prompts fixed while selecting the current instance cache.
    stack.CE_CACHE = os.environ.get("HF_HOME", "/workspace/guardian/hf_cache")
    subdir = f"system_integration_f6_{mode}"

    def build(_arm: str, case: dict) -> list[dict]:
        return stack.v10.build_nodes_v3("RAWA", case)

    stack.run_arm(f"rawsan_{mode}", "f6", build, subdir)
    result = graph.score_arm(subdir, "f6")
    if result["n_cases"] != 24:
        raise RuntimeError(f"incomplete F6 replay: {result['n_cases']}/24")
    out = HERE / "outputs" / f"f6_graph_{mode}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    print(json.dumps({"mode": mode, "n_cases": result["n_cases"],
                      "edges": result["edges"], "nodes": result["nodes"]}),
          flush=True)


if __name__ == "__main__":
    main()
