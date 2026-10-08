"""Installed by the archive builder at scripts/predict.py."""
from pathlib import Path
import os
import sys

root = Path(__file__).resolve().parents[1]
# The Linux archive carries CPython and native dependencies, so the platform's
# Python version is only used to dispatch this entry point.
bundled = root / 'runtime/python/bin/python3.12'
if bundled.exists() and os.environ.get('GUARDIAN_BUNDLED_PYTHON') != '1':
    env = dict(os.environ, GUARDIAN_BUNDLED_PYTHON='1', PYTHONHOME=str(root / 'runtime/python'),
               PYTHONDONTWRITEBYTECODE='1', PYTHONUTF8='1')
    env['LD_LIBRARY_PATH'] = str(root / 'runtime/lib')
    loader = root / 'runtime/lib/ld-linux-x86-64.so.2'
    if not loader.is_file():
        raise RuntimeError('BUNDLED_ELF_LOADER_MISSING')
    os.execve(str(loader), [str(loader), '--library-path', str(root / 'runtime/lib'),
                           str(bundled), '-X', 'utf8', str(Path(__file__).resolve()), *sys.argv[1:]], env)
sys.path[:0] = [str(root / 'src'), str(root), str(root / 'runtime/site-packages')]
from guardian_truth.submission.cli import main

if __name__ == '__main__':
    main()
