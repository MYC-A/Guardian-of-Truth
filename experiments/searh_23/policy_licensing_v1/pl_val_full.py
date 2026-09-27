import sys
sys.path.insert(0, '/workspace/guardian/repos/Guardian-of-Truth/experiments/searh_23/policy_licensing_v1')
from pl_common import load_suite
from pl_score import (CaseData, listwise_metrics, evidence_metrics, qa_metrics,
                      cf_metrics, cf_gate_metrics, mp1_metrics, pipeline_metrics)

suite = [c for c in load_suite('original') if c['split'] in ('calib', 'val')]
cds = [CaseData(c) for c in suite]

print('=== LISTWISE (calib+val) ===')
lw = listwise_metrics(cds)['ALL']
print({k: v for k, v in lw.items() if k != 'detail'})

print('\n=== EVIDENCE (calib+val) ===')
ev = evidence_metrics(cds)['ALL']
print(ev)

print('\n=== QA (calib+val) ===')
qa = qa_metrics(cds)['ALL']
print(qa)

print('\n=== CF (dataset pairs) ===')
cf = cf_metrics(cds)
print('n pairs:', cf['n'], '| ce_drops:', cf['ce_drops'], '| ce_rises:', cf['ce_rises'])
print('decision_flips_to_new:', cf['decision_flips_to_new'])

print('\n=== CF GATE (calib+val) ===')
cg = cf_gate_metrics(cds)['ALL']
for k, v in cg.items():
    print(k, {kk: vv for kk, vv in v.items() if kk in
              ('licensed', 'world_driven', 'unverified_cf', 'no_alternative',
               'precision_if_keep_licensed_only', 'precision_if_keep_all',
               'tp_licensed', 'fp_licensed', 'tp_world', 'fp_world')})

print('\n=== MP1 (calib+val swap cases) ===')
mp = mp1_metrics(cds)
print(mp['per_arm'])

print('\n=== PIPELINES (calib+val) ===')
for name, kwargs in [
    ('BASE', dict(detection='base')),
    ('A_listwise', dict(detection='listwise')),
    ('A_consensus', dict(detection='listwise_consensus')),
    ('B_evidence', dict(detection='evidence')),
    ('C_qa', dict(detection='qa')),
    ('BASE+cfgate', dict(detection='base', gate='cf')),
    ('B_evidence+cfgate', dict(detection='evidence', gate='cf')),
]:
    m = pipeline_metrics(cds, **kwargs)['ALL']
    print('%-18s prec=%.3f rec=%.3f correct=%d extra=%d miss=%d direrr=%d typed=%d unk=%d' % (
        name, m['accepted_precision'] or 0, m['recall'],
        m['edges_correct'], m['edges_extra'], m['edges_missing'],
        m['direction_errors'], m['typed_ok'], m['unknown_downgraded']))
