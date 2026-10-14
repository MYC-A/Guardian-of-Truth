"""Supervisor of the single-pass judge submission. It always produces an answer file.

Time line, seconds since the platform launched scripts/predict.py (GUARDIAN_STARTED_AT):
  start          read input; mechanical layer on CPU for every row; a first answer file is written at
                 once (hard findings -> 1, every other row 0), so a file exists whatever happens next
  then           GPU stage scripts/judge_stage.py in its own process group; it starts no chunk
                 that would end after judge_stop_seconds
  every 20 s     when new model scores arrived, the file is rewritten atomically
  kill_seconds   stage group killed if still alive; final write; exit 0
  watchdog       hard exit (code 0 when the file exists, i.e. from the first seconds on)
Coverage. Rows without a model score are explicit fallback rows: label 1 if a hard finding exists, else 0
(a row labelled 1 raises F1 only when P(error) > F1/2, about 0.3 for a working judge, above the ~0.24
base rate). Coverage below coverage_warning never blocks the file: it is reported as JUDGE_COVERAGE_LOW
in the log and in the final event, so a weak run is visible instead of silent. A stage that cannot start
or crashes leaves the mechanical answer. Rows are addressed by position; ids are written back verbatim
in input order.
"""
from __future__ import annotations

import csv
import hashlib
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

PROFILE = 'single-pass-judge-v3'
DEFAULTS = dict(model_dir='model/judge', positive_rate=0.30, hard_unknown_identifier=False,
                coverage_warning=0.9, judge_stop_seconds=1380, kill_seconds=1530, watchdog_seconds=1680,
                write_every_seconds=20)


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
    loaded = json.loads(source.read_text(encoding='utf-8')) if source.is_file() else {}
    cfg.update(loaded)
    if 'min_coverage' in loaded and 'coverage_warning' not in loaded:
        cfg['coverage_warning'] = loaded['min_coverage']  # old key: now a warning level, never a gate
    if os.environ.get('GUARDIAN_POSITIVE_RATE'):
        cfg['positive_rate'] = float(os.environ['GUARDIAN_POSITIVE_RATE'])
    return cfg


def read_scores(path):
    """-> ({key: log-odds}, rows without a score, rows with a bounded (inexact) score, stage events)."""
    scores, missing, inexact, events = {}, 0, 0, {}
    if not path or not Path(path).exists():
        return scores, missing, inexact, events
    with open(path, encoding='utf-8') as stream:
        for line in stream:
            try:
                item = json.loads(line)
            except ValueError:
                break  # torn last line of a killed writer
            if 'event' in item:
                events[item['event']] = item
                continue
            if 'key' not in item:
                continue
            if item.get('score') is None:
                missing += 1
            else:
                scores[int(item['key'])] = float(item['score'])
                inexact += not item.get('exact', False)
    return scores, missing, inexact, events


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


