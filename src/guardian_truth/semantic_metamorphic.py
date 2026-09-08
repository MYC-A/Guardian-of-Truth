"""Independent, model-free falsification contracts for semantic construction.

Fixtures are controlled sentences, not a production language recognizer. The
analyzer receives only text/schema/trace, never expected features. Passing these
tests does not establish coverage or correctness on natural Guardian examples.
"""

from dataclasses import asdict, dataclass
import json
from typing import Any, Callable


@dataclass(frozen=True)
class SemanticInput:
    text: str
    schema: tuple[dict, ...] = ()
    trace: tuple[dict, ...] = ()


@dataclass(frozen=True)
class FeatureExpectation:
    name: str
    before: tuple[Any, ...]
    after: tuple[Any, ...]
    relation: str = 'different'


@dataclass(frozen=True)
class MetamorphicCase:
    name: str
    family: str
    before: SemanticInput
    after: SemanticInput
    features: tuple[FeatureExpectation, ...]
    purpose: str


def metamorphic_cases() -> tuple[MetamorphicCase, ...]:
    """Fifteen bounded mutations including missing-binding/ambiguous-pronoun probes."""
    flight_schema = ({'field': 'arrival_time', 'concept': 'ArrivalEventTime'},
                     {'field': 'departure_time', 'concept': 'DepartureEventTime'})
    cases = []

    def pair(name, family, before, after, features, purpose, *, schema=(),
             after_schema=None, trace=(), after_trace=None):
        cases.append(MetamorphicCase(name, family, SemanticInput(before, schema, trace),
                     SemanticInput(after, schema if after_schema is None else after_schema,
                                   trace if after_trace is None else after_trace),
                     tuple(FeatureExpectation(*item) for item in features), purpose))

    pair('event_role_swap', 'arrival_departure',
         'Flight A must arrive after 18:00.', 'Flight A must depart after 18:00.',
         [('event_role', ('Arrival',), ('Departure',)),
          ('field_binding', ('arrival_time',), ('departure_time',)),
          ('temporal_operator', ('AFTER',), ('AFTER',), 'same')],
         'An identical timestamp type must not erase the event-role change.', schema=flight_schema)
    pair('temporal_direction', 'before_after',
         'Flight A must arrive before 18:00.', 'Flight A must arrive after 18:00.',
         [('temporal_operator', ('BEFORE',), ('AFTER',)),
          ('event_role', ('Arrival',), ('Arrival',), 'same')],
         'Reverse the relation, not the event or temporal anchor.', schema=flight_schema)
    pair('temporal_equality_boundary', 'strict_inclusive',
         'Flight A must arrive strictly after 18:00.', 'Flight A must arrive at or after 18:00.',
         [('comparison', ('GT',), ('GE',)), ('allows_equality', (False,), (True,))],
         'The equality boundary is a distinguishing witness.', schema=flight_schema)
    pair('cardinality_boundary', 'at_most_less_than',
         'The agent may make at most two tool calls.', 'The agent may make less than two tool calls.',
         [('comparison', ('LE',), ('LT',)), ('threshold', (2,), (2,), 'same')],
         'Count equal to the threshold must distinguish the representations.')
    pair('normative_force', 'may_must',
         'The agent may notify the customer.', 'The agent must notify the customer.',
         [('modality', ('MAY',), ('MUST',))],
         'Permission is not obligation; omission is not automatically a MAY violation.')
    pair('quantifier_swap', 'all_some',
         'All submitted documents must be valid.', 'Some submitted documents must be valid.',
         [('quantifier', ('ALL',), ('SOME',))],
         'A mixed-validity set distinguishes universal from existential force.')
    pair('implication_direction', 'if_only_if',
         'RefundAllowed if conditions A and B hold.', 'RefundAllowed only if conditions A and B hold.',
         [('condition_direction', ('SUFFICIENT',), ('NECESSARY',)),
          ('condition_operator', ('AND',), ('AND',), 'same')],
         'Only-if does not permit deriving RefundAllowed from A AND B.')
    pair('exception_addition', 'exception',
         'The agent must notify the customer.', 'The agent must notify the customer unless consent is absent.',
         [('exception_present', (False,), (True,)),
          ('modality', ('MUST',), ('MUST',), 'same')],
         'Adding unless must add structure or an explicit structural hole.')
    pair('exception_removal', 'exception',
         'The agent must notify the customer unless consent is absent.', 'The agent must notify the customer.',
         [('exception_present', (True,), (False,))],
         'An exception from a previous sentence must not persist after removal.')
    pair('voice_invariance', 'active_passive',
         'The agent must cancel Booking A.', 'Booking A must be cancelled by the agent.',
         [('action', ('Cancel',), ('Cancel',), 'same'),
          ('agent', ('Agent',), ('Agent',), 'same'),
          ('patient', ('Booking A',), ('Booking A',), 'same')],
         'Surface voice changes must preserve semantic agent and patient.')
    pair('unambiguous_reference', 'pronoun_entity',
         'Account A is selected. Account A must remain active.',
         'Account A is selected. It must remain active.',
         [('reference_form', ('EXPLICIT',), ('PRONOUN',)),
          ('entity_binding', ('Account A',), ('Account A',), 'same')],
         'A unique antecedent preserves identity while exposing coreference.')
    pair('ambiguous_reference', 'pronoun_entity',
         'Account A and Account B are selected. Account A must remain active.',
         'Account A and Account B are selected. It must remain active.',
         [('reference_form', ('EXPLICIT',), ('PRONOUN',)),
          ('entity_binding', ('Account A',), ('UNRESOLVED',))],
         'A singular pronoun after two possible antecedents must not force Account A.')
    pair('stale_state_insertion', 'stale_state',
         'Use the current status of Account A.', 'Use the current status of Account A.',
         [('current_state', ('ACTIVE',), ('ACTIVE',), 'same'),
          ('state_entity', ('Account A',), ('Account A',), 'same')],
         'Appending an older observation must not overwrite a later version.',
         trace=({'entity': 'Account A', 'sequence': 20, 'status': 'ACTIVE'},),
         after_trace=({'entity': 'Account A', 'sequence': 20, 'status': 'ACTIVE'},
                      {'entity': 'Account A', 'sequence': 10, 'status': 'CLOSED'}))
    pair('irrelevant_field_insertion', 'distractor_field',
         'Flight A must arrive after 18:00.', 'Flight A must arrive after 18:00.',
         [('field_binding', ('arrival_time',), ('arrival_time',), 'same'),
          ('event_role', ('Arrival',), ('Arrival',), 'same')],
         'An extra same-typed field must not steal an established semantic binding.',
         schema=({'field': 'arrival_time', 'concept': 'ArrivalEventTime'},),
         after_schema=({'field': 'departure_time', 'concept': 'DepartureEventTime'},
                       {'field': 'arrival_time', 'concept': 'ArrivalEventTime'}))
    pair('missing_concept_with_distractor', 'distractor_field',
         'Flight A must arrive after 18:00.', 'Flight A must arrive after 18:00.',
         [('field_binding', ('UNBOUND_CONCEPT',), ('UNBOUND_CONCEPT',), 'same'),
          ('event_role', ('Arrival',), ('Arrival',), 'same')],
         'An unrelated timestamp does not resolve the missing arrival concept.',
         after_schema=({'field': 'departure_time', 'concept': 'DepartureEventTime'},))
    return tuple(cases)


