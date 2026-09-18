"""core_engine_bakeoff_v1 — OPTIONAL Soufflé 2.5 provenance probe.

Focused question (per the directive): could Soufflé replace/improve
Guardian's derived-fact/provenance layer?  NOT a full Core candidate.

What is tested:
  * facts -> derived relation (transitive reachability) with Soufflé's
    recursive Datalog evaluation
  * --provenance mode: the `explain` interface for a derived tuple

The probe is a MINIMAL smoke test; conclusions are recorded in
engine_capabilities.json and the final report.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
OUT = REPO / "outputs" / "core_engine_bakeoff_v1"

SOUFFLE = os.environ.get("BAKEOFF_SOUFFLE", "/home/z/souffle-root/bin/souffle")
LD_LIBRARY_PATH = os.environ.get(
    "BAKEOFF_SOUFFLE_LIBS",
    "/home/z/souffle-root/usr/lib/x86_64-linux-gnu")

PROGRAM = r"""
.decl fact_node(n: symbol)
.decl edge(a: symbol, b: symbol)
.decl derived_path(a: symbol, b: symbol) output

// input facts (synthetic; generic placeholders)
edge("e1", "e2").
edge("e2", "e3").
edge("e3", "e4").
edge("e5", "e6").
fact_node("e1"). fact_node("e2"). fact_node("e3").
fact_node("e4"). fact_node("e5"). fact_node("e6").

// recursive derived relation with a join
derived_path(x, y) :- edge(x, y).
derived_path(x, y) :- edge(x, z), derived_path(z, y).
"""


def run_probe() -> dict:
    """Run the minimal provenance probe; returns a findings record."""
    started = time.perf_counter()
    if not Path(SOUFFLE).exists():
        return {"status": "SOUFFLE_SKIPPED_ENVIRONMENT",
                "reason": f"souffle binary not found at {SOUFFLE}"}
    findings = {"status": "RUN", "program": "transitive reachability"}
    with tempfile.TemporaryDirectory(prefix="bakeoff_souffle_") as td:
        td = Path(td)
        prog = td / "probe.dl"
        prog.write_text(PROGRAM, encoding="utf-8")
        env = dict(os.environ)
        env["LD_LIBRARY_PATH"] = LD_LIBRARY_PATH + ":" + env.get("LD_LIBRARY_PATH", "")
        # 1) plain evaluation
        try:
            proc = subprocess.run(
                [SOUFFLE, "-D", str(td), str(prog)],
                capture_output=True, text=True, timeout=60, env=env,
                stdin=subprocess.DEVNULL)
            plain_ok = proc.returncode == 0
            rows = (td / "derived_path.csv").read_text().strip().splitlines() \
                if (td / "derived_path.csv").exists() else []
            findings["plain_eval"] = {
                "ok": plain_ok, "derived_tuples": len(rows),
                "sample": rows[:3]}
        except Exception as error:
            findings["plain_eval"] = {"ok": False,
                                      "error": f"{type(error).__name__}: {error}"}
        # 2) provenance mode: -t explain gives the interactive derivation
        #    tree for a derived tuple (native rule-level justification)
        try:
            explain = subprocess.run(
                [SOUFFLE, "-t", "explain", str(prog)],
                input="explain derived_path(\"e1\", \"e4\")\nexit\n",
                capture_output=True, text=True, timeout=60, env=env)
            ok = ("R2" in explain.stdout and "e2" in explain.stdout)
            findings["explain_query"] = {
                "ok": ok,
                "output_excerpt": explain.stdout[:600]}
        except Exception as error:
            findings["explain_query"] = {
                "ok": False, "error": f"{type(error).__name__}: {error}"}
    findings["runtime_s"] = round(time.perf_counter() - started, 2)
    return findings


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    result = run_probe()
    (OUT / "souffle_probe.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=1))
