"""Verify frozen JSON contents and response schemas across Windows/Git EOLs.

Historical E6/E7 manifests were hashed with Windows CRLF line endings.
Keep the original frozen bytes and manifests; also verify an LF/CRLF
checkout without changing the parsed policy/gold content.
"""
from __future__ import annotations
import hashlib
import json
import subprocess
from pathlib import Path
HERE=Path(__file__).parent


def run():
    audit={}
    for manifest in ('manifest.json','boundary_manifest.json','sentence_manifest.json'):
        data=json.loads((HERE/'frozen'/manifest).read_text(encoding='utf-8'))
        hashes=data.get('hashes',{k:v for k,v in data.items() if k.endswith('.json')})
        records=[]
        for name,expected in hashes.items():
            path=HERE/'frozen'/name; raw=path.read_bytes()
            lf=raw.replace(b'\r\n',b'\n')
            possibilities={'LF':lf,'CRLF':lf.replace(b'\n',b'\r\n')}
            matching=[k for k,v in possibilities.items() if hashlib.sha256(v).hexdigest()==expected]
            if not matching: raise ValueError(f'frozen content/layout changed: {name}')
            records.append({'name':name,'pre_inference_manifest_hash':expected,'recorded_layout':matching[0],
                            'canonical_lf_hash':hashlib.sha256(lf).hexdigest()})
        audit[manifest]=records
    # Exact parsed equality of pre-inference files, not merely equal labels.
    gitroot=Path(subprocess.check_output(['git','rev-parse','--show-toplevel'],text=True).strip())
    for directory in ('frozen','outputs/ALIGNMENT','outputs_rescue/ALIGNMENT','outputs_rescue/FRONTEND'):
        for path in (HERE/directory).glob('*.json'):
            relative=path.resolve().relative_to(gitroot.resolve()).as_posix()
            old=subprocess.check_output(['git','show','HEAD:'+relative])
            assert json.loads(old)==json.loads(path.read_text(encoding='utf-8')),path
    results=json.loads((HERE/'strict_graph_audit.json').read_text(encoding='utf-8'))
    arms=sum(map(len,results.values()))
    assert arms==18
    assert all(r['complete'] and r['n_cases']==10 for x in results.values() for r in x.values())
    cachecount=0
    for root in ('outputs','outputs_fixed','outputs_gold','outputs_rescue'):
        for path in (HERE/root/'_cache').glob('*.json'):
            r=json.loads(path.read_text(encoding='utf-8'))
            assert set(r)<= {'raw','finish_reason','served_model','usage','latency','cached'},path
            cachecount+=1
    (HERE/'hash_audit.json').write_text(json.dumps({'manifests':audit,'downstream_arms':arms,
        'case_records':180,'checked_response_cache_records':cachecount,
        'committed_parsed_data_unchanged':True},indent=2)+'\n',encoding='utf-8',newline='\n')
    print('Verified frozen content, unchanged committed data, 18 complete arms and',cachecount,'response schemas')
if __name__=='__main__': run()
