"""Backend expressibility controls; no natural-language model or gold labels."""
import sys
from pathlib import Path
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).resolve().parents[1] /
                      "experiments/searh_23/hybrid_service_v1"))
from classical_ground_probe import solve_classical


def literal(name, polarity="POS"):
    return NS(atom_id=name, polarity=polarity)


def test_only_if_necessary_condition_can_refute_permission():
    program = NS(status="FORMALIZED", atoms=[NS(id="a1"), NS(id="a2")],
        facts=[NS(literal=literal("a2", "NEG"))], query=literal("a1"),
        rules=[NS(direction="ONLY_IF", conditions=[literal("a2")], conclusion=literal("a1"))])
    assert solve_classical(program)["relation"] == "CONTRADICTS"
    program.facts = [NS(literal=literal("a2"))]
    assert solve_classical(program)["relation"] == "INSUFFICIENT"


def test_inconsistent_theory_never_proves_arbitrary_query():
    program = NS(status="FORMALIZED", atoms=[NS(id="a1"), NS(id="a2")],
        facts=[NS(literal=literal("a2")), NS(literal=literal("a2", "NEG"))],
        query=literal("a1"), rules=[])
    assert solve_classical(program) == {"relation": "INSUFFICIENT", "reason": "inconsistent_theory"}
