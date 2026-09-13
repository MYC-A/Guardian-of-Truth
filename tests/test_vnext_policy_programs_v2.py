from dataclasses import replace
import json

import pytest

from guardian_truth.vnext.integrity import digest
from guardian_truth.vnext.policy_programs_v2 import AuthoritativePrograms, PolicyProgram, ProgramHypothesis, aggregate_program_meanings, parse_policy_programs, program_values
from guardian_truth.vnext.semantic import Proposal
from guardian_truth.vnext.types import CoreStatus, CoverageStatus, Span, Truth


POLICY = 'Archive only if approved.'
ATOMS = ('ACT', 'APPROVED')
ONLY_IF = PolicyProgram((('ACT', '!APPROVED'),), ())
IF = PolicyProgram((('APPROVED', '!ACT'),), ())


def reading(program=ONLY_IF, *, terms=(), quote=POLICY):
    return {'basis': 'candidate behavioral reading', **program.as_json(),
        'source_quotes': [quote], 'unresolved_terms': list(terms)}


class Backend:
    def __init__(self, initial=None, challenger=None, failure=None):
        self.initial = initial if initial is not None else [reading()]
        self.challenger = challenger if challenger is not None else []
        self.failure, self.tasks = failure, []

    def propose(self, task, payload, schema):
        self.tasks.append(task)
        if task == self.failure:
            return Proposal(None, 'ERROR', 'NOT_EVALUATED', 'timeout')
        return Proposal(json.dumps({'interpretations': self.challenger if 'missing' in task else self.initial,
            'unresolved_terms': []}), 'SUCCESS', 'VALID')


def universe(*programs, complete=True):
    return AuthoritativePrograms('explicit controlled whole-policy meaning declaration', 'EXPLICIT_CLOSED_DEFINITION',
        digest(POLICY), ATOMS, tuple(ProgramHypothesis('declared:' + str(index), 'authoritative source definition', program,
            (Span('policy', 0, len(POLICY)),)) for index, program in enumerate(programs)), complete)


def test_only_if_and_if_are_behaviorally_distinct_not_conflated_slots():
    facts = {'ACT': Truth.TRUE, 'APPROVED': Truth.FALSE}
    assert program_values(ONLY_IF, facts)[0] is Truth.TRUE
    assert program_values(IF, facts)[0] is Truth.FALSE


def test_negated_missing_fact_is_unknown_not_closed_world_false():
    assert program_values(ONLY_IF, {'ACT': Truth.TRUE})[0] is Truth.UNKNOWN


def test_frontend_and_separate_challenger_preserve_both_meanings_without_vote():
    backend = Backend(challenger=[reading(IF)])
    parsed = parse_policy_programs(POLICY, ATOMS, backend)
    assert len(backend.tasks) == len(parsed.hypotheses) == 2
    assert len(parsed.coverage.challenger_alternatives) == 1
    result = aggregate_program_meanings(parsed, {'ACT': Truth.TRUE, 'APPROVED': Truth.FALSE})
    assert result['status'] is CoreStatus.UNRESOLVED
    assert set(result['violation_values']) == {Truth.TRUE, Truth.FALSE}


def test_finite_atom_catalog_and_empty_challenger_do_not_close_meaning():
    parsed = parse_policy_programs(POLICY, ATOMS, Backend())
    assert parsed.coverage.status is CoverageStatus.EMPIRICALLY_COVERED
    assert not parsed.coverage.enumeration_complete
    assert aggregate_program_meanings(parsed, {'ACT': Truth.TRUE, 'APPROVED': Truth.TRUE})['status'] is CoreStatus.UNRESOLVED


def test_empirical_all_error_is_explicitly_conditional_policy_layer_not_core_certificate():
    parsed = parse_policy_programs(POLICY, ATOMS, Backend())
    result = aggregate_program_meanings(parsed, {'ACT': Truth.TRUE, 'APPROVED': Truth.FALSE})
    assert result['status'] is CoreStatus.PROVED_ERROR
    assert result['conditional_semantics']
    assert 'NOT_CERTIFIED_CORE' in result['scope']


