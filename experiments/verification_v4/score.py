"""V4 scorer (PROTOCOL §6-§11). Same cause judge as V2/V3 (ministral-14b-2512, unchanged integrated-v1 JUDGE_PROMPT,
cached verdict store). Gold is read here only.
  python -m experiments.verification_v4.score judge|report|flips --set S --rep R [--reps 1,2,3] --tag T"""
import argparse, json, re
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from guardian_truth.integrated import Transport
from guardian_truth.verification.v4 import decide_v4
from experiments.integrated_v1.score import JUDGE_PROMPT, JUDGE_MODEL
from experiments.verification_v2.run import paced
from experiments.verification_v2.score import OUT, gold as gold_v2, jkey, prf, verdicts, sign_p

ROOT = Path(__file__).resolve().parents[2]
ARMS = ('A', 'A_DF', 'A_DF_mech', 'A_Ems', 'A_Ems_mech', 'A_AT', 'A_CTRL', 'V4', 'V4_mechanical', 'V4_mech_strict', 'A_CB_shadow',
        'A_DF_raw', 'A_Ems_raw', 'A_AT_raw', 'A_CTRL_raw', 'V4_raw')
COMPS = ('DF4', 'Ems', 'AT', 'CTRL', 'CB')
VIOL = re.compile(r'violat|exceed|breach|not allowed|forbidden|наруш|превыш|запрещ|недопуст', re.I)
NEG = re.compile(r'\b(?:no|not|does not|doesn\'t|without|never)\b[^.]{0,30}(?:violat|exceed|breach)|не наруш|не превыш', re.I)


def gold(name):
    if name.startswith('ext_'):
        return json.loads((ROOT / 'outputs/verification_v4/external' / name[4:] / 'GOLD_eval_only.json').read_text())
    return gold_v2(name)


def load(name, rep, tag):
    recs = {}
    for line in (OUT / 'runs' / name / f'rep{rep}{tag}.jsonl').read_text().splitlines():
        r = json.loads(line)
        recs[r['id']] = r
    return recs


def cands(rec):
    for k in COMPS:
        x = rec.get(k)
        for c in (x if isinstance(x, list) else [x] if x else []):
            if c.get('candidate'):
                yield k, c['candidate'], (c.get('verify') or {}).get('verdict')


def ctext(c):
    return (c.get('requirement') or '') + ' — ' + c['reason']


def judge(name, rep, tag, max_calls=900):
    g, recs = gold(name), load(name, rep, tag)
    t = Transport('mistral', JUDGE_MODEL, OUT / 'cache' / 'judge', max_calls=max_calls, retry_failed=3, sender=paced)
    store = OUT / 'judge' / 'verdicts.jsonl'
    done = {json.loads(x)['key'] for x in store.read_text().splitlines()} if store.exists() else set()
    jobs = {}
    for i, rec in recs.items():
        if i not in g or g[i]['label'] != 1 or not g[i].get('cause') or 'error' in rec:
            continue
        texts = [acc['text'] for p, acc in decide_v4(rec).values() if p and acc['origin'] != 'GUARD' and acc['text']]
        texts += [ctext(c) for _, c, _ in cands(rec)]
        for x in texts:
            k = jkey(x, g[i]['cause'])
            if k not in done:
                jobs[k] = (x, g[i]['cause'])

    def one(item):
        k, (text, cause) = item
        msg = json.dumps(dict(gold_explanation=cause, verifier=dict(reason=text)), ensure_ascii=False)
        req = dict(model=JUDGE_MODEL, temperature=0, max_tokens=600, response_format=dict(type='json_object'),
                   messages=[dict(role='system', content=JUDGE_PROMPT), dict(role='user', content=msg)])
        r = t.call(req, tag='judge')
        try:
            v = json.loads(r['content'])['match']
        except Exception:
            v = None
        if v:
            with open(store, 'a') as f:
                f.write(json.dumps(dict(key=k, match=v)) + '\n')
    with ThreadPoolExecutor(2) as ex:
        list(ex.map(one, jobs.items()))
    print('judge jobs', len(jobs), t.counts)


