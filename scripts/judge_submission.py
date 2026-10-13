"""Supervisor of the single-pass judge submission.

Time line, seconds since the platform launched scripts/predict.py (GUARDIAN_STARTED_AT):
  start          read input; mechanical layer on CPU for every row
  then           GPU stage scripts/judge_stage.py in its own process group; it starts no chunk
                 that would end after judge_stop_seconds
  every 20 s     output rewritten atomically from all scores so far (rank rule over scored rows)
  kill_seconds   stage group killed if still alive; final write; exit 0
  watchdog       hard exit (code 0 if an output exists)
If the stage produced no score at all, no output is written and the exit code is non-zero, so the
platform does not count the attempt. Rows are addressed by position; ids are written back verbatim
in input order.
"""
from __future__ import annotations

import csv
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / 'src')):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from guardian_truth.judge.decision import decide  # noqa: E402
from guardian_truth.judge.mechanical import analyze  # noqa: E402

PROFILE = 'single-pass-judge-v1'
DEFAULTS = dict(model_dir='model/judge', positive_rate=0.30, hard_unknown_identifier=True,
                judge_stop_seconds=1380, kill_seconds=1530, watchdog_seconds=1680, write_every_seconds=20)


class Clock:
    def __init__(self, started_wall=None):
        now_wall, now = time.time(), time.monotonic()
        try:
            started_wall = float(started_wall)
        except (TypeError, ValueError):
            started_wall = now_wall
        self.started_wall = min(now_wall, max(now_wall - 1800, started_wall))
        self.origin = now - (now_wall - self.started_wall)

    def elapsed(self):
        return time.monotonic() - self.origin

    def wall_at(self, seconds):
        return self.started_wall + seconds


def log(clock, event, **values):
    print('GUARDIAN_JUDGE ' + json.dumps(dict(t=round(clock.elapsed(), 1), event=event, **values),
                                         ensure_ascii=False, default=str), flush=True)


def _text(value):
    if value is None or (isinstance(value, float) and value != value):
        return ''
    return value if isinstance(value, str) else str(value)


def read_input(path):
    """id/prompt/response from Parquet (by magic bytes) or CSV; ids kept verbatim, duplicates allowed."""
    path = Path(path)
    with path.open('rb') as stream:
        parquet = stream.read(4) == b'PAR1'
    if parquet:
        import pyarrow.parquet as pq
        table = pq.read_table(path)
        names = {name.strip().lstrip('\ufeff').lower(): name for name in table.column_names}
        if not {'id', 'prompt', 'response'} <= set(names):
            raise ValueError('REQUIRED_COLUMNS: id,prompt,response; got %s' % table.column_names)
        columns = {key: table.column(names[key]).to_pylist() for key in ('id', 'prompt', 'response')}
        records = [dict(zip(columns, values)) for values in zip(*columns.values())]
    else:
        csv.field_size_limit(2 ** 31 - 1)
        with path.open(encoding='utf-8-sig', errors='replace', newline='') as stream:
            reader = csv.DictReader(stream)
            names = {(name or '').strip().lstrip('\ufeff').lower(): name for name in reader.fieldnames or []}
            if not {'id', 'prompt', 'response'} <= set(names):
                raise ValueError('REQUIRED_COLUMNS: id,prompt,response; got %s' % reader.fieldnames)
            records = [{key: row.get(names[key]) for key in ('id', 'prompt', 'response')} for row in reader]
    return [{key: _text(record[key]) for key in ('id', 'prompt', 'response')} for record in records]


def write_labels(path, ids, labels):
    """Atomic write: Parquet if the path ends with .parquet, else CSV; columns id,label."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    labels = [int(v) for v in labels]
    if len(ids) != len(labels) or any(v not in (0, 1) for v in labels):
        raise ValueError('BAD_LABELS')
    fd, tmp = tempfile.mkstemp(prefix='.' + path.name + '.', suffix='.tmp', dir=path.parent)
    try:
        if path.suffix.lower() == '.parquet':
            os.close(fd)
            import pandas as pd
            frame = pd.DataFrame({'id': list(ids), 'label': labels})
            frame['label'] = frame['label'].astype('int64')
            frame.to_parquet(tmp, index=False)
        else:
            with os.fdopen(fd, 'w', encoding='utf-8', newline='') as stream:
                writer = csv.writer(stream, lineterminator='\n')
                writer.writerow(['id', 'label'])
                writer.writerows(zip(ids, labels))
                stream.flush()
                os.fsync(stream.fileno())
        umask = os.umask(0)
        os.umask(umask)
        os.chmod(tmp, 0o666 & ~umask | 0o444)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def load_config(root, path=None):
    cfg = dict(DEFAULTS)
    source = Path(path) if path else Path(root) / 'JUDGE_CONFIG.json'
    if source.is_file():
        cfg.update(json.loads(source.read_text(encoding='utf-8')))
    if os.environ.get('GUARDIAN_POSITIVE_RATE'):
        cfg['positive_rate'] = float(os.environ['GUARDIAN_POSITIVE_RATE'])
    return cfg


def read_scores(path):
    scores, missing = {}, 0
    if not Path(path).exists():
        return scores, missing
    with open(path, encoding='utf-8') as stream:
        for line in stream:
            try:
                item = json.loads(line)
            except ValueError:
                break  # torn last line of a killed writer
            if 'key' not in item:
                continue
            if item.get('p') is None:
                missing += 1
            else:
                scores[int(item['key'])] = float(item['p'])
    return scores, missing


def kill_group(process, grace=15):
    """SIGTERM, then SIGKILL the stage's whole process group (vLLM engine core included)."""
    for signum, budget in ((signal.SIGTERM, grace), (signal.SIGKILL, 5)):
        try:
            os.killpg(process.pid, signum)
        except ProcessLookupError:
            return True
        except Exception:
            pass
        stop = time.monotonic() + budget
        while time.monotonic() < stop:
            process.poll()
            try:
                os.killpg(process.pid, 0)
            except ProcessLookupError:
                return True
            except Exception:
                return False
            time.sleep(0.2)
    return False