def test_undefined_material_terms_remain_open_even_with_a_program():
    parsed = parse_policy_programs(POLICY, ATOMS, Backend(initial=[reading(terms=['undefined old'])]))
    assert parsed.coverage.status is CoverageStatus.OPEN_SEMANTICS
    assert aggregate_program_meanings(parsed, {'ACT': Truth.TRUE, 'APPROVED': Truth.FALSE})['status'] is CoreStatus.UNRESOLVED


def test_unquoted_source_is_discarded_and_opens_coverage_not_silently_dropped():
    parsed = parse_policy_programs(POLICY, ATOMS, Backend(initial=[reading(quote='invented policy')]))
    assert not parsed.hypotheses
    assert parsed.coverage.discarded_hypotheses
    assert parsed.coverage.status is CoverageStatus.OPEN_SEMANTICS


def test_invalid_literal_is_schema_failure_not_an_invented_fact():
    parsed = parse_policy_programs(POLICY, ATOMS, Backend(initial=[reading(PolicyProgram((('INVENTED',),), ()))]))
    assert parsed.failures[0][1].value == 'SCHEMA_ERROR'
    assert not parsed.hypotheses


def test_self_contradictory_program_is_audited_not_a_batch_crash():
    parsed = parse_policy_programs(POLICY, ATOMS, Backend(initial=[reading(PolicyProgram((('ACT', '!ACT'),), ()))]))
    assert parsed.coverage.discarded_hypotheses[0][1] == 'UNSUPPORTED_OR_CONTRADICTORY_PROGRAM'
    assert parsed.coverage.status is CoverageStatus.OPEN_SEMANTICS


def test_challenger_transport_failure_retains_initial_reading_but_blocks_closure():
    parsed = parse_policy_programs(POLICY, ATOMS, Backend(failure='policy_program_missing_reading_v2'))
    assert len(parsed.hypotheses) == 1
    assert parsed.coverage.status is CoverageStatus.OPEN_SEMANTICS
    assert parsed.failures[0][1].value == 'TRANSPORT_ERROR'


def test_duplicate_clause_order_does_not_become_extra_votes():
    parsed = parse_policy_programs(POLICY, ATOMS, Backend(challenger=[reading(PolicyProgram((('!APPROVED', 'ACT'),), ()))]))
    assert len(parsed.hypotheses) == 1
    assert not parsed.coverage.challenger_alternatives


def test_full_authoritative_meaning_universe_is_enumerated_not_model_confidence():
    parsed = parse_policy_programs(POLICY, ATOMS, Backend(initial=[reading(IF)]), universe=universe(ONLY_IF))
    assert parsed.coverage.status is CoverageStatus.PROVABLY_CLOSED
    assert parsed.coverage.enumeration_complete
    assert parsed.hypotheses[0].program == ONLY_IF
    assert parsed.empirical_hypotheses[0].program == IF
    assert any(reason == 'OUTSIDE_AUTHORITATIVE_UNIVERSE' for _, reason in parsed.coverage.discarded_hypotheses)
    assert aggregate_program_meanings(parsed, {'ACT': Truth.TRUE, 'APPROVED': Truth.TRUE})['status'] is CoreStatus.PROVED_NO_ERROR


def test_partial_authoritative_universe_or_schema_authority_is_not_closure():
    parsed = parse_policy_programs(POLICY, ATOMS, Backend(), universe=universe(ONLY_IF, complete=False))
    assert parsed.coverage.status is CoverageStatus.OPEN_SEMANTICS
    with pytest.raises(ValueError):
        replace(universe(ONLY_IF), authority_basis='FINITE_SCHEMA')
    with pytest.raises(ValueError):
        parse_policy_programs(POLICY, ATOMS, Backend(), universe=replace(universe(ONLY_IF), policy_sha256=digest('different policy')))


def test_fact_values_require_explicit_truth_not_python_booleans():
    with pytest.raises(TypeError):
        program_values(ONLY_IF, {'ACT': True})
