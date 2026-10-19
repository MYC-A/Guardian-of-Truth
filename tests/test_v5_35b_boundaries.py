import copy
import json
from pathlib import Path
import pytest
from scripts.v5_35b_common import target_names, target_suffixes
from scripts.v5_35b_prepare import source_request
from scripts.v5_35b_train import check_gate


def test_language_tower_and_layer_boundaries():
    names = ['model.language_model.layers.%d.%s' % (i, suffix) for i in range(40) for suffix in
             ('self_attn.q_proj', 'linear_attn.in_proj_qkv', 'mlp.shared_expert.gate_proj', 'mlp.experts.0.gate_proj')]
    names += ['model.visual.layers.39.self_attn.q_proj', 'mtp.language_model.layers.39.self_attn.q_proj']
    found = target_names(names, 8, True)
    assert len(found) == 24
    assert all('.experts.' not in n and '.visual.' not in n and not n.startswith('mtp.') for n in found)
    assert len(target_names(names[:-1], 8, False)) == 16
    assert 'in_proj_a' not in target_suffixes(True)


def test_gold_and_provenance_do_not_enter_training_request():
    row = dict(id='example', policy='Follow the tool schema.', tools=[], history=[],
               target_turn=dict(role='assistant', content='Hello'), label=0, rationale='SECRET_GOLD',
               violation_type='none', provenance='SECRET_SOURCE')
    other = copy.deepcopy(row)
    other.update(label=1, rationale='DIFFERENT_GOLD', violation_type='error', provenance='DIFFERENT_SOURCE')
    assert source_request(row) == source_request(other)
    assert 'SECRET_' not in str(source_request(row))


def test_training_refuses_missing_native_activation_proof(tmp_path):
    from scripts.v5_35b_common import sha
    pilot = tmp_path / 'pilot.json'
    native = tmp_path / 'native.json'
    pilot.write_text(json.dumps(dict(complete=True, optimizer_updates=0, technical_feasible=True)))
    native.write_text(json.dumps(dict(complete=True, nonzero_adapter_binding_proven=False)))
    gate = tmp_path / 'gate.json'
    gate.write_text(json.dumps(dict(layers=40, shared=True, train_tokens_sha256='data',
        pilot=dict(path=str(pilot), sha256=sha(pilot)), native=dict(path=str(native), sha256=sha(native)))))
    with pytest.raises(ValueError, match='NATIVE_ADAPTER_BINDING_NOT_PROVEN'):
        check_gate(gate, dict(train_tokens_sha256='data'), 40, True)
    native.write_text('{}')
    with pytest.raises(ValueError, match='GATE_RECEIPT_DRIFT'):
        check_gate(gate, dict(train_tokens_sha256='data'), 40, True)