def start_watchdog(clock, output, seconds):
    def fire():
        code = 0 if Path(output).is_file() else 1
        try:
            log(clock, 'watchdog_exit', code=code)
            sys.stdout.flush()
            sys.stderr.flush()
        finally:
            os._exit(code)
    timer = threading.Timer(max(0.0, seconds - clock.elapsed()), fire)
    timer.daemon = True
    timer.start()
    return timer


def run(root, input_path, output, *, python=None, work=None, started_wall=None, config=None, watchdog=True):
    clock = Clock(started_wall)
    root = Path(root).resolve()
    cfg = load_config(root, config)
    if watchdog:
        start_watchdog(clock, output, float(cfg['watchdog_seconds']))
    rows = read_input(input_path)
    ids, n = [row['id'] for row in rows], len(rows)
    log(clock, 'input', rows=n, profile=PROFILE, unique_ids=len(set(ids)),
        max_prompt_chars=max([len(r['prompt']) for r in rows] or [0]), positive_rate=cfg['positive_rate'])
    if not rows:
        write_labels(output, [], [])
        return 0

    findings = [analyze(r['prompt'], r['response'], bool(cfg['hard_unknown_identifier'])) for r in rows]
    hard = {i for i, f in enumerate(findings) if f.hard}
    kinds = {}
    for f in findings:
        for item in f.hard:
            kinds[item.split()[0]] = kinds.get(item.split()[0], 0) + 1
    log(clock, 'mechanical', hard_rows=len(hard), hard_kinds=kinds,
        rows_with_hints=sum(1 for f in findings if f.hints))

    work = Path(work or tempfile.mkdtemp(prefix='guardian-judge-')).resolve()
    work.mkdir(parents=True, exist_ok=True)
    cache = work / 'cache'
    os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', HF_HOME=str(cache / 'huggingface'),
                      XDG_CACHE_HOME=str(cache), VLLM_CACHE_ROOT=str(cache / 'vllm'),
                      TRITON_CACHE_DIR=str(cache / 'triton'), TORCHINDUCTOR_CACHE_DIR=str(cache / 'torchinductor'),
                      VLLM_NO_USAGE_STATS='1', DO_NOT_TRACK='1', PYTHONDONTWRITEBYTECODE='1')
    stage_input = work / 'stage_input.jsonl'
    with stage_input.open('w', encoding='utf-8') as stream:
        for i, (row, f) in enumerate(zip(rows, findings)):
            stream.write(json.dumps(dict(key=i, prompt=row['prompt'], response=row['response'], hints=f.hints),
                                    ensure_ascii=False) + '\n')
    stage_config = work / 'judge_config.json'
    stage_config.write_text(json.dumps(cfg), encoding='utf-8')
    scores_path = work / 'scores.jsonl'

    bundled = root / 'runtime/python/run_python.sh'
    if python is None:
        python = bundled if bundled.is_file() else Path(sys.executable)
    model = Path(cfg['model_dir'])
    model = model if model.is_absolute() else root / model
    command = [str(python), str(root / 'scripts/judge_stage.py'), '--model', str(model),
               '--input', str(stage_input), '--output', str(scores_path), '--config', str(stage_config),
               '--stop-at', repr(clock.wall_at(float(cfg['judge_stop_seconds'])))]
    env = dict(os.environ, HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', VLLM_NO_USAGE_STATS='1',
               DO_NOT_TRACK='1', PYTHONNOUSERSITE='1')
    if Path(python) == bundled:
        # Same environment contract as the platform-tested Granite stage.
        for key in ('LD_LIBRARY_PATH', 'PYTHONPATH', 'PYTHONHOME', 'LD_PRELOAD'):
            env.pop(key, None)

    state = dict(scored=0, positives=None)

    def publish():
        scores, _ = read_scores(scores_path)
        if not scores:
            return 0
        labels = decide(n, hard, scores, float(cfg['positive_rate']))
        write_labels(output, ids, labels)
        state.update(scored=len(scores), positives=sum(labels))
        return len(scores)

    log(clock, 'stage_start', model=str(model))
    status, gone = 'UNKNOWN', None
    with (work / 'stage.log').open('w', encoding='utf-8') as stream:
        process = subprocess.Popen(command, stdout=stream, stderr=subprocess.STDOUT, env=env,
                                   start_new_session=True, cwd=str(work))
        try:
            last = time.monotonic()
            while True:
                code = process.poll()
                if code is not None:
                    status = 'EXITED_%d' % code
                    break
                if clock.elapsed() >= float(cfg['kill_seconds']):
                    status = 'KILLED_AT_DEADLINE'
                    break
                if time.monotonic() - last >= float(cfg['write_every_seconds']):
                    publish()
                    log(clock, 'progress', scored=state['scored'], positives=state['positives'])
                    last = time.monotonic()
                time.sleep(1)
        finally:
            gone = kill_group(process)
    scored = publish()
    tail = (work / 'stage.log').read_text(encoding='utf-8', errors='replace')[-4000:]
    print('=== GUARDIAN JUDGE STAGE LOG TAIL ===\n' + tail, file=sys.stderr, flush=True)
    log(clock, 'final', status=status, group_gone=gone, rows=n, scored=scored, hard_rows=len(hard),
        positives=state['positives'], work=str(work))
    if not scored:
        raise RuntimeError('JUDGE_PRODUCED_NO_SCORES')
    return 0
