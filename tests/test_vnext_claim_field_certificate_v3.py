import ast
from dataclasses import replace
import json
from pathlib import Path

from guardian_truth.cycle2.claims import response_spans
from guardian_truth.vnext.claim_field_bindings_v3 import interpret_graph_result_fields
from guardian_truth.vnext.claim_field_certificate_v3 import check_field_evidence, check_field_receipt, make_field_receipt
from guardian_truth.vnext.claims import ClaimGraph
from guardian_truth.vnext.identity_aliases_v2 import IdentityAliasIndex
from guardian_truth.vnext.integrity import digest
from guardian_truth.vnext.ledger import EvidenceLedger
from guardian_truth.vnext.normalize import normalize
from guardian_truth.vnext.types import ClaimKind, Span, Truth
from test_vnext_claim_field_bindings_v3 import Backend, claim
from test_vnext_scoped_result_evidence_v2 import DECLARATION, TOOL


def fixture(records=None, *, backend=None, complete=True):
    records = records or [{'id': 'a', 'name': 'Alex', 'price': 42}]
    prompt = '⟦ASSISTANT_TOOL_CALL name="read_records" call_id="c"⟧\n{}\n'
    prompt += '⟦TOOL_RESULT name="read_records" call_id="c" requestor="assistant"⟧\n' + json.dumps({'items': records})
    text = 'Tool reported price 42 for Alex.'
    span = response_spans(text)[0]
    node = replace(claim(text), claim_id=span['span_id'], span=Span('response', span['start'], span['end']))
    graph = ClaimGraph(digest(text), (node,), (), (), ())
    ledger = EvidenceLedger.from_events(normalize(prompt, text, tool_identities=(TOOL,)),
        history_complete=complete, completeness_basis='controlled prefix' if complete else None)
    source = IdentityAliasIndex(ledger, (DECLARATION,))
    evidence = interpret_graph_result_fields(text, graph, source, backend or Backend())
    args = (prompt, text, (TOOL,), (DECLARATION,), graph)
    kwargs = {'history_complete': complete, 'completeness_basis': 'controlled prefix' if complete else None}
    return args, kwargs, evidence


def test_original_source_graph_bindings_and_numeric_proofs_independently_validate():
    args, kwargs, evidence = fixture()
    assert check_field_evidence(*args, evidence, **kwargs).valid
    receipt = make_field_receipt(*args, evidence, **kwargs)
    assert check_field_receipt(receipt, *args, evidence, **kwargs).valid
    assert not hasattr(receipt, 'status')
    assert 'Core safety' in dict(receipt.assumptions)['SCOPE']


def test_alternative_binding_cannot_be_dropped_to_make_claim_true():
    args, kwargs, evidence = fixture([{'id': 'a', 'name': 'Alex', 'price': 42}, {'id': 'b', 'name': 'Alex', 'price': 99}])
    assert check_field_evidence(*args, evidence, **kwargs).valid
    row = replace(evidence.claims[0], bindings=evidence.claims[0].bindings[:1], value=Truth.TRUE)
    bad = replace(evidence, claims=(row,))
    checked = check_field_evidence(*args, bad, **kwargs)
    assert not checked.valid and any('ALTERNATIVE_DROPPED' in error for error in checked.errors)


def test_false_result_cannot_be_relabelled_positive_by_tampering_primitive():
    args, kwargs, evidence = fixture([{'id': 'a', 'name': 'Alex', 'price': 99}])
    binding = evidence.claims[0].bindings[0]
    forged = replace(binding, proof=replace(binding.proof, value=Truth.TRUE))
    bad = replace(evidence, claims=(replace(evidence.claims[0], bindings=(forged,), value=Truth.TRUE),))
    assert not check_field_evidence(*args, bad, **kwargs).valid


def test_retrieval_miss_or_partial_history_cannot_be_promoted_to_complete_agreement():
    args, kwargs, evidence = fixture(complete=False)
    assert check_field_evidence(*args, evidence, **kwargs).valid
    bad = replace(evidence, claims=(replace(evidence.claims[0], candidate_set_complete=True, value=Truth.TRUE),))
    assert not check_field_evidence(*args, bad, **kwargs).valid


def test_target_literal_query_value_is_reconstructed_not_trusted_from_output():
    args, kwargs, evidence = fixture()
    binding = evidence.claims[0].bindings[0]
    bad_binding = replace(binding, query=replace(binding.query, expected_json='true'))
    bad = replace(evidence, claims=(replace(evidence.claims[0], bindings=(bad_binding,)),))
    assert not check_field_evidence(*args, bad, **kwargs).valid


def test_evidence_scope_cannot_be_changed_to_current_state_or_core_verdict():
    args, kwargs, evidence = fixture()
    bad = replace(evidence, claims=(replace(evidence.claims[0], scope='CURRENT_STATE_PROVED_NO_ERROR'),))
    assert not check_field_evidence(*args, bad, **kwargs).valid


def test_changed_source_or_receipt_assumptions_are_rejected():
    args, kwargs, evidence = fixture()
    receipt = make_field_receipt(*args, evidence, **kwargs)
    assert not check_field_receipt(replace(receipt, assumptions=()), *args, evidence, **kwargs).valid
    changed = (args[0].replace('42', '99'), *args[1:])
    assert not check_field_receipt(receipt, *changed, evidence, **kwargs).valid


def test_field_attribution_cannot_be_recast_as_completed_or_causal_claim():
    args, kwargs, evidence = fixture()
    graph = replace(args[-1], claims=(replace(args[-1].claims[0], kind=ClaimKind.CAUSAL_ATTRIBUTION),))
    changed = (*args[:-1], graph)
    assert not check_field_evidence(*changed, evidence, **kwargs).valid


def test_transport_schema_failures_remain_unknown_and_auditable_not_false():
    args, kwargs, evidence = fixture(backend=Backend(fail='timeout'))
    assert check_field_evidence(*args, evidence, **kwargs).valid
    assert evidence.claims[0].value is Truth.UNKNOWN
    assert not check_field_evidence(*args, replace(evidence, failures=()), **kwargs).valid


def test_checker_imports_no_binding_builder_solver_or_semantic_backend():
    source = Path(__file__).resolve().parents[1] / 'src/guardian_truth/vnext/claim_field_certificate_v3.py'
    tree = ast.parse(source.read_text(encoding='utf-8'))
    names = {alias.name for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) for alias in node.names}
    assert not names & {'ClaimFieldIndex', 'interpret_claim_result_field', 'interpret_graph_result_fields', 'solve', 'SemanticBackend'}
