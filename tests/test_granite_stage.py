import json
import sys
import types

import pandas as pd
import pytest

from scripts import granite_stage as gs


def fake_vllm(monkeypatch, reverse=False):
    class Tok:
        def apply_chat_template(self, msgs, tokenize=False, add_generation_prompt=True, documents=()):
            return 'PROMPT:' + documents[0]['text']

        def __call__(self, text, add_special_tokens=False):
            return dict(input_ids=[0] * 10)

    class LLM:
        def __init__(self, **kwargs):
            pass

        def get_tokenizer(self):
            return Tok()

        def generate(self, prompts, sp, use_tqdm=False):
            out = [types.SimpleNamespace(prompt=p, outputs=[types.SimpleNamespace(
                text='yes' if p.endswith('hall') else 'no', logprobs=None, token_ids=[])]) for p in prompts]
            return out[::-1] if reverse else out
    module = types.ModuleType('vllm')
    module.LLM, module.SamplingParams = LLM, lambda **kw: None
    monkeypatch.setitem(sys.modules, 'vllm', module)


def run(tmp_path, n=7, chunk=3):
    data = pd.DataFrame(dict(id=['row%07d' % k for k in range(n)],
                             prompt=['ctx%d %s' % (k, 'hall' if k % 2 else 'ok') for k in range(n)],
                             response=['r'] * n))
    data.to_parquet(tmp_path / 'in.parquet', index=False)
    gs.main(['--model', 'm', '--input', str(tmp_path / 'in.parquet'), '--output', str(tmp_path / 'o.jsonl'),
             '--chunk', str(chunk)])
    lines = [json.loads(line) for line in (tmp_path / 'o.jsonl').read_text().splitlines()]
    return {r['id']: r['pred'] for r in lines if 'id' in r}


def test_labels_follow_rows_across_chunks(tmp_path, monkeypatch):
    fake_vllm(monkeypatch)
    assert run(tmp_path) == {'row%07d' % k: k % 2 for k in range(7)}


def test_reordered_outputs_are_rejected(tmp_path, monkeypatch):
    fake_vllm(monkeypatch, reverse=True)
    with pytest.raises(RuntimeError, match='GRANITE_OUTPUT_ORDER_MISMATCH'):
        run(tmp_path)
