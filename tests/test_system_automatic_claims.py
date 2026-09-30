"""Literal claim compiler must abstain on adversarial source changes."""
from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from guardian_truth.integration.automatic_claims import compile_candidate_claims
from guardian_truth.step2.verifier import CallEvent, TrajectoryCase


def _case():
    tool = {"name": "opaque", "description": "Marks one task done.",
            "parameters": {"task_id": "string", "amount": "number"},
            "result_schema": {"task_id": "string", "state": "scalar"},
            "documented_contracts": [{
                "entity_argument": "task_id", "entity_type": "task",
                "result_entity_path": "$.task_id", "result_value_path": "$.state",
                "predicate": "task.state", "strength": "EXECUTED",
                "allowed_values": ["done"], "meaning": "Marks one task done."}]}
    return TrajectoryCase("control", "policy", "test", (tool,),
                          (CallEvent(0, "c1", "opaque", {"task_id": "X-7", "amount": 250}),),
                          ())


def _proposal(quote: str) -> str:
    return json.dumps({"candidates": [
        {"id": "c0", "mode": "CLAIMED_COMPLETED", "quote": quote}]})


def test_exact_entity_value_and_amount_make_a_bound_query():
    response = "I marked task X-7 done for 250."
    compiled = compile_candidate_claims(response, 4, _case(), _proposal(response))
    assert compiled.inventory_complete and not compiled.issues
    assert len(compiled.queries) == 1
    assert compiled.queries[0].scope_arguments == (("amount", "250"),)
    assert compiled.queries[0].actor == "ASSISTANT"


def test_wrong_amount_and_wrong_entity_are_unbound():
    for response in ("I marked task X-7 done for 100.",
                     "I marked task X-8 done for 250."):
        compiled = compile_candidate_claims(response, 4, _case(), _proposal(response))
        assert not compiled.queries and not compiled.inventory_complete


def test_negated_literal_cannot_establish_positive_completion():
    response = "I did not mark task X-7 done for 250."
    compiled = compile_candidate_claims(response, 4, _case(), _proposal(response))
    assert not compiled.queries and not compiled.inventory_complete
    assert "c0:negated_literal_requires_semantics" in compiled.issues


def test_uncovered_second_sentence_makes_inventory_incomplete():
    response = "I marked task X-7 done for 250. Please wait."
    first = "I marked task X-7 done for 250."
    compiled = compile_candidate_claims(response, 4, _case(), _proposal(first))
    assert len(compiled.queries) == 1
    assert not compiled.inventory_complete
    assert any(x.startswith("uncovered_response_words") for x in compiled.issues)
