"""Deadline cascade: Granite Guardian 4.1 FP8 gate, then Qwen3.8-27B AWQ B2 under a budget.

Final label = Granite OR Qwen-B2 (Qwen only on rows Granite marked 0, highest Granite
P(yes) first). Every row always has a label from Granite; Qwen can only add positives,
and only for rows whose every model call finished cleanly before the hard stop.

Time is measured from the platform's launch of scripts/predict.py (GUARDIAN_STARTED_AT
set by the dispatcher before exec). The output file is written right after Granite and
rewritten as Qwen rows finish, always atomically (temp file + os.replace in the same
directory). No output is written unless real model predictions exist: if Granite yields
nothing the run fails (non-zero exit, the platform returns the attempt).
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
import csv
import json
import os
from pathlib import Path
import secrets
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time

PROFILE = 'cascade-granite41fp8-or-qwen38awq-b2-v1'
GRANITE_MODEL = 'model/granite-guardian-4.1-8b-fp8-block128-ab01ccca'
QWEN_REPOSITORY = 'cyankiwi/Qwen3.8-27B-AWQ-INT4'
QWEN_REVISION = '6e134bae811fb5adac50ee042ae5f029ac6779aa'
QWEN_MANIFEST = 'QWEN_MANIFEST.json'
QWEN_QUANT_METHODS = ('compressed-tensors',)
QWEN_SERVER_ARGS = ('--structured-outputs-config', '{"backend":"xgrammar","disable_any_whitespace":true}')
QWEN_WORKERS, QWEN_SLOTS, QWEN_CONTEXT = 24, 32, 32768

# Seconds since launch. The platform limit is 30 min for the whole script.
GRANITE_END = 14 * 60       # Granite must be done (partial results are used after this)
QWEN_LAUNCH_LATEST = 14 * 60  # do not start the Qwen engine later than this
ACCEPT_UNTIL = 21 * 60      # no new Qwen rows after this
HARD_STOP = 25 * 60         # every Qwen call ends by this; then cleanup and final write
WRITE_EVERY = 15


def _text(value):
    """None/NaN -> '', everything else -> str; never fail the whole run on one cell."""
    if value is None:
        return ''
    if isinstance(value, float) and value != value:
        return ''
    return value if isinstance(value, str) else str(value)


def read_input(path):
    """id/prompt/response from Parquet (by magic bytes) or CSV, tolerant of the platform's quirks.

    CSV: UTF-8 with or without BOM (undecodable bytes replaced), quoted multi-line fields,
    fields far above the csv module's default 128 KiB limit, extra columns. Missing cells
    become ''. Column names are matched after stripping whitespace/BOM. Ids are kept as
    text exactly as given; duplicates are allowed (they share one label).
    """
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
            fields = reader.fieldnames or []
            names = {(name or '').strip().lstrip('\ufeff').lower(): name for name in fields}
            if not {'id', 'prompt', 'response'} <= set(names):
                raise ValueError('REQUIRED_COLUMNS: id,prompt,response; got %s' % fields)
            records = [{key: row.get(names[key]) for key in ('id', 'prompt', 'response')} for row in reader]
    rows = [{key: _text(record[key]) for key in ('id', 'prompt', 'response')} for record in records]
    return rows


class Clock:
    def __init__(self, started_wall=None):
        now_wall, now = time.time(), time.monotonic()
        try:
            started_wall = float(started_wall)
        except (TypeError, ValueError):
            started_wall = now_wall
        # Never trust a value from the future or one older than the whole 30 min limit.
        started_wall = min(now_wall, max(now_wall - 1800, started_wall))
        self.origin = now - (now_wall - started_wall)

    def elapsed(self):
        return time.monotonic() - self.origin

    def at(self, seconds):
        return self.origin + seconds


def log(clock, event, **values):
    print('GUARDIAN_CASCADE ' + json.dumps(dict(t=round(clock.elapsed(), 1), event=event, **values),
                                           ensure_ascii=False, default=str), flush=True)


def write_labels(path, ids, labels):
    """Atomic: id,label as CSV unless the requested path ends with .parquet."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    values = [int(labels[i]) for i in ids]
    if any(v not in (0, 1) for v in values):
        raise ValueError('NON_BINARY_LABEL')
    fd, tmp = tempfile.mkstemp(prefix='.' + path.name + '.', suffix='.tmp', dir=path.parent)
    try:
        if path.suffix.lower() == '.parquet':
            os.close(fd)
            import pandas as pd
            frame = pd.DataFrame({'id': list(ids), 'label': values})
            frame['label'] = frame['label'].astype('int64')
            frame.to_parquet(tmp, index=False)
        else:
            with os.fdopen(fd, 'w', encoding='utf-8', newline='') as stream:
                writer = csv.writer(stream, lineterminator='\n')
                writer.writerow(['id', 'label'])
                writer.writerows(zip(ids, values))
                stream.flush()
                os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def kill_owned_group(pgid, token, seconds=(10, 3)):
    """Owner-verified pidfd cleanup; falls back to killpg of our own new session if pidfd fails."""
    try:
        return _kill_owned_group(pgid, token, seconds)
    except Exception as error:
        print('GUARDIAN_CASCADE pidfd cleanup unavailable: %s; using killpg' % type(error).__name__, flush=True)
    for signum, budget in ((signal.SIGTERM, seconds[0]), (signal.SIGKILL, seconds[1])):
        try:
            os.killpg(pgid, signum)
        except ProcessLookupError:
            return True
        except Exception:
            return False
        stop = time.monotonic() + budget
        while time.monotonic() < stop:
            try:  # the leader is our child: reap it, or its zombie keeps the group "alive"
                os.waitpid(pgid, os.WNOHANG)
            except ChildProcessError:
                pass
            try:
                os.killpg(pgid, 0)
            except ProcessLookupError:
                return True
            except Exception:
                return False
            time.sleep(0.1)
    return False


