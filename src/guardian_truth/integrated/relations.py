"""Deterministic, scoped source relations for the CURRENT assistant move.

Every fact is a SOURCE_OBSERVATION: an exact string / status / identity relation over
the full original input (SourceStore), with exact spans. None of them is a verdict:
an argument value absent from earlier text may be legitimately derived, an ERROR receipt is
not an assistant violation, and a repeated call may be allowed. The reviewer receives the facts
and the cited original spans; the decision stays a MODEL_HYPOTHESIS. Labels are never read.

Fact kinds
  ARG_VALUE_PROVENANCE  identifier-like scalar argument of a current call: where the exact value was
                        observed before the move (actor/kind/event), or NOT_OBSERVED anywhere in the
                        earlier record (whole prompt, not just the packet).
  PRIOR_ERROR_RECEIPT   tool receipt with transport status ERROR among the last events before the move,
                        or for the same tool as a current call.
  REPEATED_CALL         a current call identical (tool + arguments) to an earlier call, with that earlier
                        call's receipt status.
  PROSE_VALUE_NOT_OBSERVED  identifier/number stated in current assistant prose that occurs nowhere in the
                        earlier record (may be computed; shadow only, never decisive).
"""
from __future__ import annotations

import json
import re

ID_LIKE = re.compile(r'(?=[A-Za-z0-9_#-]*\d)[A-Za-z0-9_#-]{4,40}')
PROSE_TOKEN = re.compile(r'(?<![\w.,/-])#?(?:\d[\d,]*(?:\.\d+)?|[A-Za-z]*\d[A-Za-z0-9]{3,})(?![\w/-])')
RECENT_WINDOW = 4
MAX_FACTS = 24
VERSION = 'integrated-relations-v1'


def _scalars(value, path='$'):
    if isinstance(value, dict):
        for k, v in value.items():
            yield from _scalars(v, f'{path}.{k}')
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield from _scalars(v, f'{path}[{i}]')
    elif isinstance(value, bool) or value is None:
        return
    elif isinstance(value, int) and abs(value) >= 1000:
        yield path, str(value)
    elif isinstance(value, str) and ID_LIKE.fullmatch(value.strip()):
        yield path, value.strip()


def _occurs(text, value):
    return re.search(r'(?<![\w])' + re.escape(value) + r'(?![\w])', text) is not None


def _sid(document, index):
    return ('h' if document == 'prompt' else 't') + str(index)


def _ref(event, index, document):
    s = event.source
    return dict(source_id=_sid(document, index), document=s.document, start=s.start, end=s.end,
                role=event.role, kind=event.kind, tool=event.name)


def compute(store):
    """Return {'version','facts','decisive','source_refs','truncated'}; deterministic, label-free."""
    history, targets = store.history_events, store.target_events
    facts = []
    calls = [(i, e) for i, e in enumerate(targets) if e.role == 'assistant' and e.kind == 'call']
    for ti, call in calls:                                   # 1. argument provenance
        if not call.json_valid:
            continue
        for path, value in _scalars(call.value):
            seen = [(i, e) for i, e in enumerate(history) if _occurs(e.text, value)]
            observed = [(i, e) for i, e in seen if e.role != 'system']
            entry = dict(kind='ARG_VALUE_PROVENANCE', status='SOURCE_OBSERVATION', target_id=_sid('response', ti),
                         tool=call.name, path=path, value=value)
            if observed:
                (fi, fe), (li, le) = observed[0], observed[-1]
                entry.update(relation='OBSERVED_BEFORE_MOVE', decisive=False, first=_ref(fe, fi, 'prompt'),
                             last=_ref(le, li, 'prompt'),
                             observed_in=sorted({f'{e.role}/{e.kind}' for _, e in observed}))
            elif seen:
                entry.update(relation='OBSERVED_ONLY_IN_SYSTEM_TEXT', decisive=True, first=_ref(seen[0][1], seen[0][0], 'prompt'))
            else:
                ci = value.casefold()
                near = [(i, e) for i, e in enumerate(history) if e.role != 'system' and ci in e.text.casefold()]
                entry.update(relation='ONLY_CASE_OR_SUBSTRING_VARIANT_OBSERVED' if near else 'NOT_OBSERVED_IN_EARLIER_RECORD',
                             decisive=True, **({'first': _ref(near[0][1], near[0][0], 'prompt')} if near else {}))
            facts.append(entry)
    current_tools = {c.name for _, c in calls}               # 2. error receipts
    n = len(history)
    for i, e in enumerate(history):
        if e.kind != 'result' or e.status != 'ERROR':
            continue
        recent = i >= n - RECENT_WINDOW
        if recent or e.name in current_tools:
            facts.append(dict(kind='PRIOR_ERROR_RECEIPT', status='SOURCE_OBSERVATION', relation='TOOL_RECEIPT_STATUS_ERROR',
                              decisive=recent, tool=e.name, receipt=_ref(e, i, 'prompt'), events_before_move=n - i,
                              same_tool_as_current_call=e.name in current_tools))
    prior_calls = [(i, e) for i, e in enumerate(history) if e.kind == 'call' and e.json_valid]
    for ti, call in calls:                                   # 3. repeated identical calls
        if not call.json_valid:
            continue
        key = json.dumps(call.value, sort_keys=True, ensure_ascii=False)
        for i, e in prior_calls:
            if e.name == call.name and json.dumps(e.value, sort_keys=True, ensure_ascii=False) == key:
                receipt = next(((j, r) for j, r in enumerate(history[i + 1:], i + 1) if r.kind == 'result'), None)
                facts.append(dict(kind='REPEATED_CALL', status='SOURCE_OBSERVATION', relation='IDENTICAL_TOOL_AND_ARGUMENTS',
                                  decisive=bool(receipt and receipt[1].status == 'ERROR'), target_id=_sid('response', ti),
                                  tool=call.name, earlier_call=_ref(e, i, 'prompt'),
                                  earlier_receipt=_ref(receipt[1], receipt[0], 'prompt') if receipt else None,
                                  earlier_receipt_status=(receipt[1].status or 'NOT_STATED') if receipt else 'NO_RECEIPT'))
    earlier = store.raw['prompt']                            # 4. prose values (shadow)
    for ti, e in enumerate(targets):
        if e.role != 'assistant' or e.kind != 'text':
            continue
        for m in PROSE_TOKEN.finditer(e.text):
            tok = m.group(0).lstrip('#')
            if len(re.sub(r'\D', '', tok)) < 3 or re.fullmatch(r'(19|20)\d\d', tok):
                continue
            if not any(_occurs(earlier, v) for v in {tok, tok.replace(',', '')}):
                facts.append(dict(kind='PROSE_VALUE_NOT_OBSERVED', status='SOURCE_OBSERVATION',
                                  relation='STRING_ABSENT_FROM_EARLIER_RECORD', decisive=False, target_id=_sid('response', ti),
                                  value=tok, note='may be computed or derived; a missing string is not a false fact'))
    order = sorted(range(len(facts)), key=lambda k: (not facts[k]['decisive'], k))
    kept = [facts[k] for k in order[:MAX_FACTS]]
    for k, f in enumerate(kept):
        f['fact_id'] = f'R{k + 1}'
    refs = [f[key] for f in kept for key in ('first', 'last', 'receipt', 'earlier_call', 'earlier_receipt') if f.get(key)]
    return dict(version=VERSION, facts=kept, decisive=[f['fact_id'] for f in kept if f['decisive']],
                source_refs=refs, truncated=len(facts) > MAX_FACTS)
