"""Complete immutable input, compact references, and explicit graph navigation.

Edges mean co-recorded identities, never ownership, permission or current truth.
Working views do not restrict the index. Examined tools are never executed.
"""
from collections import defaultdict, deque
from dataclasses import asdict
import hashlib
import json
import re

from guardian_truth.parsing import parse_events
from guardian_truth.provenance import build_graph, value_key


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':')).encode()).hexdigest()


def entity_key(entity):
    if not isinstance(entity, dict) or not isinstance(entity.get('field'), str):
        raise ValueError('entity requires a field and typed value')
    return entity['field'], value_key(entity['value'])


class SourceStore:
    def __init__(self, row, *, chunk_chars=1600):
        self.raw = {k: row[k] for k in ('prompt', 'response')}
        if not all(isinstance(v, str) for v in self.raw.values()):
            raise ValueError('source must be text')
        self.source_sha256 = digest(self.raw)
        self.sources, self.quotes, self.facts = {}, {}, {}
        self._span_ids, self.by_entity = {}, defaultdict(list)
        self.entities, self.adjacency = {}, defaultdict(dict)
        self.chunks = []
        history = parse_events(row['prompt'], 'prompt')
        target = parse_events(row['response'], 'response')
        self.history_events, self.target_events = history, target
        for document, text in self.raw.items():
            self.sources[document] = {'id': document, 'document': document, 'start': 0,
                'end': len(text), 'kind': 'raw', 'role': 'unknown', 'event': None,
                'tool': None, 'sha256': hashlib.sha256(text.encode()).hexdigest()}
        for document, events in (('prompt', history), ('response', target)):
            for i, event in enumerate(events):
                sid = ('h' if document == 'prompt' else 't') + str(i)
                span = asdict(event.source)
                text = self.raw[document][span['start']:span['end']]
                self.sources[sid] = {'id': sid, **span, 'event': i, 'role': event.role,
                    'kind': event.kind, 'tool': event.name, 'json_valid': event.json_valid,
                    'sha256': hashlib.sha256(text.encode()).hexdigest()}
                # Index all events, including plain-text KB/tool results. Chunks
                # are offsets into the raw source, not duplicated stored strings.
                for start in range(span['start'], span['end'], max(1, chunk_chars - 160)):
                    end = min(start + chunk_chars, span['end'])
                    self.chunks.append({'source_id': sid, 'start': start, 'end': end})
        native = build_graph(history, target, max_links=256)
        self.issues = list(native.issues)
        for node in native.facts:
            f = asdict(node)
            f['source_refs'] = [self.quote_id(s.document, s.start, s.end) for s in node.sources]
            del f['sources']
            f['epistemic_status'] = 'OBSERVED_PAYLOAD_NOT_CURRENT_TRUTH'
            self.facts[f['id']] = f
            keys = []
            for entity in f['entities']:
                key = entity_key(entity)
                self.entities[key] = entity
                self.by_entity[key].append(f['id'])
                keys.append(key)
            for left in keys:
                for right in keys:
                    if left != right:
                        edge = self.adjacency[left].setdefault(right, {'kind': 'CO_RECORDED',
                            'fact_ids': [], 'source_refs': []})
                        edge['fact_ids'].append(f['id'])
                        edge['source_refs'].extend(f['source_refs'])
        for edges in self.adjacency.values():
            for edge in edges.values():
                for field in ('fact_ids', 'source_refs'):
                    edge[field] = list(dict.fromkeys(edge[field]))

    def quote_id(self, document, start, end):
        if document not in self.raw or type(start) is not int or type(end) is not int:
            raise ValueError('invalid span')
        if not 0 <= start < end <= len(self.raw[document]):
            raise ValueError('span outside raw source')
        key = (document, start, end)
        if key not in self._span_ids:
            qid = 'q' + str(len(self.quotes))
            self._span_ids[key] = qid
            self.quotes[qid] = {'document': document, 'start': start, 'end': end}
        return self._span_ids[key]

    def text(self, source_id):
        s = self.quotes.get(source_id) or self.sources.get(source_id)
        if s is None:
            raise ValueError('unknown source_id')
        return self.raw[s['document']][s['start']:s['end']]

    def read_source(self, source_id, *, start=0, end=None, expand=0, limit=4000):
        s = self.quotes.get(source_id) or self.sources.get(source_id)
        if s is None:
            raise ValueError('unknown source_id')
        length = s['end'] - s['start']
        end = length if end is None else end
        if any(type(v) is not int for v in (start, end, expand, limit)) or not (
                0 <= start < end <= length and 0 <= expand <= 4000 and 1 <= limit <= 8000):
            raise ValueError('invalid read range')
        left = max(s['start'], s['start'] + start - expand)
        requested_right = min(s['end'], s['start'] + end + expand)
        right = min(requested_right, left + limit)
        qid = self.quote_id(s['document'], left, right)
        return {'source_id': source_id, 'source_ref': qid, **self.quotes[qid],
            'text': self.text(qid), 'was_truncated': right < requested_right,
            'next_cursor': right - s['start'] if right < requested_right else None,
            'source_length': length, 'coverage': 'EXACT_SOURCE_WINDOW'}

    @staticmethod
    def _page(items, cursor=0, limit=12):
        if type(cursor) is not int or type(limit) is not int or not (
                0 <= cursor <= len(items) and 1 <= limit <= 40):
            raise ValueError('invalid page')
        stop = min(cursor + limit, len(items))
        return {'items': items[cursor:stop], 'total': len(items),
            'was_truncated': stop < len(items), 'next_cursor': stop if stop < len(items) else None}

    def search_sources(self, query, *, source_types=None, before_target=True, cursor=0, limit=8):
        terms = set(re.findall(r'\w+', str(query).casefold()))
        if not terms:
            raise ValueError('empty search')
        hits = []
        for chunk in self.chunks:
            s = self.sources[chunk['source_id']]
            if before_target and s['document'] != 'prompt':
                continue
            if source_types and s['kind'] not in source_types and s['role'] not in source_types:
                continue
            text = self.raw[s['document']][chunk['start']:chunk['end']]
            tokens = set(re.findall(r'\w+', text.casefold()))
            score = len(terms & tokens)
            if not score:
                continue
            qid = self.quote_id(s['document'], chunk['start'], chunk['end'])
            hits.append({'source_id': s['id'], 'source_ref': qid, 'score': score,
                'role': s['role'], 'kind': s['kind'], 'tool': s['tool'],
                'excerpt': text[:300], 'excerpt_truncated': len(text) > 300})
        hits.sort(key=lambda h: (-h['score'], h['source_id'], h['source_ref']))
        return {**self._page(hits, cursor, limit), 'coverage': 'ALL_PARSED_SOURCE_EVENTS',
                'index_complete': True, 'absence_proves_semantic_absence': False}

    def lookup_entity(self, field, value, *, value_type=None, cursor=0, limit=12):
        if value_type is not None and value_type != type(value).__name__:
            raise ValueError('entity type mismatch')
        key = entity_key({'field': field, 'value': value})
        return {**self._page([self.facts[f] for f in self.by_entity[key]], cursor, limit),
            'entity': {'field': field, 'value': value}, 'coverage': 'FULL_STRUCTURED_INDEX',
            'interpretation': 'observations, not permission or current state'}

    def neighbors(self, entity, *, relation_types=None, cursor=0, limit=12):
        if relation_types and any(k != 'CO_RECORDED' for k in relation_types):
            raise ValueError('only explicit co-recorded edges are indexed')
        key = entity_key(entity)
        rows = [{'entity': self.entities[k], **edge} for k, edge in self.adjacency[key].items()]
        rows.sort(key=lambda r: json.dumps(r['entity'], sort_keys=True))
        return {**self._page(rows, cursor, limit), 'coverage': 'ALL_CO_RECORDED_NEIGHBORS',
                'interpretation': 'shared JSON record ancestry, not a business relation'}

    def traverse(self, entity, *, strategy='BFS', max_depth=2, max_nodes=24,
                 relation_types=None, fields=None):
        if strategy not in ('BFS', 'DFS') or type(max_depth) is not int or not 0 <= max_depth <= 4:
            raise ValueError('invalid traversal')
        if type(max_nodes) is not int or not 1 <= max_nodes <= 80:
            raise ValueError('invalid node limit')
        if relation_types and relation_types != ['CO_RECORDED']:
            raise ValueError('unsupported relation')
        root = entity_key(entity)
        frontier = deque([(root, 0, [])]); visited = set(); rows = []
        while frontier and len(visited) < max_nodes:
            key, depth, path = frontier.popleft() if strategy == 'BFS' else frontier.pop()
            if key in visited:
                continue
            visited.add(key)
            rows.append({'entity': self.entities.get(key, entity), 'depth': depth, 'path': path,
                         'fact_ids': self.by_entity[key]})
            if depth < max_depth:
                for neighbor, edge in sorted(self.adjacency[key].items(), key=lambda item: str(item[0])):
                    if neighbor not in visited and (not fields or neighbor[0] in fields):
                        frontier.append((neighbor, depth + 1, path + [{'from': self.entities[key],
                            'to': self.entities[neighbor], **edge}]))
        remaining = [self.entities[k] for k, _, _ in frontier if k not in visited]
        return {'items': rows, 'visited': len(visited), 'strategy': strategy,
            'was_truncated': bool(remaining),
            'frontier': remaining,
            'coverage': 'BOUNDED_EXPLICIT_GRAPH_NAVIGATION_NOT_AUTHORIZATION'}

    def list_sources(self, *, cursor=0, limit=12, role=None, kind=None):
        rows = [s for s in self.sources.values() if s['kind'] != 'raw'
                and (role is None or s['role'] == role) and (kind is None or s['kind'] == kind)]
        return self._page(rows, cursor, limit)

    def compact(self, *, fact_limit=16, source_limit=12):
        target = self.raw['response']
        selected = [f for f in self.facts.values()
                    if any(str(e['value']) and str(e['value']) in target for e in f['entities'])]
        chosen = selected[:fact_limit]
        refs = {q for f in chosen for q in f['source_refs']}
        source_rows = [s for s in self.sources.values() if s['kind'] != 'raw']
        return {'source_sha256': self.source_sha256,
            'sources': source_rows[:source_limit], 'sources_total': len(source_rows),
            'initial_sources_truncated': len(source_rows) > source_limit,
            'initial_facts': chosen, 'facts_total': len(self.facts),
            'initial_facts_truncated': len(selected) > fact_limit,
            'full_index_accessible': True, 'quotes': {q: self.quotes[q] for q in refs},
            'issues': self.issues,
            'warning': 'Compact projection is not the search universe; quote refs are provenance only.'}

    def resolve_quote(self, reference):
        """Recover bad IDs only by a unique exact quote; never discard raw vote."""
        if not isinstance(reference, dict) or not isinstance(reference.get('quote'), str) or not reference['quote']:
            raise ValueError('nonempty exact quote required')
        quote, sid = reference['quote'], reference.get('source_id')
        s = self.quotes.get(sid) or self.sources.get(sid)
        candidates = []
        if s is not None:
            document, left, right = s['document'], s['start'], s['end']
            ranges = [(document, left, right)]
        else:
            ranges = [(document, 0, len(text)) for document, text in self.raw.items()]
        for document, left, right in ranges:
            offset = left
            while True:
                pos = self.raw[document].find(quote, offset, right)
                if pos < 0:
                    break
                candidates.append((document, pos, pos + len(quote)))
                offset = pos + 1
        if len(candidates) != 1:
            raise ValueError('quote missing or ambiguous')
        document, start, end = candidates[0]
        qid = self.quote_id(document, start, end)
        return {'source_ref': qid, **self.quotes[qid], 'quote': quote,
            'repair': 'UNIQUE_EXACT_QUOTE_ID_RECOVERY' if s is None else 'VERIFIED_IN_NAMED_SOURCE'}

    def snapshot(self):
        # Store raw strings exactly once. The remaining tables contain refs.
        return {'schema': 'guardian-source-store/1', 'raw': self.raw,
            'source_sha256': self.source_sha256, 'sources': self.sources,
            'quotes': self.quotes, 'facts': self.facts, 'chunks': self.chunks, 'issues': self.issues}
