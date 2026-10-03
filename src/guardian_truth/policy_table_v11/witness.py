"""Source-bound, conservative witnesses; no model assertion proves a prerequisite."""
from datetime import datetime, timedelta, timezone
import re
from guardian_truth.parsing import parse_catalog
from guardian_truth.policy_table.evaluate import Value, UNKNOWN
from guardian_truth.policy_table.segment import system_text

DATE = r'\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2}|\s+(?:UTC|GMT|EST|EDT|CST|CDT|MST|MDT|PST|PDT))?'
OFFSETS = {'UTC': 0, 'GMT': 0, 'EST': -5, 'EDT': -4, 'CST': -6, 'CDT': -5,
           'MST': -7, 'MDT': -6, 'PST': -8, 'PDT': -7}


def parsed_time(text):
    match = re.fullmatch(DATE, text.strip())
    if not match: return None
    text = match[0]
    zone = re.search(r'\s+([A-Z]{3})$', text)
    try:
        if zone:
            value = datetime.fromisoformat(text[:zone.start()]).replace(tzinfo=timezone(timedelta(hours=OFFSETS[zone[1]])))
        else: value = datetime.fromisoformat(text.replace('Z', '+00:00'))
        return value.isoformat() if value.tzinfo is not None else None
    except ValueError: return None


def timeline(store, target):
    sid = target['source_id']
    source = store.sources.get(sid)
    if not source: return []
    if source['document'] == 'prompt':
        return [('h' + str(i), e) for i, e in enumerate(store.history_events[:source['event']])]
    return ([('h' + str(i), e) for i, e in enumerate(store.history_events)] +
            [('t' + str(i), e) for i, e in enumerate(store.target_events[:source['event']])])


def current_datetime(store, target):
    matches = []
    for sid, event in timeline(store, target):
        if event.role == 'system':
            for m in re.finditer(r'\bcurrent\s+time\s+is\s+(' + DATE + ')', event.text, re.I):
                matches.append((parsed_time(m[1]), sid))
    if matches:
        values = {v for v, _ in matches}
        if len(values) == 1 and None not in values:
            return Value('RESOLVED', matches[0][0], tuple(s for _, s in matches), 'EXPLICIT_POLICY_TIMEZONE')
        return Value('UNRESOLVED', reason='policy_time_ambiguous_or_timezone_missing')
    catalog = parse_catalog(store.history_events, store.raw['prompt'])
    eligible = set()
    for name, spec in catalog.tools.items():
        declaration = store.raw['prompt'][spec.source.start:spec.source.end].split('\n')[0]
        if re.search(r'\bcurrent\s*(?:time|date|datetime)\b', name.replace('_', ' ') + ' ' + declaration, re.I): eligible.add(name)
    results = [(sid, e) for sid, e in timeline(store, target) if e.kind == 'result' and e.name in eligible]
    if not results: return UNKNOWN
    sid, event = results[-1]
    if not event.json_valid:
        raw = event.text.strip()
        phrase = re.fullmatch(r'The\s+current\s+time\s+is\s+(' + DATE + r')\.?', raw, re.I)
        value = parsed_time(phrase[1] if phrase else raw)
        return Value('RESOLVED', value, (sid,), 'LATEST_LITERAL_CURRENT_TIME_TOOL_RESULT') if value else Value(
            'UNRESOLVED', source_ids=(sid,), reason='latest_current_time_result_invalid_or_timezone_missing')
    def strings(value):
        if isinstance(value, str): yield value
        elif isinstance(value, dict):
            for child in value.values(): yield from strings(child)
        elif isinstance(value, list):
            for child in value: yield from strings(child)
    values = [parsed_time(s) for s in strings(event.value) if re.fullmatch(DATE, s.strip())]
    if len(values) == 1 and values[0] is not None:
        return Value('RESOLVED', values[0], (sid,), 'LATEST_CURRENT_TIME_TOOL_RESULT')
    return Value('UNRESOLVED', source_ids=(sid,), reason='current_time_result_ambiguous_or_timezone_missing')


