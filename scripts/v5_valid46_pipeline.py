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
BASELINE_CONFIG_SHA = '413f663a1c5421ddbd7f1dceb1ad5442e85a1a4b557e5eef1366a6b6ced5ed36'


def pipeline_config(model):
    cfg = json.loads((ROOT / 'submission/JUDGE_OPEN_REVIEW40.json').read_bytes())
    digest = hashlib.sha256(json.dumps(cfg, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    if digest != BASELINE_CONFIG_SHA:
        raise ValueError('BEST_ZIP_CONFIG_DRIFT')
    cfg.update(model_dir=str(model), bounded_turn_shape=True,
               engine_overrides=dict(enforce_eager=True, async_scheduling=False))
    return cfg


def binding_probe(worker, adapter_path):
    """Read-only worker proof: source modules survive packing and match GPU buffers."""
    from pathlib import Path
    import torch
    from safetensors import safe_open
    manager = worker.model_runner.lora_manager._adapter_manager
    loaded = manager.get_adapter(1)
    if loaded is None or 1 not in manager.lora_index_to_id:
        raise ValueError('ADAPTER_NOT_ACTIVE_ON_WORKER')
    slot = manager.lora_index_to_id.index(1)
    def suffix(name): return 'layers.' + name.split('.layers.', 1)[1]
    with safe_open(str(Path(adapter_path) / 'adapter_model.safetensors'), framework='pt') as f:
        expected = {suffix(k.rsplit('.lora_A.', 1)[0]) for k in f.keys() if '.lora_A.' in k}
    covered = set(); checked = []; errors = []
    for name, weights in loaded.loras.items():
        module = manager.modules.get(name)
        if module is None:
            errors.append('UNBOUND_MODULE:' + name); continue
        aa, bb = weights.lora_a, weights.lora_b
        packed = isinstance(aa, list)
        sources = manager.packed_modules.get(name, [name]) if packed else [name]
        al = aa if packed else [aa]
        bl = bb if isinstance(bb, list) else [bb]
        if len(sources) != len(al):
            errors.append('PACKED_SOURCE_COUNT:' + name); continue
        for source, a, b in zip(sources, al, bl):
            if a is not None and b is not None: covered.add(suffix(source))
        ga = list(module.lora_a_stacked); gb = list(module.lora_b_stacked)
        if not packed and len(ga) > 1:
            al = [aa] * len(ga)
            sizes = list(module.base_layer.output_sizes)
            bl = list(torch.split(bb, sizes, dim=0))
        if len(al) != len(ga) or len(bl) != len(gb):
            errors.append('GPU_SLICE_COUNT:' + name); continue
        for i, (a, b) in enumerate(zip(al, bl)):
            if a is None or b is None: continue
            av = ga[i][slot, 0, :a.shape[0], :a.shape[1]]
            bv = gb[i][slot, 0, :b.shape[0], :b.shape[1]]
            ae = torch.equal(av, a.to(device=av.device, dtype=av.dtype))
            be = torch.equal(bv, b.to(device=bv.device, dtype=bv.dtype))
            checked.append(dict(module=name, slice=i, a_equal=ae, b_equal=be))
            if not ae or not be: errors.append('GPU_WEIGHT_MISMATCH:' + name)
    if covered != expected: errors.append('SOURCE_COVERAGE_MISMATCH')
    return dict(complete=not errors, expected_modules=len(expected), covered_modules=len(covered),
                packed_modules=len(loaded.loras), gpu_pairs_checked=len(checked),
                missing_sources=sorted(expected-covered), extra_sources=sorted(covered-expected),
                errors=errors, checks=checked, target_filter=manager.lora_config.target_modules)


def repair_shared_aliases(worker, adapter_path):
    """Remove only duplicate registrations sharing the exact same GPU storage."""
    from pathlib import Path
    from safetensors import safe_open
    manager = worker.model_runner.lora_manager._adapter_manager
    def suffix(name): return 'layers.' + name.split('.layers.', 1)[1]
    with safe_open(str(Path(adapter_path) / 'adapter_model.safetensors'), framework='pt') as f:
        expected = {suffix(k.rsplit('.lora_A.', 1)[0]) for k in f.keys() if '.lora_A.' in k}
    groups = {}
    for name, module in manager.modules.items():
        pointers = tuple(t.untyped_storage().data_ptr() for t in
                         [*module.lora_a_stacked, *module.lora_b_stacked])
        groups.setdefault(pointers, []).append(name)
    removed = []; details = []
    for names in groups.values():
        if len(names) < 2: continue
        candidates = [name for name in names if any(suffix(s) in expected for s in
                       manager.packed_modules.get(name, [name]))]
        if not candidates: continue
        if len(candidates) != 1 or '.shared_expert.' not in candidates[0]:
            raise ValueError('AMBIGUOUS_GPU_ALIAS_REPAIR')
        canonical = candidates[0]
        if any('shared_expert' not in name for name in names):
            raise ValueError('UNEXPECTED_NON_SHARED_ALIAS')
        details.append(dict(canonical=canonical, aliases=names, shared_gpu_storage=True))
        for name in names:
            if name == canonical: continue
            manager.modules.pop(name); manager.packed_modules.pop(name, None); removed.append(name)
    if not removed:
        raise ValueError('NO_SHARED_GPU_ALIAS_TO_REPAIR')
    manager.deactivate_adapter(1)
    manager.activate_adapter(1)
    return dict(complete=True, removed_count=len(removed), removed=removed, groups=details,
                weights_modified=False, base_model_modified=False)


def bound_llm(original, request, audit_path, binding_adapter=None):
    """Every generation, including review and probes, uses the same arm."""
    class Bound(original):
        def __init__(self, *args, **kwargs):
            self.binding_checked = False
            kwargs.update(enable_lora=True, max_lora_rank=16, max_loras=1,
                          max_cpu_loras=1, lora_target_modules=NATIVE_LORA_TARGETS)
            super().__init__(*args, **kwargs)

        def generate(self, prompts, params, **kwargs):
            if 'lora_request' in kwargs:
                raise ValueError('UNEXPECTED_NESTED_LORA_REQUEST')
            result = super().generate(prompts, params, lora_request=request, **kwargs)
            regenerated = False
            if request is not None and binding_adapter is not None and not self.binding_checked:
                proof = self.collective_rpc(binding_probe, timeout=60, args=(str(binding_adapter),))
                if len(proof) == 1 and not proof[0]['complete']:
                    write(Path(audit_path).with_name('ADAPTER_BINDING_BEFORE.json'), proof)
                    if not proof[0].get('errors') or any(not e.startswith('GPU_WEIGHT_MISMATCH:') or '.shared_expert.' not in e for e in proof[0]['errors']):
                        raise ValueError('UNRECOGNIZED_ADAPTER_BINDING_FAILURE')
                    if len(prompts) != 1 or params.max_tokens != 1:
                        raise ValueError('ALIAS_REPAIR_ONLY_AT_TECHNICAL_PROBE')
                    repair = self.collective_rpc(repair_shared_aliases, timeout=60, args=(str(binding_adapter),))
                    write(Path(audit_path).with_name('SHARED_ALIAS_REPAIR.json'), repair)
                    proof = self.collective_rpc(binding_probe, timeout=60, args=(str(binding_adapter),))
                    regenerated = True
                write(Path(audit_path).with_name('ADAPTER_BINDING.json'), proof)
                if len(proof) != 1 or not proof[0]['complete'] or proof[0]['expected_modules'] != 50:
                    raise ValueError('FULL_ADAPTER_GPU_BINDING_NOT_PROVEN')
                self.binding_checked = True
                if regenerated:
                    # The original result was only the technical exactness probe.
                    # Return a fresh probe with all source weights actually active.
                    result = super().generate(prompts, params, lora_request=request, **kwargs)
            with Path(audit_path).open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(dict(adapter_applied=request is not None,
                    prompts=len(prompts), outputs=len(result), max_tokens=params.max_tokens,
                    extra_technical_probe_prompts=len(prompts) if regenerated else 0,
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
    vllm.LLM = bound_llm(vllm.LLM, request, os.environ['V5_PIPELINE_AUDIT'], binding_adapter=adapter)
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
                   V5_PIPELINE_AUDIT=str(a.out / 'generation_audit.jsonl'),
                   VLLM_ALLOW_INSECURE_SERIALIZATION='1')
        if a.kernel_cache is not None:
            env.update(TRITON_CACHE_DIR=str(a.kernel_cache / 'triton'),
                       TORCHINDUCTOR_CACHE_DIR=str(a.kernel_cache / 'torchinductor'))
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
    if arm == 'adapter':
        proof = json.loads((out / 'ADAPTER_BINDING.json').read_bytes())
        if len(proof) != 1 or not proof[0]['complete']:
            raise ValueError('INCOMPLETE_WORKER_BINDING')
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
        # Start from the actual best ZIP profile, including its batch sizes,
        # deadlines and legacy review citation contract, plus mechanical fixes.
        cfg = pipeline_config(a.lab / 'models/qwen36-awq')
        write(a.out / 'config.json', cfg)
        write(a.out / 'START.json', dict(rows=46, inputs_sha256=sha(a.out / 'inputs.csv'),
            config_sha256=sha(a.out / 'config.json'), adapter_sha256=ADAPTER_SHA,
            baseline_zip='guardian-judge-qwen36-awq-open-review40-max-34fb1c75-20261018.zip',
            baseline_config_canonical_sha256=BASELINE_CONFIG_SHA,
            reused_kernel_cache=str(a.kernel_cache) if a.kernel_cache else None,
            runtime_deviation='eager synchronous scheduling in both arms; LoRA enabled in control too',
            auxiliary_4b=False, arms=['base', 'adapter'], repeats=1, quality_retries=0,
            source_sha256=sha(Path(__file__)), scope='35B overall + open review + MAX + mechanical fixes; valid46 only'))
        collected = {}
        for arm in ('base', 'adapter'):
            out = a.out / arm; out.mkdir()
            if arm == 'base' and a.reuse_base is not None:
                import shutil
                old = a.reuse_base
                if sha(old / 'config.json') != sha(a.out / 'config.json') or sha(old / 'inputs.csv') != sha(a.out / 'inputs.csv'):
                    raise ValueError('TECHNICAL_REUSE_INPUT_OR_CONFIG_DRIFT')
                validate_arm(old / 'base', 'base', rows)
                shutil.copytree(old / 'base', out, dirs_exist_ok=True, ignore=shutil.ignore_patterns('cache'))
                labels, decisions, receipt = validate_arm(out, 'base', rows)
                collected['base'] = dict(labels=labels, decisions=decisions, receipt=receipt)
                write(a.out / 'REUSED_BASE.json', dict(source=str(old / 'base'),
                    scores_sha256=sha(out / 'work/scores.jsonl'), reason='read-only worker binding audit after warning; no base configuration change'))
                continue
            write(a.out / 'PROGRESS.json', dict(arm=arm, phase='running', seconds=time.monotonic()-started))
            command = [sys.executable, str(Path(__file__)), 'arm', '--arm', arm, '--training', str(a.training),
                '--input', str(a.out / 'inputs.csv'), '--config', str(a.out / 'config.json'), '--out', str(out)]
            if a.kernel_cache is not None:
                if not a.kernel_cache.is_dir(): raise ValueError('MISSING_KERNEL_CACHE')
                command += ['--kernel-cache', str(a.kernel_cache)]
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
            runtime_deviation='eager synchronous scheduling and LoRA-capable control', seconds=time.monotonic()-started)
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
    r.add_argument('--reuse-base', type=Path)
    ar = s.add_parser('arm'); ar.add_argument('--arm', choices=['base', 'adapter'], required=True)
    for n in ('input', 'config'): ar.add_argument('--'+n, type=Path, required=True)
    for parser in (r, ar):
        for n in ('training', 'out'): parser.add_argument('--'+n, type=Path, required=True)
        parser.add_argument('--kernel-cache', type=Path)
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
