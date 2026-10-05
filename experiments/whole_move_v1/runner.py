"""Frozen matched whole-move diagnostic; original inputs never shortened.

Old/new reviewer see identical FULL source packets; mechanical findings form a
separately reported variant. Gold is confined to selection/evaluation sidecars.
"""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess

from experiments.evidence_packer_v2.llm_eval import rows, review_packet
from experiments.hybrid_mechanisms.interfaces import body as baseline_body
from experiments.hybrid_mechanisms.transport import Client, read, save, serialized, bound, preflight
from experiments.retrieval_bakeoff_v1.runner import decode
from guardian_truth.evidence_packer import pack, resolve, PackerConfig
from guardian_truth.parsing import decode_json
from guardian_truth.source_search.store import digest
from . import fixtures, mechanical, reviewer

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'outputs/whole_move_v1'
MODEL = 'ministral-14b-2512'
MAX_OUTPUT = 3600


def fingerprint(path, binary=False):
    data = Path(path).read_bytes()
    return hashlib.sha256(data if binary else data.replace(b'\r\n', b'\n')).hexdigest()


def code_hashes():
    paths = list((ROOT/'src/guardian_truth').rglob('*.py'))
    for directory in ('experiments/whole_move_v1', 'experiments/hybrid_mechanisms',
                      'experiments/retrieval_bakeoff_v1', 'experiments/evidence_packer_v2'):
        paths += list((ROOT/directory).glob('*.py'))
    paths += [ROOT/'experiments/research_v3/pilot.py']
    return {p.relative_to(ROOT).as_posix(): fingerprint(p) for p in sorted(set(paths))}


def full_packet(row):
    source = {k: row[k] for k in ('prompt', 'response')}
    p = pack(source, PackerConfig(budget_bytes=None))
    resolve(p, source)
    if p.get('failure') or p.get('mode') != 'FULL_INPUT':
        raise ValueError('FULL_PACKET_REQUIRED')
    return review_packet(p, True)


