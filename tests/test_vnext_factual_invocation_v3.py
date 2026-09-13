import json

from guardian_truth.vnext.factual_invocation_v3 import FactualInvocationInput, analyze_factual_fields
from guardian_truth.vnext.semantic import Proposal
from guardian_truth.vnext.types import Disposition, Reason, Truth
from test_vnext_claim_field_bindings_v3 import Backend
from test_vnext_scoped_result_evidence_v2 import DECLARATION, TOOL


class GraphBackend(Backend):
    def __init__(self, *, graph_failure=None):
        super().__init__()
        self.graph_failure, self.graph_calls = graph_failure, []

    def propose(self, task, payload, schema):
        if task == 'claim_result_field_meanings_v3':
            return super().propose(task, payload, schema)
        self.graph_calls.append(task)
        if task == self.graph_failure:
            return Proposal(None, 'ERROR', 'NOT_EVALUATED', 'timeout')
        if task == 'claim_relations':
            return Proposal('{"relations":[]}', 'SUCCESS', 'VALID')
        values = {'disposition': 'VERIFIABLE_TYPED', 'kind': 'ATTRIBUTION', 'actor': 'tool',
            'predicate': 'price', 'object': '42', 'entity_refs': ['Alex'], 'modality': 'REPORTED',
            'polarity': 'POSITIVE', 'time_anchor': 'PAST', 'source_refs': ['TOOL'], 'explicit_causality': False}
        fields = schema['properties']['spans']['items']['properties']
        result = {'spans': [{name: span['span_id'] if name == 'span_id' else values[name] for name in fields}
            for span in payload['span_inventory']]}
        return Proposal(json.dumps(result), 'SUCCESS', 'VALID')


def data(*, declarations=True, duplicate=False):
    prompt = '⟦ASSISTANT_TOOL_CALL name="read_records" call_id="c"⟧\n{}\n'
    records = [{'id': 'a', 'name': 'Alex', 'price': 42}]
    if duplicate:
        records.append({'id': 'b', 'name': 'Alex', 'price': 99})
    prompt += '⟦TOOL_RESULT name="read_records" call_id="c" requestor="assistant"⟧\n' + json.dumps({'items': records})
    return FactualInvocationInput(prompt, 'Tool reported price 42 for Alex.', (TOOL,),
        (DECLARATION,) if declarations else (), True, 'controlled history prefix')


def test_one_runnable_path_connects_source_graph_index_primitive_and_independent_receipt():
    backend = GraphBackend()
    result = analyze_factual_fields(data(), backend)
    assert len(backend.graph_calls) == 10 and len(backend.calls) == 1
    assert result.evidence.claims[0].value is Truth.TRUE
    assert result.receipt is not None and result.receipt_check.valid
    assert result.ledger.effects == ()
    assert not hasattr(result, 'status') and 'NOT_FULL_CORE' in result.scope


def test_missing_authoritative_identity_metadata_is_unknown_not_guessed_from_name():
    result = analyze_factual_fields(data(declarations=False), GraphBackend())
    assert result.receipt_check.valid
    assert result.evidence.claims[0].value is Truth.UNKNOWN
    assert Reason.ENTITY_UNBOUND in (result.diagnostics.primary_reason, *result.diagnostics.contributing_reasons)


def test_duplicate_name_retains_both_records_and_exposes_blocked_claim():
    result = analyze_factual_fields(data(duplicate=True), GraphBackend())
    assert result.receipt_check.valid
    assert result.evidence.claims[0].value is Truth.UNKNOWN
    assert len(result.evidence.claims[0].bindings) == 2
    assert result.diagnostics.blocked_claims == (result.graph.claims[0].claim_id,)


def test_failed_graph_field_remains_a_span_with_transport_diagnostic():
    result = analyze_factual_fields(data(), GraphBackend(graph_failure='claim_kind'))
    assert result.receipt_check.valid
    assert result.graph.claims[0].disposition is Disposition.UNKNOWN_SEMANTICS
    assert result.diagnostics.primary_reason is Reason.TRANSPORT_ERROR
    assert result.evidence.claims[0].value is Truth.UNKNOWN


def test_empty_source_and_target_make_no_semantic_request_or_claim_of_safety():
    backend = GraphBackend()
    result = analyze_factual_fields(FactualInvocationInput('', ''), backend)
    assert not backend.graph_calls and not backend.calls
    assert result.receipt_check.valid and not result.graph.claims
    assert not hasattr(result.receipt, 'status')


def test_explicit_backend_path_never_loads_credentials_or_constructs_implicit_client(monkeypatch):
    from guardian_truth import settings
    def forbidden(*args, **kwargs):
        raise AssertionError('implicit environment/credential read')
    monkeypatch.setattr(settings, 'load_env_file', forbidden)
    assert analyze_factual_fields(data(), GraphBackend()).receipt_check.valid
