"""Clingo bridge: runs ASP programs via python3.13 (clingo 5.8.2 lives there).

The main venv is python3.12; clingo is installed for python3.13. We execute a
small runner script in a subprocess and parse its JSON output.
"""
from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

RUNNER = r'''
import json, sys
import clingo

def solve(program: str, max_models: int = 10):
    ctl = clingo.Control(["-n", str(max_models)])
    ok = True
    try:
        ctl.add("base", [], program)
        ctl.ground([("base", [])])
    except RuntimeError as e:
        return {"ok": False, "error": f"ground-error: {e}", "models": []}
    models = []
    ret = {"sat": None}
    try:
        with ctl.solve(yield_=True) as h:
            for m in h:
                models.append(sorted(str(a) for a in m.symbols(atoms=True)))
                if len(models) >= max_models:
                    break
            ret["sat"] = h.get().satisfiable
    except RuntimeError as e:
        return {"ok": False, "error": f"solve-error: {e}", "models": []}
    return {"ok": True, "models": models, "satisfiable": ret["sat"]}

if __name__ == "__main__":
    with open(sys.argv[1]) as f:
        program = f.read()
    print(json.dumps(solve(program)))
'''


def solve(program: str, max_models: int = 10) -> dict:
    """Solve an ASP program. Returns {ok, models: [[atom_str,...]], satisfiable}."""
    with tempfile.TemporaryDirectory() as td:
        prog_f = Path(td) / "prog.lp"
        run_f = Path(td) / "runner.py"
        prog_f.write_text(program, encoding="utf-8")
        run_f.write_text(RUNNER, encoding="utf-8")
        proc = subprocess.run(
            ["/usr/bin/python3.13", str(run_f), str(prog_f)],
            capture_output=True, text=True, timeout=60,
        )
        if proc.returncode != 0:
            return {"ok": False, "error": proc.stderr[-500:], "models": []}
        try:
            return json.loads(proc.stdout.strip().splitlines()[-1])
        except (json.JSONDecodeError, IndexError):
            return {"ok": False, "error": f"parse: {proc.stdout[-300:]}", "models": []}


# ----------------- typed queries used by C/D checks -----------------

def query_holds(facts: list[str], rule: str, query_atom: str) -> dict:
    """Check if query_atom holds in ALL models (cautious) / SOME model (brave)."""
    program = "\n".join(facts) + "\n" + rule + f'\n{query_atom[:-1]} :- not holds.' if False else "\n".join(facts) + "\n" + rule
    # We add a marker: holds(X) queries are formulated by the caller.
    res = solve(program)
    if not res.get("ok"):
        return {"status": "ERROR", "detail": res.get("error", ""), "models": []}
    models = res.get("models", [])
    if not models:
        return {"status": "UNSAT_PREMISES", "detail": "no models — inconsistent facts", "models": []}
    all_hold = all(any(a.startswith(query_atom) for a in m) for m in models)
    some_hold = any(any(a.startswith(query_atom) for a in m) for m in models)
    if all_hold:
        status = "HOLDS_ALL"
    elif some_hold:
        status = "HOLDS_SOME"
    else:
        status = "HOLDS_NONE"
    return {"status": status, "n_models": len(models), "models": models[:4]}
