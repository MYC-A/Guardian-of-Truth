import json

import pytest

from guardian_truth.vnext.claims import PASSES, build_claim_graph
from guardian_truth.vnext.semantic import Proposal, schema_valid
from guardian_truth.vnext.types import ClaimKind, Disposition, Reason


class FakeBackend:
    def __init__(self, *, fail=None, missing=None, invented_entity=False, causal=False):
        self.fail, self.missing = fail, missing
        self.invented_entity, self.causal = invented_entity, causal
        self.tasks = []

    def propose(self, task, payload, schema):
        self.tasks.append((task, payload, schema))
        assert "start" not in payload["span_inventory"][0]
        assert "history" not in payload and "gold" not in payload
        if task == self.fail:
            return Proposal(None, "ERROR", "NOT_EVALUATED", "timeout")
        spans = payload["span_inventory"]
        if task == "claim_relations":
            value = {"relations": []}
        else:
            field = schema["properties"]["spans"]["items"]["properties"]
            values = {"disposition": "VERIFIABLE_TYPED", "kind": "CAUSAL_ATTRIBUTION" if self.causal else "ACTION_COMPLETED",
                "actor": "assistant", "predicate": "archive", "object": "R-71", "entity_refs": ["invented" if self.invented_entity else "R-71"],
                "modality": "ASSERTED", "polarity": "POSITIVE", "time_anchor": "PAST", "source_refs": ["ASSISTANT"],
                "explicit_causality": None if self.causal else False}
            value = {"spans": [{key: (span["span_id"] if key == "span_id" else values[key]) for key in field} for span in spans]}
            if task == self.missing:
                value["spans"] = []
        return Proposal(json.dumps(value), "SUCCESS", "VALID")


def test_all_ten_passes_are_narrow_and_offset_free():
    backend = FakeBackend()
    graph = build_claim_graph("I archived R-71.", backend)
    assert [task for task, _, _ in backend.tasks] == [task for task, _, _ in PASSES]
    assert len(graph.claims) == 1
    assert graph.claims[0].kind is ClaimKind.ACTION_COMPLETED
    assert graph.claims[0].disposition is Disposition.VERIFIABLE_TYPED
    assert graph.claims[0].span.start == 0
    assert not graph.failures


@pytest.mark.parametrize("task", [item[0] for item in PASSES if item[0] not in {"claim_relations", "claim_explicit_causality"}])
def test_failed_field_preserves_span_and_unknown_instead_of_dropping(task):
    graph = build_claim_graph("I archived R-71.", FakeBackend(fail=task))
    assert len(graph.claims) == 1
    assert graph.claims[0].disposition is Disposition.UNKNOWN_SEMANTICS
    assert (task, Reason.TRANSPORT_ERROR) in graph.failures


def test_schema_inventory_omission_is_not_semantic_nonverifiable():
    graph = build_claim_graph("I archived R-71.", FakeBackend(missing="claim_kind"))
    assert graph.claims[0].disposition is Disposition.UNKNOWN_SEMANTICS
    assert ("claim_kind", Reason.SCHEMA_ERROR) in graph.failures


def test_entity_ids_must_be_grounded_in_response():
    graph = build_claim_graph("I archived R-71.", FakeBackend(invented_entity=True))
    assert graph.claims[0].disposition is Disposition.UNKNOWN_SEMANTICS
    assert graph.claims[0].entity_refs == ()


def test_causal_type_does_not_silently_become_state_or_proof():
    graph = build_claim_graph("My call archived R-71.", FakeBackend(causal=True))
    assert graph.claims[0].kind is ClaimKind.CAUSAL_ATTRIBUTION
    assert graph.claims[0].disposition is Disposition.UNKNOWN_SEMANTICS
    assert "explicit_causality" in graph.claims[0].unknown_fields


def test_empty_inventory_makes_no_network_call():
    backend = FakeBackend()
    assert build_claim_graph("", backend).claims == ()
    assert backend.tasks == []


def test_schema_validator_rejects_extra_keys_and_bool_integer():
    assert not schema_valid(True, {"type": "integer"})
    assert not schema_valid({"x": 1}, {"type": "object", "properties": {}, "additionalProperties": False})
    assert not schema_valid(["a", "a"], {"type": "array", "uniqueItems": True, "items": {"type": "string"}})
