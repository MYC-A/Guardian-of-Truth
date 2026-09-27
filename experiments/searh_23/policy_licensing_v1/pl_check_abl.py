import sys
sys.path.insert(0, '/workspace/guardian/repos/Guardian-of-Truth/experiments/searh_23/policy_licensing_v1')
from pl_common import load_suite
from pl_score import CaseData, aggregate_detection

suite = [c for c in load_suite('original') if c['split'] in ('calib', 'val')]
cds = [CaseData(c) for c in suite]

ARMS = [
    ('DET-both(BASE llm)', lambda c, k: c.dec_llm(k, 'det_mistral')),
    ('DET-pol(policy-only)', lambda c, k: c.dec_llm(k, 'det_pol_mistral')),
    ('DET-tool(tool-only)', lambda c, k: c.dec_llm(k, 'det_tool_mistral')),
]
for name, dec in ARMS:
    try:
        m = aggregate_detection(cds, dec)['ALL']
    except Exception as e:
        print(name, 'not ready:', e)
        continue
    print("%-24s P=%.3f R=%.3f FP=%d(h%d/e%d) FN=%d" % (
        name, m['precision'], m['recall'], m['fp'], m['fp_hard'], m['fp_easy'], m['fn']))
    for f in m['fp_detail'][:8]:
        print("   FP", f[3], f[0], f[1] + '-' + f[2])
