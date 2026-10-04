"""Typed self-consistency diagnostics are not certificates of normative truth."""
from dataclasses import dataclass


TRUTH = {'TRUE', 'FALSE', 'UNKNOWN'}


def audit_consistency(reply):
    decision = reply.get('decision')
    if decision not in ('ERROR', 'NO_ERROR', 'UNKNOWN', None):
        raise ValueError('DECISION_INVALID')
    norms = reply.get('norm_assessments', [])
    if not isinstance(norms, list):
        raise ValueError('NORM_ASSESSMENTS_INVALID')
    flags = []
    for index, norm in enumerate(norms):
        if not isinstance(norm, dict) or norm.get('applicability') not in ('YES', 'NO', 'UNKNOWN'):
            raise ValueError('APPLICABILITY_INVALID')
        if norm.get('modality') not in ('FORBID', 'REQUIRE', 'PERMIT'):
            raise ValueError('MODALITY_INVALID')
        if any(norm.get(k) not in TRUTH for k in ('condition', 'exception', 'violated')):
            raise ValueError('NORM_TRUTH_VALUE_INVALID')
        applicable, condition, exception, violated = (norm[k] for k in ('applicability','condition','exception','violated'))
        if violated=='TRUE' and (applicable=='NO' or exception=='TRUE' or norm['modality']=='PERMIT'):
            flags.append(dict(norm_index=index, kind='NORM_STATUS_SELF_CONTRADICTION'))
        established = applicable=='YES' and exception=='FALSE' and (
            (norm['modality']=='FORBID' and condition=='TRUE') or
            (norm['modality']=='REQUIRE' and condition=='FALSE'))
        if established and violated=='FALSE':
            flags.append(dict(norm_index=index, kind='CONDITION_VIOLATION_SELF_CONTRADICTION'))
        if (established or (applicable=='YES' and violated=='TRUE' and exception=='FALSE')) and decision=='NO_ERROR':
            flags.append(dict(norm_index=index, kind='DECISION_VIOLATION_SELF_CONTRADICTION'))
    # ERROR can be justified by an omitted norm or structural finding; no inverted
    # blanket claim that all listed FALSE means ERROR is logically impossible.
    return dict(status='POTENTIAL_CONTRADICTION' if flags else 'NO_TYPED_CONTRADICTION_FOUND',
        original_decision=decision, decision=decision, changed=False, flags=flags,
        semantic_truth_certified=False, assessed_norm_count=len(norms))


def hypothesis_adapter(semantics):
    """Aggregate admitted Stage-A hypotheses, not independently proven policy.

    The caller admits original target/policy/evidence references first. `condition`
    means forbidden-state truth for FORBID and requirement satisfaction for REQUIRE;
    antecedent applicability belongs to `applicability`. This modest adapter cannot
    discover missing norms and must be scored separately from a qualified proof.
    """
    audit = audit_consistency(dict(decision=None, **semantics))
    base = dict(code_proof=False, semantic_truth_certified=False,
        epistemic_status='MODEL_HYPOTHESIS_AGGREGATION',
        independent_proof_decision='UNKNOWN', consistency_audit=audit)
    if audit['flags']:
        return {**base, 'decision':'UNKNOWN', 'reason':'INCONSISTENT_SEMANTIC_HYPOTHESES'}
    norms=semantics.get('norm_assessments',[])
    # A claimed violation is accepted only when the typed components agree and
    # cite both its original norm and current target. No prose is searched.
    positive=[]
    for i,n in enumerate(norms):
        refs=n.get('source_refs',[])
        referenced=(isinstance(refs,list) and all(isinstance(s,str) for s in refs)
                    and isinstance(n.get('target_id'),str) and isinstance(n.get('policy_source_id'),str)
                    and n['target_id'] in refs and n['policy_source_id'] in refs)
        violated_condition=((n['modality']=='FORBID' and n['condition']=='TRUE') or
                            (n['modality']=='REQUIRE' and n['condition']=='FALSE'))
        if (referenced and n['applicability']=='YES' and n['exception']=='FALSE'
                and n['violated']=='TRUE' and violated_condition):
            positive.append(i)
    if positive:
        return {**base,'decision':'ERROR','reason':'CONSISTENT_POSITIVE_MODEL_HYPOTHESIS', 'norm_indices':positive}
    unknown = any(n['applicability']=='UNKNOWN' or
                  (n['applicability']=='YES' and n['modality']!='PERMIT' and
                   (n['violated']!='FALSE' or n['condition']=='UNKNOWN' or n['exception']=='UNKNOWN'))
                  for n in norms)
    if (not unknown and semantics.get('coverage')=='SUFFICIENT'
            and semantics.get('open_questions')==[]):
        return {**base,'decision':'NO_ERROR','reason':'MODEL_DECLARED_COVERAGE_WITHOUT_POSITIVE_HYPOTHESIS',
                'norm_indices':[]}
    return {**base,'decision':'UNKNOWN','reason':'INSUFFICIENT_OR_UNRESOLVED_MODEL_HYPOTHESES', 'norm_indices':[]}


