"""Create one F3/F4 frontend and replay both W1 v10 arms on it."""
from __future__ import annotations

import importlib
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
IE = HERE.parent / "event_ie_frontends_v1"
W1 = HERE.parent / "step1_working_v1"
sys.path[:0] = [str(ROOT / "src"), str(IE), str(W1),
                str(HERE.parent / "policy_licensing_v1")]


def main() -> None:
    suite = []
    for name in ("f3", "f4"):
        suite += json.loads((IE / "frozen" / f"level_{name}_cases.json").read_text(encoding="utf-8"))
    if len(suite) != 10 or len({x["case_id"] for x in suite}) != 10:
        raise ValueError("expected ten unique frozen cases")
    path = HERE / "outputs/f3f4_paired_inputs.json"
    path.write_text(json.dumps(suite, indent=2) + "\n", encoding="utf-8")

    from pl_common import Mistral as BaseClient

    class ConfiguredClient(BaseClient):
        def __init__(self, model=None, cache_dir=None):
            super().__init__(model=None, cache_dir=cache_dir)

    frontend = importlib.import_module("lf_llm_frontends")
    hygiene = importlib.import_module("w1_hygiene")
    bnorm = importlib.import_module("w1_bnorm")
    for module in (frontend, hygiene, bnorm):
        module.Mistral = ConfiguredClient
        module.load_suite = lambda *args: suite
    frontend.run_llm_sg("original")
    sys.argv = ["w1_hygiene.py", "LLM_SG"]
    hygiene.main()
    sys.argv = ["w1_bnorm.py", "LLM_SG"]
    bnorm.main()
    os.environ["W1_INPUTS"] = str(path)
    for label, guarded in (("paired_baseline", False), ("paired_guard", True)):
        os.environ["W1_SCOPE_GUARD"] = "1" if guarded else "0"
        os.environ["W1_RUN_OUTPUTS"] = str(HERE / "outputs" / label)
        pipe = importlib.reload(importlib.import_module("w1_pipe3"))
        pipe.Mistral = ConfiguredClient
        sys.argv = ["w1_pipe3.py", "LLM_SG"]
        pipe.main()
    print("F3F4_PAIRED_COMPLETE", flush=True)


if __name__ == "__main__":
    main()
