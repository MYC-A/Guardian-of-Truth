"""Phase 3 policy-semantic and prose invariants on synthetic, out-of-domain dialogues."""
import json
from guardian_truth.policy_table_v11.service import Gate
from guardian_truth.policy_table_v11.prose import arithmetic_violations
from guardian_truth.policy_table_v11.records import parse_dates, parse_date

GATE = Gate(None)


def _row(policy, tools, turns, response):
    prompt = '⟦SYSTEM⟧\n' + policy + '\n\n[AVAILABLE TOOLS]\n' + tools + '\n\n' + '\n\n'.join(turns)
    return {'id': 'x', 'prompt': prompt, 'response': response}


def _codes(row):
    out = GATE.check(row)
    return out['verdict'], [v['code'] for v in out['violations']]


# --------------------------------------------------------------- temporal prohibition
LIB_POLICY = ('The current time is 2031-03-10 09:00:00 EST.\n'
              "You must not reopen a ticket if the ticket's warranty end date is in the past, even if the customer insists.")
LIB_TOOLS = ('- get_ticket — Reads one ticket.\n    ticket_id: string! — ticket ID\n'
             '- reopen_ticket — Reopens a closed ticket.\n    ticket_id: string! — ticket ID\n'
             '- close_ticket — Closes a ticket.\n    ticket_id: string! — ticket ID')


def _lib(end_date, call='reopen_ticket'):
    turns = ['⟦USER⟧\nPlease reopen ticket TK-9.',
             '⟦ASSISTANT⟧\n→ TOOL_CALL get_ticket: {"ticket_id": "TK-9"}\n← TOOL_RESPONSE get_ticket: ' +
             json.dumps({'ticket_id': 'TK-9', 'status': 'closed', 'warranty_end_date': end_date})]
    return _row(LIB_POLICY, LIB_TOOLS, turns, '→ TOOL_CALL %s: {"ticket_id": "TK-9"}' % call)


def test_temporal_prohibition_fires_only_for_past_date_and_bound_tool():
    assert _codes(_lib('2031-01-31')) == ('VIOLATION', ['TEMPORAL_PROHIBITION'])
    assert _codes(_lib('2031-12-31')) == ('ADMISSIBLE', [])
    assert _codes(_lib('2031-01-31', call='close_ticket')) == ('ADMISSIBLE', [])  # other action


def test_temporal_prohibition_needs_reference_time():
    row = _lib('2031-01-31'); row['prompt'] = row['prompt'].replace('The current time is 2031-03-10 09:00:00 EST.\n', '')
    assert _codes(row) == ('ADMISSIBLE', [])


# --------------------------------------------------------------- aggregate over past records
AGG_POLICY = 'The current time is 2030-06-15 12:00:00 UTC.'
AGG_TOOLS = ('- get_booking — Reads a booking.\n    booking_id: string! — booking ID\n'
             '- calculate — Evaluates an arithmetic expression.\n    expression: string! — expression')


def _agg(question, expression):
    rec = lambda bid, day, amount: json.dumps({'booking_id': bid, 'events': [{'date': day}], 'payments': [{'amount': amount}]})
    turns = ['⟦USER⟧\n' + question,
             '⟦ASSISTANT⟧\n→ TOOL_CALL get_booking: {"booking_id": "B1"}\n← TOOL_RESPONSE get_booking: ' + rec('B1', '2030-07-01', 120),
             '⟦ASSISTANT⟧\n→ TOOL_CALL get_booking: {"booking_id": "B2"}\n← TOOL_RESPONSE get_booking: ' + rec('B2', '2030-06-01', 75)]
    return _row(AGG_POLICY, AGG_TOOLS, turns, '→ TOOL_CALL calculate: {"expression": "%s"}' % expression)


def test_aggregate_of_upcoming_items_must_not_include_past_records():
    assert _codes(_agg('What is the total of my upcoming bookings?', '120 + 75')) == ('VIOLATION', ['AGGREGATE_INCLUDES_PAST'])
    assert _codes(_agg('What is the total of my upcoming bookings?', '120')) == ('ADMISSIBLE', [])
    assert _codes(_agg('What is the total of all my bookings?', '120 + 75')) == ('ADMISSIBLE', [])  # no future filter