@dataclass(frozen=True)
class IndependentQualification:
    """Trusted caller-side human/source audit, never decoded from a model reply.

    This narrow adapter is oracle-assisted if these semantic qualifications are
    provided by a researcher. It does not automatically create such an audit.
    """
    policy_sources: tuple[str, ...]
    target_source: str
    state_sources: tuple[str, ...]
    exception_closure_sources: tuple[str, ...]
    applicability_confirmed: bool
    state_relation_confirmed: bool
    exception_closure_confirmed: bool
    source_audit_id: str


def proof_adapter(proof, qualification, allowed_source_ids):
    unresolved = dict(decision='UNKNOWN', status='UNRESOLVED', semantic_truth_certified=False,
        qualification_kind='INDEPENDENT_SOURCE_AUDIT_REQUIRED')
    if not isinstance(qualification, IndependentQualification):
        return {**unresolved, 'reason':'NO_INDEPENDENT_QUALIFICATION'}
    if any(not isinstance(v,tuple) for v in (qualification.policy_sources, qualification.state_sources,
                                            qualification.exception_closure_sources)):
        return {**unresolved, 'reason':'QUALIFICATION_SOURCE_TYPES_INVALID'}
    flags = (qualification.applicability_confirmed, qualification.state_relation_confirmed,
             qualification.exception_closure_confirmed)
    if any(type(v) is not bool or not v for v in flags) or not qualification.source_audit_id:
        return {**unresolved, 'reason':'INCOMPLETE_SEMANTIC_QUALIFICATION'}
    refs = qualification.policy_sources+qualification.state_sources+qualification.exception_closure_sources+(qualification.target_source,)
    if not all((qualification.policy_sources, qualification.state_sources, qualification.exception_closure_sources)):
        return {**unresolved, 'reason':'QUALIFICATION_SOURCE_COVERAGE_MISSING'}
    if any(not isinstance(sid,str) or sid not in set(allowed_source_ids) for sid in refs):
        return {**unresolved, 'reason':'QUALIFICATION_SOURCE_NAMESPACE_INVALID'}
    if not isinstance(proof, dict) or any(proof.get(k)!=v for k,v in (
            ('modality','FORBID'), ('applicability','YES'), ('condition','TRUE'), ('exception','FALSE'))):
        return {**unresolved, 'reason':'SUPPORTED_FORBID_OBJECT_REQUIRED'}
    if proof.get('target_id') != qualification.target_source:
        return {**unresolved, 'reason':'PROOF_TARGET_MISMATCH'}
    proof_refs = proof.get('source_refs')
    if not isinstance(proof_refs,list) or not proof_refs or any(not isinstance(sid,str) or sid not in set(refs) for sid in proof_refs):
        return {**unresolved, 'reason':'PROOF_SOURCE_REFS_INVALID'}
    if not set(refs) <= set(proof_refs):
        return {**unresolved, 'reason':'PROOF_SOURCE_COVERAGE_MISSING'}
    # The caller has separately qualified all semantic roles and exception
    # closure. This is an auditable conditional/oracle result, not production
    # automatic grounding, and never a universal NO_ERROR certificate.
    return dict(decision='ERROR', status='QUALIFIED_EXPLICIT_PROHIBITION',
        semantic_truth_certified=False, qualification_kind='INDEPENDENT_SOURCE_AUDIT_ASSISTED',
        source_audit_id=qualification.source_audit_id, source_refs=list(dict.fromkeys(refs)),
        reason='Conditionally follows from independently supplied applicability, state and exception-closure audit.')
