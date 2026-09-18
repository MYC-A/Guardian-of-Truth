"""full_architecture_v1 — Clingo backend over the SPLIT program (§13/§15).

Runs the per-case data + static evidence.lp + static policy.lp through the
clingo Python API and extracts:

  * per-model world verdicts (one stable model per interpretation — the
    choice rule in policy.lp enumerates them natively)
  * per-query tval snapshots (the evidence module's trusted/support/refute
    four-valued view; sup/ref fact ids are recovered for witnesses)
  * obligation safety values
  * consensus status + explicit brave/cautious-vs-consensus equivalence check
  * per-rule witnesses (supporting/refuting fact ids + unknown dependencies)

The result contract is the bake-off BackendResult so the 43-scenario
regression (directive §19) compares apples to apples.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

_FULLARCH = Path(__file__).resolve().parents[1]
_BAKEOFF = _FULLARCH.parent / "core_engine_bakeoff_v1"
for p in (str(_BAKEOFF), str(_BAKEOFF / "backends"), str(_FULLARCH)):
    if p not in sys.path:
        sys.path.insert(0, p)

import clingo  # noqa: E402

from neutral_types import (  # noqa: E402
    BackendResult, BackendWitness, NeutralAtom, NeutralCoreInput,
    PrimitiveResult, WorldResult,
)
from clingo_backend import (  # noqa: E402
    _asp_truth, _consensus, _run_program, _witnesses,
)
from evidence.adapter import EVIDENCE_LP, POLICY_LP, build_program  # noqa: E402

BACKEND_NAME = "fullarch-clingo(evidence.lp+policy.lp)"


def evaluate(ci: NeutralCoreInput) -> BackendResult:
    started = time.perf_counter()
    if not ci.interpretations:
        return BackendResult(backend=BACKEND_NAME, status="UNRESOLVED",
                             input_content_hash=ci.content_hash(),
                             notes="empty interpretation space")
    program_text, prog, obligations = build_program(ci)

    try:
        _control, models = _run_program(program_text)
    except Exception as error:  # pragma: no cover
        return BackendResult(backend=BACKEND_NAME, status="ERROR",
                             input_content_hash=ci.content_hash(),
                             detail=f"{type(error).__name__}: {error}")

    if not models:
        return BackendResult(backend=BACKEND_NAME, status="ERROR",
                             input_content_hash=ci.content_hash(),
                             detail="no stable models")

    worlds: list[WorldResult] = []
    obligation_interp = {oid: interp_id
                         for oid, interp_id, _rule, _fact in obligations}
    for model in models:
        werr: dict[str, str] = {}
        safs: dict[str, str] = {}
        for atom in model:
            if atom.name == "werr" and len(atom.arguments) == 2:
                werr[str(atom.arguments[0]).strip('"')] = \
                    _asp_truth(str(atom.arguments[1]))
            elif atom.name == "saf" and len(atom.arguments) == 2:
                safs[str(atom.arguments[0])] = _asp_truth(str(atom.arguments[1]))
        for interp_id, value in werr.items():
            # only obligations of THIS interpretation form the world's
            # safety conjuncts (saf is derived for every obligation)
            safety = tuple(sorted(
                (oid, safety_value) for oid, safety_value in safs.items()
                if obligation_interp.get(oid) == interp_id))
            worlds.append(WorldResult(interp_id, value, safety))

    status = _consensus(worlds)

    # brave/cautious equivalence check (tested per case, not assumed)
    cautious_true = all(any(w.interp_id == wid and w.error_value == "TRUE"
                            for w in worlds)
                        for wid in {w.interp_id for w in worlds})
    cautious_false = all(w.error_value == "FALSE" for w in worlds)
    brave_both = any(w.error_value == "BOTH" for w in worlds)
    any_unk = any(w.error_value == "UNKNOWN" for w in worlds)
    any_true = any(w.error_value == "TRUE" for w in worlds)
    any_false = any(w.error_value == "FALSE" for w in worlds)
    if brave_both:
        bc_status = "INCONSISTENT"
    elif cautious_true and not any_false:
        bc_status = "PROVED_ERROR"
    elif cautious_false and not any_true:
        bc_status = "PROVED_NO_ERROR"
    else:
        bc_status = "UNRESOLVED"
    equiv = "brave/cautious-vs-consensus:" + (
        "EQUIVALENT" if bc_status == status else
        f"MISMATCH(consensus={status},b/c={bc_status})")

    witnesses = _witnesses(models, prog, obligations)
    runtime_ms = (time.perf_counter() - started) * 1000.0
    return BackendResult(backend=BACKEND_NAME, status=status,
                         worlds=tuple(worlds), witnesses=witnesses,
                         runtime_ms=runtime_ms,
                         input_content_hash=ci.content_hash(),
                         notes=f"models={len(models)}; {equiv}")


def probe(ci: NeutralCoreInput, atoms: list[NeutralAtom]) \
        -> list[PrimitiveResult]:
    """Evaluate raw query atoms (evidence primitives).

    Same contract as the bake-off probe: emits the case's facts plus the
    probe atoms' query descriptors, runs data + evidence.lp + policy.lp (the
    tval layer is world-independent — verified across models), and returns
    per-atom truth with supporting/refuting fact ids where the engine
    derives them (sup/2; ref/1 has no fact id, matching the ASP design).
    """
    from clingo_backend import _emit_facts, _Program, _support_map
    prog = _Program()
    _emit_facts(ci, prog)
    if not any(line.startswith("interp(") for line in prog.data):
        # no interpretations: add a degenerate one so the choice rule is
        # satisfiable and tval can be read from a model
        prog.line('interp("probe").')
    qids = [prog.query_id(atom, atom.time_index) for atom in atoms]
    program_text = ("\n".join(prog.data) + "\n" + EVIDENCE_LP + "\n"
                    + POLICY_LP + "\n")
    try:
        _control, models = _run_program(program_text)
    except Exception:
        return [PrimitiveResult(atom_key=a.key(), value="UNKNOWN")
                for a in atoms]
    results: list[PrimitiveResult] = []
    if models:
        tvals: dict[str, str] = {}
        consistent = True
        for model in models:
            current = {}
            for atom in model:
                if atom.name == "tval" and len(atom.arguments) == 2:
                    current[str(atom.arguments[0])] = \
                        _asp_truth(str(atom.arguments[1]))
            if not tvals:
                tvals = current
            elif current != tvals:
                consistent = False
        supports = _support_map(models)
        for qid in qids:
            value = tvals.get(qid, "UNKNOWN")
            sup, ref = supports.get(qid, ((), ()))
            results.append(PrimitiveResult(prog.queries[qid], value,
                                           tuple(sup), tuple(ref)))
        if not consistent:
            results.append(PrimitiveResult("tval_consistency", "FALSE", (), ()))
    else:
        for qid in qids:
            results.append(PrimitiveResult(prog.queries[qid], "UNKNOWN", (), ()))
    return results
