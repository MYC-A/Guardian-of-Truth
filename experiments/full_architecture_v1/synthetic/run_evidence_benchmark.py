"""full_architecture_v1 — Phase D runner: evidence benchmark (directive §20).

Runs every evidence case's probe atoms through:
  * current  (incumbent Python evidence via the bake-off adapter)
  * clingo   (evidence.lp + policy.lp split program)
  * invariant (trace-matching comparator, presence-only subset)
and compares per-primitive truth values against the S1-S3 oracle.

Mismatches are classified:
  ORACLE_MISMATCH_<backend>  — backend disagrees with the reference contract
  CURRENT_LIMITATION         — incumbent honest abstention on a primitive it
                               does not implement (comparison/cardinality...)
  INVARIANT_NOT_EXPRESSIBLE  — comparator scope (documented, not a failure)
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

_FULLARCH = Path(__file__).resolve().parents[1]
_BAKEOFF = _FULLARCH.parent / "core_engine_bakeoff_v1"
for p in (str(_BAKEOFF), str(_BAKEOFF / "backends"), str(_FULLARCH)):
    if p not in sys.path:
        sys.path.insert(0, p)

from synthetic.evidence_cases import build_evidence_cases  # noqa: E402
from evidence.clingo_backend import probe as clingo_probe  # noqa: E402
from evidence.current_backend import probe as current_probe  # noqa: E402

REPO = _FULLARCH.parents[1]
OUT = REPO / "outputs" / "full_architecture_v1" / "synthetic"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    cases = build_evidence_cases()
    rows = []
    summary = {
        "cases": len(cases),
        "current": {"oracle_match": 0, "oracle_mismatch": 0,
                    "current_limitation": 0, "probe_error": 0},
        "clingo": {"oracle_match": 0, "oracle_mismatch": 0,
                   "probe_error": 0},
        "invariant": {"applicable_match": 0, "applicable_mismatch": 0,
                      "not_expressible": 0},
    }
    started = time.time()
    for case in cases:
        row = {"case_id": case.case_id, "description": case.description}
        # current backend
        try:
            current_values = {p.atom_key: p.value
                              for p in current_probe(case.core_input,
                                                     list(case.probe_atoms))}
        except Exception as error:
            current_values = {}
            row["current_error"] = f"{type(error).__name__}: {error}"[:150]
            summary["current"]["probe_error"] += 1
        # clingo backend
        try:
            clingo_values = {p.atom_key: p.value
                             for p in clingo_probe(case.core_input,
                                                   list(case.probe_atoms))}
        except Exception as error:
            clingo_values = {}
            row["clingo_error"] = f"{type(error).__name__}: {error}"[:150]
            summary["clingo"]["probe_error"] += 1
        # invariant comparator
        try:
            from evidence.invariant_backend import probe as invariant_probe
            invariant_values = {p.atom_key: p.value
                                for p in invariant_probe(
                                    case.core_input, list(case.probe_atoms))}
        except Exception as error:
            invariant_values = {}
            row["invariant_error"] = f"{type(error).__name__}: {error}"[:150]

        mismatches = []
        for key, expected in case.expected.items():
            got_current = current_values.get(key, "PROBE_MISSING")
            got_clingo = clingo_values.get(key, "PROBE_MISSING")
            row.setdefault("primitives", []).append({
                "atom": key, "oracle": expected,
                "current": got_current, "clingo": got_clingo,
                "invariant": invariant_values.get(key, "NOT_RUN")})
            if got_current == expected:
                summary["current"]["oracle_match"] += 1
            elif got_current in ("UNKNOWN",) and expected in ("TRUE", "FALSE",
                                                              "BOTH"):
                summary["current"]["current_limitation"] += 1
                mismatches.append(f"CURRENT_LIMITATION:{key}")
            else:
                summary["current"]["oracle_mismatch"] += 1
                mismatches.append(f"ORACLE_MISMATCH_current:{key}")
            if got_clingo == expected:
                summary["clingo"]["oracle_match"] += 1
            else:
                summary["clingo"]["oracle_mismatch"] += 1
                mismatches.append(f"ORACLE_MISMATCH_clingo:{key}")
        for key, expected in case.invariant_expected.items():
            got = invariant_values.get(key)
            if got is None:
                continue
            if got == "NOT_EXPRESSIBLE":
                summary["invariant"]["not_expressible"] += 1
            elif got == expected:
                summary["invariant"]["applicable_match"] += 1
            else:
                summary["invariant"]["applicable_mismatch"] += 1
                mismatches.append(f"INVARIANT_MISMATCH:{key}")
        if mismatches:
            row["mismatches"] = mismatches
        rows.append(row)

    payload = {
        "captured_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "comparison": "current Python evidence vs clingo evidence.lp vs "
                      "invariant comparator (per-primitive, oracle = S1-S3 "
                      "reference contract)",
        "summary": summary,
        "rows": rows,
        "wall_time_s": round(time.time() - started, 1),
    }
    (OUT / "evidence_benchmark.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(summary, indent=1))
    print(f"wall time: {payload['wall_time_s']}s")


if __name__ == "__main__":
    main()
