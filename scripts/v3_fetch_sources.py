"""Pinned v3 source inventory and license evidence; no external code execution."""
import argparse
import hashlib
import json
import time
import urllib.request
from pathlib import Path


def fetch(url, target, binary=False):
    if target.exists():
        raise RuntimeError('REFUSE_REPLACE_SOURCE: ' + str(target))
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Guardian-v3-source-inventory'})
            with urllib.request.urlopen(req, timeout=45) as response:
                raw = response.read()
            target.write_bytes(raw)
            return raw if binary else json.loads(raw)
        except Exception:
            if attempt == 2:
                raise
            time.sleep(2)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args()
    a.out.mkdir(parents=True, exist_ok=False)
    started = time.time()
    (a.out / 'START.json').write_text(json.dumps(dict(started_unix=started, phase='B1-inventory')))
    sources = []
    for kind, repo in [('github', 'sierra-research/tau2-bench'),
                       ('github', 'UCSB-NLP-Chang/CompliBench'),
                       ('github', 'ParticleMedia/RAGTruth'),
                       ('hf', 'ibm-research/ToolRM-train-data'),
                       ('hf', 'PatronusAI/HaluBench'),
                       ('hf', 'Salesforce/APIGen-MT-5k')]:
        folder = a.out / repo.replace('/', '__')
        folder.mkdir()
        rec = dict(kind=kind, repository=repo, status='INVENTORY_ONLY_NOT_ADMITTED', files={})
        try:
            if kind == 'github':
                requested = '96a3ef92329baf908ffe9dfe188cea34e8701d2a' if repo.endswith('tau2-bench') else 'HEAD'
                meta = fetch(f'https://api.github.com/repos/{repo}/commits/{requested}', folder / 'revision.json')
                revision = meta['sha']
                tree = fetch(f'https://api.github.com/repos/{repo}/git/trees/{revision}?recursive=1', folder / 'tree.json')
                assert not tree.get('truncated'), 'TRUNCATED_SOURCE_TREE'
                names = [x['path'] for x in tree['tree'] if x['type'] == 'blob']
                wanted = [n for n in names if n in ('README.md', 'LICENSE', 'LICENSE.md', 'LICENSE.txt')]
                for name in wanted:
                    fetch(f'https://raw.githubusercontent.com/{repo}/{revision}/{name}', folder / name, True)
                rec.update(revision=revision, archive_url=f'https://codeload.github.com/{repo}/zip/{revision}', paths=names)
            else:
                meta = fetch(f'https://huggingface.co/api/datasets/{repo}', folder / 'revision.json')
                revision = meta['sha']
                names = [x['rfilename'] for x in meta.get('siblings', [])]
                for name in names:
                    if name.lower() in ('readme.md', 'license', 'license.md', 'license.txt', 'dataset_infos.json'):
                        fetch(f'https://huggingface.co/datasets/{repo}/resolve/{revision}/{name}', folder / name, True)
                rec.update(revision=revision, declared_license=meta.get('cardData', {}).get('license'), paths=names)
        except Exception as e:
            rec.update(status='INVENTORY_FAILED_EXCLUDED', error_type=type(e).__name__, error=str(e)[:300])
        for f in folder.iterdir():
            if f.is_file():
                rec['files'][f.name] = dict(bytes=f.stat().st_size, sha256=hashlib.sha256(f.read_bytes()).hexdigest())
        sources.append(rec)
        (a.out / 'sources_manifest.json').write_text(json.dumps(dict(sources=sources), indent=2))
        print(json.dumps({k: v for k, v in rec.items() if k not in ('files', 'paths')}), flush=True)
    done = dict(complete=True, phase='B1-inventory', sources=len(sources), seconds=time.time() - started,
                code_executed_from_sources=False, training_started=False)
    (a.out / 'DONE.json').write_text(json.dumps(done, indent=2))
    print(json.dumps(done), flush=True)


if __name__ == '__main__':
    main()
