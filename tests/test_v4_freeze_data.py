import copy
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from v4_freeze_data import alias_pair,stable
from v4_data import judge_input
from jsonschema import Draft202012Validator


def test_aliases_rename_argument_name_but_preserve_schema_and_message_structure():
    key=next(str(i) for i in range(100) if int(stable('rename:'+str(i))[:8],16)/2**32<.30)
    row=dict(id='row',pair_id=key,policy='Use lookup with id and name.',governing_rule='Use lookup with id and name.',
        tools=[dict(type='function',function=dict(name='lookup',parameters=dict(type='object',properties={
            'id':dict(type='string'),'name':dict(type='string')},required=['id','name'],additionalProperties=False)))],
        history=[dict(id='m0',role='user',content='The requested id is resource_123.')],
        target_turn=dict(role='assistant',content='',tool_calls=[dict(function=dict(name='lookup',arguments={'id':'resource_123','name':'Alice'}))]))
    original=copy.deepcopy(row);changed=alias_pair([row])[0];mapping=changed['alias_map']
    assert row==original
    assert changed['history'][0]['id']=='m0' and changed['history'][0]['role']=='user'
    tool=changed['tools'][0]['function'];f=changed['target_turn']['tool_calls'][0]['function']
    assert tool['name']==f['name']==mapping['lookup']
    assert set(tool['parameters']['properties'])=={mapping['id'],mapping['name']}
    assert not list(Draft202012Validator(tool['parameters']).iter_errors(f['arguments']))
    assert f['arguments'][mapping['id']]=='resource_123'
    assert changed['governing_rule'] in changed['policy']
    assert 'alias_map' not in str(judge_input(changed))
