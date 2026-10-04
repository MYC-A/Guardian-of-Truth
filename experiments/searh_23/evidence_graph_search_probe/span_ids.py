"""Code-owned exact line spans and schema-enforced formula arity.

Lines are address candidates, never claimed to be independent directives.
All parent/context text remains visible. No model-produced offsets or quotes.
"""
from copy import deepcopy
import re

from ranked_search import SearchGraph, RankedGraph
from guardian_truth.source_search.store import digest


class IdGraph(SearchGraph):
    def _job(self, task, key, packet):
        job = super()._job(task, key, packet)
        packet = deepcopy(job['packet'])
        old_id = job.pop('id')
        del self.jobs[old_id]
        candidates, identities = {}, {}
        def add(sid, start, end):
            identity = (sid, start, end)
            if identity not in identities:
                span_id = 's' + str(len(candidates))
                identities[identity] = span_id
                candidates[span_id] = {'source_id': sid, 'start': start, 'end': end}
        for fragment in packet['fragments']:
            offset = fragment['start']
            for line in fragment['text'].splitlines(keepends=True):
                end = offset + len(line)
                if line.strip():
                    add(fragment['source_id'], offset, end)
                offset = end
            if task == 'WITNESS':
                # Generic JSON scalar addresses enable code arithmetic. These are
                # address candidates, not a dictionary of business thresholds.
                for match in re.finditer(r'(?<![\w.])(?:-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?|true|false|null)(?![\w.])', fragment['text']):
                    add(fragment['source_id'], fragment['start'] + match.start(),
                        fragment['start'] + match.end())
        if not candidates:
            raise ValueError('NO_NONEMPTY_SOURCE_LINES')
        job['packet']['span_catalog'] = [{'span_id': sid, **span,
            'text': self.resolve(span)['text']} for sid, span in candidates.items()]
        schema = job['response_format']['json_schema']['schema']
        schema['$defs']['Span'] = {'type': 'object', 'additionalProperties': False,
            'properties': {'span_id': {'type': 'string', 'enum': list(candidates)}},
            'required': ['span_id']}
        if task == 'INVENTORY':
            anchored = [sid for sid, span in candidates.items() if span['source_id'] == packet['unit_id']]
            schema['$defs']['Requirement']['properties']['source_spans']['items'] = {
                'type': 'object', 'additionalProperties': False,
                'properties': {'span_id': {'type': 'string', 'enum': anchored}},
                'required': ['span_id']}
        if 'Formula' in schema['$defs']:
            original = deepcopy(schema['$defs']['Formula'])
            alternatives = []
            for op, minimum, maximum in [('ATOM', 0, 0), ('UNKNOWN', 0, 0),
                    ('AND', 2, None), ('OR', 2, None), ('NOT', 1, 1), ('BEFORE', 2, 2), ('AFTER', 2, 2)]:
                variant = deepcopy(original)
                variant['properties']['op'] = {'type': 'string', 'const': op}
                variant['properties']['children']['minItems'] = minimum
                if maximum is not None:
                    variant['properties']['children']['maxItems'] = maximum
                alternatives.append(variant)
            schema['$defs']['Formula'] = {'anyOf': alternatives}
        job['messages'][0]['content'] = job['messages'][0]['content'].split(
            'Evidence spans contain source_id')[0] + (
            'Evidence spans contain only span_id selected from span_catalog. Code '
            'owns their original text and offsets. Lines are address candidates, '
            'not separate rules: preserve shared conditions and parent context. '
            'Only read_requests use source_id/start/end numeric offsets. For '
            'INVENTORY, source_spans must be anchored in the requested unit; '
            'neighbor text supplies context and must not add unrelated directives.')
        if task == 'INVENTORY':
            job['messages'][0]['content'] += (
                '\nIR semantics: REQUIRE means its condition must be TRUE when '
                'the governed action is performed; FORBID means the action is '
                'prohibited when its condition is TRUE. guard is the rule-trigger '
                'condition, not the obligation. A necessary condition introduced '
                'by only-if or not-unless is REQUIRE, including a conditional '
                'permission with explicit necessity. Plain may is PERMIT and '
                'does not imply a prohibition. For an unconditional prohibition '
                'use FORBID with the prohibited occurrence as condition. Keep '
                'AND/OR, shared antecedents, exceptions and order in their '
                'original scope. Use UNKNOWN and open_questions for unresolved '
                'semantics. Do not infer missing business rules.')
        job['messages'][1]['content'] = __import__('json').dumps(job['packet'], ensure_ascii=False)
        jid = digest({'version': self.VERSION, 'source': self.store.source_sha256, **job})
        job['id'] = jid
        self.jobs.setdefault(jid, job)
        return deepcopy(self.jobs[jid])

    def admit(self, job_id, response):
        job = self.jobs[job_id]
        catalog = {item['span_id']: {k: item[k] for k in ('source_id', 'start', 'end')}
                   for item in job['packet']['span_catalog']}

        def convert(obj, path=()):
            if isinstance(obj, list):
                return [convert(v, path + (i,)) for i, v in enumerate(obj)]
            if not isinstance(obj, dict):
                return obj
            if set(obj) == {'span_id'}:
                if obj['span_id'] not in catalog:
                    raise ValueError('UNKNOWN_CODE_SPAN_ID')
                return deepcopy(catalog[obj['span_id']])
            # Evidence addresses must follow the experimental wire contract.
            if 'read_requests' not in path and ('source_id' in obj and ('start' in obj or 'quote' in obj)):
                raise ValueError('NON_ID_EVIDENCE_ADDRESS')
            return {key: convert(value, path + (key,)) for key, value in obj.items()}

        try:
            converted = convert(response)
        except (ValueError, TypeError, KeyError) as error:
            self.failures[job_id] = {'task': job['task'], 'key': job['key'], 'cause': str(error)}
            return {'valid': False, 'cause': str(error), 'code_proof': False}
        return super().admit(job_id, converted)


class RankedIdGraph(IdGraph, RankedGraph):
    """Identical source-ID contract, with window ranking instead of BFS/DFS."""
