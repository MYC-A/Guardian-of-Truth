"""Author new diagnostic contrasts; freeze before inference, never overwrite."""
from pathlib import Path
import hashlib
import json

HERE=Path(__file__).resolve().parent


def run():
    spec=[('j_crates','Inspect','sealing','crate','51','52','PRECONDITION'),
          ('j_conduits','Measure','opening','conduit','R','S','PRECONDITION'),
          ('j_bundles','Mark','wrapping','bundle','K','L','ORDER_BEFORE'),
          ('j_samples','Label','archiving','sample','XN-61','XN-62','ORDER_BEFORE')]
    inputs=[]; gold=[]
    for cid,verb,nextverb,noun,a,b,relation in spec:
        policy=f'{verb} {noun} {a} before {nextverb} {noun} {a}. {verb} {noun} {b} before {nextverb} {noun} {b}.'
        row={'case_id':cid,'policy':policy,'tools':[
            {'name':'opaque_0','description':f'{verb}s a {noun}.','input':{'entity_id':'string'},'output':{'status':'string'}},
            {'name':'opaque_1','description':f'Performs {nextverb} of a {noun}.','input':{'entity_id':'string'},'output':{'status':'string'}}]}
        mentions=[]
        for i,token in enumerate((a,b)):
            for j,span in enumerate((f'{verb} {noun} {token}',f'{nextverb} {noun} {token}')):
                start=policy.index(span)
                assert policy.find(span,start+1)<0
                mentions.append({'span':span,'start':start,'end':start+len(span),'cid':f'E{2*i+j+1}'})
        edges=[{'from_cid':f'E{2*i+1}','to_cid':f'E{2*i+2}',
                'acceptable':sorted({relation,'ORDER_BEFORE','PRECONDITION'})} for i in range(2)]
        inputs.append(row); gold.append({**row,'mentions':mentions,'normative_edges':edges})
    runtime=[]
    for cid,changes,status in [
        ('prior_true',{},'CONDITION_SATISFIED'),
        ('prior_false',{'approved':False},'VIOLATION'),
        ('different_entity',{'result_entity':'E-99'},'UNKNOWN'),
        ('different_amount',{'evidence_amount':70},'UNKNOWN'),
        ('typed_amount',{'evidence_amount':'50'},'UNKNOWN'),
        ('future_result',{'result_index':3},'UNKNOWN'),
        ('no_entity_echo',{'no_echo':True},'UNKNOWN'),
        ('wrong_predicate',{'proposal_predicate':'item.executed'},'UNKNOWN'),
        ('unreviewed_mapping',{'no_binding':True},'UNKNOWN'),
        ('untrusted_strength',{'proposal_strength':'CONFIRMED'},'UNKNOWN'),
        ('wrong_producer',{'other_result_tool':True},'UNKNOWN'),
        ('check_is_not_execution',{'target_is_check':True},'NOT_APPLICABLE'),
        ('revoked',{'revoked':True},'VIOLATION'),
        ('stale_then_valid',{'renewed':True},'CONDITION_SATISFIED'),
        ('approval_after_target',{'late_approval':True},'VIOLATION'),
        ('opaque_rename',{'rename':True},'CONDITION_SATISFIED')]:
        runtime.append({'id':cid,'changes':changes,'expected':status})
    dest=HERE/'frozen'; dest.mkdir(exist_ok=True)
    for name,data in [('graph_inputs.json',inputs),('graph_gold.json',gold),('runtime_controls.json',runtime)]:
        p=dest/name
        if p.exists(): raise RuntimeError('already frozen: '+str(p))
        p.write_text(json.dumps(data,indent=2)+'\n',encoding='utf-8',newline='\n')
    manifest={'scope':'new author-written mechanism contrasts, not contest holdout',
              'graph_cases':4,'graph_edges':8,'runtime_controls':len(runtime),
              'hashes':{n:hashlib.sha256((dest/n).read_bytes()).hexdigest() for n in
                        ('graph_inputs.json','graph_gold.json','runtime_controls.json')}}
    (dest/'followup_manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps(manifest))


if __name__=='__main__': run()
