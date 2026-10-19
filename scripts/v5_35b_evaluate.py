"""Separate CPU preparation, paired native scoring, and post-freeze gold analysis."""
import argparse
from collections import defaultdict
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'src'), str(ROOT / 'scripts')]
from v5_35b_common import BASE_REVISION, NATIVE_LORA_TARGETS, read, sha, verify_frozen, verify_model, write


def table(path):
    with Path(path).open(encoding='utf-8', newline='') as stream:
        return list(csv.DictReader(stream))


def prepare(a):
    from transformers import AutoTokenizer
    import transformers
    from guardian_truth.judge.mechanical import analyze
    from guardian_truth.judge.prompting import build_prompt
    from scripts.judge_stage import answer_ids
    if transformers.__version__ != '5.8.0':
        raise ValueError('EVAL_PREP_REQUIRES_PRODUCTION_TRANSFORMERS')
    verify_frozen(a.frozen)
    tok = AutoTokenizer.from_pretrained(a.model, local_files_only=True, trust_remote_code=False)
    yes, no = answer_ids(tok)
    sources = {}; joined = []
    valid = {r['id'] for r in table(a.saved / 'valid46_r1/rows.csv')}
    for partition in ('dev', 'holdout', 'regression_seen', 'compli_dev'):
        fresh = partition in ('dev', 'holdout')
        ip = a.frozen / (partition + '_inputs.jsonl') if fresh else a.protected / partition / 'inputs.csv'
        gp = a.frozen / (partition + '.jsonl') if fresh else a.protected / partition / 'labels.jsonl'
        inputs = read(ip) if fresh else table(ip); gold = read(gp)
        if len(inputs) != len(gold):
            raise ValueError('EVAL_INPUT_GOLD_COUNT:' + partition)
        for path in (ip, gp):
            sources[str(path)] = sha(path)
        for row, g in zip(inputs, gold):
            if row['id'] != g['id'] or g['label'] not in (0, 1):
                raise ValueError('EVAL_INPUT_GOLD_ID:' + partition)
            cohorts = [dict(dev='dev152', holdout='hold336', regression_seen='seen397', compli_dev='dev520')[partition]]
            if partition == 'regression_seen':
                if row['id'] in valid:
                    cohorts.append('valid46')
                if g['domain'] in {'ext_tau2', 'hold_tau2h', 'hold_holdout2'}:
                    cohorts.append('real191')
            finding = analyze(row['prompt'], row['response'], False, bounded_turn_shape=True)
            request = dict(prompt=row['prompt'], response=row['response'], hints=finding.hints)
            text, count, trimmed, policy_trimmed = build_prompt(tok, request, 49144)
            ids = tok.encode(text, add_special_tokens=False)
            if len(ids) != count or count > 49150:
                raise ValueError('EVAL_TOKEN_COUNT_DRIFT')
            key = partition + '::' + row['id']
            joined.append((dict(id=key, ids=ids, tokens=count,
                                text_sha256=hashlib.sha256(text.encode()).hexdigest()),
                           dict(id=key, original_id=row['id'], partition=partition, label=g['label'],
                                group=g.get('split_component') or g.get('conversation') or g.get('group') or row['id'],
                                domain=g['domain'], cohorts=cohorts, hard=bool(finding.hard),
                                tokens=count, trimmed=trimmed, policy_trimmed=policy_trimmed)))
    if len(joined) != 1405 or len({r['id'] for r, _ in joined}) != 1405:
        raise ValueError('EVAL_ROW_SET_DRIFT')
    with (a.out / 'tokens.jsonl').open('w', encoding='utf-8') as stream:
        for record, _ in joined:
            stream.write(json.dumps(record) + '\n')
    write(a.out / 'INDEX.json', dict(rows=[r for _, r in joined], source_sha256=sources,
                                    labels_separate_from_model_inputs=True))
    write(a.out / 'PREPARED.json', dict(complete=True, rows=len(joined), base_revision=BASE_REVISION,
        tokens_sha256=sha(a.out / 'tokens.jsonl'), index_sha256=sha(a.out / 'INDEX.json'),
        max_tokens=max(r['tokens'] for r, _ in joined), answer_ids=dict(yes=sorted(yes), no=sorted(no)),
        trimmed_rows=sum(bool(r['trimmed']) for _, r in joined), renderer='production overall/hints-on/legacy',
        fixed_input_cap=49144, production_dynamic_cap_replayed=False,
        model_input_contains_gold=False, human_reviewed=False, source_sha256=sha(Path(__file__))))


