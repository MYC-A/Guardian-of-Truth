"""Finite three-valued constraints, not a natural-language completeness solver."""


def conjunction(values):
    if 'FALSE' in values:
        return 'FALSE'
    return 'UNKNOWN' if 'UNKNOWN' in values else 'TRUE'


def disjunction(values):
    if 'TRUE' in values:
        return 'TRUE'
    return 'UNKNOWN' if 'UNKNOWN' in values else 'FALSE'


def negate(value):
    return {'TRUE': 'FALSE', 'FALSE': 'TRUE', 'UNKNOWN': 'UNKNOWN'}[value]


def evaluate(formula, witnesses, path='condition'):
    """Temporal nodes require actual native event positions, never label order."""
    op = formula['op']
    if op == 'UNKNOWN':
        return {'value': 'UNKNOWN', 'open': [{'leaf_id': path,
            'cause': 'UNPARSED_FORMULA', 'detail': formula['label']}]}
    if op == 'ATOM':
        witness = witnesses.get(path)
        if not witness or witness['value'] == 'UNKNOWN':
            return {'value': 'UNKNOWN', 'open': [{'leaf_id': path,
                'cause': 'MISSING_WITNESS' if not witness else 'UNRESOLVED_WITNESS',
                'detail': 'No admitted witness' if not witness else witness['reason']}]}
        return {'value': witness['value'], 'open': []}
    children = [evaluate(c, witnesses, path + '.' + str(i))
                for i, c in enumerate(formula['children'])]
    values = [c['value'] for c in children]
    if op in ('BEFORE', 'AFTER'):
        left = witnesses.get(path + '.0', {}).get('position')
        right = witnesses.get(path + '.1', {}).get('position')
        # No occurrence and absent ordering are different questions.
        if values != ['TRUE', 'TRUE'] or left is None or right is None:
            value = 'UNKNOWN'
        else:
            value = 'TRUE' if (left < right if op == 'BEFORE' else left > right) else 'FALSE'
    elif op == 'AND':
        value = conjunction(values)
    elif op == 'OR':
        value = disjunction(values)
    else:
        value = negate(values[0])
    unresolved = [o for c in children for o in c['open']]
    if op in ('BEFORE', 'AFTER') and value == 'UNKNOWN':
        unresolved.append({'leaf_id': path, 'cause': 'TEMPORAL_OCCURRENCE_UNRESOLVED',
                           'detail': 'Two uniquely grounded native occurrences are required'})
    return {'value': value, 'open': unresolved}


def evaluate_requirement(requirement, witnesses):
    condition = evaluate(requirement['condition'], witnesses)
    guard = (evaluate(requirement['guard'], witnesses, 'guard') if requirement['guard']
             else {'value': 'TRUE', 'open': []})
    exceptions = [evaluate(f, witnesses, 'exception.' + str(i))
                  for i, f in enumerate(requirement['exceptions'])]
    exemption = disjunction([e['value'] for e in exceptions])
    opened = guard['open'] + condition['open'] + [o for e in exceptions for o in e['open']]
    if guard['value'] == 'FALSE' or exemption == 'TRUE':
        status = 'NOT_TRIGGERED'
    elif guard['value'] == 'UNKNOWN' or exemption == 'UNKNOWN' or requirement['open_questions']:
        status = 'UNKNOWN'
    elif requirement['modality'] == 'PERMIT':
        # Failure of a permission condition is not automatically a prohibition.
        status = 'UNKNOWN'
        opened.append({'leaf_id': 'condition', 'cause': 'PERMISSION_NOT_A_PROHIBITION',
                       'detail': 'A separate necessary-condition rule would be needed'})
    elif condition['value'] == 'UNKNOWN':
        status = 'UNKNOWN'
    else:
        violation = (condition['value'] == 'FALSE' if requirement['modality'] == 'REQUIRE'
                     else condition['value'] == 'TRUE')
        status = 'VIOLATED' if violation else 'SATISFIED'
    opened += [{'leaf_id': 'requirement', 'cause': 'UNRESOLVED_REQUIREMENT', 'detail': q}
               for q in requirement['open_questions']]
    return {'status': status, 'condition': condition['value'], 'guard': guard['value'],
            'exception': exemption, 'open': opened,
            'assurance': 'SHADOW_INTERPRETATION', 'code_proof': False}
