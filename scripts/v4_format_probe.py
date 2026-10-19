"""Versioned history-format probe, NOT the renderer of the running V4 job.

Keep source policy/tools/target and omit label/proof metadata. A tool result
continues its caller's message, rather than inventing an assistant message.
Reject ambiguous binding instead of moving an event or guessing its owner.
"""
import json
import re
from v3_data import canonical, turn_text


def judge_input(row):
    parts=['\u27e6SYSTEM\u27e7\n<policy>\n'+row['policy']+
        '\n</policy>\n[AVAILABLE TOOLS]\n'+canonical(row['tools'])+'\n']
    pending=[];last_role=None;turns=0
    for message in [*row['history'],row['target_turn']]:
        names=[c.get('function',c)['name'] for c in message.get('tool_calls',[])]
        if message['role']=='tool':names.append(message.get('name',''))
        if any(not re.fullmatch(r'[A-Za-z0-9_.-]+',name) for name in names):
            raise ValueError('UNSUPPORTED_ARROW_TOOL_NAME')
    for message in row['history']:
        role=message['role']
        if role=='tool':
            name=message.get('name');call_id=message.get('tool_call_id')
            matches=[c for c in pending if c['name']==name and (call_id is None or c['id']==call_id)]
            if len(matches)!=1:raise ValueError('AMBIGUOUS_OR_UNBOUND_RESULT')
            call=matches[0]
            if call['role']!=last_role:raise ValueError('RESULT_CROSSES_OWNER_MESSAGE')
            pending.remove(call)
            content=message.get('content') or ''
            if not isinstance(content,str):content=canonical(content)
            # Transport indentation prevents result text from becoming another
            # call, role header, or user-visible assistant message.
            content=content.replace('\r\n','\n').replace('\r','\n')
            lines=content.split('\n')
            parts.append('\t\u2190 TOOL_RESPONSE '+name+': '+lines[0]+
                ''.join('\n\t  '+line for line in lines[1:])+'\n')
            continue
        if role not in {'assistant','user'}:raise ValueError('UNSUPPORTED_HISTORY_ROLE')
        last_role=role;turns+=1
        parts.append('\u27e6'+role.upper()+'\u27e7\n'+turn_text(message)+'\n')
        for c in message.get('tool_calls',[]):
            f=c.get('function',c)
            pending.append(dict(name=f['name'],id=c.get('id'),role=role))
    if row['target_turn']['role']!='assistant':raise ValueError('NOT_ASSISTANT_TARGET')
    return dict(id=row['id'],prompt=''.join(parts),response='\u27e6ASSISTANT \u00b7 \u0445\u043e\u0434 '+str(turns+1)+
        '\u27e7\n'+turn_text(row['target_turn']),hints=[])


def inventory(frozen,out):
    """Check roundtrip against raw source events, not a potentially broken parser."""
    from collections import Counter
    import hashlib
    from pathlib import Path
    from guardian_truth.transcript import parse_document
    from v4_data import judge_input as old
    result={}
    for partition in ('train','dev','holdout'):
        records=[];counts=Counter()
        for line in (Path(frozen)/(partition+'.jsonl')).read_bytes().splitlines():
            row=json.loads(line);record=dict(id=row['id'])
            try:
                a=old(row);b=judge_input(row);ad=parse_document(a['prompt']);bd=parse_document(b['prompt'])
                expected=[];pending=[]
                for m in row['history']:
                    for c in m.get('tool_calls',[]):
                        f=c.get('function',c);args=f['arguments']
                        args=json.loads(args) if isinstance(args,str) else args
                        expected.append(('call',m['role'],f['name'],args));pending.append((m['role'],f['name']))
                    if m['role']=='tool':
                        binding=[c for c in pending if c[1]==m['name']]
                        assert len(binding)==1,'SOURCE_BINDING_AMBIGUOUS'
                        owner,name=binding[0];pending.remove(binding[0]);content=m.get('content') or ''
                        content=content if isinstance(content,str) else canonical(content)
                        content=content.replace('\r\n','\n').replace('\r','\n').strip()
                        try:
                            value=json.loads(content)
                            value=value if isinstance(value,(dict,list)) else content
                        except ValueError:value=content
                        expected.append(('result',owner,name,value))
                signature=lambda d:[(e.kind,e.owner,e.tool,e.value if e.is_json else e.body)
                    for e in d.events if e.kind in {'call','result'}]
                assert signature(bd)==expected,'SOURCE_ROUNDTRIP_FAILED'
                target=parse_document(b['response'],'response')
                assert len(target.messages)==1 and not target.diagnostics,'BAD_CURRENT_TARGET'
                assert b['response'].split('\n',1)[1]==a['response'].split('\n',1)[1],'TARGET_BODY_DRIFT'
                counts['converted']+=1
                counts['old_event_content_differs_from_source']+=signature(ad)!=expected
                for key,doc in [('old',ad),('new',bd)]:
                    counts[key+'_result_role_owner_mismatch_rows']+=any(e.owner!=e.role for e in doc.results())
                for key,request in [('old',a),('new',b)]:
                    record[key+'_sha256']=hashlib.sha256((request['prompt']+'\0'+request['response']).encode()).hexdigest()
            except (ValueError,AssertionError) as error:
                counts['rejected']+=1;record['error']=str(error) or type(error).__name__
            records.append(record)
        result[partition]=dict(counts=counts,rows=records)
    Path(out).write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    return {k:v['counts'] for k,v in result.items()}


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--frozen',required=True);p.add_argument('--out',required=True)
    args=p.parse_args();print(json.dumps(inventory(args.frozen,args.out)))
