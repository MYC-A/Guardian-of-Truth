"""Execute the unchanged AUTHOR SelfCheckNLI class, without unused backends.

AST extraction removes import dependencies for MQAG/BERTScore, not the NLI
algorithm. Original binary DeBERTa checkpoint and pair ordering preserved.
"""
import ast
from pathlib import Path
from typing import List

AUTHOR_ROOT = Path('/workspace/guardian/third_party_modular_20261002/selfcheckgpt')
AUTHOR_REVISION = '19b492a2a380931bf1ed0ca94a9565c9aa7b03e1'


def load_native(model_path):
    import numpy as np
    import torch
    from transformers import DebertaV2Tokenizer, DebertaV2ForSequenceClassification
    source = AUTHOR_ROOT / 'selfcheckgpt/modeling_selfcheck.py'
    tree = ast.parse(source.read_text())
    nodes = [node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'SelfCheckNLI']
    if len(nodes) != 1:
        raise ValueError('author_class_not_found')
    namespace = {'np': np, 'torch': torch, 'List': List,
                 'DebertaV2Tokenizer': DebertaV2Tokenizer,
                 'DebertaV2ForSequenceClassification': DebertaV2ForSequenceClassification}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), 'exec'), namespace)
    instance = namespace['SelfCheckNLI'](nli_model=model_path, device=torch.device('cuda'))
    if instance.model.config.num_labels != 2:
        raise ValueError('native_SelfCheck_checkpoint_must_have_two_classes')
    return instance


def sample_bank(llm, model, messages, *, caller, json_mode=True, max_tokens=1400):
    if any(not isinstance(m.get('content'), str) for m in messages):
        raise ValueError('sample_message_content_must_be_string')
    return [llm.chat(model, messages, temperature=.7, seed=seed, max_tokens=max_tokens,
                     json_mode=json_mode, transport_retries=0, caller=caller + f'/seed{seed}')
            for seed in (19, 37, 53)]


def agreement(values):
    from collections import Counter
    import math
    valid = [v for v in values if v is not None]
    if not valid:
        return {'status': 'INSUFFICIENT', 'agreement': None, 'frequency_entropy': None}
    counts = Counter(valid)
    probs = [n / len(valid) for n in counts.values()]
    return {'status': 'SAMPLED_SIGNAL', 'agreement': max(probs),
            'frequency_entropy': -sum(p * math.log(p) for p in probs),
            'sample_count': len(valid), 'warning': 'Frequency over sampled labels is not hidden-state SEP or truth.'}