# --------------------------------------------------------------- verification quorum
VER_POLICY = ('To verify the identity of the user, ensure that they are able to give correctly any 2 out of the following '
              'values: date of birth, email, phone number, address.')
VER_TOOLS = ('- find_member — Finds a member by name.\n    name: string! — full name\n'
             '- record_verification — Record a verification after the member was verified.\n'
             '    member_id: string! — id\n    email: string! — email\n    phone_number: string! — phone\n'
             '    date_of_birth: string! — MM/DD/YYYY')
MEMBER = {'member_id': 'm77', 'email': 'ann.lee@mail.test', 'phone_number': '415-555-0101', 'date_of_birth': '03/04/1990'}


def _ver(user_text):
    turns = ['⟦USER⟧\n' + user_text,
             '⟦ASSISTANT⟧\n→ TOOL_CALL find_member: {"name": "Ann Lee"}\n← TOOL_RESPONSE find_member: ' + json.dumps(MEMBER)]
    return _row(VER_POLICY, VER_TOOLS, turns, '→ TOOL_CALL record_verification: ' + json.dumps(MEMBER))


def test_verification_quorum_counts_only_user_provided_values():
    assert _codes(_ver('I am Ann Lee, phone 415 555 0101.')) == ('VIOLATION', ['VERIFICATION_QUORUM_NOT_MET'])
    assert _codes(_ver('I am Ann Lee, phone 415 555 0101, born March 4, 1990.')) == ('ADMISSIBLE', [])
    assert _codes(_ver('Ann Lee here: ann.lee@mail.test and (415) 555-0101')) == ('ADMISSIBLE', [])


# --------------------------------------------------------------- prose channel
PROSE_TOOLS = '- get_profile — Reads a profile.\n    profile_id: string! — id'


def _prose(reply):
    turns = ['⟦USER⟧\nBook a seat for Maria Gomez and me.',
             '⟦ASSISTANT⟧\n→ TOOL_CALL get_profile: {"profile_id": "p1"}\n← TOOL_RESPONSE get_profile: ' +
             json.dumps({'profile_id': 'p1', 'name': {'first_name': 'Maria', 'last_name': 'Gomez'}, 'dob': '1980-02-02'})]
    return _row('Be helpful.', PROSE_TOOLS, turns, '⟦ASSISTANT⟧\n' + reply)


def test_prose_is_admissible_when_bounded_checks_pass():
    out = GATE.check(_prose('Your seat is booked.'))
    assert out['verdict'] == 'ADMISSIBLE' and any(n['code'] == 'PROSE_RESIDUAL_RISK' for n in out['notes'])


def test_redundant_request_for_observed_field_of_named_person():
    assert _codes(_prose('Please provide the date of birth for Maria Gomez.')) == ('VIOLATION', ['REDUNDANT_INFO_REQUEST'])
    assert _codes(_prose('Пожалуйста, уточните дату рождения для Maria Gomez.')) == ('VIOLATION', ['REDUNDANT_INFO_REQUEST'])
    assert _codes(_prose('Please provide the date of birth for John Smith.')) == ('ADMISSIBLE', [])  # not observed
    assert _codes(_prose('Please provide the email for Maria Gomez.')) == ('ADMISSIBLE', [])  # field not observed


def test_arithmetic_claims():
    assert arithmetic_violations('208.6 - 200.8 = **7.8$**') == []
    assert arithmetic_violations('Total: $1,200.50 + $99.50 = $1,300.00') == []
    assert arithmetic_violations('100 + 50 = 160')[0]['computed'] == '150'


def test_date_parsing_formats():
    assert parse_date('2025-01-31').isoformat() == '2025-01-31'
    assert {d.isoformat() for d in parse_dates('born 22 июля 1985')} == {'1985-07-22'}
    assert '1985-07-22' in {d.isoformat() for d in parse_dates('07/22/1985')}
