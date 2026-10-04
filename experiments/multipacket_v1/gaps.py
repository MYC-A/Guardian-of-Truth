"""Gap-text and question construction from an admitted I4 reply (no gold)."""
from guardian_truth.multipacket.controller import Question, classify


def d2_queries(reply):
    """D2: the model's own stated gaps + its norm interpretations and exception analysis."""
    if not reply:
        return []
    q = list(reply.get('open_questions', []))
    q += [n['interpretation'] for n in reply.get('applicable_norms', [])]
    q += [reply.get('exception_analysis', ''), reply.get('reason', '')]
    return [x for x in q if x]


def g2_questions(reply):
    """G2 evidence sufficiency: what must hold for the PROPOSED claim (norm scope, exceptions, facts, receipts)."""
    if not reply:
        return []
    qs = []
    norms = [n['policy_source_id'] for n in reply.get('applicable_norms', [])]
    for n in reply.get('applicable_norms', []):
        qs.append(Question(f"conditions and exceptions of: {n['interpretation']}", 'G2', kind='MISSING_EXCEPTION_CHECK', linked_norms=[n['policy_source_id']]))
    for e in reply.get('supporting_evidence', []):
        qs.append(Question(e['fact'], 'G2', kind=classify(e['fact']), linked_norms=norms))
    qs.append(Question(reply['regulated_action']['description'], 'G2', kind='MISSING_ENTITY_BINDING', linked_norms=norms))
    return qs


def g4_questions(reply, assessments=()):
    """G4: open questions of the first pass plus UNKNOWN norm assessments of the blinded obligation scan."""
    qs = [Question(q, 'OPEN_QUESTION', kind=classify(q)) for q in (reply or {}).get('open_questions', [])]
    for a in assessments:
        if 'UNKNOWN' in (a.get('applicability'), a.get('condition'), a.get('exception'), a.get('violated')):
            qs.append(Question(a['interpretation'], 'OBLIGATION_SCAN', kind='POSSIBLE_MISSED_OBLIGATION', linked_norms=[a['policy_source_id']]))
    return qs
