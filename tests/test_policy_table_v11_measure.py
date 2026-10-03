"""Label-free checks of the V11 measurement harness. None of these tests read gold."""
import json
from pathlib import Path
import sys
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'experiments/searh_23/v11'))
measure = pytest.importorskip('measure')
from guardian_truth.parsing import parse_events
from guardian_truth.source_search.store import digest


def manifest():
    return json.loads(measure.MUTATIONS.read_text(encoding='utf-8'))


def test_old_direct_counts_match_historical_direct_arm():
    values = measure.old_direct()
    assert len(values) == 46
    assert sum(v == 'ERROR' for v in values.values()) == 15
    assert sum(v == 'NO_ERROR' for v in values.values()) == 31


def test_every_manifest_mutant_rematerializes_bit_exactly():
    originals = measure.inputs(); data = manifest()
    assert data['mutants']
    for spec in data['mutants']:
        mutated = measure.materialize(spec, originals)
        assert digest({k: mutated[k] for k in ('prompt', 'response')}) == spec['mutated_source_sha256']
        assert spec['mutated_source_sha256'] != spec['base_source_sha256']


def test_mutants_are_rebuilt_deterministically(tmp_path, monkeypatch):
    # The historical manifest remains immutable; stricter witnesses require a new version.
    monkeypatch.setattr(measure, 'MUTATIONS', tmp_path / 'manifest.json')
    measure.build_mutations(); before = measure.MUTATIONS.read_bytes()
    measure.build_mutations()
    assert measure.MUTATIONS.read_bytes() == before


def test_removal_drops_only_the_requested_events():
    row = next(iter(measure.inputs().values()))
    events = parse_events(row['prompt'], 'prompt')
    index = max(i for i, e in enumerate(events) if e.role == 'user' and e.kind == 'text')
    text = measure.remove_events(row['prompt'], 'prompt', [index])
    expected = [s for i, s in enumerate(measure.signature(events)) if i != index]
    assert measure.signature(parse_events(text, 'prompt')) == expected


def test_tampered_base_is_rejected():
    spec = dict(manifest()['mutants'][0]); spec['base_source_sha256'] = '0' * 64
    with pytest.raises(ValueError, match='base_changed'): measure.materialize(spec)


def test_annotations_are_policy_text_quotes_and_admissible_atoms():
    from prepare import groups
    from guardian_truth.policy_table.segment import clauses
    stores = groups()
    for key, spec in measure.annotations().items():
        text = {c['id']: c['text'] for c in clauses(stores[key][0])}
        policy = json.loads((measure.OUTPUT / (key + '.json')).read_text(encoding='utf-8'))
        for req in spec.get('requirements', []):
            assert req['clause_ids'] and all(req['quote'] in text[c] for c in req['clause_ids']), req['id']
            for tool in req['tools']:
                assert tool in policy['catalog']['tools'], (req['id'], tool)
                measure.annotation_atom(req, policy, tool)


def test_positive_mutants_have_held_premises_only():
    for spec in manifest()['mutants']:
        if spec['status'] == 'POSITIVE':
            assert spec['premises'] and all(p['holds'] for p in spec['premises'])
            assert all(p['control_value'] != 'UNRESOLVED' and not p['control_finding'] and p['mutant_finding']
                       for p in spec['premises'])


def test_score_refuses_unsealed_predictions_without_reading_gold(monkeypatch):
    opened = []
    real = Path.read_text
    def guarded(self, *a, **kw):
        if self.name == 'score.json': opened.append(self)
        return real(self, *a, **kw)
    monkeypatch.setattr(Path, 'read_text', guarded)
    monkeypatch.setattr(measure, 'committed', lambda path: False)
    with pytest.raises(ValueError, match='predictions_not_sealed_in_HEAD'): measure.score()
    assert not opened


def test_predict_requires_committed_final_freeze():
    if (measure.RUN / 'final_freeze.json').exists(): pytest.skip('final freeze present; predict is a sealed one-shot phase')
    before = measure.PREDICTIONS.exists()
    with pytest.raises(Exception): measure.predict()
    assert measure.PREDICTIONS.exists() == before


def test_missing_tables_remain_in_mutant_denominator():
    expected = sum(s['status'] == 'POSITIVE' for s in manifest()['mutants'])
    result = measure.measure_mutations({})['summary']
    assert result['positive_mutants'] == expected == 4
    assert result['missing_tables'] == 4 and result['recall_decisive'] == 0