def _same(left, right):
    # Avoid Python's True == 1 equivalence in representation contracts.
    return type(left) is type(right) and left == right


def assess_pair(case: MetamorphicCase, before_view: dict, after_view: dict) -> dict:
    """Check expected representation deltas, independently of final verdicts."""
    failures = []
    before = before_view.get('features') if isinstance(before_view, dict) else None
    after = after_view.get('features') if isinstance(after_view, dict) else None
    if not isinstance(before, dict) or not isinstance(after, dict):
        return {'case': case.name, 'family': case.family, 'passed': False,
                'failures': ['invalid_feature_view'], 'checked_features': 0}
    for expectation in case.features:
        name = expectation.name
        if name not in before or name not in after:
            failures.append(f'{name}:missing')
            continue
        if not any(_same(before[name], value) for value in expectation.before):
            failures.append(f'{name}:wrong_before')
        if not any(_same(after[name], value) for value in expectation.after):
            failures.append(f'{name}:wrong_after')
        equal = _same(before[name], after[name])
        if expectation.relation == 'same' and not equal:
            failures.append(f'{name}:unexpected_change')
        if expectation.relation == 'different' and equal:
            failures.append(f'{name}:missing_expected_change')
    return {'case': case.name, 'family': case.family, 'passed': not failures,
            'failures': failures, 'checked_features': len(case.features)}


