"""V4 uses explicit production transcript headers, without changing old evidence."""
from v3_data import judge_input as v3_judge_input
from guardian_truth.judge.prompting import build_prompt, render


def judge_input(row):
    request=v3_judge_input(row)
    request['response']='\u27e6ASSISTANT \u00b7 \u0445\u043e\u0434 '+str(len(row['history'])+1)+'\u27e7\n'+request['response']
    return request


def training_text(tok,row,cap=32768):
    request=judge_input(row)
    plain=render(tok,request['prompt'],request['response'],[])
    production,count,trimmed,policy_trimmed=build_prompt(tok,request,cap)
    if trimmed or policy_trimmed or production!=plain or count>cap:
        raise ValueError('OVER_CAP_NO_SILENT_TRIMMING')
    return plain,count
