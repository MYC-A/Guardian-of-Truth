import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from v4_natural_labels import classify,convert,safe_read

POLICY='You should not provide any information, knowledge, or procedures not provided by the user or available tools, or give subjective recommendations or comments.\nThe user must provide their user id.'
TOOLS=[dict(type='function',function=dict(name='get_user_details',parameters=dict(type='object',properties={'user_id':{'type':'string'}},required=['user_id'])))]


def target(name,args):return dict(role='assistant',content='',tool_calls=[dict(function=dict(name=name,arguments=args))])


def test_invented_tool_is_positive_but_user_supplied_unknown_id_is_not():
    h=[dict(id='m0',role='user',content='My user ID is unknown_123.')]
    assert classify('airline',POLICY,TOOLS,h,target('invented_tool',{}))[0]==1
    # Nonexistent entity is not itself a violation: user supplied it. Main
    # excludes this proposed read negative when actual execution reports error.
    assert classify('airline',POLICY,TOOLS,h,target('get_user_details',{'user_id':'unknown_123'}))[0]==0
    assert classify('airline',POLICY,TOOLS,h,target('get_user_details',{'user_id':'invented_456'})) is None


def test_user_owned_calls_and_results_retain_binding():
    raw=[dict(role='user',content='',tool_calls=[dict(id='c',name='device_read',arguments={})]),
         dict(role='tool',id='c',content='OK',requestor='user')]
    out=convert(raw)
    assert out[0]['role']=='user' and out[1]['name']=='device_read'


def test_unobserved_order_and_other_users_order_cannot_be_negative():
    h=[dict(role='user',content='a@example.com'),dict(role='tool',name='find_user_id_by_email',content='a'),
       dict(role='tool',name='get_user_details',content='{"user_id":"b","orders":["#W12345"]}')]
    assert not safe_read('retail',dict(name='get_order_details',arguments={'order_id':'#W12345'}),h)