def run_metamorphic_suite(analyze: Callable[[dict], dict], cases=None) -> dict:
    """Adapter hook: analyze receives input only, with no expected annotation."""
    cases = metamorphic_cases() if cases is None else tuple(cases)
    reports = []
    for case in cases:
        try:
            before = analyze(asdict(case.before))
            after = analyze(asdict(case.after))
            report = assess_pair(case, before, after)
        except Exception:
            report = {'case': case.name, 'family': case.family, 'passed': False,
                      'failures': ['analyzer_error'], 'checked_features': 0}
        reports.append(report)
    passed = sum(report['passed'] for report in reports)
    return {'cases': len(reports), 'passed': passed, 'failed': len(reports)-passed,
            'sensitivity': passed / len(reports) if reports else None, 'reports': reports,
            'scope': 'controlled_representation_contracts_not_natural_language_accuracy'}


def check_coverage(text: str | dict[str, str], obligations: list[dict],
                   represented_ids, nodes: list[dict]) -> dict:
    """Audit discovered obligations both ways; spans alone do not prove meaning.

    Source dictionaries use document/start/end, with optional exact quote.
    For a plain text input the document name is 'rule'. FORMALIZED obligations
    need a node; HOLE/RESIDUAL/UNSUPPORTED must still be represented explicitly.
    """
    documents = {'rule': text} if isinstance(text, str) else text
    issues = []

    def valid_source(source):
        if not isinstance(source, dict):
            return False
        document, start, end = source.get('document'), source.get('start'), source.get('end')
        body = documents.get(document) if isinstance(documents, dict) and isinstance(document, str) else None
        return (isinstance(body, str) and type(start) is int and type(end) is int
                and 0 <= start < end <= len(body)
                and ('quote' not in source or source['quote'] == body[start:end]))

    if (not isinstance(obligations, list) or not isinstance(nodes, list)
            or any(not isinstance(item, dict) for item in obligations + nodes)
            or not isinstance(represented_ids, (list, tuple, set))
            or any(not isinstance(key, str) for key in represented_ids)):
        return {'passed': False, 'issues': ['malformed_coverage_input'], 'coverage': None}
    ids = [item.get('id') for item in obligations]
    if any(not isinstance(key, str) or not key for key in ids) or len(set(ids)) != len(ids):
        return {'passed': False, 'issues': ['invalid_obligation_ids'], 'coverage': None}
    represented = set(represented_ids)
    if represented - set(ids):
        issues.append('invented_obligation_reference')
    node_refs = set()
    for node in nodes:
        if not valid_source(node.get('source')):
            issues.append('node_without_valid_source')
        refs = node.get('obligation_ids')
        if not isinstance(refs, list) or not refs or any(not isinstance(ref, str) for ref in refs):
            issues.append('node_without_obligation_basis')
        else:
            node_refs.update(refs)
            if set(refs) - set(ids):
                issues.append('node_invented_obligation')
    unresolved = []
    for obligation in obligations:
        key, status = obligation['id'], obligation.get('status')
        if not valid_source(obligation.get('source')):
            issues.append(f'{key}:invalid_source')
        if status not in {'FORMALIZED', 'HOLE', 'RESIDUAL', 'UNSUPPORTED'}:
            issues.append(f'{key}:invalid_status')
        if key not in represented:
            issues.append(f'{key}:lost_construction')
        if status == 'FORMALIZED' and key not in node_refs:
            issues.append(f'{key}:formalized_without_node')
        if status != 'FORMALIZED':
            unresolved.append(key)
    return {'passed': not issues, 'issues': sorted(set(issues)),
            'coverage': len(set(ids) & represented)/len(ids) if ids else None,
            'unresolved_ids': unresolved,
            'all_discovered_formalized': bool(ids) and not unresolved and not issues,
            'semantic_equivalence_proved': False,
            'scope': 'discovered_obligations_only_not_complete_semantic_coverage'}


