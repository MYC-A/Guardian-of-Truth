"""Build a bounded TRAIN-only SFT corpus from visible native observations.

Never use future native execution results or mutation predicates as explanations.
Source audit checks constructor labels separately. No evaluation labels select rows.
"""
import argparse
from collections import Counter
import copy
import hashlib
import json
from pathlib import Path
import re
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'src'),str(ROOT/'scripts')]
from scripts.v5_35b_common import read,sha,write,verify_frozen,BASE_REVISION
from scripts.v13_native_mining import select,paired


def restored(row):
    inverse={v:k for k,v in row.get('alias_map',{}).items()}
    if not inverse:return copy.deepcopy(row)
    pattern=re.compile(r'(?<![A-Za-z0-9_])(?:'+'|'.join(re.escape(k) for k in sorted(inverse,key=lambda k:(-len(k),k)))+r')(?![A-Za-z0-9_])')
    def walk(v):
        if isinstance(v,str):return pattern.sub(lambda m:inverse[m.group()],v)
        if isinstance(v,list):return [walk(x) for x in v]
        if isinstance(v,dict):return {inverse.get(k,k):walk(x) for k,x in v.items()}
        return v
    return walk(row)


def visible_evidence(original):
    """Pure function of policy-visible history/current turn, not labels or proofs."""
    from scripts.v4_natural_labels import observations
    r=restored({k:original[k] for k in ('history','target_turn','family','domain','alias_map') if k in original})
    obs=observations(r['history']);family=r['family'];target=r['target_turn']
    def last(name):return next(v for n,v in reversed(obs) if n==name)
    current=(target.get('tool_calls') or [{}])[0].get('function',{})
    args=current.get('arguments',{});facts={}
    if family in ('consent','consent_binding','reason_binding','compensation'):
        users=[m['content'] for m in r['history'] if m['role']=='user'];facts['last_user']=users[-1]
    if family in ('consent','consent_binding'):
        approvals=[m['content'] for m in r['history'] if m['role']=='user' and m['content'].startswith('Yes,')]
        facts['prior_authorization']=approvals[-1] if approvals else None
        facts['current_arguments']=(original['target_turn'].get('tool_calls') or [{}])[0].get('function',{}).get('arguments',{})
    elif family=='reason_binding':facts['current_reason']=args['reason']
    elif family=='order_status':
        actual=(original['target_turn'].get('tool_calls') or [{}])[0].get('function',{})
        facts.update(observed_status=last('get_order_details')['status'],operation=actual['name'])
    elif family=='unsupported_fact':
        stated=json.loads(target['content']);k=next(iter(stated))
        facts.update(stated=json.loads(original['target_turn']['content']),last_observed_value=next(v[k] for _,v in reversed(obs) if isinstance(v,dict) and k in v))
    elif family=='modify_scope':
        order=last('get_order_details');old=next(i for i in order['items'] if i['item_id']==args['item_ids'][0])
        product=next(v for n,v in obs if n=='get_product_details' and v['product_id']==old['product_id'])
        facts.update(order_status=order['status'],old_item_ids=args['item_ids'],new_item_ids=args['new_item_ids'],
            same_number_of_items=len(args['item_ids'])==len(args['new_item_ids']),
            all_replacements_available_in_original_product=all(i in product['variants'] and product['variants'][i]['available'] for i in args['new_item_ids']))
    elif family=='refund_method':
        order=last('get_order_details');profile=last('get_user_details');pid=args['payment_method_id']
        facts.update(order_status=order['status'],requested_payment_method=pid,original_payment_method=order['payment_history'][0]['payment_method_id'],
            requested_method_source=profile['payment_methods'][pid]['source'])
    elif family=='completion_without_result':
        facts.update(last_observed_order_status=last('get_order_details')['status'],
            current_turn_kind='tool_call' if target.get('tool_calls') else 'user_facing_message',
            current_message=target.get('content') or '')
    elif family=='cancellation_eligibility':
        res=last('get_reservation_details');facts.update(created_at=res['created_at'],cabin=res['cabin'],insurance=res['insurance'],
            observed_flight_statuses=[v for n,v in obs if n=='get_flight_status'])
    elif family in ('flight_change','basic_cabin_change'):
        res=last('get_reservation_details')
        facts.update(original_cabin=res['cabin'],requested_cabin=args['cabin'],
            flights_changed=[(v['flight_number'],v['date']) for v in args['flights']]!=[(v['flight_number'],v['date']) for v in res['flights']])
    elif family=='compensation':
        res=last('get_reservation_details');profile=last('get_user_details')
        facts.update(membership=profile['membership'],insurance=res['insurance'],cabin=res['cabin'],
            observed_flight_statuses=[v for n,v in obs if n=='get_flight_status'],requested_amount=args['amount'],passengers=len(res['passengers']))
    elif family not in ('consent','consent_binding','reason_binding'):
        raise ValueError('UNSUPPORTED_VISIBLE_EVIDENCE_FAMILY:'+family)
    return 'Visible current-turn and history facts: '+json.dumps(facts,sort_keys=True,ensure_ascii=True,separators=(',',':'))


