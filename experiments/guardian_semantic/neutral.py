"""Move-independent, bounded pre-analysis view of the original prompt.

No row ID, gold, response, or current-action retrieval result enters this function.
Packing remains explicitly incomplete when source windows do not fit. Prefixing
IDs prevents accidental aliasing with the separately packed review sources.
"""
from __future__ import annotations

import json
from guardian_truth.parsing import parse_catalog, parse_events
from guardian_truth.verification.pipeline import packet_for

VERSION = 'neutral-prompt-view-v2'


def neutral_view(original_row, budget_bytes=20000):
    if not isinstance(original_row, dict) or not isinstance(original_row.get('prompt'), str):
        return None, {'status': 'NOT_EXECUTED', 'reason': 'ORIGINAL_PROMPT_REQUIRED', 'version': VERSION}
    prompt = original_row['prompt']
    events = parse_events(prompt, 'prompt')
    catalog = parse_catalog(events, prompt)
    declaration = None
    declaration_gap = None
    remaining = budget_bytes
    if catalog.source is not None:
        span = catalog.source
        owner = next((i for i, e in enumerate(events) if e.source.start <= span.start and span.end <= e.source.end), None)
        declaration = dict(source_id=f'catalog:{span.start}:{span.end}', role='system', kind='catalog', tool=None,
                           event=owner, text=prompt[span.start:span.end],
                           source_span=dict(document='prompt', start=span.start, end=span.end))
        cost = len(json.dumps([declaration], ensure_ascii=False, separators=(',', ':')).encode('utf-8'))
        if remaining is not None and cost >= remaining:
            declaration = None
            declaration_gap = dict(category='DECLARATION', reason='NEUTRAL_CATALOG_NOT_READ_BUDGET',
                                   source_span=dict(document='prompt', start=span.start, end=span.end))
        elif remaining is not None:
            remaining -= cost
    # The response is cleared BEFORE parsing, query construction and selection.
    packet = packet_for({'prompt': prompt, 'response': ''}, remaining)
    if packet is None:
        return None, {'status': 'NOT_EXECUTED', 'reason': 'NEUTRAL_VIEW_BUDGET_EXCEEDED', 'version': VERSION,
                      'budget_bytes': budget_bytes}
    packet.pop('current_targets', None)
    packet['coverage'].pop('declaration_status', None)
    packet['coverage']['view_version'] = VERSION
    packet['coverage']['source_scope'] = 'ORIGINAL_PROMPT_ONLY'
    if declaration is not None:
        packet['declarations'] = [declaration]
    if declaration_gap is not None:
        packet['coverage']['unread'].append(declaration_gap)
        packet['coverage']['complete_input'] = False
    # These IDs belong to this view, not to the current-action reviewer packet.
    for key in ('normative_sources', 'declarations', 'history'):
        for source in packet.get(key, []):
            source['source_id'] = 'blind:' + source['source_id']
    packet['note'] = "The assistant's next move is hidden. Source IDs are local to this pre-analysis view."
    return packet, {'status': 'READY', 'version': VERSION, 'budget_bytes': budget_bytes,
                    'complete_input': packet['coverage']['complete_input'], 'unread': packet['coverage']['unread']}
