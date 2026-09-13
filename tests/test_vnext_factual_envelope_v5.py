"""Native frontend/runtime integration via controlled backend; no model scoring."""

from dataclasses import replace
import importlib.util
import json
from pathlib import Path

import pytest

from guardian_truth.vnext.claim_method_certificate_v5 import check_claim_method_evidence, validate_claim_method_receipt
from guardian_truth.vnext.factual_envelope_v5 import analyze_envelope_factual_v5
from guardian_truth.vnext.semantic import Proposal
from guardian_truth.vnext.source_envelope_v4 import SourceFrame
from guardian_truth.vnext.types import CoverageStatus, Disposition, Reason, Span, Truth

ROOT = Path(__file__).resolve().parents[1]


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


REFERENCE = load("native_method_source", "benchmarks/vnext/binding_fixture_reference_v2.py")
ADAPTER = load("native_method_adapter", "benchmarks/vnext/binding_fixture_adapter_v2.py")


class Backend:
    def __init__(self, *, actor="assistant", polarity="POSITIVE", kind="ACTION_COMPLETED", failure=None, terms=(),
            refs=("N-31",), causal=False, alternate=False):
        self.calls, self.method_calls = [], []
        self.actor, self.polarity, self.kind, self.failure = actor, polarity, kind, failure
        self.terms, self.refs, self.causal, self.alternate = terms, refs, causal, alternate

    def propose(self, task, payload, schema):
        if task == "claim_source_method_meanings_v5":
            self.method_calls.append(payload)
            if self.failure == "method":
                return Proposal(None, "ERROR", "NOT_EVALUATED", "TransportError")
            selected = [item["meaning_id"] for item in payload["source_method_catalog"]
                if item["identities"][0]["name"] in ({"store.archive", "store.delete"} if self.alternate else {"store.archive"})]
            return Proposal(json.dumps({"method_meaning_ids": selected, "unresolved_terms": list(self.terms)}), "SUCCESS", "VALID")
        if task == "claim_result_field_meanings_v3":
            raise AssertionError("completed-method claim incorrectly entered scalar attribution pass")
        self.calls.append(task)
        if task == self.failure:
            return Proposal(None, "ERROR", "NOT_EVALUATED", "TransportError")
        if task == "claim_relations":
            return Proposal('{"relations":[]}', "SUCCESS", "VALID")
        values = {"disposition": "VERIFIABLE_TYPED", "kind": self.kind, "actor": self.actor,
            "predicate": "archive", "object": "N-31", "entity_refs": list(self.refs), "modality": "ASSERTED",
            "polarity": self.polarity, "time_anchor": "PAST", "source_refs": ["ASSISTANT"], "explicit_causality": self.causal}
        fields = schema["properties"]["spans"]["items"]["properties"]
        result = {"spans": [{name: span["span_id"] if name == "span_id" else values[name] for name in fields}
            for span in payload["span_inventory"]]}
        return Proposal(json.dumps(result), "SUCCESS", "VALID")


def context(steps=(), response="I archived N-31.", *, complete=True, initial=None):
    initial = initial or [{"record_id": "N-31", "name": "Method Alpha", "exists": True, "archived": False},
        {"record_id": "N-32", "name": "Method Beta", "exists": True, "archived": False}]
    steps = [{"record_id": "N-31", **step} for step in steps]
    projected = REFERENCE.candidate_input(REFERENCE.execute_fixture({"initial": initial, "steps": steps,
        "history_complete": complete, "query": {"kind": "FIELD_AT_LAST_READ", "entity": {"mode": "id", "value": "N-31"}, "field": "exists", "expected": True}}))
    envelope, snapshots, registry, methods, _ = ADAPTER.make_context(projected)
    envelope = replace(envelope, response=response, frames=envelope.frames + (SourceFrame(Span("response", 0, len(response)),
        Span("response", 0, len(response)), "assistant", "text"),))
    return envelope, snapshots, registry, methods


def analyze(source, backend=None):
    backend = backend or Backend()
    result = analyze_envelope_factual_v5(*source, backend)
    assert result.field_receipt_valid and result.method_receipt_valid
    return result


def test_native_c2_is_called_once_and_lowered_to_real_t1_history_proof():
    backend = Backend()
    source = context([{"operation": "archive"}, {"operation": "read"}])
    result = analyze(source, backend)
    assert len(backend.calls) == 10 and len(backend.method_calls) == 1
    assert result.method_evidence[0].value is Truth.TRUE
    assert result.method_evidence[0].coverage is CoverageStatus.EMPIRICALLY_COVERED
    assert result.source.ledger.effects == () and not hasattr(result, "status")
    assert validate_claim_method_receipt(result.method_receipt, *source, result.graph, result.method_evidence)


def test_never_archived_is_refuted_by_history_even_after_undo():
    result = analyze(context([{"operation": "archive"}, {"operation": "unarchive"}, {"operation": "read"}],
        "I never archived N-31."), Backend(kind="ABSENCE", polarity="NEGATIVE"))
    assert result.method_evidence[0].value is Truth.FALSE