def steps_of(rec):
    out = list(rec['A'].get('steps') or [])
    for k in COMPS:
        x = rec.get(k)
        for c in (x if isinstance(x, list) else [x] if x else []):
            for s in ('step', 'extract', 'plan_step', 'check', 'verify'):
                if isinstance(c.get(s), dict) and c[s].get('key'):
                    out.append(dict(c[s], comp=k))
            if k == 'CTRL' and c.get('key'):
                out.append(dict(c, comp=k))
    return out


def audit(rec):
    """Post-processing invariants (PROTOCOL §11) -> list of findings."""
    f = []
    d = rec.get('DF4') or {}
    mism = [c for c in d.get('self_checks') or [] if c['status'] == 'MISMATCH'] + [b for b in d.get('bindings') or [] if b['check']['status'] == 'MISMATCH']
    if mism and not d.get('candidate'):
        f.append('DF4_MISMATCH_WITHOUT_CANDIDATE')
    e = rec.get('Ems') or {}
    if any(c.get('status') == 'VIOLATED' for c in e.get('checks') or []) and not e.get('candidate'):
        f.append('EMS_VIOLATED_WITHOUT_CANDIDATE')
    for c in e.get('checks') or []:
        if c.get('note') == 'CONTRADICTION_MODEL_VIOLATED_CODE_HOLDS':
            f.append('EMS_CONTRADICTION_' + c['req_id'])
        if c.get('mode') == 'SEMANTIC' and c.get('status') == 'SATISFIED' and VIOL.search(c.get('reason') or '') and not NEG.search(c.get('reason') or ''):
            f.append('EMS_REASON_VIOLATION_STATUS_SATISFIED_' + c['req_id'])
        if c.get('raw_status') == 'VIOLATED' and c.get('status') != 'VIOLATED':
            f.append(f"EMS_RAW_VIOLATED_DOWNGRADED_{c['req_id']}:{c.get('note')}")
    a = rec.get('AT') or {}
    if (a.get('coverage') or {}).get('complete') and any(t.get('admitted') for t in a.get('targets') or []) and not a.get('candidate'):
        f.append('AT_ADMITTED_ERROR_WITHOUT_CANDIDATE')
    if a.get('raw_error_targets') and not a.get('candidate'):
        f.append('AT_RAW_ERROR_NOT_ADMITTED:' + (a.get('admission') or ''))
    for k, c, v in cands(rec):
        vr = next((x.get('verify') for x in ([rec[k]] if not isinstance(rec[k], list) else rec[k]) if x.get('candidate') is c), None) or {}
        if vr.get('raw_verdict') == 'SUPPORTED' and vr.get('verdict') != 'SUPPORTED':
            f.append(f'{k}_VERIFIER_SUPPORTED_DOWNGRADED:{vr.get("downgraded")}')
        if c.get('code_proven') and v != 'SUPPORTED':
            f.append(f'{k}_CODE_PROVEN_NOT_SUPPORTED:{v}')
    adm = rec.get('A_adm2') or {}
    if adm.get('decision') != 'ERROR' and VIOL.search(adm.get('reason') or '') and not NEG.search(adm.get('reason') or ''):
        f.append('A_REASON_MENTIONS_VIOLATION_BUT_' + str(adm.get('decision')))
    return f


