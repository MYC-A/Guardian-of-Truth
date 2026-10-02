"""Original-model availability attempts with bounded disk use and journals."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

OUT = Path('/workspace/guardian/results/modular_steps_20261002/model_setup')
OUT.mkdir(parents=True, exist_ok=True)


def save(name, payload):
    (OUT / (name + '.json')).write_text(json.dumps(payload, indent=2) + '\n')


def deduplicate_own_factcg():
    # Prior task created the duplicate cache. Only byte-identical OWN FactCG
    # blobs are replaced atomically by a hardlink; all model paths preserved.
    candidates = []
    for root in (Path('/workspace/.hf_home'), Path('/workspace/guardian/hf_cache')):
        for file in root.rglob('*'):
            if file.is_file() and not file.is_symlink() and file.stat().st_size > 500_000_000 and '/blobs/' in str(file):
                h = hashlib.sha256()
                with file.open('rb') as f:
                    for block in iter(lambda: f.read(8 << 20), b''):
                        h.update(block)
                candidates.append((file, h.hexdigest(), file.stat()))
    operations = []
    for a, ah, ast in candidates:
        for b, bh, bst in candidates:
            if '/workspace/.hf_home/' not in str(b) or a == b or ah != bh or ast.st_dev != bst.st_dev or ast.st_ino == bst.st_ino:
                continue
            if '/workspace/guardian/hf_cache/' not in str(a):
                continue
            temp = b.with_name(b.name + '.modular-hardlink')
            os.link(a, temp)
            os.replace(temp, b)
            assert a.stat().st_ino == b.stat().st_ino
            operations.append({'source': str(a), 'duplicate_path_preserved': str(b), 'sha256': ah, 'bytes_saved': ast.st_size})
    save('own_factcg_deduplication', {'operations': operations, 'free_bytes': shutil.disk_usage('/workspace').free})


def ccg():
    import gdown
    record = {'method': 'original EasyCCG pretrained model', 'attempts': []}
    try:
        files = gdown.download_folder(url='https://drive.google.com/drive/folders/0B7AY6PGZ8lc-NGVOcUFXNU5VWXc',
                                     skip_download=True, quiet=True)
        record['files'] = [{'id': f.id, 'path': f.path} for f in files or []]
        save('ccg_model_attempt', record)
        # Original folder may contain several large models. Only default model.
        choices = [f for f in files or [] if Path(f.path).name in ('model.tar.gz', 'model.tgz', 'model.zip')]
        if not choices:
            record.update(status='BLOCKED', reason='original_folder_unavailable_or_no_default_model_archive')
        else:
            selected = choices[0]
            path = Path('/workspace/guardian/third_party_modular_20261002/easyccg') / Path(selected.path).name
            gdown.download(id=selected.id, output=str(path), quiet=True)
            record.update(status='DOWNLOADED', archive=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    except Exception as exc:
        record.update(status='BLOCKED', reason=type(exc).__name__, public_download_error=str(exc)[:1200])
    save('ccg_model_attempt', record)
    if shutil.which('java') is None:
        with (OUT / 'java_install.log').open('w') as log:
            r = subprocess.run(['apt-get', 'update'], stdout=log, stderr=subprocess.STDOUT, timeout=180)
            if r.returncode == 0:
                r = subprocess.run(['apt-get', 'install', '-y', '--no-install-recommends', 'openjdk-17-jre-headless'], stdout=log, stderr=subprocess.STDOUT, timeout=240)
        save('java_install', {'returncode': r.returncode, 'java_present': bool(shutil.which('java'))})


def selfcheck():
    from huggingface_hub import HfApi, snapshot_download
    model = 'potsawee/deberta-v3-large-mnli'
    record = {'model': model, 'author_revision': '19b492a2a380931bf1ed0ca94a9565c9aa7b03e1', 'started': time.time()}
    try:
        info = HfApi().model_info(model, files_metadata=True)
        names = [s.rfilename for s in info.siblings]
        weight = 'model.safetensors' if 'model.safetensors' in names else 'pytorch_model.bin'
        patterns = [weight, '*.json', '*.model', 'README.md', '*.txt']
        size = sum(s.size or 0 for s in info.siblings if s.rfilename == weight or s.rfilename.endswith(('.json', '.model')))
        record.update(revision=info.sha, required_bytes=size, free_bytes=shutil.disk_usage('/workspace').free)
        if size + 180_000_000 > record['free_bytes']:
            record.update(status='BLOCKED', reason='insufficient_disk_without_removing_existing_models')
        else:
            folder = snapshot_download(model, revision=info.sha, allow_patterns=patterns,
                cache_dir='/workspace/guardian/modular_hf_cache', max_workers=2)
            record.update(status='DOWNLOADED', path=folder)
    except Exception as exc:
        record.update(status='BLOCKED', reason=type(exc).__name__)
    save('selfcheck_model_attempt', record)


if __name__ == '__main__':
    deduplicate_own_factcg()
    ccg()
    selfcheck()
