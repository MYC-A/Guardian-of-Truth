"""Isolated full 35B pipeline comparison; production sources stay unchanged."""
import argparse
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'src')]
from scripts.v5_35b_common import BASE_REVISION, NATIVE_LORA_TARGETS, sha, verify_model, write

ADAPTER_SHA = 'eb7cee08c0a00c29ad1d21904aa94d29f4f83f126d53e1438dd65ef85a34ba4f'


def bound_llm(original, request, audit_path):
    """Every generation, including review and probes, uses the same arm."""
    class Bound(original):
        def __init__(self, *args, **kwargs):
            kwargs.update(enable_lora=True, max_lora_rank=16, max_loras=1,
                          max_cpu_loras=1, lora_target_modules=NATIVE_LORA_TARGETS)
            super().__init__(*args, **kwargs)

        def generate(self, prompts, params, **kwargs):
            if 'lora_request' in kwargs:
                raise ValueError('UNEXPECTED_NESTED_LORA_REQUEST')
            result = super().generate(prompts, params, lora_request=request, **kwargs)
            with Path(audit_path).open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(dict(adapter_applied=request is not None,
                    prompts=len(prompts), outputs=len(result), max_tokens=params.max_tokens,
                    inputs_sha256=hashlib.sha256(json.dumps(prompts, sort_keys=True,
                        ensure_ascii=True, separators=(',', ':')).encode()).hexdigest())) + '\n')
            return result
    return Bound


def stage():
    import vllm
    from vllm.lora.request import LoRARequest
    from scripts import judge_stage
    arm = os.environ['V5_PIPELINE_ARM']
    adapter = Path(os.environ['V5_PIPELINE_ADAPTER'])
    if arm not in ('base', 'adapter') or sha(adapter / 'adapter_model.safetensors') != ADAPTER_SHA:
        raise ValueError('PIPELINE_ADAPTER_OR_ARM_DRIFT')
    request = None if arm == 'base' else LoRARequest('v5-full-pipeline', 1, str(adapter.resolve()))
    vllm.LLM = bound_llm(vllm.LLM, request, os.environ['V5_PIPELINE_AUDIT'])
    judge_stage.main()
    sys.stdout.flush(); sys.stderr.flush(); os._exit(0)


def arm_run(a):
    from scripts import judge_submission as primary
    original = primary.prepare_stage

    def prepare(*args, **kwargs):
        command, env, scores, model = original(*args, **kwargs)
        command[1] = str(Path(__file__).resolve())
        env.update(V5_PIPELINE_STAGE='1', V5_PIPELINE_ARM=a.arm,
                   V5_PIPELINE_ADAPTER=str(a.training / 'adapter'),
                   V5_PIPELINE_AUDIT=str(a.out / 'generation_audit.jsonl'))
        return command, env, scores, model

    primary.prepare_stage = prepare
    code = primary.run(ROOT, a.input, a.out / 'predictions.csv', work=a.out / 'work',
                       config=a.config, started_wall=time.time(), watchdog=False)
    if code:
        raise RuntimeError('PRIMARY_RETURN_CODE:' + str(code))


def metrics(rows, gold, labels):
    tp = sum(gold[r['id']] == 1 and y == 1 for r, y in zip(rows, labels))
    fp = sum(gold[r['id']] == 0 and y == 1 for r, y in zip(rows, labels))
    fn = sum(gold[r['id']] == 1 and y == 0 for r, y in zip(rows, labels))
    return dict(tp=tp, fp=fp, fn=fn, tn=len(rows)-tp-fp-fn,
                precision=tp/(tp+fp) if tp+fp else 0,
                recall=tp/(tp+fn) if tp+fn else 0,
                f1=2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else 0)


