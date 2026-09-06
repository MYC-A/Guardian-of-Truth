"""Development screening: shared first answer, directed recovery vs plain repeat.

Selection/order are frozen from input IDs before API calls, without using labels
or audit annotations. Every final result, including failures, remains in metrics.
"""

import argparse
from collections import Counter
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path

from guardian_truth.benchmarking import Example, Score, metrics, paired_comparison
from guardian_truth.cli import read_rows, validate_rows
from guardian_truth.decision import decide
from guardian_truth.language import LanguageAnalyzer
from guardian_truth.llm_client import Completion
from guardian_truth.pipeline import Detector
from guardian_truth.runtime import add_runtime_arguments, detector_from_args
from guardian_truth.settings import load_env_file
from guardian_truth.uncertainty import Uncertainty, recovery_action


class CaptureClient:
    def __init__(self, client, replay=None):
        self.client, self.first, self.replay = client, None, replay
        self.calls = 0

    def complete_budgeted(self, messages, *, budget):
        self.calls += 1
        if self.calls == 1 and self.replay is not None:
            # Shared experimental observation, NOT another HTTP request/token bill.
            return Completion(self.replay.content, {})
        result = self.client.complete_budgeted(messages, budget=budget)
        if self.calls == 1:
            self.first = result
        return result


def row_order(row):
    return hashlib.sha256(('uncertainty-screen-v1:' + str(row['id'])).encode()).hexdigest()


