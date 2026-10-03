"""Exact operation certificates for consent. Prose needs a separately verified parser.

This recognises a small, explicit source protocol, not domain verbs or case names.
It never equates mentioning an ID or answering a factual question with authorisation.
"""
import re
from guardian_truth.parsing import decode_json, parse_catalog
from guardian_truth.policy_table.evaluate import Value, same

FRAME = re.compile(r'^(?P<head>Confirm|Подтвердите|I will call|Вызову)\s+'
                   r'(?P<tool>[\w.-]+)\s*:\s*(?P<arguments>\{.*\})\s*(?P<question>\?)?$', re.I | re.S)
AFFIRM = {'yes', 'yes please', 'confirm', 'confirmed', 'i confirm', 'go ahead', 'please proceed',
          'proceed', 'ok', 'okay', 'да', 'подтверждаю', 'согласен', 'согласна', 'верно'}
REFUSE = {'no', 'nope', 'no thanks', 'no thank you', 'i do not confirm', "i don't confirm",
          'do not proceed', "don't proceed", "please don't", 'нет', 'нет спасибо', 'не подтверждаю',
          'не согласен', 'не согласна', 'не надо', 'не нужно', 'не делайте', 'нет не надо',
          'no i changed my mind'}
COURTESY = {'thank you', 'thanks', 'спасибо', 'thank you processing now', 'спасибо выполняю'}


def words(text):
    return ' '.join(re.sub(r'[,.;!:«»"—]', ' ', text.strip().lower()).split())


def reply_kind(text):
    if any(char in text for char in '«»"'): return 'UNCLEAR'  # Do not remove quotation scope.
    value = words(text)
    # A closed reply grammar: never approve an uninspected free-text tail.
    value = re.sub(r'^(?:no problems?|no worries|no objections?|нет проблем|нет возражений)\s+', '', value)
    if value in AFFIRM: return 'AFFIRM'
    if value in REFUSE: return 'REFUSE'
    return 'UNCLEAR'


def action_frame(text, declared):
    match = FRAME.fullmatch(text.strip())
    if not match or match['tool'] not in declared: return None
    arguments, valid = decode_json(match['arguments'])
    if not valid or not isinstance(arguments, dict): return None
    return {'tool': match['tool'], 'arguments': arguments,
            'request': match['head'].lower() in ('confirm', 'подтвердите')}


def explicit_confirmation(store, target, events):
    declared = parse_catalog(store.history_events, store.raw['prompt']).tools
    wanted = {'tool': target.get('tool'), 'arguments': target.get('arguments') or {}}
    frames = [(i, action_frame(e.text, declared)) for i, (_, e) in enumerate(events)
              if e.role == 'assistant' and e.kind == 'text']
    frames = [(i, f) for i, f in frames if f is not None]
    matched = [(i, f) for i, f in frames if f['tool'] == wanted['tool'] and same(f['arguments'], wanted['arguments'])]
    if not matched: return Value('UNRESOLVED', reason='no_complete_action_certificate')
    index, frame = matched[-1]
    # Prefer an answered identical proposal over a later exact narration.
    if not frame['request']:
        answered = [(i, f) for i, f in matched if i < index and f['request']
                    and any(e.role == 'user' for _, e in events[i + 1:index])]
        if answered: index, frame = answered[-1]
    sid = events[index][0]
    if any(e.kind in ('call', 'result') for _, e in events[index + 1:]):
        return Value('UNRESOLVED', source_ids=(sid,), reason='intervening_native_act_requires_new_binding')
    if any(i > index and (f['tool'] != wanted['tool'] or not same(f['arguments'], wanted['arguments'])) for i, f in frames):
        return Value('UNRESOLVED', source_ids=(sid,), reason='operation_or_parameters_changed_after_proposal')
    users = [i for i in range(index + 1, len(events)) if events[i][1].role == 'user' and events[i][1].kind == 'text']
    if not users:
        if any(i < index and any(e.role == 'user' for _, e in events[i + 1:index]) for i, _ in matched):
            return Value('UNRESOLVED', source_ids=(sid,), reason='later_unanswered_proposal_after_earlier_reply')
        return Value('RESOLVED', False, (sid, target['source_id']), 'NO_USER_TURN_AFTER_BOUND_DESCRIPTION')
    if users != list(range(index + 1, index + 1 + len(users))):
        return Value('UNRESOLVED', source_ids=(sid,), reason='reply_not_immediately_bound_or_conversation_continued')
    reply = [events[i][0] for i in users]
    for later_sid, event in events[users[-1] + 1:]:
        if event.kind == 'text' and event.role == 'assistant':
            later = action_frame(event.text, declared)
            if later and not later['request'] and later['tool'] == wanted['tool'] and same(later['arguments'], wanted['arguments']): continue
            if words(event.text) in COURTESY: continue
            return Value('UNRESOLVED', source_ids=(sid, later_sid), reason='unverified_message_after_reply')
        if event.kind in ('call', 'result'):
            return Value('UNRESOLVED', source_ids=(sid, later_sid), reason='intervening_native_act_requires_new_binding')
    kinds = {reply_kind(events[i][1].text) for i in users}
    sources = (sid, *reply)
    if kinds == {'AFFIRM'}: return Value('RESOLVED', True, sources, 'AFFIRMATION_AFTER_BOUND_DESCRIPTION')
    if kinds == {'REFUSE'}: return Value('RESOLVED', False, sources, 'EXPLICIT_REFUSAL_AFTER_BOUND_DESCRIPTION')
    return Value('UNRESOLVED', source_ids=sources, reason='user_reply_not_unambiguous_confirmation')