def validate_arm(out, arm, rows):
    from scripts import judge_submission as primary
    work = out / 'work'
    scores, missing, inexact, events = primary.read_scores(work / 'scores.jsonl', exact_only=True)
    final = primary.read_review_scores(work / 'scores.jsonl', isolate_duplicates=True)
    if set(scores) != set(range(46)) or set(final) != set(range(46)) or missing or inexact:
        raise ValueError('INCOMPLETE_EXACT_PIPELINE_COVERAGE:' + arm)
    if 'done' not in events or events.get('failed'):
        raise ValueError('STAGE_DID_NOT_COMPLETE:' + arm)
    audit = [json.loads(line) for line in (out / 'generation_audit.jsonl').read_bytes().splitlines()]
    if not audit or any(x['adapter_applied'] != (arm == 'adapter') for x in audit):
        raise ValueError('LORA_NOT_APPLIED_TO_EVERY_CALL:' + arm)
    if not any(x['max_tokens'] > 1 for x in audit):
        raise ValueError('GENERATIVE_REVIEW_NOT_RUN:' + arm)
    with (out / 'predictions.csv').open(newline='', encoding='utf-8') as f:
        predictions = list(csv.DictReader(f))
    if [r['id'] for r in predictions] != [r['id'] for r in rows]:
        raise ValueError('PREDICTION_ORDER_DRIFT')
    labels = [int(r['label']) for r in predictions]
    decisions = [json.loads(line) for line in (work / 'decisions.jsonl').read_bytes().splitlines()]
    if len(decisions) != 46 or any(d['ranking'] != 'max_exact_overall_final' for d in decisions):
        raise ValueError('RANKING_DRIFT')
    if any(y not in (0, 1) for y in labels) or any(not math.isfinite(s) for s in [*scores.values(), *final.values()]):
        raise ValueError('INVALID_LABEL_OR_SCORE')
    return labels, decisions, dict(primary_exact=46, final_exact=46, audit_calls=len(audit),
                                  generation_prompts=sum(x['prompts'] for x in audit))