def test_late_read_does_not_resolve_timeout_completion():
    result = analyze(context([{"operation": "archive", "status": "timeout", "latent_apply": True}, {"operation": "read"}]))
    assert result.method_evidence[0].value is Truth.UNKNOWN
    assert result.diagnostics.blocked_claims == (result.graph.claims[0].claim_id,)


def test_user_mutation_cannot_support_assistant_claim():
    result = analyze(context([{"operation": "archive", "actor": "user"}, {"operation": "read"}]))
    assert result.method_evidence[0].value is Truth.FALSE


def test_multiple_method_meanings_are_not_a_vote_or_union_of_actions():
    result = analyze(context([{"operation": "archive"}, {"operation": "read"}]), Backend(alternate=True))
    assert len(result.method_evidence[0].meanings) == 2 and len(result.method_evidence[0].bindings) == 2
    assert result.method_evidence[0].value is Truth.UNKNOWN


def test_retired_alias_remains_a_material_historical_binding():
    result = analyze(context([{"operation": "archive"}, {"operation": "rename", "new_name": "Method Beta"}, {"operation": "read"}],
        "I archived Method Alpha."), Backend(refs=("Method Alpha",)))
    assert result.method_evidence[0].value is Truth.TRUE
    assert result.method_evidence[0].bindings[0].evidence.bindings[0].entity.value == "N-31"


def test_duplicate_historical_names_keep_both_disagreeing_identities():
    initial = [{"record_id": "N-31", "name": "Shared Method", "exists": True, "archived": False},
        {"record_id": "N-32", "name": "Shared Method", "exists": True, "archived": False}]
    result = analyze(context([{"operation": "archive"}, {"operation": "read"}], "I archived Shared Method.", initial=initial),
        Backend(refs=("Shared Method",)))
    assert len(result.method_evidence[0].bindings) == 2 and result.method_evidence[0].value is Truth.UNKNOWN


@pytest.mark.parametrize("failure", ["claim_actor", "method"])
def test_transport_failure_preserves_span_and_unknown_diagnostic(failure):
    result = analyze(context([{"operation": "archive"}]), Backend(failure=failure))
    assert len(result.graph.claims) == len(result.method_evidence) == 1
    assert result.method_evidence[0].value is Truth.UNKNOWN
    assert Reason.TRANSPORT_ERROR in (result.diagnostics.primary_reason, *result.diagnostics.contributing_reasons)


@pytest.mark.parametrize("response", ["I archived N-31 yesterday.", "I archived N-31 twice.", "I archived N-31 2 times."])
def test_unresolved_time_or_count_is_not_lowered_to_simple_history(response):
    backend = Backend()
    result = analyze(context([{"operation": "archive"}], response), backend)
    assert result.method_evidence[0].value is Truth.UNKNOWN and not backend.method_calls


@pytest.mark.parametrize("causal", [True, None])
def test_causal_or_unknown_c2_flag_cannot_become_simple_completion(causal):
    backend = Backend(causal=causal)
    result = analyze(context([{"operation": "archive"}]), backend)
    assert result.method_evidence[0].value is Truth.UNKNOWN and not backend.method_calls


def test_semantic_unknown_term_never_becomes_a_fact_or_closed_meaning():
    result = analyze(context([{"operation": "archive"}]), Backend(terms=("unspecified operation sense",)))
    assert result.method_evidence[0].value is Truth.UNKNOWN
    assert result.method_evidence[0].coverage is CoverageStatus.OPEN_SEMANTICS


def test_dropped_binding_or_false_closed_coverage_fails_independent_check():
    source = context([{"operation": "archive"}, {"operation": "read"}])
    result = analyze(source)
    row = result.method_evidence[0]
    assert check_claim_method_evidence(*source, result.graph, (replace(row, bindings=()),))
    assert check_claim_method_evidence(*source, result.graph, (replace(row, coverage=CoverageStatus.PROVABLY_CLOSED),))


def test_independent_method_checker_does_not_invoke_binder_or_backend(monkeypatch):
    from guardian_truth.vnext import claim_method_bindings_v5
    source = context([{"operation": "archive"}])
    result = analyze(source)
    def forbidden(*args, **kwargs):
        raise AssertionError("candidate called during independent checking")
    monkeypatch.setattr(claim_method_bindings_v5, "bind_native_method_claim", forbidden)
    assert validate_claim_method_receipt(result.method_receipt, *source, result.graph, result.method_evidence)


def test_one_unbound_explicit_entity_cannot_silently_disappear():
    result = analyze(context([{"operation": "archive"}], "I archived N-31 and a missing entity."),
        Backend(refs=("N-31", "missing entity")))
    assert result.method_evidence[0].value is Truth.UNKNOWN
    assert result.method_evidence[0].candidate_set_complete is False
    assert result.method_evidence[0].coverage is CoverageStatus.OPEN_SEMANTICS


def test_incompatible_identity_codec_is_unknown_not_absent_method():
    envelope, snapshots, registry, methods = context([], "I archived Method Alpha.")
    snapshots = tuple(replace(item, identity=replace(item.identity, id_type="integer")) for item in snapshots)
    result = analyze((envelope, snapshots, registry, methods), Backend(refs=("Method Alpha",)))
    assert result.method_evidence[0].value is Truth.UNKNOWN
    assert result.method_evidence[0].meanings and not result.method_evidence[0].bindings
