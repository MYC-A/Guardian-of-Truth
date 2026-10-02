"""Source-grounded ISO timestamp arithmetic, independent of policy semantics.

No tool/domain dictionaries. Never turns a policy literal into a state fact.
Every relation is arithmetic between quoted literals, NOT policy applicability.
"""
from datetime import datetime, timezone
from itertools import combinations
import re
from modular_common import source_sha
from guardian_truth.parsing import parse_events

ISO = re.compile(r'\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})\b')


def timestamps(row, *, max_relations=32):
    sources = []
    for event in parse_events(row['prompt'], 'prompt'):
        if event.role == 'assistant' and event.kind != 'result':
            continue
        for match in ISO.finditer(event.text):
            # Source-offset matching uses the original event slice; reject
            # transformed parser text if an absolute span cannot be located.
            original = row['prompt'][event.source.start:event.source.end]
            text_offset = original.find(event.text)
            if text_offset < 0:
                continue
            local = text_offset + match.start()
            try:
                value = datetime.fromisoformat(match.group().replace('Z', '+00:00'))
            except ValueError:
                continue
            start = event.source.start + local
            sources.append({'literal': match.group(), 'role': event.role, 'kind': event.kind,
                'source_id': 'prompt', 'start': start, 'end': start + len(match.group()),
                'quote': match.group(), 'utc': value.astimezone(timezone.utc).isoformat(), '_value': value})
    relations = []
    total = len(sources) * (len(sources) - 1) // 2
    for left, right in combinations(sources, 2):
        if len(relations) >= max_relations:
            break
        delta = (left['_value'] - right['_value']).total_seconds()
        relations.append({'left_source': {k: v for k, v in left.items() if k != '_value'},
                          'right_source': {k: v for k, v in right.items() if k != '_value'},
                          'relation': 'EQUAL' if delta == 0 else 'LESS_THAN' if delta < 0 else 'GREATER_THAN',
                          'delta_seconds': delta, 'provenance': 'COMPUTED_ISO_DATETIME_ARITHMETIC'})
    return {'module': 'typed-ISO-relations/1', 'status': 'ADVISORY' if sources else 'INSUFFICIENT',
            'source_sha256': source_sha(row), 'relations': relations,
            'coverage': {'literals': len(sources), 'possible_pairs': total, 'emitted_pairs': len(relations),
                         'pair_limit_reached': total > max_relations},
            'assumptions': ['Timezone-aware source literals are parsed as timestamps.'],
            'limitations': ['Numerical ordering does not establish the normative operator, relevant clock or governed action.',
                            'Unzoned timestamps and relative dates are unsupported; no default timezone is guessed.'],
            'decision': 'ADVISORY_ONLY_NOT_AUTOMATIC_ERROR'}