def worker(a):
    from vllm import LLM, SamplingParams
    from vllm.lora.request import LoRARequest
    from scripts.judge_stage import answer_ids, answer_score, engine_kwargs
    done = json.loads((a.training / 'TRAINED.json').read_bytes())
    prepared = json.loads((a.data / 'PREPARED.json').read_bytes())
    if not done['complete'] or done['optimizer_updates'] <= 0 or done['base_revision'] != BASE_REVISION:
        raise ValueError('TRAINING_NOT_COMPLETE')
    adapter = a.training / 'adapter'
    if sha(adapter / 'adapter_model.safetensors') != done['adapter_sha256']:
        raise ValueError('TRAINED_ADAPTER_DRIFT')
    if not prepared['complete'] or prepared['base_revision'] != BASE_REVISION or sha(a.data / 'tokens.jsonl') != prepared['tokens_sha256']:
        raise ValueError('EVAL_INPUT_DRIFT')
    verify_model(a.model, a.manifest)
    rows = read(a.data / 'tokens.jsonl')
    allowed = {'id', 'ids', 'tokens', 'text_sha256'}
    if len(rows) != 1405 or any(set(r) != allowed for r in rows):
        raise ValueError('EVAL_INPUT_SCHEMA_OR_COUNT')
    cfg = json.loads((ROOT / 'submission/JUDGE_BLEND40.json').read_bytes())
    cfg.update(max_model_len=49152, gpu_memory_utilization=.85, max_num_seqs=1,
               max_num_batched_tokens=8192, dtype='bfloat16', multimodal=True,
               engine_overrides={'enforce_eager': True})
    kwargs, dropped = engine_kwargs(str(a.model), cfg)
    kwargs.update(enable_lora=True, max_lora_rank=16, max_loras=1, max_cpu_loras=1,
                  lora_target_modules=NATIVE_LORA_TARGETS)
    llm = LLM(**kwargs)
    yes, no = answer_ids(llm.get_tokenizer())
    if sorted(yes) != prepared['answer_ids']['yes'] or sorted(no) != prepared['answer_ids']['no']:
        raise ValueError('EVAL_ANSWER_TOKEN_DRIFT')
    params = SamplingParams(temperature=1.0, top_p=1.0, max_tokens=1, logprobs=20, seed=0,
                            allowed_token_ids=sorted(yes | no))
    started = time.monotonic(); coverage = {}; values = {}
    with (a.out / 'scores.jsonl').open('w', encoding='utf-8', buffering=1) as stream:
        for arm, request in [('base', None), ('adapter', LoRARequest('v5-trained', 1, str(adapter.resolve())))]:
            coverage[arm] = 0; values[arm] = []
            for offset in range(0, len(rows), 8):
                batch = rows[offset:offset + 8]
                outputs = llm.generate([dict(prompt_token_ids=r['ids']) for r in batch], params,
                                       use_tqdm=False, lora_request=request)
                if len(outputs) != len(batch):
                    raise ValueError('EVAL_OUTPUT_COUNT')
                for row, output in zip(batch, outputs):
                    score, exact = answer_score(output, yes, no)
                    if list(output.prompt_token_ids) != row['ids'] or not exact or score is None or not math.isfinite(score):
                        raise ValueError('EVAL_TOKEN_DRIFT_OR_INEXACT_SCORE:' + row['id'])
                    values[arm].append(score)
                    stream.write(json.dumps(dict(id=row['id'], arm=arm, score=score, exact=True,
                                                 tokens=row['tokens'], text_sha256=row['text_sha256'])) + '\n')
                coverage[arm] += len(batch)
                write(a.out / 'PROGRESS.json', dict(coverage=coverage, seconds=time.monotonic() - started))
    effect = max(abs(x - y) for x, y in zip(values['base'], values['adapter']))
    if effect <= .0001:
        raise ValueError('TRAINED_ADAPTER_HAS_NO_NATIVE_EFFECT')
    write(a.out / 'WORKER_DONE.json', dict(complete=True, coverage=coverage, all_exact=True,
        tokens_sha256=prepared['tokens_sha256'], adapter_sha256=done['adapter_sha256'],
        epoch_complete=done['epoch_complete'], epoch_fraction=done['epoch_fraction'],
        max_abs_adapter_effect=effect, seconds=time.monotonic() - started, dropped_engine_kwargs=dropped,
        scores_sha256=sha(a.out / 'scores.jsonl'), source_sha256=sha(Path(__file__)),
        scope='paired classifier-only; not an end-to-end open-review/MAX comparison'))