def evaluate_outer_coverage(admissible: list[dict], outer: list[dict],
                            strict_verdict='UNRESOLVED', working=None) -> dict:
    """Compare independently annotated normalized interpretations to outer.

    Each record is {signature: JSON value, verdict: VIOLATION|NO_VIOLATION}.
    Signature equivalence must be established by the caller; this helper only
    checks canonical JSON identity and never claims to solve semantic equivalence.
    """
    allowed = {'VIOLATION', 'NO_VIOLATION'}

    def records(items):
        if not isinstance(items, list):
            raise ValueError
        result = {}
        for item in items:
            if not isinstance(item, dict) or 'signature' not in item or item.get('verdict') not in allowed:
                raise ValueError
            signature = json.dumps(item['signature'], sort_keys=True, ensure_ascii=False, allow_nan=False)
            if signature in result and result[signature] != item['verdict']:
                raise ValueError
            result[signature] = item['verdict']
        return result

    try:
        expected, actual = records(admissible), records(outer)
        selected = {} if working is None else records(working)
        if strict_verdict not in {'PROVED_VIOLATION', 'PROVED_NO_VIOLATION', 'UNRESOLVED'}:
            raise ValueError
    except (ValueError, TypeError):
        return {'valid': False, 'issues': ['invalid_interpretation_contract']}
    if not expected:
        return {'valid': False, 'issues': ['no_independent_admissible_interpretation']}
    missing = set(expected) - set(actual)
    conflicts = [signature for signature in set(expected) & set(actual) if expected[signature] != actual[signature]]
    working_outside = [signature for signature in selected
                       if signature not in actual or selected[signature] != actual[signature]]
    claimed = strict_verdict.removeprefix('PROVED_') if strict_verdict != 'UNRESOLVED' else None
    opposite = bool(claimed and any(verdict != claimed for verdict in expected.values()))
    invariant = next(iter(set(actual.values()))) if len(set(actual.values())) == 1 else None
    strict_not_outer_invariant = bool(claimed and (not actual or invariant != claimed))
    return {'valid': True, 'admissible_count': len(expected), 'outer_width': len(actual),
            'missing_count': len(missing), 'missing_interpretation_rate': len(missing)/len(expected),
            'formalization_coverage': 1-len(missing)/len(expected),
            'matching_signature_verdict_conflicts': len(conflicts),
            'working_subset_outer': not working_outside,
            'empty_outer': not actual, 'outer_invariant_verdict': invariant,
            'opposite_admissible_verdict': opposite,
            'strict_not_outer_invariant': strict_not_outer_invariant,
            'confident_wrong': bool(claimed and (missing or conflicts or opposite or strict_not_outer_invariant)),
            'strict_with_missing_interpretation': bool(claimed and missing),
            'unresolved': strict_verdict == 'UNRESOLVED'}


def find_information_witness(worlds: list[dict], observable_fields: tuple[str, ...]) -> dict | None:
    """Find equal available projections with different supplied violation values.

    Worlds and their boolean violation outcomes are independent test inputs, not
    model predictions. Finding no finite witness does not prove sufficiency.
    """
    if (not isinstance(worlds, list) or not isinstance(observable_fields, tuple)
            or any(not isinstance(name, str) or name == 'violation' for name in observable_fields)
            or len(set(observable_fields)) != len(observable_fields)):
        raise ValueError('Invalid witness inputs')
    projections = {}
    for index, world in enumerate(worlds):
        if (not isinstance(world, dict) or type(world.get('violation')) is not bool
                or any(name not in world for name in observable_fields)):
            raise ValueError('Worlds need complete projections and explicit boolean outcomes')
        projection = {name: world[name] for name in observable_fields}
        key = json.dumps(projection, sort_keys=True, allow_nan=False)
        if key in projections:
            other_index, other = projections[key]
            if other['violation'] != world['violation']:
                return {'world_indices': [other_index, index], 'projection': projection,
                        'violation_values': [other['violation'], world['violation']],
                        'conclusion': 'AVAILABLE_INFORMATION_INSUFFICIENT'}
        else:
            projections[key] = (index, world)
    return None
