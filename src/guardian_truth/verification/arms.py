"""Arm projections of one run_row record (protocol §2). Returns 1 (ERROR) / 0 per arm."""


def decide(rec):
    a = int(rec['A']['final'] == 'ERROR')
    esc = rec.get('escalated', False)

    def cand_err(k, verified):
        x = rec.get(k) or {}
        if not esc or not x.get('candidate'):
            return 0
        if not verified:
            return 1
        return int((x.get('verify') or {}).get('verdict') == 'SUPPORTED')
    out = dict(A=a, B=max(a, cand_err('B', False)), Bv=max(a, cand_err('B', True)),
               C=max(a, cand_err('C', False)), D=max(a, cand_err('C', True)))
    av = rec.get('Av')
    model_owned = rec['A'].get('proof') == 'MODEL_HYPOTHESIS'      # guard proofs are never dropped
    out['Av'] = 0 if (a and model_owned and av and av.get('verdict') == 'REFUTED') else a          # shadow
    out['Av_strict'] = 0 if (a and model_owned and av and av.get('verdict') != 'SUPPORTED') else a  # shadow
    out['A_adm2'] = int(rec.get('A_adm2', {}).get('decision') == 'ERROR' or rec['A'].get('guard_error')) if rec.get('A_adm2') else a
    return out
