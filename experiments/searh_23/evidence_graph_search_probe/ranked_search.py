"""Window-level BM25 and source diversity, as a retrieval hypothesis only.

Ranking the entire prefix in windows can reach a match at the end of a long
observation, unlike ranking its source and showing only its first 2400 chars.
No semantic extraction, entity ownership inference or benchmark vocabulary.
"""
from collections import Counter
from copy import deepcopy
import json
import math
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'evidence_graph_v1'))
from quote_adapter import QuoteGraph
from guardian_truth.evidence_graph.graph import windows


def terms(text):
    return re.findall(r'\w+', text.casefold())


def bm25(query, texts, *, k1=1.5, b=.75):
    documents = [Counter(terms(text)) for text in texts]
    if not documents:
        return []
    length = [sum(doc.values()) for doc in documents]
    average = sum(length) / len(length) or 1
    frequencies = Counter(term for doc in documents for term in doc)
    result = []
    for doc, size in zip(documents, length):
        score = 0.
        for token in set(terms(query)):
            frequency = doc[token]
            if not frequency:
                continue
            idf = math.log(1 + (len(documents) - frequencies[token] + .5) / (frequencies[token] + .5))
            score += idf * frequency * (k1 + 1) / (frequency + k1 * (1 - b + b * size / average))
        result.append(score)
    return result


class SearchGraph(QuoteGraph):
    """Search route is not evidence and is hidden from the applicability model."""
    def _job(self, task, key, packet):
        if task == 'LINK':
            packet = deepcopy(packet)
            packet.pop('search_route', None)
        return super()._job(task, key, packet)


class RankedGraph(SearchGraph):
    def _job(self, task, key, packet):
        if task != 'WITNESS':
            return super()._job(task, key, packet)
        packet = deepcopy(packet)
        tid = packet['target_id']
        prior = self._allowed_prior(tid)
        query = packet['leaf']['label'] + ' ' + packet['requirement']['action']
        query += ' ' + json.dumps(packet['target'], ensure_ascii=False)
        candidates = [self.fragment(sid, left, right) for sid in prior
            for left, right in windows(self.text(sid), self.chunk_chars)]
        scores = bm25(query, [c['text'] for c in candidates])
        ranking = sorted(range(len(candidates)), key=lambda i: (-scores[i], i))
        chosen, identities, source_counts = [], set(), Counter()

        def add(fragment):
            identity = (fragment['source_id'], fragment['start'], fragment['end'])
            if identity not in identities:
                chosen.append(fragment); identities.add(identity)
                source_counts[fragment['source_id']] += 1

        # Keep the actual target and the latest conversational exchange available.
        add(self.fragment(tid, 0, min(len(self.text(tid)), self.chunk_chars)))
        conversation = [sid for sid in prior if sid != tid
            and self.refs[sid]['role'] in ('user', 'assistant') and self.refs[sid]['kind'] == 'text']
        for sid in conversation[-2:]:
            if len(chosen) < self.witness_sources:
                add(self.fragment(sid, 0, min(len(self.text(sid)), self.chunk_chars)))
        # First distribute ranked windows among sources, then fill unused capacity.
        for maximum_per_source in (1, self.witness_sources):
            for index in ranking:
                if len(chosen) >= self.witness_sources:
                    break
                fragment = candidates[index]
                if source_counts[fragment['source_id']] < maximum_per_source:
                    add(fragment)
        for span in packet['leaf']['spans']:
            add(self.fragment(span['source_id'], span['start'], min(span['end'], span['start'] + self.chunk_chars)))
        history = self.witnesses.get((tid, packet['requirement_id'], packet['leaf_id']), [])
        for answer in history:
            for span in answer['read_requests']:
                add(self.fragment(span['source_id'], span['start'], span['end']))
        packet['fragments'] = chosen
        packet['navigation'] = {'strategy': 'BM25_SOURCE_WINDOWS_AND_DIVERSITY',
            'was_truncated': len(candidates) > self.witness_sources,
            'candidate_windows': len(candidates), 'k1': 1.5, 'b': .75,
            'retrieval_only': True}
        return super()._job(task, key, packet)
