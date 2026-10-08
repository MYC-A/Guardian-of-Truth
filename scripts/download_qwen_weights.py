"""Download the exact public Q8 checkpoint with the official resumable Xet SDK.

Operator-only dependencies stay outside the final offline submission package.
No server credentials or existing Hugging Face token are used.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import threading
import time

REPO = 'ggml-org/Qwen3.8-27B-GGUF'
REVISION = '71bc7b627595dc8a91039addd9c791ae548d6747'
FILENAME = 'Qwen3.8-27B-Q8_0.gguf'
SIZE = 28595763648
SHA256 = 'aab65c67ef0dad127960efef9247f1832bca105faa1c7a052cc039b223cf86a1'


def monitor_xet_progress(reporter, save, *, interval=10):
    """Instrument the next SDK run with numeric payload counters only.

    The operator owns this single-process SDK invocation. Preserve its original
    progress callback and return a restoration hook; neither SDK requests nor
    reconstruction behavior is changed.
    """
    original = reporter.update_progress
    lock = threading.Lock()
    last = [float('-inf')]

    def update(instance, report, *args, **kwargs):
        result = original(instance, report, *args, **kwargs)
        now = time.monotonic()
        with lock:
            if now - last[0] < interval:
                return result
            last[0] = now
            counters = {}
            for output, name in (
                ('received_bytes', 'total_transfer_bytes_completed'),
                ('reconstructed_bytes', 'total_bytes_completed'),
                ('transfer_bytes_per_second', 'total_transfer_bytes_completion_rate'),
            ):
                value = getattr(report, name, None)
                if type(value) in (int, float) and value >= 0:
                    counters[output] = value
            try:
                save('DOWNLOADING_PUBLIC_MODEL', **counters)
            except OSError:
                # A monitoring write failure must not change an active transfer;
                # final size/hash verification and READY still require save().
                pass
        return result

    reporter.update_progress = update
    return lambda: setattr(reporter, 'update_progress', original)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--directory', type=Path, required=True)
    ap.add_argument('--operator-libs', type=Path)
    a = ap.parse_args()
    if a.operator_libs:
        sys.path.insert(0, str(a.operator_libs))
    os.environ.setdefault('HF_XET_HIGH_PERFORMANCE', '1')
    os.environ.setdefault('HF_XET_CHUNK_CACHE_SIZE_BYTES', '0')
    os.environ.setdefault('HF_XET_CACHE', str(a.directory / '.xet-cache'))
    os.environ.setdefault('HF_HUB_DISABLE_TELEMETRY', '1')
    from huggingface_hub import hf_hub_download
    import importlib.metadata
    a.directory.mkdir(parents=True, exist_ok=True)
    status = a.directory / 'download.json'
    ownership = a.directory / 'download.lock'
    started = time.monotonic()
    def save(state, **more):
        value = dict(state=state, pid=os.getpid(), repo=REPO, revision=REVISION,
                     expected_bytes=SIZE, expected_sha256=SHA256,
                     elapsed_seconds=time.monotonic()-started,
                     versions={n: importlib.metadata.version(n) for n in ('huggingface_hub', 'hf-xet')}, **more)
        temp = status.with_suffix('.json.new')
        temp.write_text(json.dumps(value, indent=2), encoding='utf-8')
        os.replace(temp, status)
    with ownership.open('x', encoding='utf-8') as f:
        json.dump(dict(pid=os.getpid()), f)
    restore_monitor = None
    try:
        save('DOWNLOADING_PUBLIC_MODEL')
        from huggingface_hub.utils._xet_progress_reporting import XetDownloadProgressReporter
        restore_monitor = monitor_xet_progress(XetDownloadProgressReporter, save)
        model = Path(hf_hub_download(repo_id=REPO, filename=FILENAME, revision=REVISION,
                                     local_dir=a.directory, token=False))
        save('VERIFYING_MODEL', path=str(model))
        if model.stat().st_size != SIZE:
            raise ValueError('MODEL_SIZE_MISMATCH')
        digest = hashlib.sha256()
        with model.open('rb') as source:
            for part in iter(lambda: source.read(8*1024*1024), b''):
                digest.update(part)
        if digest.hexdigest() != SHA256:
            raise ValueError('MODEL_HASH_MISMATCH')
        save('READY', path=str(model.resolve()), bytes=SIZE, sha256=SHA256)
        print(status.read_text(encoding='utf-8'))
    except BaseException as e:
        # Transport errors may contain transient signed URLs. Retain only type.
        save('FAILED', error=type(e).__name__)
        raise RuntimeError('PUBLIC_MODEL_DOWNLOAD_FAILED: ' + type(e).__name__) from None
    finally:
        if restore_monitor is not None:
            restore_monitor()
        ownership.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