def _kill_owned_group(pgid, token, seconds):
    from scripts.qwen_vllm_adapter import owned_group_handles
    for signum, budget in zip((signal.SIGTERM, signal.SIGKILL), seconds):
        stop = time.monotonic() + budget
        while True:
            handles = owned_group_handles(pgid, token)
            if not handles:
                return True
            try:
                for _, descriptor in handles:
                    try:
                        signal.pidfd_send_signal(descriptor, signum)
                    except ProcessLookupError:
                        pass
            finally:
                for _, descriptor in handles:
                    os.close(descriptor)
            if time.monotonic() >= stop:
                break
            time.sleep(0.1)
    handles = owned_group_handles(pgid, token)
    for _, descriptor in handles:
        os.close(descriptor)
    return not handles


def gpu_used_mib():
    for binary in (shutil.which('nvidia-smi'), '/usr/local/nvidia/bin/nvidia-smi', '/usr/bin/nvidia-smi'):
        if binary and Path(binary).is_file():
            try:
                out = subprocess.run([binary, '--query-gpu=memory.used', '--format=csv,noheader,nounits'],
                                     capture_output=True, text=True, timeout=10).stdout
                return int(out.split()[0])
            except Exception:
                return None
    return None


def wait_gpu_released(clock, limit_mib=4096, seconds=30):
    stop = time.monotonic() + seconds
    used = gpu_used_mib()
    while used is not None and used > limit_mib and time.monotonic() < stop:
        time.sleep(1)
        used = gpu_used_mib()
    log(clock, 'gpu_after_granite', used_mib=used)


def read_granite(path):
    records, ready, done = {}, None, False
    if not Path(path).exists():
        return records, ready, done
    with open(path, encoding='utf-8') as stream:
        for line in stream:
            try:
                item = json.loads(line)
            except ValueError:
                break  # a torn last line from a killed writer
            if item.get('event') == 'ready':
                ready = item
            elif item.get('event') == 'done':
                done = True
            elif 'id' in item and item.get('pred') in (0, 1):
                records[item['id']] = item
    return records, ready, done


def run_granite(root, python, snapshot, work, clock):
    results = work / 'granite.jsonl'
    token = secrets.token_hex(24)
    env = dict(os.environ, GUARDIAN_VLLM_OWNER_TOKEN=token, HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
               VLLM_NO_USAGE_STATS='1', DO_NOT_TRACK='1', PYTHONNOUSERSITE='1')
    for key in ('LD_LIBRARY_PATH', 'PYTHONPATH', 'PYTHONHOME', 'LD_PRELOAD'):
        env.pop(key, None)
    command = [str(python), str(root / 'scripts/granite_stage.py'), '--model', str(root / GRANITE_MODEL),
               '--input', str(snapshot), '--output', str(results)]
    log(clock, 'granite_start')
    with (work / 'granite.log').open('w', encoding='utf-8') as stream:
        process = subprocess.Popen(command, stdout=stream, stderr=subprocess.STDOUT, env=env,
                                   start_new_session=True, cwd=str(work))
        status = 'TIMEOUT'
        try:
            last = 0
            while clock.elapsed() < GRANITE_END:
                code = process.poll()
                if code is not None:
                    status = 'EXITED_%d' % code
                    break
                if time.monotonic() - last > 30:
                    records, ready, _ = read_granite(results)
                    log(clock, 'granite_progress', ready=bool(ready), rows=len(records))
                    last = time.monotonic()
                time.sleep(0.5)
        finally:
            gone = kill_owned_group(process.pid, token)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
    records, ready, done = read_granite(results)
    log(clock, 'granite_end', status=status, done=done, rows=len(records), group_gone=gone,
        startup_s=(ready or {}).get('startup_s'), positives=sum(r['pred'] for r in records.values()))
    if not records:
        tail = (work / 'granite.log').read_text(encoding='utf-8', errors='replace')[-6000:]
        print('=== GUARDIAN GRANITE LOG TAIL ===\n' + tail, file=sys.stderr, flush=True)
    return records, done, gone


