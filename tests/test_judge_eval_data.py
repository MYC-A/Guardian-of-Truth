"""Protect gold isolation, temporal boundaries and reproducible family partitions."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from scripts.prepare_judge_eval_data_20261018 import (
    compli_rows, make_split, near_pairs, select_pilot, write_set,
)
from guardian_truth.transcript import parse_document
from scripts.eval_judge_valid import read_labels_sidecar


def fixture():
    return dict(intent_name='refund', assistant_guidelines={
        'Category 1: Universal Compliance': {'tone': 'Keep a friendly tone.'},
        'Category 2: Intent Triggered Guidelines': {'refund': {'Phase 1': 'Ask for the order ID.'}},
        'Category 3: Condition Triggered Guidelines': {'exception': 'Transfer only on request.'}},
        message_list=[dict(turn_index=0, role='user', content='Hello'),
            dict(turn_index=1, role='assistant', content='Order ID?', category='Category 2', key='refund', phase=1,
                 guideline_text='ANNOTATION_CANARY'),
            dict(turn_index=2, role='user', content='FUTURE_CANARY')],
        mistakes=[], assistant_guidelines_shuffled={'wrong': 'MODIFIED_CANARY'},
        persona={'private': 'PERSONA_CANARY'}, violation_directives=['GOLD_CANARY'])


class EvalDataTests(unittest.TestCase):
    def test_gold_and_future_never_rendered(self):
        doc = fixture()
        row = compli_rows(doc, 'data/airlines/c.json', 'sha', 'group')[0]
        text = row['prompt']+row['response']
        for forbidden in ('ANNOTATION_CANARY', 'FUTURE_CANARY', 'MODIFIED_CANARY', 'PERSONA_CANARY', 'GOLD_CANARY'):
            self.assertNotIn(forbidden, text)
        changed = copy.deepcopy(doc)
        changed['mistakes'] = [dict(turn_index=1, evidence='LABEL_CANARY')]
        other = compli_rows(changed, 'data/airlines/c.json', 'sha', 'group')[0]
        self.assertEqual((row['prompt'], row['response']), (other['prompt'], other['response']))
        self.assertEqual((row['label'], other['label']), (0, 1))

    def test_actual_parser_and_response_boundary(self):
        row = compli_rows(fixture(), 'data/airlines/c.json', 'sha', 'group')[0]
        parsed = parse_document(row['prompt'])
        self.assertEqual([m.role for m in parsed.messages], ['system', 'user'])
        self.assertNotIn('Order ID?', row['prompt'])
        self.assertEqual([m.role for m in parse_document(row['response']).messages], ['assistant'])

    def test_invalid_or_missing_gold_rejected(self):
        doc = fixture(); doc['mistakes'] = [dict(turn_index=0)]
        with self.assertRaises(ValueError):
            compli_rows(doc, 'data/a/c.json', 'sha', 'group')
        doc = fixture(); del doc['message_list'][1]['category']
        with self.assertRaises(ValueError):
            compli_rows(doc, 'data/a/c.json', 'sha', 'group')

    def test_all_workflows_and_turns_share_family_split(self):
        docs = [('data/airlines/c%d.json' % i, dict(intent_name='i'+str(i//2))) for i in range(12)]
        groups, split = make_split(docs, [], inspected=['compli:airlines:i2'])
        self.assertEqual(split['compli:airlines:i2'], 'dev')
        for i in range(0, 12, 2):
            self.assertEqual(groups[docs[i][0]], groups[docs[i+1][0]])
        self.assertEqual((groups, split), make_split(list(reversed(docs)), [], inspected=['compli:airlines:i2']))

    def test_near_clones_merge_families(self):
        a = fixture(); b = copy.deepcopy(a); b['intent_name'] = 'different'
        docs = [('data/airlines/a.json', a), ('data/airlines/b.json', b)]
        pairs = near_pairs(docs)
        self.assertEqual(len(pairs), 1)
        docs += [('data/airlines/x%d.json' % i, dict(intent_name='other'+str(i))) for i in range(4)]
        groups, _ = make_split(docs, pairs)
        self.assertEqual(groups['data/airlines/a.json'], groups['data/airlines/b.json'])

    def test_pilot_label_blind_and_one_per_conversation(self):
        rows = [dict(id=str(i), conversation=str(i//2), prompt='a'*(i+1), response='b', label=i%2) for i in range(64)]
        selected = select_pilot(rows)
        self.assertEqual(len(selected), 24)
        self.assertEqual(len({r['conversation'] for r in selected}), 24)
        flipped = [dict(r, label=1-r['label']) for r in rows]
        self.assertEqual([r['id'] for r in selected], [r['id'] for r in select_pilot(flipped)])

    def test_labels_sidecar_and_lf_only_jsonl(self):
        row = compli_rows(fixture(), 'data/airlines/c.json', 'sha', 'group')[0]
        row['response'] += '\u2028\u2029\u0085'
        row['upstream_annotation'] = dict(evidence='x\u2028y\u2029z\u0085')
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder); write_set(out, 'x', [row], 'test')
            raw = (out/'x/labels.jsonl').read_bytes()
            self.assertEqual(len(raw.splitlines()), 1)
            self.assertIn(b'\\u2028', raw)
            self.assertEqual(json.loads(raw)['position'], 0)
            self.assertEqual((out/'x/inputs.csv').read_text(encoding='utf-8').splitlines()[0], 'id,prompt,response')

    def test_sidecar_literal_duplicate_ids_and_misalignment(self):
        rows = [dict(id=' 01 '), dict(id=' 01 ')]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'labels.jsonl'
            records = [dict(position=0, id=' 01 ', label=1), dict(position=1, id=' 01 ', label=0)]
            path.write_text('\n'.join(json.dumps(r) for r in records)+'\n', encoding='utf-8')
            self.assertEqual(read_labels_sidecar(path, rows), [1, 0])
            records.reverse()
            path.write_text('\n'.join(json.dumps(r) for r in records)+'\n', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'POSITION_ID'):
                read_labels_sidecar(path, rows)

    def test_sidecar_rejects_changed_source_under_same_id(self):
        row = compli_rows(fixture(), 'data/airlines/c.json', 'sha', 'group')[0]
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder); write_set(out, 'x', [row], 'test')
            path = out/'x/labels.jsonl'
            self.assertEqual(read_labels_sidecar(path, [row]), [0])
            changed = dict(row, prompt=row['prompt']+'different history')
            with self.assertRaisesRegex(ValueError, 'SOURCE_PAIR'):
                read_labels_sidecar(path, [changed])


if __name__ == '__main__':
    unittest.main()
