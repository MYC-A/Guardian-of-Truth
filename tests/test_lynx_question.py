import pytest
from experiments.guardian_local_a100 import lynx_native_v2 as native
from experiments.guardian_local_a100.lynx_question import question_request


def test_only_question_changes_and_latest_actual_user_is_addressed():
    row = dict(prompt='⟦USER⟧\nOld question\n⟦ASSISTANT⟧\nOld answer\n⟦USER⟧\nInspect REC-17.\n',
               response='Current answer. -- DOCUMENT: literal delimiter')
    document = 'Exact evidence with -- QUESTION: embedded delimiter.'
    original = dict(model='lynx',max_tokens=600,temperature=0,
                    messages=native.messages(document,'What does the document say?',row['response']))
    request, source = question_request(row,original)
    question = row['prompt'][source['start']:source['end']]
    assert question.strip() == 'Inspect REC-17.'
    assert request['messages'] == native.messages(document,question,row['response'])
    assert original['messages'] == native.messages(document,'What does the document say?',row['response'])


def test_missing_user_and_changed_answer_are_explicit_errors():
    original = dict(model='lynx',max_tokens=600,messages=native.messages('doc','What does the document say?','old'))
    with pytest.raises(ValueError,match='NO_PARSED_USER'):
        question_request(dict(prompt='⟦SYSTEM⟧\nPolicy',response='old'),original)
    with pytest.raises(ValueError,match='WITNESS_ANSWER_CHANGED'):
        question_request(dict(prompt='⟦USER⟧\nQuestion',response='new'),original)
