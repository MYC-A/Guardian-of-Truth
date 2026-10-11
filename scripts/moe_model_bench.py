"""Research-only: run the unchanged B2 pipeline (qwen_vllm_adapter + Layers)
against a different vLLM checkpoint and report F1 and timings on a labelled set.

Only identity constants of the adapter are re-pointed (repository, revision,
quantization method, extra server flags); prompts, admission, recovery and the
submission profile (workers/slots/context) stay as in production. Labels are
read only after inference, for scoring. Never part of a submission.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT)]


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1 << 24), b''):
            h.update(block)
    return h.hexdigest()


def asset_manifest(model_dir, repository, revision, output):
    files = sorted(p for p in model_dir.iterdir() if p.is_file() and not p.name.startswith('.'))
    with ThreadPoolExecutor(8) as pool:
        digests = list(pool.map(sha256, files))
    manifest = dict(repository=repository, revision=revision,
                    files=[dict(path=p.name, size=p.stat().st_size, sha256=d) for p, d in zip(files, digests)])
    output.write_text(json.dumps(manifest, indent=1), encoding='utf-8')
    return manifest


def score(labels, predictions):
    tp = sum(1 for k, y in labels.items() if y == 1 and predictions.get(k) == 1)
    fp = sum(1 for k, y in labels.items() if y == 0 and predictions.get(k) == 1)
    fn = sum(1 for k, y in labels.items() if y == 1 and predictions.get(k) != 1)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return dict(tp=tp, fp=fp, fn=fn, tn=len(labels) - tp - fp - fn, precision=round(precision, 4),
                recall=round(recall, 4), f1=round(f1, 4), positives_predicted=tp + fp)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repository', required=True)
    parser.add_argument('--model-dir', type=Path, required=True, help='Directory with config/tokenizer/safetensors')
    parser.add_argument('--quant-methods', default='fp8,compressed-tensors')
    parser.add_argument('--extra-server-arg', action='append', default=[])
    parser.add_argument('--python', required=True, help='Bundled runtime python (platform-identical vLLM)')
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--workers', type=int, default=16)
    parser.add_argument('--slots', type=int, default=16)
    parser.add_argument('--context', type=int, default=32768)
    parser.add_argument('--duration', type=float, default=3600)
    parser.add_argument('--startup-timeout', type=float, default=900)
    parser.add_argument('--timeout', type=float, default=600)
    parser.add_argument('--limit', type=int, default=10**6)
    args = parser.parse_args(argv)

    from scripts import qwen_vllm_adapter as adapter
    from guardian_truth.submission.cli import read_rows
    import pandas as pd

    model_dir = args.model_dir.resolve()
    revision = model_dir.name
    adapter.REPOSITORY, adapter.REVISION = args.repository, revision
    adapter.MODEL = f'{args.repository}@{revision}:vllm-{adapter.ENGINE_VERSION}'
    adapter.QUANT_METHODS = tuple(m for m in args.quant_methods.split(',') if m)
    adapter.EXTRA_SERVER_ARGS = tuple(args.extra_server_arg)

    args.output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    manifest_path = args.output / 'asset_manifest.json'
    asset_manifest(model_dir, args.repository, revision, manifest_path)
    hashing_seconds = time.monotonic() - started

    rows = read_rows(args.input)[:args.limit]
    snapshot = args.output / 'input.parquet'  # id/prompt/response only: labels never reach inference
    pd.DataFrame(rows, columns=['id', 'prompt', 'response']).to_parquet(snapshot, index=False)

    timing = {}
    original_enter = adapter.OwnedVllmServer.__enter__

    def timed_enter(self):
        begin = time.monotonic()
        result = original_enter(self)
        timing['startup_seconds'] = round(time.monotonic() - begin, 1)
        return result
    adapter.OwnedVllmServer.__enter__ = timed_enter

    run_dir = args.output / 'run'
    begin = time.monotonic()
    error = None
    try:
        adapter.main(['--python', args.python, '--model-dir', str(model_dir), '--asset-manifest', str(manifest_path),
                      '--input', str(snapshot), '--output', str(run_dir), '--limit', str(len(rows)),
                      '--workers', str(args.workers), '--slots', str(args.slots), '--context', str(args.context),
                      '--startup-timeout', str(args.startup_timeout), '--duration', str(args.duration),
                      '--timeout', str(args.timeout), '--max-calls', str(10**6)])
    except BaseException as caught:  # keep receipts; report below
        error = f'{type(caught).__name__}: {str(caught)[:300]}'
    total = time.monotonic() - begin

    summary = dict(repository=args.repository, model_dir=str(model_dir), rows=len(rows),
                   workers=args.workers, slots=args.slots, context=args.context,
                   extra_server_args=list(args.extra_server_arg), hashing_seconds=round(hashing_seconds, 1),
                   run_seconds=round(total, 1), error=error, **timing)
    if 'startup_seconds' in timing:
        summary['inference_seconds'] = round(total - timing['startup_seconds'], 1)
    done = run_dir / 'DONE.json'
    if done.exists():
        summary['done'] = json.loads(done.read_text(encoding='utf-8'))
        predictions = pd.read_parquet(run_dir / 'predictions.parquet')
        predicted = dict(zip(predictions['id'].astype(str), predictions['label'].astype(int)))
        labelled = pd.read_parquet(args.input)
        if 'label' in labelled.columns:
            labels = {str(k): int(v) for k, v in zip(labelled['id'], labelled['label']) if str(k) in predicted}
            summary['metrics'] = score(labels, predicted)
        if summary.get('inference_seconds'):
            summary['rows_per_minute'] = round(len(predicted) / summary['inference_seconds'] * 60, 2)
    (args.output / 'summary.json').write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    return 0 if error is None else 1


if __name__ == '__main__':
    raise SystemExit(main())
