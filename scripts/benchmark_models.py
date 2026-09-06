"""Group-aware model comparison on explicit calibration/test data, with audit."""

import argparse
from collections import Counter
from dataclasses import asdict
import hashlib
import json
from pathlib import Path

from guardian_truth.benchmarking import ActiveClock, load_examples, run_benchmark
from guardian_truth.language import RunBudget
from guardian_truth.llm_client import ChatClientError
from guardian_truth.runtime import add_runtime_arguments, detector_from_args
from guardian_truth.settings import load_env_file


class AuditedDetector:
    def __init__(self, detector, stream):
        self.detector,self.stream=detector,stream
        self.calls=0
        self.budget_failures=0
        self.issues=Counter()
        self.semantic_scores=0
        self.hard_violations=0
        self.clock=ActiveClock()
        original=getattr(detector.semantic,'budget',None)
        if original is not None:
            detector.semantic.budget=RunBudget(original.max_requests,original.max_input_chars,
                                               original.seconds,clock=self.clock)

    def review(self,prompt,response):
        with self.clock.measure():
            result=self.detector.review(prompt,response)
        self.calls+=1
        self.budget_failures+=int(any('budget_exceeded' in issue for issue in result.unresolved))
        self.issues.update(result.unresolved)
        self.semantic_scores+=int(result.semantic_score is not None)
        self.hard_violations+=int(result.status=='violation')
        digest=hashlib.sha256((prompt+'\x00'+response).encode('utf-8')).hexdigest()
        self.stream.write(json.dumps({'input_hash':digest,**asdict(result)},ensure_ascii=False,allow_nan=False)+'\n')
        self.stream.flush()
        return result

    def summary(self):
        return {'reviews':self.calls,'budget_failures':self.budget_failures,
                'semantic_scores':self.semantic_scores,'hard_violations':self.hard_violations,
                'unresolved_counts':dict(self.issues),'active_seconds':self.clock()}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--baseline-mode',choices=('direct','graph','rlm'),default='direct')
    parser.add_argument('--candidate-mode',choices=('direct','graph','rlm'),default='rlm')
    parser.add_argument('--calibrate',action='store_true')
    parser.add_argument('--bootstrap-samples',type=int,default=1000)
    parser.add_argument('--seed',type=int,default=0)
    parser.add_argument('--env-file',type=Path,default=Path('.env'))
    add_runtime_arguments(parser)
    args=parser.parse_args()
    names=('baseline_audit.jsonl','candidate_audit.jsonl','report.json','scores.jsonl','configuration.json','frozen_manifest.json')
    if any((args.output_dir/name).exists() for name in names): parser.error('Use a fresh output directory')
    if any((args.output_dir/name).resolve() in (args.input.resolve(),args.env_file.resolve()) for name in names):
        parser.error('Outputs must not overwrite inputs or credentials')
    examples=load_examples(args.input)
    load_env_file(args.env_file)
    try:
        args.mode=args.baseline_mode; baseline=detector_from_args(args)
        args.mode=args.candidate_mode; candidate=detector_from_args(args)
    except (ValueError,ChatClientError) as error: parser.error(str(error))
    package=Path(__import__('guardian_truth').__file__).parent
    configuration={key:getattr(args,key) for key in (
        'backend','baseline_mode','candidate_mode','threshold','checks','max_requests','max_input_chars',
        'seconds','max_rounds','max_evidence_chars','max_prompt_chars','rolling_evidence','max_output_tokens','timeout_seconds','retries','recovery')}
    configuration['budget_time_basis']='per_detector_active_review_time_calibration_and_test_combined'
    configuration['source_hashes']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(package.glob('*.py'))}
    if args.backend!='none':
        configuration['model']=baseline.semantic.client.config.model
        configuration['base_url']=baseline.semantic.client.config.base_url
    args.output_dir.mkdir(parents=True,exist_ok=True)
    # Persist configuration before any model is asked to score calibration or test.
    (args.output_dir/'configuration.json').write_text(json.dumps(configuration,indent=2),encoding='utf-8')
    with (args.output_dir/'baseline_audit.jsonl').open('w',encoding='utf-8') as first_stream, \
         (args.output_dir/'candidate_audit.jsonl').open('w',encoding='utf-8') as second_stream:
        first,second=AuditedDetector(baseline,first_stream),AuditedDetector(candidate,second_stream)
        result=run_benchmark(examples,first,second,configuration=configuration,calibrate=args.calibrate,
                             baseline_threshold=args.threshold,candidate_threshold=args.threshold,
                             baseline_use_semantic=args.backend!='none',candidate_use_semantic=args.backend!='none',
                             bootstrap_samples=args.bootstrap_samples,seed=args.seed,
                             on_frozen=lambda manifest:(args.output_dir/'frozen_manifest.json').write_text(
                                 json.dumps(manifest,indent=2,allow_nan=False),encoding='utf-8'))
    scores=result.pop('per_example')
    result['resource_audit']={
        'baseline':first.summary(),
        'candidate':second.summary(),
        'quality_comparison_without_budget_failures':not(first.budget_failures or second.budget_failures)}
    for name,detector in (('baseline',baseline),('candidate',candidate)):
        if hasattr(detector.semantic,'budget'):
            result['resource_audit'][name]['budget']=detector.semantic.budget.summary()
    (args.output_dir/'report.json').write_text(json.dumps(result,indent=2,allow_nan=False),encoding='utf-8')
    with (args.output_dir/'scores.jsonl').open('w',encoding='utf-8') as stream:
        for row in scores: stream.write(json.dumps(row,allow_nan=False)+'\n')
    print(json.dumps({'test_kind':result['test_kind'],'baseline':result['report']['baseline'],
                      'candidate':result['report']['candidate'],'delta':result['report']['delta'],
                      'resource_audit':result['resource_audit']}),flush=True)


if __name__=='__main__': main()
