"""Separate original agent input and retrieved source text from evaluator turns."""
import re
from guardian_truth.parsing import parse_catalog


def retrieved_texts(store, result):
    """Retain only text actually returned, never expand a search excerpt."""
    found = []
    def visit(value):
        if isinstance(value, dict):
            sid = value.get('source_ref', value.get('source_id'))
            text = value.get('text', value.get('excerpt'))
            if isinstance(sid, str) and isinstance(text, str) and text:
                span = store.quotes.get(sid) or store.sources.get(sid)
                if span and store.text(sid).startswith(text):
                    exact = store.quote_id(span['document'], span['start'], span['start'] + len(text))
                    found.append({'source_id': exact, 'text': text})
            for child in value.values(): visit(child)
        elif isinstance(value, list):
            for child in value: visit(child)
    visit(result)
    return found


def final_packet(store, initial, retrieved):
    linked = dict(initial.get('source_linked_context', {}))
    if 'full_system_sources' in initial:
        linked['system_sources'] = initial['full_system_sources']
    if 'index' in initial:
        linked['initial_source_view'] = initial['index']
    evidence = {(r['source_id'], r['text']): r for r in retrieved}
    return {'target_response': store.raw['response'], 'source_linked_context': linked,
        'retrieved_evidence': list(evidence.values())}


def evaluator_artifact(store, explanation, names):
    catalog = parse_catalog(store.history_events, store.raw['prompt'])
    if not catalog.complete:
        return []  # absence is not established by a partial catalog
    return [name for name in names if name not in catalog.tools and re.search(
        r'(?<![\w])' + re.escape(name) + r'(?![\w])', explanation)]