def run(a):
    from transformers import AutoTokenizer
    from scripts.v6_verifier_data import source_audit
    from scripts.v5_35b_prepare import encode
    from scripts.v7_prepare import reasoning_text,dump
    from scripts.v8_quote_contract import admit_review
    from scripts.v14_role_contrasts import audit_row
    a.out.mkdir(parents=True,exist_ok=False)
    frozen=a.lab/'v4-20261019/frozen-v2';verify_frozen(frozen)
    mine=a.lab/'v13-native-mining-20261020/mining-v1';meta=json.loads((mine/'DONE.json').read_bytes())
    result=json.loads((mine/'RESULTS.json').read_bytes())
    if not meta['complete'] or sha(mine/'RESULTS.json')!=meta['results_sha256'] or sha(mine/'scores.jsonl')!=result['scores_sha256']:raise ValueError('MINING_DRIFT')
    scores={r['id']:r['score'] for r in read(mine/'scores.jsonl')}
    v7=a.lab/'v7-workflow-20261020/prepared-v1';old=json.loads((v7/'PREPARED.json').read_bytes())
    if sha(v7/'replay_tokens.jsonl')!=old['replay_tokens_sha256']:raise ValueError('REPLAY_DRIFT')
    replay=read(v7/'replay_tokens.jsonl');assert len(replay)==32
    replay_ids={r['id'] for r in replay};replay_pairs={r.get('pair_id') for r in replay if r.get('pair_id')}
    tok=AutoTokenizer.from_pretrained(a.lab/'models/qwen36-awq',local_files_only=True)
    originals={r['id']:r for r in read(frozen/'train.jsonl')}
    accepted=[];tokens={};teachers={};reject=[]
    def encoded(row,rationale):
        review=rationale.split('\nVerdict:')[0]
        ok,status,support=admit_review(review,row['policy'])
        if not ok:raise ValueError('TEACHER_SOURCE:'+status)
        if len(tok.encode(review,add_special_tokens=False))>176:raise ValueError('REVIEW_WOULD_EXCEED_192_TOKEN_BUDGET')
        _,base=encode(tok,row);text=tok.decode(base['ids'],skip_special_tokens=False)
        prompt=reasoning_text(text);ids=tok.encode(prompt,add_special_tokens=False);allids=tok.encode(prompt+rationale,add_special_tokens=False)
        if allids[:len(ids)]!=ids or len(allids)>49144:raise ValueError('ANSWER_BOUNDARY_OR_CAP')
        return dict(id=row['id'],ids=ids,answer_ids=allids[len(ids):],tokens=len(allids),label=row['label'],
            pair_id=row['pair_id'],domain=row['domain'],family=row['family'],template_id=row['template_id'],objective='sft',
            text_sha256=hashlib.sha256(prompt.encode()).hexdigest(),rationale_sha256=hashlib.sha256(rationale.encode()).hexdigest())
    index=read(a.lab/'v13-native-mining-20261020/prepared-v2/TRAIN_INDEX.jsonl')
    for pair in paired(index):
        if any(r['id'] in replay_ids or r['pair_id'] in replay_pairs for r in pair):continue
        if pair[0]['family']=='turn_shape':continue # already handled by exact code
        batch=[]
        try:
            for item in pair:
                row=originals[item['id']];source_audit(row)
                rationale='Rule: '+' '.join(row['governing_rule'].split())+'\nEvidence: '+visible_evidence(row)+'\nVerdict: '+('YES' if row['label'] else 'NO')
                batch.append(encoded(row,rationale))
                teachers[row['id']]=rationale
        except Exception as e:reject.append(dict(pair_id=pair[0]['pair_id'],reason=str(e)));continue
        accepted.extend(pair);tokens.update({r['id']:r for r in batch})
    chosen=select(accepted,scores)[:128]
    chosen=chosen[:len(chosen)//8*8] # retain complete pairs and full effective batches
    native=[tokens[r['id']] for r in chosen]
    hard_negatives=sum(not r['label'] and scores[r['id']]>0 for r in chosen)
    if hard_negatives<16:raise ValueError('FEWER_THAN_16_NATIVE_TRAIN_FALSE_ACCUSATIONS_NO_UNDIRECTED_TRAINING')
    roles=a.lab/'v14-native-role-data-20261020/data-v1';rm=json.loads((roles/'DONE.json').read_bytes())
    if sha(roles/'train.jsonl')!=rm['files']['train.jsonl']:raise ValueError('ROLE_DATA_DRIFT')
    role=[]
    for row in read(roles/'train.jsonl'):
        if row['proposed_split']!='train':raise ValueError('ROLE_HOLDOUT_IN_TRAIN')
        audit_row(row);role.append(encoded(row,row['rationale']))
        teachers[row['id']]=row['rationale']
    if len(role)!=16 or len(native)<64:raise ValueError('INSUFFICIENT_SOURCE_CHECKED_SFT_NO_FILL')
    records=native+role+replay
    if len({r['id'] for r in records})!=len(records) or len(records)%8:raise ValueError('DUPLICATE_OR_PARTIAL_BATCH')
    for r in replay:r['objective']='bce'
    dump(a.out/'train_tokens.jsonl',records)
    dump(a.out/'RATIONALE_AUDIT.jsonl',[dict(id=r['id'],rationale=teachers[r['id']]) for r in native+role])
    write(a.out/'SOURCE_AUDIT.json',dict(native_sft=len(native),new_native_role_sft=len(role),replay_bce=32,rejected_pairs=reject,
        family_counts={str(k):v for k,v in Counter((r['domain'],r['family']) for r in native+role).items()},
        selected_native_fp=hard_negatives,
        future_execution_results_used_in_rationale=False,mutation_predicates_used_in_rationale=False,
        native_source_repetition_is_not_new_data=True,unavailable_human_review_not_replaced=True))
    write(a.out/'DONE.json',dict(complete=True,recipe='V15_NATIVE_RATIONALE_V1',rows=len(records),sft_rows=len(native)+16,replay_bce_rows=32,
        base_revision=BASE_REVISION,train_tokens_sha256=sha(a.out/'train_tokens.jsonl'),answer_ids=old['answer_ids'],
        source_sha256=sha(Path(__file__)),source_train_sha256=sha(frozen/'train.jsonl'),mining_scores_sha256=sha(mine/'scores.jsonl'),
        role_train_sha256=sha(roles/'train.jsonl'),role_holdout_sha256=sha(roles/'holdout.jsonl'),
        tokens=sum(r['tokens'] for r in records),max_tokens=max(r['tokens'] for r in records),eval_used=False,
        human_reviewed=False,status='EXPLORATORY_ONLY_HUMAN_UNVERIFIED'))


if __name__=='__main__':
    p=argparse.ArgumentParser()
    for k in ('lab','out'):p.add_argument('--'+k,type=Path,required=True)
    run(p.parse_args())