def prepare_stage(root, cfg, rows, findings, clock, work, python):
    """Stage input, config and command. -> (command, env, scores_path, model)."""
    cache = work / 'cache'
    os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', HF_HOME=str(cache / 'huggingface'),
                      XDG_CACHE_HOME=str(cache), VLLM_CACHE_ROOT=str(cache / 'vllm'),
                      TRITON_CACHE_DIR=str(cache / 'triton'), TORCHINDUCTOR_CACHE_DIR=str(cache / 'torchinductor'),
                      VLLM_NO_USAGE_STATS='1', DO_NOT_TRACK='1', PYTHONDONTWRITEBYTECODE='1')
    stage_input = work / 'stage_input.jsonl'
    with stage_input.open('w', encoding='utf-8') as stream:
        for i, (row, f) in enumerate(zip(rows, findings)):
            stream.write(json.dumps(dict(key=i, prompt=row['prompt'], response=row['response'], hints=f.hints,
                                        features=f.features, strong=f.strong, weak=f.weak),
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
    return command, env, scores_path, model


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

    strict = bool(cfg.get('hard_unknown_identifier', False))
    findings = [analyze(r['prompt'], r['response'], strict) for r in rows]
    hard = {i for i, f in enumerate(findings) if f.hard}
    kinds = {}
    for f in findings:
        for item in f.hard:
            kinds[item.split()[0]] = kinds.get(item.split()[0], 0) + 1
    log(clock, 'mechanical', hard_rows=len(hard), hard_kinds=kinds,
        rows_with_hints=sum(1 for f in findings if f.hints))
    format_counts = {}
    for finding in findings:
        for key, value in finding.features.items():
            if key.startswith(('prompt_', 'response_')) and isinstance(value, int):
                format_counts[key] = format_counts.get(key, 0) + value
    log(clock, 'transcript', counts=format_counts,
        analysis_errors=sum('analysis_error' in f.features for f in findings),
        date_gate_errors=sum('date_gate_error' in f.features for f in findings),
        incomplete_catalog_rows=sum(not f.features.get('catalog_complete', False) for f in findings),
        strong_rows=sum(bool(f.strong) for f in findings))

    rate = float(cfg['positive_rate'])
    state = dict(scored=0, positives=None, labels=None, scores={}, writes=0)

    def publish(scores):
        labels = decide(n, hard, scores, rate)
        write_labels(output, ids, labels)
        state.update(scored=len(scores), positives=sum(labels), labels=labels, scores=scores,
                     writes=state['writes'] + 1)

    publish({})
    log(clock, 'baseline_written', positives=state['positives'])

    status, gone, stage_error, process, scores_path, work_dir = 'NOT_STARTED', None, None, None, None, None

    def refresh():
        try:
            scores = read_scores(scores_path)[0]
            if len(scores) != state['scored']:
                publish(scores)
        except Exception as error:
            log(clock, 'write_error', error='%s: %s' % (type(error).__name__, error))

    try:
        work_dir = Path(work or tempfile.mkdtemp(prefix='guardian-judge-')).resolve()
        work_dir.mkdir(parents=True, exist_ok=True)
        command, env, scores_path, model = prepare_stage(root, cfg, rows, findings, clock, work_dir, python)
        log(clock, 'stage_start', model=str(model))
        with (work_dir / 'stage.log').open('w', encoding='utf-8') as stream:
            process = subprocess.Popen(command, stdout=stream, stderr=subprocess.STDOUT, env=env,
                                       start_new_session=True, cwd=str(work_dir))
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
                    refresh()
                    log(clock, 'progress', scored=state['scored'], of=n, positives=state['positives'])
                    last = time.monotonic()
                time.sleep(1)
    except Exception as error:
        status, stage_error = 'STAGE_ERROR', '%s: %s' % (type(error).__name__, error)
        log(clock, 'stage_error', error=stage_error)
    finally:
        if process is not None:
            gone = kill_group(process)

    try:
        scores, missing, inexact, events = read_scores(scores_path)
    except Exception as error:
        log(clock, 'read_error', error='%s: %s' % (type(error).__name__, error))
        scores, missing, inexact, events = state['scores'], 0, 0, {}
    try:
        publish(scores)
    except Exception as error:
        log(clock, 'final_write_error', error='%s: %s' % (type(error).__name__, error), kept_writes=state['writes'])
        if not Path(output).is_file():
            raise
    coverage = state['scored'] / n
    low = coverage < float(cfg['coverage_warning'])
    if low:
        log(clock, 'JUDGE_COVERAGE_LOW', scored=state['scored'], rows=n, coverage=round(coverage, 4),
            warning_below=cfg['coverage_warning'], fallback_rows=n - state['scored'])
    if work_dir is not None:
        stage_log = work_dir / 'stage.log'
        if stage_log.exists():
            tail = stage_log.read_text(encoding='utf-8', errors='replace')[-4000:]
            print('=== GUARDIAN JUDGE STAGE LOG TAIL ===\n' + tail, file=sys.stderr, flush=True)
        try:
            with (work_dir / 'decisions.jsonl').open('w', encoding='utf-8') as stream:
                for i in range(n):
                    source = 'hard' if i in hard else ('model' if i in state['scores'] else 'fallback_zero')
                    stream.write(json.dumps(dict(key=i, id=ids[i], label=state['labels'][i], source=source,
                                                 hard=findings[i].hard, strong=findings[i].strong,
                                                 weak=findings[i].weak, features=findings[i].features,
                                                 prompt_sha256=hashlib.sha256(rows[i]['prompt'].encode('utf-8')).hexdigest(),
                                                 response_sha256=hashlib.sha256(rows[i]['response'].encode('utf-8')).hexdigest(),
                                                 score=state['scores'].get(i))) + '\n')
        except Exception as error:
            log(clock, 'decisions_write_error', error=type(error).__name__)
    log(clock, 'final', status=status, group_gone=gone, rows=n, scored=state['scored'], coverage=round(coverage, 4),
        coverage_low=low, fallback_rows=n - state['scored'], no_score_rows=missing, inexact_rows=inexact,
        hard_rows=len(hard), positives=state['positives'], writes=state['writes'], stage_error=stage_error,
        stage_failed=events.get('failed'), work=str(work_dir))
    return 0