AFFIRM = re.compile(r'^(?:да|подтверждаю|согласен|согласна|верно|yes|confirm|confirmed|i confirm|go ahead|please proceed|proceed|ok|okay)\b', re.I)
REFUSE = re.compile(r'^(?:нет|не подтверждаю|не согласен|не согласна|отмените|no|do not|don.t|cancel|stop)\b', re.I)
# "No problem"/"нет возражений" is not a refusal; it is stripped and the remainder decides.
NOT_REFUSAL = re.compile(r'^(?:no\s+(?:problem|problems|worries|objections?)|нет\s+(?:проблем|возражений))\b[\s,.!:;-]*', re.I)
HEDGE = re.compile(r'\b(?:но|but|если|if|нет|not|не|no|don.?t|do not|cancel|stop|wait|отмен\w*|подожд\w*|стоп)\b', re.I)
ASK = re.compile(r'подтверд|соглас(?:ие|ны)|(?:can|shall|may) i\b|confirm|confirmation|go ahead|proceed|\?', re.I)
DESCRIBE = re.compile(r'\b(?:will|shall|would|going to)\b|(?:сделаю|изменю|оформлю|выполню|добавлю|удалю|заменю|проведу|переведу)', re.I)


def key_values(arguments):
    keys = [k for k in arguments if k == 'id' or k.endswith('_id')]
    values = [arguments[k] for k in keys] if keys else list(arguments.values())
    return [v for v in values if isinstance(v, str) and v.strip() or type(v) in (int, float)]


def contains_value(text, value):
    # "X" must not bind to "X-1", "X_2" or "X.3": joined identifier characters count as one token.
    return bool(re.search(r'(?<![\w-])' + re.escape(str(value)) + r'(?![\w-]|[./]\w)', text))


def reply_kind(text):
    text = text.strip().strip('«»"\' ').lower()
    stripped = NOT_REFUSAL.sub('', text, count=1)
    if stripped != text:
        if not stripped: return 'UNCLEAR'
        text = stripped
    elif REFUSE.search(text): return 'REFUSE'
    if AFFIRM.search(text) and not HEDGE.search(text): return 'AFFIRM'
    return 'UNCLEAR'


def same_call(event, target):
    return event.name == target.get('tool') and event.value == (target.get('arguments') or {})


def explicit_confirmation(store, target):
    events = timeline(store, target)
    values = key_values(target.get('arguments') or {})
    if not values: return Value('UNRESOLVED', reason='no_key_argument_for_action_binding')
    texts = [i for i, (_, e) in enumerate(events) if e.role == 'assistant' and e.kind == 'text']
    if not texts: return Value('UNRESOLVED', reason='no_assistant_description')
    def bound(i):
        text = events[i][1].text
        return any(contains_value(text, v) for v in values) and bool(ASK.search(text) or DESCRIBE.search(text))
    def user_after(i):
        return [j for j in range(i + 1, len(events)) if events[j][1].role == 'user' and events[j][1].kind == 'text']
    bounds = [i for i in texts if bound(i)]
    if not bounds: return Value('UNRESOLVED', source_ids=(events[texts[-1]][0],), reason='latest_description_not_bound_to_action')
    answered = [i for i in bounds if user_after(i)]
    if not answered:
        return Value('RESOLVED', False, (events[bounds[-1]][0], target['source_id']), 'NO_USER_TURN_AFTER_BOUND_DESCRIPTION')
    index = answered[-1]; sid = events[index][0]
    users = user_after(index)
    # The answer is the user block right after the description; anything later must stay silent.
    reply = []
    for j in range(index + 1, len(events)):
        if events[j][1].role == 'user' and events[j][1].kind == 'text': reply.append(j)
        elif reply: break
    if len(reply) != len(users):
        return Value('UNRESOLVED', source_ids=(sid,), reason='conversation_continued_after_reply')
    # Consent is consumed by a different native act; an identical retry of the target keeps it.
    if any(e.kind == 'call' and not same_call(e, target) for _, e in events[index + 1:]):
        return Value('UNRESOLVED', source_ids=(sid,), reason='intervening_call_requires_new_action_binding')
    # A later unanswered request for confirmation reopens the binding.
    later = [i for i in bounds if i > reply[-1]]
    if any(re.search(r'\?|подтверд|confirm', events[i][1].text, re.I) for i in later):
        return Value('UNRESOLVED', source_ids=(sid, events[later[-1]][0]), reason='unanswered_later_confirmation_request')
    kinds = {reply_kind(events[j][1].text) for j in reply}
    rsids = (sid,) + tuple(events[j][0] for j in reply)
    if kinds == {'AFFIRM'}: return Value('RESOLVED', True, rsids, 'AFFIRMATION_AFTER_BOUND_DESCRIPTION')
    if kinds == {'REFUSE'}: return Value('RESOLVED', False, rsids, 'EXPLICIT_REFUSAL_AFTER_BOUND_DESCRIPTION')
    return Value('UNRESOLVED', source_ids=rsids, reason='user_reply_not_unambiguous_confirmation')
