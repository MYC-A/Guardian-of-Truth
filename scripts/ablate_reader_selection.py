"""Offline feature ablation of initial evidence selection; no model/quality claim."""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

from guardian_truth.cli import read_rows, validate_rows
from guardian_truth.pipeline import Detector
from guardian_truth.reader import EvidenceReader
from guardian_truth.semantic import SemanticResult


class WithoutIdentityResultPriority(EvidenceReader):
    """Current initialization minus only identity/latest-result priority block."""

    def initialize(self, max_initial_chars=12000):
        rolling, old_limit = self.rolling, self.max_chars
        self.rolling = False
        self.max_chars = min(old_limit, max_initial_chars)
        try:
            policy = [c.id for c in self.chunks.values() if c.role == 'system']
            self.read(policy[:1])
            # Only omitted feature: response_entity_chunks and latest-result fallback.
            users = [c for c in self.chunks.values() if c.role == 'user' and c.kind == 'text']
            if users:
                last_event = users[-1].event
                self.read([c.id for c in users if c.event == last_event])
            ids = [key for trace in self.context.graph.arguments
                   for key in (trace.alternatives + trace.supporting)[:4]]
            self.read(self.graph_chunks(ids, limit=4))
            self.read(self.search(self.context.response, limit=6))
            self.read(policy[1:])
        finally:
            self.max_chars, self.rolling = old_limit, rolling


def union(intervals):
    merged = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(end, merged[-1][1])
        else:
            merged.append([start, end])
    return merged


def covered(intervals, selected):
    return sum(max(0, min(b, d) - max(a, c))
               for a, b in union(intervals) for c, d in union(selected))


def coverage(spans, selected):
    counts = Counter({'full': 0, 'partial': 0, 'not_delivered': 0})
    for a, b in spans:
        n = covered([(a, b)], selected)
        counts['full' if n == b-a else 'partial' if n else 'not_delivered'] += 1
    total = sum(b-a for a, b in union(spans))
    delivered = covered(spans, selected)
    return dict(counts, spans=len(spans), union_chars=total, covered_union_chars=delivered,
                union_character_coverage=delivered/total if total else None)