def run(a):
    a.out.mkdir(exist_ok=False)
    started = time.monotonic()
    try:
        if subprocess.check_output(['nvidia-smi', '--query-gpu=memory.used', '--format=csv,noheader,nounits'], text=True).strip() != '0':
            raise RuntimeError('GPU_BUSY')
        verify_model(a.lab / 'models/qwen36-awq', a.training.parent / 'BASE_MODEL_MANIFEST.json')
        trained = json.loads((a.training / 'TRAINED.json').read_bytes())
        if not trained['epoch_complete'] or trained['rows_done'] != 1458 or trained['base_revision'] != BASE_REVISION:
            raise ValueError('FULL_TRAINING_NOT_VERIFIED')
        if trained['adapter_sha256'] != ADAPTER_SHA or sha(a.training / 'adapter/adapter_model.safetensors') != ADAPTER_SHA:
            raise ValueError('ADAPTER_IDENTITY_DRIFT')
        csv.field_size_limit(2**31-1)
        with (a.lab / 'runs/valid46_r1/rows.csv').open(newline='') as f:
            valid = {r['id'] for r in csv.DictReader(f)}
        data = a.lab / 'data/guardian-judge-eval-data-v1/regression_seen'
        with (data / 'inputs.csv').open(newline='') as f:
            rows = [{k:r[k] for k in ('id', 'prompt', 'response')} for r in csv.DictReader(f) if r['id'] in valid]
        if len(rows) != len(valid) or len(rows) != 46:
            raise ValueError('VALID46_IDENTITY')
        with (a.out / 'inputs.csv').open('w', newline='') as f:
            w = csv.DictWriter(f, fieldnames=['id', 'prompt', 'response']); w.writeheader(); w.writerows(rows)
        cfg = json.loads((ROOT / 'submission/JUDGE_BLEND40.json').read_bytes())
        cfg.pop('ensemble')
        cfg['model_dir'] = str(a.lab / 'models/qwen36-awq')
        # GDN LoRA was technically admitted with synchronous scheduling.
        # Apply the same single runtime deviation to both arms.
        cfg['engine_overrides'] = dict(cfg['engine_overrides'], async_scheduling=False)
        write(a.out / 'config.json', cfg)
        write(a.out / 'START.json', dict(rows=46, inputs_sha256=sha(a.out / 'inputs.csv'),
            config_sha256=sha(a.out / 'config.json'), adapter_sha256=ADAPTER_SHA,
            runtime_deviation='async_scheduling=false in both arms; LoRA enabled in control too',
            auxiliary_4b=False, arms=['base', 'adapter'], repeats=1, quality_retries=0,
            source_sha256=sha(Path(__file__)), scope='35B overall + open review + MAX + mechanical fixes; valid46 only'))
        collected = {}
        for arm in ('base', 'adapter'):
            out = a.out / arm; out.mkdir()
            write(a.out / 'PROGRESS.json', dict(arm=arm, phase='running', seconds=time.monotonic()-started))
            command = [sys.executable, str(Path(__file__)), 'arm', '--arm', arm, '--training', str(a.training),
                '--input', str(a.out / 'inputs.csv'), '--config', str(a.out / 'config.json'), '--out', str(out)]
            env = dict(os.environ, HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', PYTHON_DOTENV_DISABLED='1')
            with (out / 'predict.log').open('w', buffering=1) as log:
                child = subprocess.Popen(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                try:
                    code = child.wait(timeout=1790)
                except subprocess.TimeoutExpired:
                    from scripts.judge_submission import kill_group
                    kill_group(child); raise
            if code:
                raise RuntimeError('ARM_EXIT:' + arm + ':' + str(code))
            labels, decisions, receipt = validate_arm(out, arm, rows)
            collected[arm] = dict(labels=labels, decisions=decisions, receipt=receipt)
            write(out / 'DONE.json', receipt)
        if sha(a.out / 'base/work/stage_input.jsonl') != sha(a.out / 'adapter/work/stage_input.jsonl'):
            raise ValueError('STAGE_INPUTS_DIFFER')
        # Load labels only after both inference arms have completed.
        gold = {r['id']:r['label'] for r in [json.loads(x) for x in (data / 'labels.jsonl').read_bytes().splitlines()]}
        result = dict(complete=True, scope='valid46 explored regression; full 35B pipeline, no 4B',
            quota=.4, metrics={arm:metrics(rows, gold, z['labels']) for arm,z in collected.items()},
            coverage={arm:z['receipt'] for arm,z in collected.items()},
            changed=[dict(id=r['id'], gold=gold[r['id']], base=collected['base']['labels'][i],
                adapter=collected['adapter']['labels'][i]) for i,r in enumerate(rows)
                if collected['base']['labels'][i] != collected['adapter']['labels'][i]],
            private_improvement_measured=False, production_promoted=False,
            runtime_deviation='synchronous scheduling and LoRA-capable control', seconds=time.monotonic()-started)
        write(a.out / 'DONE.json', result)
    except Exception as error:
        import traceback
        write(a.out / 'FAIL.json', dict(error=str(error), traceback=traceback.format_exc(), seconds=time.monotonic()-started))
        raise


def main():
    if os.environ.get('V5_PIPELINE_STAGE') == '1':
        stage(); return
    p = argparse.ArgumentParser(); s = p.add_subparsers(dest='mode', required=True)
    r = s.add_parser('run'); r.add_argument('--lab', type=Path, required=True)
    ar = s.add_parser('arm'); ar.add_argument('--arm', choices=['base', 'adapter'], required=True)
    for n in ('input', 'config'): ar.add_argument('--'+n, type=Path, required=True)
    for parser in (r, ar):
        for n in ('training', 'out'): parser.add_argument('--'+n, type=Path, required=True)
    a = p.parse_args()
    if a.mode == 'run':
        try:
            run(a)
        finally:
            if a.out.exists():
                import tarfile
                archive = a.out.parent / (a.out.name + '-export.tar.gz')
                def exclude_cache(member):
                    return None if 'cache' in Path(member.name).parts else member
                with tarfile.open(archive, 'w:gz', compresslevel=3) as tar:
                    tar.add(a.out, arcname='pipeline', filter=exclude_cache)
                write(a.out.parent / (a.out.name + '-export.INDEX.json'), dict(
                    name=archive.name, bytes=archive.stat().st_size, sha256=sha(archive),
                    quality_complete=(a.out / 'DONE.json').exists(), failure_recorded=(a.out / 'FAIL.json').exists()))
    else:
        arm_run(a)


if __name__ == '__main__': main()
