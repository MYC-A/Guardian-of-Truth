"""Development-only paired claim-validator ablation using ONE generation per row."""

import argparse
from collections import Counter
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import time

from guardian_truth.benchmarking import Example, Score, paired_comparison
from guardian_truth.cli import read_rows, validate_rows
from guardian_truth.decision import decide
from guardian_truth.pipeline import Detector
from guardian_truth.runtime import add_runtime_arguments, detector_from_args
from guardian_truth.settings import load_env_file


def gate_decisions(review, threshold=.5):
    overall = review.reading_trace[-1].get('overall_assessment', {}) if review.reading_trace else {}
    shadow = replace(review, semantic_score=overall.get('score'))
    return (decide(review, threshold=threshold, use_semantic=True),
            decide(shadow, threshold=threshold, use_semantic=True))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--env-file', type=Path, default=Path('.env'))
    parser.add_argument('--limit', type=int)
    parser.add_argument('--bootstrap-samples', type=int, default=1000)
    add_runtime_arguments(parser)
    args = parser.parse_args()
    if args.limit is not None and args.limit < 1:
        parser.error('Limit must be positive')
    if args.bootstrap_samples < 1:
        parser.error('Bootstrap samples must be positive')
    names = ('configuration.json','audit.jsonl','report.json')
    paths = [args.output_dir/name for name in names]
    if any(path.exists() for path in paths):
        parser.error('Use a fresh output directory')
    if any(path.resolve() in (args.input.resolve(),args.env_file.resolve()) for path in paths):
        parser.error('Output must not overwrite input or credentials')
    rows = read_rows(args.input)
    validate_rows(rows)
    if args.limit:
        rows = rows[:args.limit]
    if not rows or any(str(row.get('label')) not in ('0','1') for row in rows):
        parser.error('A nonempty development dataset with binary labels is required')
    load_env_file(args.env_file)
    detector = detector_from_args(args)
    precheck = Detector(enabled=detector.enabled)
    decide(precheck.review('',''),threshold=args.threshold)
    config = {key:getattr(args,key) for key in (
        'backend','mode','checks','max_requests','max_input_chars','seconds','max_rounds',
        'max_evidence_chars','max_prompt_chars','rolling_evidence','max_output_tokens',
        'timeout_seconds','retries','threshold','limit','bootstrap_samples','recovery')}
    if args.backend != 'none':
        config.update(model=detector.semantic.client.config.model,base_url=detector.semantic.client.config.base_url)
    package = Path(__import__('guardian_truth').__file__).parent
    config['source_hashes'] = {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(package.glob('*.py'))}
    config['runner_hash'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    config['input_hash'] = hashlib.sha256(args.input.read_bytes()).hexdigest()
    config.update(data_role='development_only',experiment='same_generation_full_claim_gate_vs_overall_gate',
                  skip_mechanical_violations=True,threshold_tuning=False)
    args.output_dir.mkdir(parents=True,exist_ok=True)
    (args.output_dir/'configuration.json').write_text(json.dumps(config,indent=2),encoding='utf-8')
    records, examples, strict_scores, overall_scores = [], [], [], []
    issues = Counter()
    started = time.monotonic()
    with (args.output_dir/'audit.jsonl').open('w',encoding='utf-8') as stream:
        for index,row in enumerate(rows):
            # No label, explanation or ID crosses the inference boundary.
            review = precheck.review(row['prompt'],row['response'])
            skipped = review.status == 'violation'
            if not skipped:
                review = detector.review(row['prompt'],row['response'])
            strict, overall = gate_decisions(review,args.threshold)
            record = {'id':str(row['id']),'label':int(row['label']),'strict':asdict(strict),
                      'overall':asdict(overall),'skipped_mechanical':skipped,'review':asdict(review)}
            stream.write(json.dumps(record,ensure_ascii=False,allow_nan=False)+'\n')
            stream.flush()
            records.append(record)
            issues.update(issue for issue in review.unresolved if issue.startswith(('language_','semantic_')))
            examples.append(Example(str(row['id']),row['prompt'],row['response'],int(row['label']),
                                    group_id=str(row.get('group_id') or str(row['id']).split('::')[0])))
            strict_scores.append(Score(str(row['id']),float(strict.label),fixed_label=strict.label))
            overall_scores.append(Score(str(row['id']),float(overall.label),fixed_label=overall.label))
            print(json.dumps({'completed':index+1,'total':len(rows),'seconds':time.monotonic()-started,
                              'strict_fallback':strict.used_fallback,'overall_fallback':overall.used_fallback,
                              'skipped_mechanical':skipped}),flush=True)
    comparison = paired_comparison(examples,strict_scores,overall_scores,bootstrap_samples=args.bootstrap_samples)
    changed = [{'id':r['id'],'label':r['label'],'strict':r['strict']['label'],'overall':r['overall']['label']}
               for r in records if r['strict']['label'] != r['overall']['label']]
    report = {'configuration':config,'comparison':comparison,'changed':changed,'issues':dict(issues),
              'coverage':{gate:sum(not r[gate]['used_fallback'] for r in records) for gate in ('strict','overall')},
              'skipped_mechanical':sum(r['skipped_mechanical'] for r in records),
              'reported_total_tokens':sum(r['review']['semantic_usage'].get('total_tokens',0) for r in records),
              'budget':detector.semantic.budget.summary() if hasattr(detector.semantic,'budget') else None,
              'limitations':['Same claims-generating prompt; isolates validation, NOT the effect of atomic prompting.',
                             'Overall verdict remains an uncalibrated hypothesis, not a formal proof.',
                             'Development data already inspected; hidden-test transfer not established.',
                             'Fallback outcomes and transport failures are included, not dropped.',
                             'Groups use explicit group_id or the trajectory ID prefix before ::.']}
    (args.output_dir/'report.json').write_text(json.dumps(report,indent=2,allow_nan=False),encoding='utf-8')
    print(json.dumps({'comparison':comparison,'changed':changed,'coverage':report['coverage'],
                      'issues':report['issues']}),flush=True)


if __name__ == '__main__':
    main()