def score(a):
    from scripts.judge_submission import kill_group
    with (a.out / 'worker.log').open('w', encoding='utf-8') as stream:
        process = subprocess.Popen([sys.executable, str(Path(__file__)), *sys.argv[1:], '--worker'],
            stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            code = process.wait(timeout=7200)
        finally:
            gone = kill_group(process, grace=3)
    if code or not gone:
        raise ValueError('EVAL_WORKER_FAILED:' + str(code))
    result = json.loads((a.out / 'WORKER_DONE.json').read_bytes())
    result['group_gone'] = gone
    write(a.out / 'DONE.json', result)


def analyze_scores(a):
    from v3_analyze_hours import metrics, quota, paired_ci
    done = json.loads((a.run / 'DONE.json').read_bytes())
    prep = json.loads((a.data / 'PREPARED.json').read_bytes())
    if not done['complete'] or not done['all_exact'] or sha(a.run / 'scores.jsonl') != done['scores_sha256']:
        raise ValueError('INCOMPLETE_EVAL')
    if sha(a.data / 'INDEX.json') != prep['index_sha256'] or done['tokens_sha256'] != prep['tokens_sha256']:
        raise ValueError('EVAL_ANALYSIS_IDENTITY_DRIFT')
    index = json.loads((a.data / 'INDEX.json').read_bytes())['rows']
    scores = read(a.run / 'scores.jsonl'); lookup = {(r['arm'], r['id']): r['score'] for r in scores}
    if len(lookup) != len(scores) or len(scores) != 2 * len(index):
        raise ValueError('PAIRED_COVERAGE_DRIFT')
    cohorts = defaultdict(list)
    for r in index:
        for name in r['cohorts']:
            cohorts[name].append(r)
    result = dict(status='EXPLORATORY_ONLY_HUMAN_UNVERIFIED', classifier_only=True,
                  end_to_end_R0_improvement_measured=False, private_improvement_measured=False,
                  quota=.40, checkpoint_selection_on_holdout=False, datasets={})
    for name, rows in cohorts.items():
        y = [r['label'] for r in rows]; hard = {i for i, r in enumerate(rows) if r['hard']}
        arms = {arm: [lookup[arm, r['id']] for r in rows] for arm in ('base', 'adapter')}
        predictions = {arm: quota(v, hard, .40) for arm, v in arms.items()}
        old, new = predictions['base'], predictions['adapter']
        result['datasets'][name] = dict(rows=len(rows), positive=sum(y),
            metrics={arm: metrics(y, p) for arm, p in predictions.items()},
            changes=dict(fp_removed=sum(b == 1 and n == 0 and label == 0 for b, n, label in zip(old, new, y)),
                         fp_added=sum(b == 0 and n == 1 and label == 0 for b, n, label in zip(old, new, y)),
                         tp_gained=sum(b == 0 and n == 1 and label == 1 for b, n, label in zip(old, new, y)),
                         tp_lost=sum(b == 1 and n == 0 and label == 1 for b, n, label in zip(old, new, y))),
            diagnostic_quotas={str(q): {arm: metrics(y, quota(v, hard, q)) for arm, v in arms.items()} for q in (.30, .50)},
            paired=paired_ci(y, arms['base'], arms['adapter'], [r['group'] for r in rows], hard))
        write(a.out / 'RESULTS.json', result)
    write(a.out / 'DONE.json', dict(complete=True, source_sha256=sha(Path(__file__)), scores_sha256=done['scores_sha256']))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=('prepare', 'score', 'analyze'))
    for name in ('model', 'manifest', 'frozen', 'protected', 'saved', 'data', 'training', 'run', 'out'):
        parser.add_argument('--' + name, type=Path, required=name == 'out')
    parser.add_argument('--worker', action='store_true')
    a = parser.parse_args(); csv.field_size_limit(2**31 - 1)
    if not a.worker:
        a.out.mkdir(exist_ok=False)
    try:
        if a.worker:
            if a.mode != 'score':
                raise ValueError('INVALID_WORKER_MODE')
            worker(a); sys.stdout.flush(); sys.stderr.flush(); os._exit(0)
        {'prepare': prepare, 'score': score, 'analyze': analyze_scores}[a.mode](a)
    except Exception as error:
        write(a.out / ('WORKER_FAIL.json' if a.worker else 'FAIL.json'),
              dict(complete=False, error_type=type(error).__name__, error=str(error), traceback=traceback.format_exc()))
        if a.worker:
            traceback.print_exc(); sys.stdout.flush(); sys.stderr.flush(); os._exit(1)
        raise


if __name__ == '__main__':
    main()