class RowTaggingClient:
    """Delegates to VllmClient; remembers rows that had any non-clean model call."""
    def __init__(self, inner):
        self.inner, self.local, self.lock, self.unclean = inner, threading.local(), threading.Lock(), set()

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def call(self, *args, **kwargs):
        row = getattr(self.local, 'row', None)
        try:
            record = self.inner.call(*args, **kwargs)
        except BaseException:
            with self.lock:
                self.unclean.add(row)
            raise
        if (record.get('transport') or {}).get('status') not in (200, 'NOT_EXECUTED_CONTEXT_BUDGET'):
            with self.lock:
                self.unclean.add(row)
        return record


def configure_adapter(adapter):
    adapter.REPOSITORY, adapter.REVISION = QWEN_REPOSITORY, QWEN_REVISION
    adapter.MODEL = f'{QWEN_REPOSITORY}@{QWEN_REVISION}:vllm-{adapter.ENGINE_VERSION}'
    adapter.QUANT_METHODS = QWEN_QUANT_METHODS
    adapter.EXTRA_SERVER_ARGS = QWEN_SERVER_ARGS
    return adapter.MODEL


def run_qwen(root, python, rows, work, clock, on_positive):
    """B2 on rows (already ordered); calls on_positive(id) for clean Qwen positives."""
    from scripts import qwen_vllm_adapter as adapter
    from guardian_truth.submission.cli import predict_one
    from guardian_truth.v6fix.pipeline import Layers
    model = configure_adapter(adapter)
    hard_stop = clock.at(HARD_STOP)
    stats = dict(submitted=len(rows), started=0, clean=0, unclean=0, positives=0, skipped_late=0, errors=0)
    log(clock, 'qwen_start', rows=len(rows))
    startup = max(30.0, min(600.0, HARD_STOP - clock.elapsed() - 60))
    with adapter.OwnedVllmServer(str(python), root / 'model' / QWEN_REVISION, work, QWEN_CONTEXT, QWEN_SLOTS,
                                 deadline=hard_stop, asset_manifest=root / QWEN_MANIFEST,
                                 startup_timeout=startup) as server:
        log(clock, 'qwen_ready')
        inner = adapter.VllmClient(server.port, QWEN_CONTEXT, work / 'calls', api_key=server.api_key,
                                   backend_manifest=server.manifest, timeout=600, deadline=hard_stop,
                                   max_calls=10 ** 6)
        client = RowTaggingClient(inner)
        layers = Layers(client, model, budget=20000, attempts=(0, 1), frules_max_tokens=700,
                        tolerate_component_errors=True)
        accept_until = clock.at(ACCEPT_UNTIL)

        def task(row):
            if time.monotonic() >= accept_until:
                return row['id'], None
            client.local.row = row['id']
            with client.lock:
                stats['started'] += 1
            try:
                trace = predict_one(row, client, layers, model=model, provider='local-vllm')
            finally:
                client.local.row = None
            return row['id'], trace

        traces = (work / 'qwen_traces.jsonl').open('a', encoding='utf-8')
        executor = ThreadPoolExecutor(max_workers=QWEN_WORKERS)
        try:
            pending = {executor.submit(task, row) for row in rows}
            last = time.monotonic()
            while pending:
                done, pending = wait(pending, timeout=5, return_when=FIRST_COMPLETED)
                for future in done:
                    try:
                        identifier, trace = future.result()
                    except Exception as error:
                        stats['errors'] += 1
                        log(clock, 'qwen_row_error', error=type(error).__name__)
                        continue
                    if trace is None:
                        stats['skipped_late'] += 1
                        continue
                    traces.write(json.dumps(trace, ensure_ascii=False, default=str) + '\n')
                    clean = (identifier not in client.unclean and time.monotonic() < hard_stop
                             and trace.get('binary') in (0, 1))
                    stats['clean' if clean else 'unclean'] += 1
                    if clean and trace['binary'] == 1:
                        stats['positives'] += 1
                        on_positive(identifier)
                if time.monotonic() - last > WRITE_EVERY:
                    traces.flush()
                    on_positive(None)  # periodic rewrite
                    log(clock, 'qwen_progress', **stats, pending=len(pending))
                    last = time.monotonic()
        finally:
            executor.shutdown(wait=True, cancel_futures=True)
            traces.close()
        log(clock, 'qwen_done', **stats, completion_http=inner.completion_http)
    return stats


