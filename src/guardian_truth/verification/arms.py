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
               C=max(a, cand_err('C', False)), D=max(a, cand_err('C', True)),
               E=max(a, cand_err('E', False)), Ev=max(a, cand_err('E', True)))
    # amendment 3 diagnostic: directional counterfactual (original VIOLATING and >=1 variant COMPLIANT); audit records only
    cdir = int(bool((rec.get('C') or {}).get('directional')))
    out['C_dir'], out['D_dir'] = (max(a, cand_err('C', False) * cdir), max(a, cand_err('C', True) * cdir))
    av = rec.get('Av')
    model_owned = rec['A'].get('proof') == 'MODEL_HYPOTHESIS'      # guard proofs are never dropped
    out['Av'] = 0 if (a and model_owned and av and av.get('verdict') == 'REFUTED') else a          # shadow
    out['Av_strict'] = 0 if (a and model_owned and av and av.get('verdict') != 'SUPPORTED') else a  # shadow
    out['A_adm2'] = int(rec.get('A_adm2', {}).get('decision') == 'ERROR' or rec['A'].get('guard_error')) if rec.get('A_adm2') else a
    b2 = out['A_adm2']                     # amendment 2: the same candidates on top of the admission-v2 base
    for k, ver, name in (('B', False, "B'"), ('B', True, "Bv'"), ('C', False, "C'"), ('C', True, "D'"), ('E', False, "E'"), ('E', True, "Ev'")):
        out[name] = max(b2, cand_err(k, ver))
    out["C_dir'"], out["D_dir'"] = max(b2, cand_err('C', False) * cdir), max(b2, cand_err('C', True) * cdir)
    return out
