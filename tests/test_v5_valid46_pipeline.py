import json
from types import SimpleNamespace
import pytest
from scripts.v5_valid46_pipeline import bound_llm, validate_arm, pipeline_config


def test_best_zip_profile_is_preserved_with_explicit_technical_overrides():
    cfg = pipeline_config('/model')
    assert cfg['max_num_seqs'] == 64 and cfg['max_num_batched_tokens'] == 16384
    assert cfg['positive_rate'] == .4 and cfg['judge_stop_seconds'] == 1380
    assert cfg['review_ranking'] == 'max_exact' and cfg['bounded_turn_shape']
    assert cfg.get('review_citation_contract', 'legacy') == 'legacy'
    assert 'ensemble' not in cfg
    assert cfg['engine_overrides'] == dict(enforce_eager=True, async_scheduling=False)


@pytest.mark.parametrize('adapter_request', [None, object()])
def test_all_score_and_review_generations_are_bound_to_one_arm(tmp_path, adapter_request):
    class Fake:
        def __init__(self, **kwargs): self.kwargs = kwargs; self.seen = []
        def generate(self, prompts, params, **kwargs):
            self.seen.append(kwargs['lora_request']); return [object() for _ in prompts]
    p = tmp_path / 'audit.jsonl'
    llm = bound_llm(Fake, adapter_request, p)(max_num_seqs=16, enable_prefix_caching=True)
    for tokens in (1, 384, 1):
        llm.generate(['MODEL_SOURCE'], SimpleNamespace(max_tokens=tokens), use_tqdm=False)
    assert all(x is adapter_request for x in llm.seen)
    assert llm.kwargs['max_num_seqs'] == 16 and llm.kwargs['enable_prefix_caching']
    assert llm.kwargs['enable_lora'] and llm.kwargs['max_lora_rank'] == 16
    assert [x['max_tokens'] for x in map(json.loads, p.read_text().splitlines())] == [1, 384, 1]
    assert 'MODEL_SOURCE' not in p.read_text()
    with pytest.raises(ValueError, match='NESTED_LORA'):
        llm.generate(['source'], SimpleNamespace(max_tokens=1), lora_request=object())


def test_full_overall_coverage_cannot_hide_missing_final_score(tmp_path):
    work = tmp_path / 'work'; work.mkdir()
    records = [dict(key=i, score=float(i), exact=True) for i in range(46)]
    records += [dict(key=i, review='final', final_score=float(i), exact=True) for i in range(45)]
    records += [dict(event='done')]
    (work / 'scores.jsonl').write_text('\n'.join(map(json.dumps, records)))
    with pytest.raises(ValueError, match='INCOMPLETE_EXACT_PIPELINE_COVERAGE'):
        validate_arm(tmp_path, 'base', [dict(id=str(i)) for i in range(46)])


def test_failed_worker_binding_blocks_adapter_arm(tmp_path):
    class Fake:
        def __init__(self, **kwargs): pass
        def generate(self, prompts, params, **kwargs): return [object()]
        def collective_rpc(self, method, **kwargs):
            return [dict(complete=False, expected_modules=50)]
    llm = bound_llm(Fake, object(), tmp_path / 'audit.jsonl', binding_adapter=tmp_path)()
    with pytest.raises(ValueError, match='UNRECOGNIZED_ADAPTER_BINDING_FAILURE'):
        llm.generate(['probe'], SimpleNamespace(max_tokens=1))
    assert (tmp_path / 'ADAPTER_BINDING_BEFORE.json').exists()
    assert not (tmp_path / 'audit.jsonl').exists()


def test_shared_alias_repair_requires_successful_recheck_and_repeats_probe(tmp_path):
    class Fake:
        def __init__(self, **kwargs): self.calls = 0; self.rpc_calls = 0
        def generate(self, prompts, params, **kwargs): self.calls += 1; return [self.calls]
        def collective_rpc(self, method, **kwargs):
            self.rpc_calls += 1
            if self.rpc_calls == 1:
                return [dict(complete=False, expected_modules=50, errors=[
                    'GPU_WEIGHT_MISMATCH:language_model.model.layers.32.mlp.shared_expert.down_proj'])]
            if self.rpc_calls == 2: return [dict(complete=True, removed_count=16)]
            return [dict(complete=True, expected_modules=50, errors=[])]
    llm = bound_llm(Fake, object(), tmp_path / 'audit.jsonl', binding_adapter=tmp_path)()
    assert llm.generate(['probe'], SimpleNamespace(max_tokens=1)) == [2]
    assert llm.generate(['quality'], SimpleNamespace(max_tokens=384)) == [3]
    assert llm.rpc_calls == 3
    assert json.loads((tmp_path / 'audit.jsonl').read_text().splitlines()[0])['extra_technical_probe_prompts'] == 1