def report(name, rep, tag, quiet=False):
    g, recs, V = gold(name), load(name, rep, tag), verdicts()
    ids = [i for i in recs if i in g and 'error' not in recs[i]]
    dec = {i: decide_v4(recs[i]) for i in ids}

    def correct(i, arm):
        p, acc = dec[i][arm]
        if not p or g[i]['label'] != 1:
            return False
        if acc['origin'] == 'GUARD':
            return True
        return V.get(jkey(acc['text'], g[i].get('cause') or '')) == 'SAME'
    multi = [i for i in ids if (recs[i].get('n_targets') or 0) >= 2]
    later = [i for i in ids if g[i]['label'] == 1 and re.fullmatch(r't[1-9]\d*', str(g[i].get('target') or ''))]
    strata = {'all': ids, 'multi': multi}
    out = dict(set=name, rep=rep, tag=tag, rows=len(ids), errors=sum('error' in r for r in recs.values()), strata={})
    for sname, sids in strata.items():
        so = {}
        for arm in ARMS:
            pred = {i: dec[i][arm][0] for i in sids}
            m = prf(pred, g)
            gain = [i for i in sids if pred[i] and not dec[i]['A'][0] and g[i]['label'] == 1]
            cgain = [i for i in gain if correct(i, arm)]
            nfp = [i for i in sids if pred[i] and not dec[i]['A'][0] and g[i]['label'] == 0]
            lat = [i for i in later if i in sids]
            so[arm] = dict(**m, cause_correct_tp=sum(correct(i, arm) for i in sids), gain=len(gain), gain_cause_correct=len(cgain),
                           gain_wrong_cause=len(gain) - len(cgain), new_fp=len(nfp), sign_p=sign_p(len(gain), len(nfp)),
                           later_call_recall=f"{sum(pred[i] for i in lat)}/{len(lat)}",
                           gain_ids=[f"{i}:{g[i].get('case', '')}" + ('' if i in cgain else '(cause≠)') for i in gain],
                           fp_ids=[f"{i}:{g[i].get('case', '')}" for i in nfp])
        out['strata'][sname] = so
    ver = defaultdict(Counter)
    for i in ids:
        for k, c, v in cands(recs[i]):
            key = k + ('_proven' if c.get('code_proven') else '')
            if g[i]['label'] == 0:
                ver[key]['false'] += 1
                ver[key]['false_rejected'] += int(v != 'SUPPORTED')
            else:
                same = V.get(jkey(ctext(c), g[i].get('cause') or '')) == 'SAME'
                ver[key]['true_same' if same else 'true_notsame'] += 1
                ver[key]['true_same_rejected' if same else 'true_notsame_rejected'] += int(v != 'SUPPORTED')
    out['verifier'] = {k: dict(v) for k, v in ver.items()}
    trig, cov = Counter(), Counter()
    for i in ids:
        t = recs[i].get('triggers')
        if t is None:
            trig['base_error_or_skipped'] += 1
            continue
        lab = g[i]['label']
        for k in ('T_multi', 'T_calc', 'T_quant', 'T_confirm'):
            trig[f'{k}_{lab}'] += bool(t.get(k))
        trig['fallback'] += bool(t.get('fallback'))
        a = recs[i].get('AT')
        if a:
            cov['complete' if (a.get('coverage') or {}).get('complete') else 'incomplete'] += 1
    out['triggers'], out['at_coverage'] = dict(trig), dict(cov)
    calls, toks = Counter(), Counter()
    for i in ids:
        for s in steps_of(recs[i]):
            c = s.get('comp', 'A')
            calls[c] += 1
            toks[c] += (s.get('usage') or {}).get('total_tokens') or 0
    out['calls'] = dict(calls)
    out['calls_per_row'] = round(sum(calls.values()) / max(1, len(ids)), 2)
    out['tokens_per_row'] = round(sum(toks.values()) / max(1, len(ids)))
    out['tokens'] = dict(toks)
    out['audit'] = {i: a for i in ids if (a := audit(recs[i]))}
    path = OUT.parent / 'verification_v4' / 'reports' / f'{name}_rep{rep}{tag}.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    if not quiet:
        for s, so in out['strata'].items():
            print('--', s, len(strata[s]))
            for arm, m in so.items():
                if arm.endswith('_raw') and s != 'all':
                    continue
                print(f"  {arm:13s} tp={m['tp']:2d} fp={m['fp']:2d} F1={m['F1']:.3f} cc={m['cause_correct_tp']:2d} gain={m['gain']}/{m['gain_cause_correct']}cc newFP={m['new_fp']} later={m['later_call_recall']} {m['gain_ids']} FP{m['fp_ids']}")
        print('verifier', json.dumps(out['verifier']))
        print('triggers', out['triggers'], 'AT', out['at_coverage'])
        print('calls', out['calls'], 'per row', out['calls_per_row'], 'tokens/row', out['tokens_per_row'])
        print('audit', json.dumps(out['audit'], ensure_ascii=False)[:3000])
    return out


