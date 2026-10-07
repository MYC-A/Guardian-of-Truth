"""Blind-pass invariance test on REAL long rows (offline; zero model calls).

Guarantee under test (already fixed in 403d811e; this keeps it): changing the
examined RESPONSE — its IDs, numbers, tool names or its LENGTH — must not change
a single byte of the actual pre-pass request, including retrieval and coverage.
The pre-pass request is built from the ORIGINAL PROMPT only (neutral_view), so
the wire bytes must be identical.

Sanity check in the other direction: the same mutations DO change the ordinary
review packet (current move), so the test is meaningful, not vacuous.

Rows: real tau2 trajectories from outputs/guardian_v6/holdout2 (longest rows we
have in-repo); plus the semantic dev rows as short controls.

Usage:
  python -m experiments.guardian_local_a100.test_blind_invariance [--n 8]
Exit code 0 = PASS; nonzero = FAIL with a printed diff summary.
"""
import argparse
import json
import re
from pathlib import Path

from experiments.guardian_semantic.variants import BLIND_PROMPT, analysis_schema, _req
from experiments.guardian_semantic.neutral import neutral_view
from experiments.guardian_addons.variants2 import typed_schema, TYPED_PROMPT

from .run_local import rows, ROOT

MODEL_ID = 'invariance-test-model'   # request bytes include the model id; constant here


def canonical(request):
    return json.dumps(request, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def pre_requests(row):
    """The actual pre-pass requests for 'blind2' (plain) and 'blind2_typed' (typed)."""
    user, receipt = neutral_view(row, 20000)
    if user is None:
        return None, None, receipt
    plain = _req(MODEL_ID, BLIND_PROMPT, user, analysis_schema(user), 'pre_analysis_neutral_v2', 1700)
    typed = _req(MODEL_ID, TYPED_PROMPT, user, typed_schema(user), 'pre_analysis_neutral_v2', 1700)
    return canonical(plain), canonical(typed), receipt


def mutations(response):
    """Response-only mutations that must not affect the pre-pass request."""
    out = {}
    m = re.search(r'\d+', response)
    if m:
        old = m.group(0)
        new = str(int(old) + 7) if old.isdigit() else old + '0'
        out['number'] = response.replace(old, new, 1)
    m = re.search(r'[A-Za-z0-9_-]{4,}', response)
    if m and any(c.isdigit() for c in m.group(0)):
        tok = m.group(0)
        out['id_like'] = response.replace(tok, tok[::-1], 1)
    m = re.search(r'\b(get|update|cancel|send|create|transfer|exchange)_[a-z_]+\b', response)
    if m:
        out['tool_name'] = response.replace(m.group(0), 'zzz_' + m.group(0), 1)
    out['length'] = response + ' ' * 700
    return {k: v for k, v in out.items() if v is not None and v != response}


def review_packet_changes(row):
    """The ordinary review packet must change under the same mutations (sanity)."""
    from guardian_truth.verification.pipeline import packet_for
    base = json.dumps(packet_for(row, 20000), ensure_ascii=False, sort_keys=True)
    changed = {}
    for name, resp in mutations(row['response']).items():
        mutated = dict(row, response=resp)
        changed[name] = canonical(dict(packet_for(mutated, 20000))) != canonical(dict(json.loads(base)))
    return changed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--n', type=int, default=8, help='longest holdout2 rows to test')
    a = ap.parse_args()
    hold = sorted(rows('holdout2'), key=lambda r: -len(r['response']))[:a.n]
    dev = rows('dev')
    failures = []
    report = []
    for row in hold + dev:
        p_plain, p_typed, receipt = pre_requests(row)
        if p_plain is None:
            failures.append((row['id'], 'neutral_view_failed', receipt))
            continue
        muts = mutations(row['response'])
        sanity = review_packet_changes(row)
        row_report = dict(id=row['id'], len_response=len(row['response']), mutations=sorted(muts),
                          review_packet_changed=sanity)
        for name, resp in muts.items():
            mutated = dict(row, response=resp)
            q_plain, q_typed, _ = pre_requests(mutated)
            if q_plain != p_plain:
                failures.append((row['id'], f'plain pre-request differs under {name}', ''))
            if q_typed != p_typed:
                failures.append((row['id'], f'typed pre-request differs under {name}', ''))
        report.append(row_report)
    out = ROOT / 'outputs/guardian_local_a100/blind_invariance.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(dict(passed=not failures, failures=failures, rows=report), ensure_ascii=False, indent=1),
                   encoding='utf-8', newline='\n')
    print(json.dumps(dict(passed=not failures, n_rows=len(report), failures=failures[:6]), ensure_ascii=False, indent=1))
    if failures:
        raise SystemExit('BLIND_INVARIANCE_FAILED')
    print(f'PASS: pre-pass request bytes invariant under response mutations on {len(report)} rows '
          f'({len(report and report[0]["mutations"])} mutation kinds); review packets DID change (sanity ok)')


if __name__ == '__main__':
    main()
