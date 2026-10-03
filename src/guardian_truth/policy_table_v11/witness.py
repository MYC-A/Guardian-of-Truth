"""Source-bound, conservative witnesses; no model assertion proves a prerequisite."""
from datetime import datetime, timedelta, timezone
import re
from guardian_truth.parsing import parse_catalog
from guardian_truth.policy_table.evaluate import Value, UNKNOWN
from guardian_truth.policy_table.segment import system_text
from .provenance import observations

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
    events = timeline(store, target)
    results = [r for name in eligible for r in observations(events, name)]
    if not results: return UNKNOWN
    positions = {sid: i for i, (sid, _) in enumerate(events)}
    receipt = max(results, key=lambda r: positions[r.result_sid])
    sid, event = receipt.result_sid, receipt.result
    if not receipt.valid:
        return Value('UNRESOLVED', source_ids=(sid,), reason=receipt.reason)
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


def contains_value(text, value):
    return bool(re.search(r"(?<![\w./-])" + re.escape(str(value)) + r"(?![\w-]|[./]\w)", text))


def explicit_confirmation(store, target):
    from .consent import explicit_confirmation as certified
    return certified(store, target, timeline(store, target))