def run(root, input_path, output, *, python=None, work=None, started_wall=None):
    clock = Clock(started_wall)
    root = Path(root).resolve()
    python = python or root / 'runtime/python/run_python.sh'
    rows = read_input(input_path)
    ids = [row['id'] for row in rows]
    log(clock, 'input', rows=len(rows), profile=PROFILE, unique_ids=len(set(ids)),
        empty_prompt=sum(not r['prompt'] for r in rows), empty_response=sum(not r['response'] for r in rows),
        max_prompt_chars=max([len(r['prompt']) for r in rows] or [0]))
    if not rows:
        write_labels(output, [], {})
        log(clock, 'written', rows=0)
        return 0
    work = Path(work or tempfile.mkdtemp(prefix='guardian-cascade-')).resolve()
    work.mkdir(parents=True, exist_ok=True)
    cache = work / 'cache'
    os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', HF_HOME=str(cache / 'huggingface'),
                      XDG_CACHE_HOME=str(cache), VLLM_CACHE_ROOT=str(cache / 'vllm'),
                      TRITON_CACHE_DIR=str(cache / 'triton'), TORCHINDUCTOR_CACHE_DIR=str(cache / 'torchinductor'),
                      VLLM_NO_USAGE_STATS='1', DO_NOT_TRACK='1', PYTHONDONTWRITEBYTECODE='1')
    snapshot = work / 'input.parquet'
    import pandas as pd
    pd.DataFrame(rows, columns=['id', 'prompt', 'response']).to_parquet(snapshot, index=False)

    granite, granite_done, gone = run_granite(root, python, snapshot, work, clock)
    if not granite:
        raise RuntimeError('GRANITE_PRODUCED_NO_PREDICTIONS')
    labels = {i: int(granite[i]['pred']) if i in granite else 0 for i in ids}
    write_labels(output, ids, labels)
    log(clock, 'written', stage='granite', positives=sum(labels.values()), missing=len(ids) - len(granite))

    candidates = [row for row in rows if labels[row['id']] == 0 and row['id'] in granite]
    order = {i: k for k, i in enumerate(ids)}
    candidates.sort(key=lambda r: (-float(granite[r['id']].get('p_yes') or 0.0), order[r['id']]))
    reason = None
    if not (root / 'model' / QWEN_REVISION).is_dir():
        reason = 'QWEN_NOT_BUNDLED'  # Granite-only archive variant
    elif not granite_done:
        reason = 'GRANITE_INCOMPLETE'
    elif not gone:
        reason = 'GRANITE_GROUP_SURVIVED'
    elif clock.elapsed() > QWEN_LAUNCH_LATEST:
        reason = 'NO_TIME_FOR_QWEN'
    elif not candidates:
        reason = 'NO_CANDIDATES'
    if reason:
        log(clock, 'qwen_skipped', reason=reason)
        return 0
    wait_gpu_released(clock)
    lock = threading.Lock()
    state = dict(dirty=False)

    def on_positive(identifier):
        with lock:
            if identifier is not None:
                labels[identifier] = 1
                state['dirty'] = True
            elif state['dirty']:
                write_labels(output, ids, labels)
                state['dirty'] = False
    try:
        run_qwen(root, python, candidates, work, clock, on_positive)
    except BaseException as error:  # Granite output stays valid; keep any Qwen positives
        log(clock, 'qwen_failed', error=type(error).__name__, detail=str(error)[:300])
        if not isinstance(error, Exception):
            write_labels(output, ids, labels)
            raise
    write_labels(output, ids, labels)
    log(clock, 'written', stage='final', positives=sum(labels.values()))
    return 0
