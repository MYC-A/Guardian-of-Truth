"""Join frozen human claim annotations to original sources; no LLM inference."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from guardian_truth.cli import read_rows
from guardian_truth.parsing import parse_events
from guardian_truth.reader import EvidenceReader
from guardian_truth.reason_metrics import ReasonAnnotation, reason_metrics
from guardian_truth.types import EvidenceGraph


def any_valid(values):
    return True if True in values else (None if None in values else False)


def build(data, baseline, annotations):
    original = {str(row['id']):row for row in data}
    canonical = {row['id']:row for row in baseline}
    expected = {row['id'] for row in baseline if row['strict']['label'] == 1
                and not row['skipped_mechanical']}
    if {row['id'] for row in annotations} != expected or len(annotations) != len(expected):
        raise ValueError('Annotations must cover every canonical semantic positive exactly once')
    joined, metrics_rows = [], []
    for annotation in annotations:
        row_id = annotation['id']
        row, raw = original[row_id], canonical[row_id]
        reader = EvidenceReader(SimpleNamespace(prompt=row['prompt'], response=row['response'],
             history=parse_events(row['prompt'],'prompt'), graph=EvidenceGraph()))
        source_ids = {(c.source.document,c.source.start,c.source.end):c.id for c in reader.chunks.values()}
        source_ids[('response',0,len(row['response']))] = 'response'
        wanted = {i for i,f in enumerate(raw['review']['findings']) if f['code']=='semantic_contradicted'}
        if {c['finding_index'] for c in annotation['claims']} != wanted:
            raise ValueError('Claim annotation coverage mismatch')
        claims = []
        for human in annotation['claims']:
            finding = raw['review']['findings'][human['finding_index']]
            ids, evidence = [], []
            for source in finding['sources']:
                key = (source['document'],source['start'],source['end'])
                eid = source_ids[key]
                ids.append(eid)
                evidence.append({'id':eid,'text':row[source['document']][source['start']:source['end']]})
            if 'message' in human and human['message'] != finding['message']:
                raise ValueError('Raw message changed')
            if 'cited_evidence_ids' in human and human['cited_evidence_ids'] != ids:
                raise ValueError('Recovered citation mismatch')
            for source in human.get('counter_sources',[]) + human.get('h2',{}).get('counter_sources',[]):
                if not 0 <= source['start'] < source['end'] <= len(row[source['document']]):
                    raise ValueError('Counter-source out of bounds')
            claims.append({**human,'message':finding['message'],'sources':finding['sources'],
                           'cited_evidence_ids':ids,'evidence':evidence})
        material = any_valid([c['material_valid_reason'] for c in claims])
        cited = any_valid([c['cited_valid_material_reason'] for c in claims])
        metrics_rows.append(ReasonAnnotation(row_id,raw['label'],1,'semantic',material,cited))
        joined.append({'id':row_id,'label':raw['label'],'prediction':1,'material_valid_reason':material,
                       'cited_material_valid_reason':cited,'claims':claims})
    all_claims = [c for row in joined for c in row['claims']]
    h1 = lambda c:c['h1_already_sufficient_selected_evidence'] is True
    h2 = lambda c:c.get('h2',{}).get('eligible',False)
    summary = {'metrics':reason_metrics(metrics_rows),'claims':len(all_claims),
        'relations':dict(Counter(c['relation_to_cited_evidence'] for c in all_claims)),
        'claim_material_validity':dict(Counter(str(c['material_valid_reason']) for c in all_claims)),
        'h1':{'claims':sum(h1(c) for c in all_claims),
              'rows':sum(any(h1(c) for c in row['claims']) for row in joined)},
        'h2_narrow_predicate_potential':{'claims':sum(h2(c) for c in all_claims),
              'rows':sum(any(h2(c) for c in row['claims']) for row in joined),
              'by_type':dict(Counter(c['h2']['reason_type'] for c in all_claims if h2(c)))},
        'rows_with_entailed_citation':{str(label):sum(any(c['relation_to_cited_evidence']=='ENTAILED'
            for c in row['claims']) for row in joined if row['label']==label) for label in (0,1)},
        'limitations':['Human audit, not independent reason gold or hidden-test estimate.',
            'H2 potential is not automatic extraction coverage or corrected row count.',
            'No production predictions changed. Full-context RP and cited RP intentionally differ.']}
    return {'summary':summary,'rows':joined}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data',type=Path,default=Path('valid.parquet'))
    parser.add_argument('--baseline',type=Path,default=Path('outputs/claim_gate_20b_full/audit.jsonl'))
    parser.add_argument('--output-dir',type=Path,required=True)
    args=parser.parse_args()
    path=args.output_dir/'audit.json'
    if path.exists():
        parser.error('Use a fresh output directory')
    inputs=[Path('docs/v4_fp_claim_audit.json'),Path('docs/v4_tp_claim_audit.json')]
    annotations=[row for p in inputs for row in json.loads(p.read_text(encoding='utf-8'))['rows']]
    baseline=[json.loads(line) for line in args.baseline.read_text(encoding='utf-8').splitlines()]
    result=build(read_rows(args.data),baseline,annotations)
    result['input_hashes']={str(p):hashlib.sha256(p.read_bytes()).hexdigest()
                           for p in inputs+[args.data,args.baseline]}
    args.output_dir.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    print(json.dumps(result['summary'],indent=2))


if __name__=='__main__':
    main()
