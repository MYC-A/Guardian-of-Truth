"""Technical tokenizer/cap check only. Never infer F1 or choose a prompt from valid46."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT)]
from guardian_truth.judge import answer_review as ar, blind_review as br
from guardian_truth.judge.mechanical import analyze
from guardian_truth.judge.prompting import count_tokens, question_margin, score_keys
from scripts.judge_stage import answer_ids, build_row
from scripts.judge_submission import normalize_profile, read_input


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config',type=Path,default=ROOT/'submission/JUDGE_OPEN_REVIEW40.json')
    p.add_argument('--model',type=Path,required=True)
    p.add_argument('--input',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    a=p.parse_args()
    cfg,error=normalize_profile(json.loads(a.config.read_text()))
    if error or cfg.get('review_content')!='answer_audit' or cfg['positive_rate']!=.4:
        raise ValueError('WRONG_PROFILE:'+str(error))
    s=br.validate_review_config(cfg)
    from transformers import AutoTokenizer
    tok=AutoTokenizer.from_pretrained(a.model,local_files_only=True)
    yes,no=answer_ids(tok)
    margin=question_margin(tok,score_keys(cfg))
    cap=cfg['max_model_len']-8-margin-s['review_input_reserve_tokens']
    records=[]
    for i,row in enumerate(read_input(a.input)):
        finding=analyze(row['prompt'],row['response'],cfg['hard_unknown_identifier'])
        row=dict(row,key=i,hints=finding.hints)
        base,n,trimmed,ptrim,context=build_row(tok,row,cap)
        pre=ar.prepare(tok,dict(text=base,trimmed=trimmed),s,cfg['max_model_len']-8)
        final,fn,delivery,reason=br.final_prompt(tok,base,'',cfg['max_model_len']-2-margin)
        assert n+1<=cfg['max_model_len'] and pre['n']+s['prepass_max_tokens']<=cfg['max_model_len']
        assert fn+1<=cfg['max_model_len']
        records.append(dict(position=i,primary_tokens=n,audit_tokens=pre['n'],final_without_notes_tokens=fn,
            primary_over_planned_cap=n>cap,trimmed=bool(trimmed),policy_trimmed=bool(ptrim),
            response_trimmed=row['response'] not in base,context=context,
            primary_sha256=br.sha(base),audit_sha256=br.sha(pre['text']),audit_token_sha256=br.token_sha(tok,pre['text']),
            final_sha256=br.sha(final)))
    out=dict(scope='TECHNICAL_ONLY_NO_MODEL_OR_LABEL_SELECTION',rows=len(records),cap=cap,margin=margin,
        input_sha256=hashlib.sha256(a.input.read_bytes()).hexdigest(),
        config_sha256=hashlib.sha256(a.config.read_bytes()).hexdigest(),yes_ids=sorted(yes),no_ids=sorted(no),
        trimmed=sum(r['trimmed'] for r in records),policy_trimmed=sum(r['policy_trimmed'] for r in records),
        response_trimmed=sum(r['response_trimmed'] for r in records),
        max_audit_tokens=max(r['audit_tokens'] for r in records),
        max_final_tokens=max(r['final_without_notes_tokens'] for r in records),
        generation_reserve=s['prepass_max_tokens'],max_model_len=cfg['max_model_len'],gpu_tested=False,records=records)
    a.out.write_text(json.dumps(out,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in out.items() if k!='records'},indent=2))


if __name__=='__main__':main()