def eligible(review):
    if not review.reading_trace:
        return False
    items = [Uncertainty(**item) for item in review.reading_trace[-1].get('uncertainties', [])]
    return recovery_action(items)[1] is not None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--env-file', type=Path, default=Path('.env'))
    parser.add_argument('--limit', type=int)
    parser.add_argument('--bootstrap-samples', type=int, default=1000)
    add_runtime_arguments(parser)
    args = parser.parse_args()
    if args.mode != 'graph' or args.backend == 'none':
        parser.error('This live experiment requires graph mode and groq/local backend')
    if args.limit is not None and args.limit < 1 or args.bootstrap_samples < 1:
        parser.error('Limits must be positive')
    paths = [args.output_dir / name for name in ('configuration.json','audit.jsonl','report.json')]
    if any(path.exists() for path in paths):
        parser.error('Use a fresh output directory')
    if any(path.resolve() in (args.input.resolve(),args.env_file.resolve()) for path in paths):
        parser.error('Output must not overwrite input or credentials')
    rows = read_rows(args.input)
    validate_rows(rows)
    if not rows or any(str(row.get('label')) not in ('0','1') for row in rows):
        parser.error('Nonempty development data with binary labels required')
    rows = sorted(rows, key=row_order)
    if args.limit:
        rows = rows[:args.limit]
    load_env_file(args.env_file)
    args.recovery = 'observe'
    detector = detector_from_args(args)
    semantic = detector.semantic
    precheck = Detector(enabled=detector.enabled)
    decide(precheck.review('', ''), threshold=args.threshold)
    package = Path(__import__('guardian_truth').__file__).parent
    config = {key:getattr(args,key) for key in (
        'backend','mode','checks','max_requests','max_input_chars','seconds','max_rounds',
        'max_evidence_chars','max_prompt_chars','rolling_evidence','max_output_tokens',
        'timeout_seconds','retries','threshold','limit','bootstrap_samples')}
    config.update(model=semantic.client.config.model, base_url=semantic.client.config.base_url,
                  experiment='shared_structured_first_answer_then_directed_vs_plain_repeat',
                  data_role='development_screen_not_independent_test',
                  selection='sha256(uncertainty-screen-v1: + id), ascending, label-blind',
                  selected_ids=[str(row['id']) for row in rows],
                  source_hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(package.glob('*.py'))},
                  runner_hash=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  input_hash=hashlib.sha256(args.input.read_bytes()).hexdigest(),
                  branch_order='alternating directed/repeat by row index',
                  promotion_gate='positive F1 versus initial AND repeat; inspect new FP and reason fidelity; otherwise keep off')
    args.output_dir.mkdir(parents=True, exist_ok=True)
    paths[0].write_text(json.dumps(config, indent=2), encoding='utf-8')
    records, examples = [], []
    with paths[1].open('w', encoding='utf-8') as stream:
        for index, row in enumerate(rows):
            initial = precheck.review(row['prompt'],row['response'])
            skipped = initial.status == 'violation'
            capture = CaptureClient(semantic.client)
            if not skipped:
                analyzer = LanguageAnalyzer(capture, semantic.config, budget=semantic.budget)
                initial = Detector(enabled=detector.enabled, semantic=analyzer).review(row['prompt'],row['response'])
            reviews = {'initial':initial}
            for policy in (('directed','repeat') if index % 2 == 0 else ('repeat','directed')):
                if skipped or capture.first is None or not eligible(initial):
                    reviews[policy] = initial
                    continue
                client = CaptureClient(semantic.client, replay=capture.first)
                analyzer = LanguageAnalyzer(client, replace(semantic.config,recovery=policy), budget=semantic.budget)
                reviews[policy] = Detector(enabled=detector.enabled,semantic=analyzer).review(row['prompt'],row['response'])
            decisions = {key:asdict(decide(review,threshold=args.threshold,use_semantic=True)) for key,review in reviews.items()}
            record = {'id':str(row['id']), 'label':int(row['label']), 'skipped_mechanical':skipped,
                      'decisions':decisions, 'reviews':{key:asdict(review) for key,review in reviews.items()}}
            stream.write(json.dumps(record,ensure_ascii=False,allow_nan=False)+'\n')
            stream.flush()
            records.append(record)
            examples.append(Example(str(row['id']),row['prompt'],row['response'],int(row['label']),
                                    group_id=str(row.get('group_id') or str(row['id']).split('::')[0])))
            print(json.dumps({'completed':index+1,'total':len(rows),
                              'fallback':{key:value['used_fallback'] for key,value in decisions.items()},
                              'budget':semantic.budget.summary()}),flush=True)
    scores = {key:[Score(r['id'],float(r['decisions'][key]['label']),fixed_label=r['decisions'][key]['label'])
                   for r in records] for key in ('initial','directed','repeat')}
    summaries = {}
    for key in scores:
        summaries[key] = metrics([r['label'] for r in records],[r['decisions'][key]['label'] for r in records])
        summaries[key].update(fallback=sum(r['decisions'][key]['used_fallback'] for r in records),
                              explicit_unknown=sum(bool(r['reviews'][key]['reading_trace']) and
                                  r['reviews'][key]['reading_trace'][-1].get('verdict')=='unknown' for r in records),
                              issues=dict(Counter(issue for r in records for issue in r['reviews'][key]['unresolved']
                                                  if issue.startswith(('language_','semantic_')))))
    report = {'configuration':config, 'metrics':summaries,
              'paired':{key:paired_comparison(examples,scores[key],scores['directed'],bootstrap_samples=args.bootstrap_samples)
                        for key in ('initial','repeat')},
              'changed':[{'id':r['id'],'label':r['label'],'decisions':r['decisions']} for r in records
                         if len({item['label'] for item in r['decisions'].values()})>1],
              'budget':semantic.budget.summary(),
              'limitations':['Already inspected development data; no hidden-test transfer claim.',
                             'Initial prompt now requests structured uncertainty; not the old V2 baseline prompt.',
                             'First generation shared exactly; later generations stochastic and not seed-matched.',
                             'Directed bundles diagnosis, focused feedback, optional reading and revisable memory.',
                             'Fallback/generation failures retained; no automatic threshold tuning or promotion.']}
    paths[2].write_text(json.dumps(report,indent=2,allow_nan=False),encoding='utf-8')
    print(json.dumps({'metrics':summaries,'changed':report['changed']}),flush=True)


if __name__ == '__main__':
    main()
