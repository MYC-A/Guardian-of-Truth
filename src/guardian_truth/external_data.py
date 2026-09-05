"""Explicit RAGTruth adaptation for factual-grounding transfer, not tool policy.

Original prompts are preserved as data. Human span labels become response-level
labels with a documented policy for implicit truth and poor-quality responses.
"""

import hashlib

from .benchmarking import Example, prepare_examples


RAGTRUTH_REVISION = 'c103204b9ce28d6bbad859304bf30de72b8ed8fe'


def adapt_ragtruth(sources, responses, *, max_groups_per_split=100):
    if type(max_groups_per_split) is not int or max_groups_per_split < 1:
        raise ValueError('Group cap must be positive')
    source_index={}
    for source in sources:
        key=str(source['source_id'])
        if key in source_index or not isinstance(source.get('prompt'),str):
            raise ValueError('Duplicate or invalid source')
        source_index[key]=source
    candidates=[]; splits={}; excluded={}; seen=set()
    for row in responses:
        key=str(row['source_id']); identity=str(row['id'])
        if identity in seen: raise ValueError('Duplicate response ID')
        seen.add(identity)
        if key not in source_index: raise ValueError('Response has no source')
        if row.get('split') not in ('train','test'): raise ValueError('Unknown original split')
        if key in splits and splits[key]!=row['split']: raise ValueError('Source crosses original splits')
        splits[key]=row['split']
        if row.get('quality') != 'good':
            excluded['non_good_quality']=excluded.get('non_good_quality',0)+1
            continue
        if not isinstance(row.get('response'),str) or not isinstance(row.get('labels'),list):
            raise ValueError('Invalid response or annotations')
        for span in row['labels']:
            if not isinstance(span,dict) or type(span.get('implicit_true',False)) is not bool:
                raise ValueError('Invalid implicit truth annotation')
        label=int(any(not span.get('implicit_true',False) for span in row['labels']))
        # All responses to one source stay together. Original test is untouched;
        # a deterministic part of original train becomes calibration.
        digest=int(hashlib.sha256(('calibration:'+key).encode()).hexdigest(),16)
        split='test' if row['split']=='test' else 'calibration' if digest%5==0 else 'train'
        source=source_index[key]
        candidates.append(Example('ragtruth:'+identity,source['prompt'],row['response'],label,
                                  group_id='ragtruth:'+key, source_id='ragtruth:'+key,
                                  dialogue_id='ragtruth:'+key, split=split,
                                  family='ragtruth:'+str(source.get('task_type','unknown')), synthetic=False))
    selected=set()
    for split in ('train','calibration','test'):
        groups={e.group_id for e in candidates if e.split==split}
        ranked=sorted(groups,key=lambda key:hashlib.sha256(('selection:'+key).encode()).hexdigest())
        selected.update(ranked[:max_groups_per_split])
    examples,audit=prepare_examples([e for e in candidates if e.group_id in selected])
    return examples, {'source_revision':RAGTRUTH_REVISION,'rows':len(examples),'groups':audit['groups'],
                      'splits':{split:sum(e.split==split for e in examples) for split in ('train','calibration','test')},
                      'excluded':excluded,'selection':'source_hash_without_labels',
                      'label_mapping':'any_human_span_except_implicit_true; quality=good only',
                      'limitations':[
                          'External factual-grounding task, not the competition tool-policy distribution.',
                          'Incorrect refusals/truncated responses are excluded, not relabelled as correct.',
                          'Public data may have been seen in model pretraining; independence from pretraining is unknown.',
                          'Human annotations can be imperfect; this does not establish full agent-verification quality.',
                          'Original prompts are used verbatim; no labels/annotation explanations enter inference.']}