class SelectionProbe:
    name = 'offline_reader_ablation'

    def analyze(self, context):
        self.selections = {}
        for key, cls in [('without_priority', WithoutIdentityResultPriority), ('current', EvidenceReader)]:
            reader = cls(context, chunk_chars=1800, max_evidence_chars=4800, rolling=False)
            reader.initialize()
            self.selections[key] = {'ids': list(reader.selected), 'chars': reader.used_chars,
                                    'spans': [[s['start'], s['end']] for s in reader.packet()]}
            assert reader.used_chars <= 4800
        return SemanticResult()


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, default=Path('valid.parquet'))
    parser.add_argument('--output-dir', type=Path, default=Path('outputs/reader_selection_ablation'))
    args = parser.parse_args()
    output = args.output_dir/'report.json'
    if output.exists():
        parser.error('Refusing to overwrite an existing report; choose a fresh output directory')
    rows = read_rows(args.input)
    validate_rows(rows)
    probe = SelectionProbe()
    detector = Detector(semantic=probe)
    selections = {}
    # No annotations, IDs, gold labels or explanation enter selection.
    for row in rows:
        detector.review(row['prompt'], row['response'])
        selections[str(row['id'])] = probe.selections

    positive_path = Path('docs/v2_positive_reason_audit.json')
    unknown_path = Path('docs/v2_unknown_reason_audit.json')
    audit_path = Path('outputs/claim_gate_20b_full/audit.jsonl')
    positive = json.loads(positive_path.read_text(encoding='utf-8'))
    unknown = json.loads(unknown_path.read_text(encoding='utf-8'))
    run = {a['id']: a for a in map(json.loads, audit_path.read_text(encoding='utf-8').splitlines())}
    spans = {str(row['id']): set() for row in rows}
    for id_, sources in ([(a['id'], a['evidence']) for a in positive['annotations']] +
                         [(a['id'], a['source_evidence']) for a in unknown['rows']]):
        if id_ not in spans:
            continue
        for source in sources:
            if source.get('document', 'prompt') == 'prompt':
                spans[id_].add((source['start'], source['end']))
    details = []
    for row in rows:
        id_ = str(row['id'])
        for a, b in spans[id_]:
            if not 0 <= a < b <= len(row['prompt']):
                raise ValueError('Audit span outside original prompt')
        tags = ['all_annotated'] if spans[id_] else []
        a = run.get(id_)
        if a:
            actual, predicted = a['label'], a['strict']['label']
            if actual != predicted: tags.append('strict_errors')
            if actual == predicted == 1 and not a['skipped_mechanical']: tags.append('semantic_tp')
            if a['strict']['used_fallback']: tags.append('strict_fallback')
        selected = selections[id_]
        details.append({'id': id_, 'annotation_tags': tags, 'audit_spans': sorted(spans[id_]),
                        'selection_changed': selected['current']['ids'] != selected['without_priority']['ids'],
                        'coverage': {k: coverage(spans[id_], v['spans']) for k, v in selected.items()},
                        'selection': selected})
    groups = {}
    for tag in ['all_annotated', 'strict_errors', 'semantic_tp', 'strict_fallback']:
        members = [d for d in details if tag in d['annotation_tags'] and d['audit_spans']]
        groups[tag] = {'rows': len(members), 'variants': {}}
        for key in ['without_priority', 'current']:
            totals = {name: sum(d['coverage'][key][name] for d in members)
                      for name in ['spans', 'full', 'partial', 'not_delivered', 'union_chars', 'covered_union_chars']}
            totals['union_character_coverage'] = (totals['covered_union_chars']/totals['union_chars']
                                                 if totals['union_chars'] else None)
            groups[tag]['variants'][key] = totals

    # Separate already-described diagnostic case; added AFTER both selections.
    booking_probe = None
    from guardian_truth.parsing import parse_events
    for row in rows:
        if row['id'] == 'airline__24::t14':
            results = [e for e in parse_events(row['prompt'], 'prompt')
                       if e.kind == 'result' and e.name == 'book_reservation']
            if results:
                target = results[-1].source
                booking_probe = {'id': row['id'], 'span': [target.start, target.end],
                                 'derivation': 'Latest original book_reservation result; not used in selection or aggregate audit-span metrics.',
                                 'coverage': {k: coverage([(target.start, target.end)], v['spans'])
                                              for k, v in selections[row['id']].items()}}
    sources = [args.input, positive_path, unknown_path, audit_path, Path(__file__)]
    sources += [Path('src/guardian_truth')/name for name in
                ['reader.py', 'parsing.py', 'provenance.py', 'pipeline.py', 'semantic.py']]
    report = {'configuration': {'experiment': 'offline_initial_selection_feature_ablation',
                               'chunk_chars': 1800, 'max_evidence_chars': 4800,
                               'max_initial_chars': 12000, 'rolling': False, 'rows': len(rows),
                               'source_hashes': {str(p): sha(p) for p in sources}},
              'groups': groups,
              'changed_ids': [d['id'] for d in details if d['selection_changed']],
              'airline24_booking_probe': booking_probe, 'rows': details,
              'limitations': ['Feature ablation, not an exact historical reader implementation.',
                              'No API, model scores, predictions, F1, or causal quality gain are measured.',
                              'Audit spans are reviewer-selected, overlap, and are not complete gold evidence.',
                              'Spans deduplicated by id/start/end; character denominators use per-row union.',
                              'Subset tags overlap; their counts must not be summed.',
                              'Raw chunk exposure only; graph-summary exposure and semantic entailment are not measured.',
                              'All rows selected before annotations were loaded; annotations never rank sources.']}
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({'rows': len(rows), 'changed': len(report['changed_ids']), 'groups': groups,
                      'airline24_booking_probe': booking_probe}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
