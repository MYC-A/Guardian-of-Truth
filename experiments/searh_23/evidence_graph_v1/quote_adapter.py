"""Experimental wire contract: exact quotes, with unique code-resolved offsets.

No fuzzy matching, repair prompts, guessed sentence boundaries or business
lexicon. This changes address representation, not interpretation of the rules.
Read requests retain numeric offsets because their text is not yet shown.
"""
from copy import deepcopy
import json

from guardian_truth.evidence_graph import EvidenceGraph
from guardian_truth.source_search.store import digest


class QuoteGraph(EvidenceGraph):
    VERSION = 'bidirectional-evidence-graph/1-exact-quotes'

    def _job(self, task, key, packet):
        job = super()._job(task, key, packet)
        old_id = job.pop('id')
        del self.jobs[old_id]
        schema = job['response_format']['json_schema']['schema']
        original_span = deepcopy(schema['$defs']['Span'])
        schema['$defs']['Span'] = {
            'type': 'object', 'additionalProperties': False,
            'properties': {'source_id': {'type': 'string'},
                           'quote': {'type': 'string', 'minLength': 1}},
            'required': ['source_id', 'quote'],
        }
        if task == 'WITNESS':
            schema['properties']['read_requests']['items'] = original_span
        job['messages'][0]['content'] = job['messages'][0]['content'].replace(
            'Span offsets are zero-based Python Unicode character offsets relative to source_id.',
            'Evidence spans contain source_id and a nonempty verbatim quote copied '
            'from a shown fragment. Do not paraphrase, normalize spelling or count '
            'character offsets. Choose a quote unique in that source\'s shown '
            'fragments. Only read_requests use zero-based Python Unicode offsets '
            'relative to source_id, because their text may not be shown yet.')
        jid = digest({'version': self.VERSION, 'source': self.store.source_sha256, **job})
        job['id'] = jid
        self.jobs.setdefault(jid, job)
        return deepcopy(self.jobs[jid])

    def offsets(self, job, obj, path=()):
        if isinstance(obj, list):
            return [self.offsets(job, value, path + (i,)) for i, value in enumerate(obj)]
        if not isinstance(obj, dict):
            return obj
        if set(obj) == {'source_id', 'quote'} and 'read_requests' not in path:
            sid, quote = obj['source_id'], obj['quote']
            if not isinstance(sid, str) or not isinstance(quote, str) or not quote:
                raise ValueError('QUOTE_ADDRESS_INVALID')
            candidates = set()
            for fragment in job['packet']['fragments']:
                if fragment['source_id'] != sid:
                    continue
                text, offset = fragment['text'], 0
                while (position := text.find(quote, offset)) >= 0:
                    start = fragment['start'] + position
                    candidates.add((start, start + len(quote)))
                    offset = position + 1
            if len(candidates) != 1:
                raise ValueError('QUOTE_MISSING_OR_AMBIGUOUS_IN_SHOWN_SOURCE')
            start, end = next(iter(candidates))
            return {'source_id': sid, 'start': start, 'end': end}
        return {key: self.offsets(job, value, path + (key,)) for key, value in obj.items()}

    def admit(self, job_id, response):
        try:
            response = self.offsets(self.jobs[job_id], response)
        except (ValueError, TypeError, KeyError) as error:
            job = self.jobs[job_id]
            self.failures[job_id] = {'task': job['task'], 'key': job['key'], 'cause': str(error)}
            return {'valid': False, 'cause': str(error), 'code_proof': False}
        return super().admit(job_id, response)