def flips(name, reps, tag):
    """Baseline (A) stability across repetitions: classify every row whose A decision differs between reps."""
    g = gold(name)
    R = {r: load(name, r, tag) for r in reps}
    ids = sorted(set.intersection(*[set(x) for x in R.values()]))
    out = []
    for i in ids:
        a = {r: R[r][i] for r in reps}
        dec = {r: int(decide_v4(a[r])['A'][0]) if 'error' not in a[r] else None for r in reps}
        adm = {r: (a[r].get('A_adm2') or {}) for r in reps}
        if len(set(dec.values())) == 1 and len({x.get('target_id') for x in adm.values() if x.get('decision') == 'ERROR'}) <= 1:
            continue
        raw = {r: next((s for s in a[r]['A']['steps'] if s.get('tag') == 'review'), {}).get('raw_content') for r in reps}
        parsed = {}
        for r, x in raw.items():
            try:
                parsed[r] = json.loads(x)
            except Exception:
                parsed[r] = None
        if any(p is None for p in parsed.values()):
            cls = 'different serialization'
        elif len({(p.get('decision') if isinstance(p, dict) else None) for p in parsed.values()}) == 1 and len(set(dec.values())) > 1:
            cls = 'different admission'
        elif len({(p.get('regulated_action') or {}).get('target_id') for p in parsed.values()}) > 1:
            cls = 'different target selection'
        elif len(set(dec.values())) == 1:
            cls = 'different cause'
        else:
            ev = [frozenset(e.get('source_id') for e in (p.get('supporting_evidence') or [])) for p in parsed.values()]
            cls = 'same evidence, different semantic decision' if len(set(ev)) == 1 else 'different evidence, different decision'
        out.append(dict(id=i, case=g.get(i, {}).get('case'), label=g.get(i, {}).get('label'), decisions=dec,
                        raw_decisions={r: (p or {}).get('decision') for r, p in parsed.items()},
                        targets={r: (p or {}).get('regulated_action', {}).get('target_id') if p else None for r, p in parsed.items()}, cls=cls))
    res = dict(set=name, reps=reps, rows=len(ids), flipped=len([x for x in out if len(set(x['decisions'].values())) > 1]),
               classes=dict(Counter(x['cls'] for x in out)), items=out)
    path = OUT.parent / 'verification_v4' / 'reports' / f'{name}_flips{tag}.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(res, ensure_ascii=False, indent=1))
    print(json.dumps({k: v for k, v in res.items() if k != 'items'}))
    for x in out:
        print(' ', x['id'], x['case'], x['label'], x['decisions'], x['raw_decisions'], x['targets'], x['cls'])
    return res


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('stage', choices=['judge', 'report', 'flips'])
    ap.add_argument('--set', required=True)
    ap.add_argument('--rep', type=int, default=1)
    ap.add_argument('--reps', default='1,2')
    ap.add_argument('--tag', default='_v4')
    a = ap.parse_args()
    if a.stage == 'judge':
        judge(a.set, a.rep, a.tag)
    elif a.stage == 'report':
        report(a.set, a.rep, a.tag)
    else:
        flips(a.set, [int(x) for x in a.reps.split(',')], a.tag)
