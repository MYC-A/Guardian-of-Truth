"""Archive public entrypoint (installed at scripts/predict.py): Granite FP8 -> Qwen3.8 AWQ cascade.

python scripts/predict.py --input <test.csv|parquet> --output <predictions.csv|parquet>
Only id/prompt/response are read. See scripts/cascade_submission.py for the time budget.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
import time


def bootstrap(root, arguments):
    """The platform's Python only dispatches; inference runs in the bundled runtime."""
    wrapper = root / 'runtime/python/run_python.sh'
    binary = root / 'runtime/python/bin/python3.12'
    if not wrapper.is_file() or not binary.is_file():
        raise RuntimeError('BUNDLED_PYTHON_RUNTIME_MISSING')
    if (os.environ.get('GUARDIAN_BUNDLED_PYTHON') == '1'
            and Path(sys.executable).resolve() == binary.resolve()):
        return
    env = dict(os.environ, GUARDIAN_BUNDLED_PYTHON='1', PYTHONDONTWRITEBYTECODE='1',
               PYTHONUTF8='1', PYTHONNOUSERSITE='1')
    env.setdefault('GUARDIAN_STARTED_AT', repr(time.time()))
    print('GUARDIAN_CASCADE dispatch', flush=True)
    os.execve(str(wrapper), [str(wrapper), str(Path(__file__).resolve()), *arguments], env)
    raise RuntimeError('BUNDLED_PYTHON_EXEC_RETURNED')


def main(argv=None):
    arguments = list(sys.argv[1:] if argv is None else argv)
    root = Path(__file__).resolve().parents[1]
    os.environ.setdefault('GUARDIAN_STARTED_AT', repr(time.time()))
    bootstrap(root, arguments)
    sys.path[:0] = [str(root / 'src'), str(root), str(root / 'runtime/site-packages')]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--work-dir', type=Path, help='Receipt directory outside the archive')
    args = parser.parse_args(arguments)
    if args.input.resolve() == args.output.resolve():
        raise ValueError('INPUT_OUTPUT_SAME_PATH')
    from scripts.cascade_submission import run
    return run(root, args.input, args.output, work=args.work_dir,
               started_wall=os.environ.get('GUARDIAN_STARTED_AT'))


if __name__ == '__main__':
    raise SystemExit(main())
