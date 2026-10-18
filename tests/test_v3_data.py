import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from v3_data import judge_input, training_text, validate
from guardian_truth.judge.prompting import build_prompt


class Tokenizer:
    def apply_chat_template(self, messages, **kwargs):
        return json.dumps(messages, ensure_ascii=False) + '<assistant>'

    def __call__(self, text, **kwargs):
        return {'input_ids': list(text.encode())}


def example():
    return dict(id='test', source='fixture', source_revision='a'*40, domain='fixture',
                family='tool_args', scenario_id='scenario', group_id='group', pair_id='pair',
                policy='Only use supported tool arguments.', tools=[], history=[
                    dict(id='m0', role='user', content='Read order17.')],
                target_turn=dict(role='assistant', content='', tool_calls=[
                    dict(name='read_order', arguments={'order_id':'17'})]),
                label=0, violation_type='none', governing_rule='Only use supported tool arguments.',
                evidence_msg_ids=['m0'], label_origin='upstream', is_hard_negative=False,
                n_tokens=0, license='MIT')


def test_training_and_production_share_exact_rendered_text():
    row=validate(example());tok=Tokenizer()
    trained,n=training_text(tok,row)
    production,count,trimmed,policy_trimmed=build_prompt(tok,judge_input(row),32768)
    assert trained.encode()==production.encode() and n==count and not trimmed and not policy_trimmed


def test_annotations_do_not_change_model_input():
    row=example();other=copy.deepcopy(row)
    other.update(label=1,violation_type='tool_args',governing_rule='forged gold',label_origin='human',
                 evidence_msg_ids=['gold secret'],is_hard_negative=True,rationale='future label')
    assert judge_input(row)==judge_input(other)


def test_over_cap_is_rejected_instead_of_truncated():
    row=example()
    with pytest.raises(ValueError,match='NO_SILENT_TRIMMING'):
        training_text(Tokenizer(),row,cap=10)
