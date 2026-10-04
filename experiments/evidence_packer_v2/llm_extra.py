"""Post-hoc metrics on frozen replies (no new inference):
citation verifiability (admission outcome per arm) and norm scope on the 15 reference rows
(do cited policy sources completely cover the reference normative spans, and how many policy bytes are cited).
Repeated verbatim text is ambiguous and does not establish an addressed source."""
import json, sys
from collections import Counter
from pathlib import Path
from statistics import median

from experiments.evidence_packer_v2.llm_eval import ARMS, ROOT, rows


def spans_of(text, prompt):
    """Locate a verbatim packet text in the prompt; returns all occurrences (ambiguity reported, not resolved)."""
    out, i = [], prompt.find(text)
    while i >= 0 and text:
        out.append((i, i + len(text))); i = prompt.find(text, i + 1)
    return out


def fully_covered(start, end, spans):
    """Union coverage: touching one byte of a normative span is insufficient."""
    cursor = start
    for left, right in sorted(spans):
        if right <= cursor:
            continue
        if left > cursor:
            return False
        cursor = max(cursor, right)
        if cursor >= end:
            return True
    return cursor >= end


def main(out):
    out = Path(out)
    refs = json.loads((ROOT / 'experiments/retrieval_bakeoff_v1/fixtures/references.json').read_text())
    data = {r['id']: r for r in rows()}
    man = json.loads((out / 'manifest.json').read_text())
    res = {}
    for arm in ARMS:
        adm = Counter(); hit = tot = all_hit = 0; hit_err = tot_err = 0; cited_bytes = []; unloc = ambiguous = 0; span_recall = []
        for key, v in man['entries'].items():
            if not key.startswith(arm + '/') or 'file' not in v:
                continue
            rid = key.split('/', 1)[1]
            rp = out / 'replies' / v['file'].split('requests/')[1]
            rec = json.loads(rp.read_text()) if rp.exists() else {'admission': 'MISSING'}
            adm[rec['admission'].split(' ')[0][:60]] += 1
            a = rec.get('admitted')
            if not a or rid not in refs:
                continue
            pkt = json.loads((out / v['file']).read_text())['packet']
            pol = {s['source_id']: s['text'] for s in pkt['normative_sources']}
            cited = {n['policy_source_id'] for n in a.get('applicable_norms', []) if n.get('policy_source_id') in pol}
            prompt = data[rid]['prompt']; cspans = []
            for c in cited:
                loc = spans_of(pol[c], prompt)
                unloc += not loc; ambiguous += len(loc) > 1
                if len(loc) == 1:
                    cspans += loc
            req = [(s['start'], s['end']) for s in refs[rid]['required_normative_sources']]
            covered = [fully_covered(s, e, cspans) for s, e in req]
            tot += 1; hit += any(covered); all_hit += bool(req) and all(covered)
            span_recall.append(sum(covered) / len(req) if req else 1)
            cited_bytes.append(sum(len(pol[c].encode()) for c in cited))
            if a['decision'] == 'ERROR' and data[rid]['label'] == 1:
                tot_err += 1; hit_err += any(covered)
        res[arm] = dict(admission=dict(adm), ref15_admitted=tot, ref15_any_required_norm_cited=hit,
                        ref15_all_required_norms_cited=all_hit, denominator_contract='ADMITTED_REF15_ONLY',
                        ref15_mean_required_norm_recall=round(sum(span_recall) / len(span_recall), 3) if span_recall else None,
                        ref15_TP_with_required_norm=f'{hit_err}/{tot_err}',
                        median_cited_policy_bytes=median(cited_bytes) if cited_bytes else None, unlocatable_citations=unloc,
                        ambiguous_citations=ambiguous, metric_contract='COMPLETE_UNAMBIGUOUS_SPAN_COVERAGE_NOT_SEMANTIC_PROOF')
    print(json.dumps(res, indent=1)); (out / 'report_extra.json').write_text(json.dumps(res, indent=1))


if __name__ == '__main__':
    main(sys.argv[1])
