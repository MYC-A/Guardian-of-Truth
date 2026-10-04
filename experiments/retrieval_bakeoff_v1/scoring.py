"""Independent source-span scoring. References never enter retrieval queries."""
from collections import defaultdict

CATEGORIES = {
    'policy': 'required_normative_sources',
    'history': 'required_history_sources',
    'target': 'required_target_sources',
    'declaration': 'required_declarations',
    'exception': 'exception_sources',
    'entity_binding': 'entity_binding_sources',
    'long_distance': 'long_distance_sources',
}


def span_identity(unit):
    document, start, end = (unit.get(k) for k in ('document', 'start', 'end'))
    if document not in ('prompt', 'response') or type(start) is not int or type(end) is not int or not 0 <= start < end:
        raise ValueError('INVALID_REFERENCE_SPAN')
    return document, start, end


def covered(unit, sources):
    document, start, end = span_identity(unit)
    intervals = sorted((s['start'], s['end']) for s in sources if s.get('document') == document)
    cursor = start
    for left, right in intervals:
        if left > cursor:
            break
        if right > cursor:
            cursor = right
        if cursor >= end:
            return True
    return False


def unique(units):
    return list({span_identity(u): u for u in units}.values())


def score_reference(reference, packet):
    sources = packet.get('read_sources', []) + packet.get('current_targets', []) + packet.get('declarations', [])
    result = {}
    for category, key in CATEGORIES.items():
        units = unique(reference.get(key, []))
        found = [u for u in units if covered(u, sources)]
        result[category] = dict(found=len(found), required=len(units),
            recall=len(found)/len(units) if units else None,
            missing=[u for u in units if not covered(u, sources)])
    alternatives = reference.get('alternative_valid_evidence_sets', [])
    if not alternatives:
        alternatives = [unique([u for key in list(CATEGORIES.values())[:5] for u in reference.get(key, [])])]
    checks = []; alternative_units=[]
    for alternative in alternatives:
        if isinstance(alternative, dict):
            alternative = alternative.get('sources', [])
        units = unique(alternative)
        alternative_units.extend(units)
        checks.append(dict(found=sum(covered(u, sources) for u in units), required=len(units),
                           complete=bool(units) and all(covered(u, sources) for u in units)))
    matched = any(a['complete'] for a in checks)
    required_units = unique([u for key in CATEGORIES.values() for u in reference.get(key, [])]+alternative_units)
    irrelevant = [s['source_id'] for s in packet.get('read_sources', []) if not any(
        s['document'] == u['document'] and s['start'] < u['end'] and u['start'] < s['end'] for u in required_units)]
    return dict(categories=result, complete_evidence_set_success=matched,
        reference_partial=bool(reference.get('partial_reference', reference.get('uncertain_requirements'))),
        alternatives=checks, unnecessary_relative_to_reference=irrelevant,
        false_absence_risk=result['history']['required'] > result['history']['found'],
        subset_absence_is_proof=False, completeness_certified=False)


def aggregate(rows):
    totals = defaultdict(lambda: dict(found=0, required=0))
    for row in rows:
        for name, values in row['score']['categories'].items():
            totals[name]['found'] += values['found']
            totals[name]['required'] += values['required']
    return dict(n=len(rows), categories={k: dict(v, recall=v['found']/v['required'] if v['required'] else None)
                for k,v in totals.items()},
                complete=sum(r['score']['complete_evidence_set_success'] for r in rows),
                partial_reference_cases=sum(r['score']['reference_partial'] for r in rows),
                false_absence_risk=sum(r['score']['false_absence_risk'] for r in rows),
                failures=sum(bool(r['packet'].get('failure')) for r in rows),
                reads=sum(len(r['packet'].get('read_sources', [])) for r in rows),
                complete_is_reference_relative_not_NO_ERROR_proof=True)