def prepare():
    if (OUT/'protocol.json').exists():
        verify(); print('ALREADY_FROZEN'); return
    if os.environ.get('PYTHONHASHSEED') != '0':
        raise ValueError('HASH_SEED_0_REQUIRED')
    # These six are previously examined diagnostic cases, not a hidden test.
    selection = read(ROOT/'outputs/retrieval_corrections_v2/selection_eval_only.json')
    ids = [s['id'] for s in selection if s['cohort'] == 'valid_known']
    real = {r['id']: r for r in rows()}
    inputs = [dict(id=i, prompt=real[i]['prompt'], response=real[i]['response'],
                   cohort='valid_known') for i in ids]
    fresh = fixtures.build(extended=True)
    inputs += [dict(r, cohort='fresh_authored') for r in fresh]
    fg = fixtures.gold(extended=True)
    evaluations = [dict(id=i, cohort='valid_known', label=real[i]['label'],
                        expected_cause=real[i]['explanation']) for i in ids]
    evaluations += [dict(id=r['id'], cohort='fresh_authored', **fg[r['id']]) for r in fresh]
    jobs = []
    mech = []
    for row in inputs:
        packet = full_packet(row)
        checked = mechanical.check(row)
        mech.append(dict(id=row['id'], cohort=row['cohort'], **checked))
        for arm in ('BASELINE', 'WHOLE_MOVE'):
            req = baseline_body(packet, 'mistral', MODEL, interface='I4') if arm == 'BASELINE' else reviewer.body(packet, 'mistral', MODEL)
            req['max_tokens'] = MAX_OUTPUT
            reserve = bound(req)
            if reserve > 262144:
                raise ValueError('CONTEXT_EXCEEDS_LIMIT_NO_TRUNCATION')
            jobs.append(dict(id=row['id'], cohort=row['cohort'], arm=arm, packet=packet,
                             request=req, wire_sha256=hashlib.sha256(serialized(req)).hexdigest(),
                             reservation_tokens=reserve))
    if len(jobs) > 36:
        raise ValueError('TOO_MANY_REQUESTS')
    save(OUT/'inputs.json', inputs)
    save(OUT/'evaluation_only.json', evaluations)
    save(OUT/'mechanical_offline.json', mech)
    save(OUT/'jobs.json', jobs)
    protocol = dict(version='whole-move-v1', source_commit=subprocess.check_output(
        ['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(), code_hashes=code_hashes(),
        file_hashes={name: fingerprint(OUT/name) for name in ('inputs.json','evaluation_only.json','mechanical_offline.json','jobs.json')},
        valid_sha256=fingerprint(ROOT/'valid.parquet',True),
        packages={n:importlib.metadata.version(n) for n in ('pydantic','numpy','pandas','pyarrow','bm25s')},
        providers={'mistral':dict(model=MODEL,context_limit=262144)}, limits=dict(http=len(jobs),tokens=280000),
        planned_requests=len(jobs), max_tokens=MAX_OUTPUT, temperature=0,
        selection='Six previously audited original valid rows; twelve independently authored source-policy contrasts. No selection by new model answers.',
        packet_contract='Identical FULL parsed-source-event packets old/new, including complete catalog and every current target; parser transport delimiters excluded.',
        arms=['BASELINE','WHOLE_MOVE','WHOLE_MOVE_PLUS_MECHANICAL'],
        mechanical='Generic positive original-declaration constraints only; no domain/name/row rules. Does not certify absence of business-policy violations.',
        interpretation='Known valid diagnostic and author-controlled fresh contrast suite, not external hidden holdout or all46 model F1. Literal quotes and target coverage are structural gates, not semantic proof.',
        unknown_binary_mapping=0, technical_binary_mapping=0,
        retry_policy='Single attempt120sec; provider breaker on any failed/unknown-usage response; no fallback model or silent truncation.',
        production_promotion=False)
    protocol['protocol_sha256'] = digest(protocol)
    save(OUT/'protocol.json',protocol)
    print(json.dumps(dict(status='FROZEN_NO_INFERENCE',requests=len(jobs),protocol=protocol['protocol_sha256'])))


def verify():
    p=read(OUT/'protocol.json')
    if digest({k:v for k,v in p.items() if k!='protocol_sha256'}) != p['protocol_sha256']:
        raise ValueError('PROTOCOL_CHANGED')
    if code_hashes()!=p['code_hashes']: raise ValueError('CODE_CHANGED')
    if any(fingerprint(OUT/n)!=h for n,h in p['file_hashes'].items()): raise ValueError('FROZEN_DATA_CHANGED')
    if fingerprint(ROOT/'valid.parquet',True)!=p['valid_sha256']: raise ValueError('VALID_CHANGED')
    if any(importlib.metadata.version(n)!=v for n,v in p['packages'].items()): raise ValueError('PACKAGES_CHANGED')
    return p


def decode_whole(record,failure,packet):
    if failure or not record or record.get('status')!='OK':
        return dict(decision=None,failure=failure or (record or {}).get('status','NO_RECORD'))
    data=record.get('provider_response')
    choices=data.get('choices') if isinstance(data,dict) else None
    if (not isinstance(choices,list) or len(choices)!=1 or not isinstance(choices[0],dict)
        or not isinstance(choices[0].get('message'),dict)):
        return dict(decision=None,failure='PROVIDER_SHAPE_INVALID')
    if choices[0].get('finish_reason')!='stop':
        return dict(decision=None,failure='INVALID_OR_UNFINISHED_JSON')
    raw=choices[0]['message'].get('content')
    value,ok=decode_json(raw) if isinstance(raw,str) else (None,False)
    if not ok: return dict(decision=None,failure='INVALID_JSON')
    try:
        admitted=reviewer.admit(value,packet)
        result=reviewer.aggregate(admitted)
        return dict(result,admitted=admitted,parsed=value,failure=None)
    except (ValueError,TypeError,KeyError) as exc:
        return dict(decision=None,failure=str(exc)[:240],parsed=value)


def run(live=False):
    p=verify(); client=Client(OUT/'model',p,live=live)
    if live:
        pf=preflight('mistral',MODEL);save(OUT/'model/preflight.json',pf)
        if pf['status']!='READY': print(json.dumps(pf));return
    decisions=[]; model_stop=False
    for index,j in enumerate(read(OUT/'jobs.json')):
        if model_stop: rec,failure=None,'MODEL_IDENTITY_STOP_NO_RETRY'
        else: rec,failure=client.ask(j['id']+'/'+j['arm'],'mistral',j['request'])
        d=decode(rec,failure,j['packet']) if j['arm']=='BASELINE' else decode_whole(rec,failure,j['packet'])
        if rec and rec.get('actual_model')!=MODEL:
            d=dict(d,decision=None,failure='ACTUAL_MODEL_MISMATCH'); model_stop=True
        decisions.append(dict(index=index,id=j['id'],cohort=j['cohort'],arm=j['arm'],
            wire_sha256=j['wire_sha256'],request_sha256=(rec or {}).get('request_sha256'),
            usage=((rec or {}).get('provider_response') or {}).get('usage'),**d))
        save(OUT/'model/decisions.json',decisions)
        save(OUT/'model/budget.json',client.summary())
        print(json.dumps({k:decisions[-1].get(k) for k in ('index','cohort','arm','decision','failure')}),flush=True)
    print(json.dumps(client.summary()))


def report():
    p=verify()
    decisions=read(OUT/'model/decisions.json'); jobs=read(OUT/'jobs.json')
    expected={(j['id'],j['arm']):j['wire_sha256'] for j in jobs}
    actual={(d['id'],d['arm']):d['wire_sha256'] for d in decisions}
    if len(actual)!=len(decisions) or expected!=actual: raise ValueError('INCOMPLETE_OR_CHANGED_RECORDS')
    # Verify provider records, wire/raw hashes and re-admit successful replies.
    # This read-only replay never overwrites the original live budget summary.
    client=Client(OUT/'model',p,live=False)
    for d,j in zip(decisions,jobs):
        if (d['id'],d['arm'])!=(j['id'],j['arm']): raise ValueError('RESULT_ORDER_CHANGED')
        if d.get('request_sha256') is None:
            if d.get('decision') is not None or d.get('usage') is not None or not d.get('failure'):
                raise ValueError('UNATTEMPTED_STAGE_CANNOT_HAVE_VERDICT_OR_USAGE')
            continue
        rec,failure=client.ask(j['id']+'/'+j['arm'],'mistral',j['request'])
        derived=decode(rec,failure,j['packet']) if j['arm']=='BASELINE' else decode_whole(rec,failure,j['packet'])
        if rec and rec.get('actual_model')!=MODEL: derived=dict(derived,decision=None,failure='ACTUAL_MODEL_MISMATCH')
        if any(d.get(k)!=v for k,v in derived.items()): raise ValueError('DECISION_DIFFERS_FROM_RAW_REPLAY')
    if client.new_http: raise ValueError('REPORT_MUST_NOT_INFER')
    reserved_names={item['name'] for item in client.ledger.values()}
    gold={e['id']:e for e in read(OUT/'evaluation_only.json')}
    mechanics={e['id']:e for e in read(OUT/'mechanical_offline.json')}
    output=[]
    for cohort in ('valid_known','fresh_authored'):
      for arm in ('BASELINE','WHOLE_MOVE','WHOLE_MOVE_PLUS_MECHANICAL','MECHANICAL_ONLY'):
        selected=[d for d in decisions if d['cohort']==cohort and d['arm']==('BASELINE' if arm=='BASELINE' else 'WHOLE_MOVE')]
        tp=fp=fn=tn=unk=tech=0
        for d in selected:
            decision=d['decision']
            if arm=='MECHANICAL_ONLY': decision='ERROR' if mechanics[d['id']]['mechanically_established_error'] else 'UNKNOWN'
            elif arm=='WHOLE_MOVE_PLUS_MECHANICAL' and mechanics[d['id']]['mechanically_established_error']: decision='ERROR'
            y=gold[d['id']]['label']; pred=decision=='ERROR'
            tp+=bool(y==1 and pred);fp+=bool(y==0 and pred);fn+=bool(y==1 and not pred);tn+=bool(y==0 and not pred)
            unk+=decision=='UNKNOWN';tech+=decision is None
        output.append(dict(cohort=cohort,arm=arm,n=len(selected),tp=tp,fp=fp,fn=fn,tn=tn,
            f1=2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else 0,unknown=unk,technical=tech,
            underlying_reviewer_unknown=sum(d['decision']=='UNKNOWN' for d in selected),
            underlying_reviewer_technical=sum(d['decision'] is None for d in selected),
            reviewer_attempts=sum(d['id']+'/'+d['arm'] in reserved_names for d in selected),
            reviewer_reply_records=sum(d.get('request_sha256') is not None for d in selected),
            reviewer_admitted=sum(d['decision'] is not None for d in selected),
            reviewer_skipped=sum(d['id']+'/'+d['arm'] not in reserved_names for d in selected),
            interpretation='n is planned pairs projected to binary, not successful inference count. Mechanical-only uses no reviewer; underlying fields describe the associated paired stage.'))
    save(OUT/'model/summary.json',output);print(json.dumps(output,indent=2))


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('stage',choices=['prepare','run','report']);ap.add_argument('--live',action='store_true');args=ap.parse_args()
    {'prepare':prepare,'run':lambda:run(args.live),'report':report}[args.stage]()
