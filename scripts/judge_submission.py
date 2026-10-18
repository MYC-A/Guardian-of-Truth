"""Supervisor of the single-pass judge submission. It always produces an answer file.

Time line, seconds since the platform launched scripts/predict.py (GUARDIAN_STARTED_AT):
  start          read input; mechanical layer on CPU for every row; a first answer file is written at
                 once (hard findings -> 1, every other row 0), so a file exists whatever happens next
  then           GPU stage scripts/judge_stage.py in its own process group; it starts no chunk
                 that would end after judge_stop_seconds
  every 20 s     when the stage file changed (new primary scores or extra scores), the file is rewritten
                 atomically
  kill_seconds   stage group killed if still alive; final write; exit 0
  watchdog       hard exit (code 0 when the file exists, i.e. from the first seconds on)
Coverage. Rows without a model score are explicit fallback rows: label 1 if a hard finding exists, else 0
(a row labelled 1 raises F1 only when P(error) > F1/2, about 0.3 for a working judge, above the ~0.24
base rate). Coverage below coverage_warning never blocks the file: it is reported as JUDGE_COVERAGE_LOW
in the log and in the final event, so a weak run is visible instead of silent. A stage that cannot start
or crashes leaves the mechanical answer. Rows are addressed by position; ids are written back verbatim
in input order.

v3. The scoring profile (questions x hint_modes, aggregate, extras_schedule) is validated before the stage
starts; an invalid profile is logged as CONFIG_INVALID and replaced by the production profile overall@on +
primary. A non-primary aggregate is used only when every scored row has all its input keys; otherwise the
primary score is used for every row (aggregate_incomplete in the log). Hard findings are never switched off
by their share: a high share is only logged per rule kind (HARD_RATE_HIGH) together with parse diagnostics.
"""
from __future__ import annotations

from collections import Counter
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import re
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

from guardian_truth.judge.decision import aggregate_inputs, combine, complete_inputs, decide, validate_aggregate  # noqa: E402
from guardian_truth.judge.mechanical import analyze  # noqa: E402
from guardian_truth.judge.prompting import score_keys  # noqa: E402
from guardian_truth.judge.blind_review import select_ranking, validate_review_config  # noqa: E402

PROFILE = 'single-pass-judge-v3.1'
PRODUCTION_PROFILE = dict(questions=['overall'], hint_modes=['on'], aggregate='primary', extras_schedule='after_primary')
DEFAULTS = dict(model_dir='model/judge', positive_rate=0.30, hard_unknown_identifier=False,
                coverage_warning=0.9, judge_stop_seconds=1380, kill_seconds=1530, watchdog_seconds=1680,
                write_every_seconds=20, hard_rate_warning=0.2, **PRODUCTION_PROFILE)


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


def normalize_profile(cfg):
    """-> (cfg, error). A profile that cannot run is replaced by the production profile."""
    try:
        keys = [k for k, _, _ in score_keys(cfg)]
        if cfg.get('extras_schedule', 'after_primary') not in ('after_primary', 'per_chunk'):
            raise ValueError('BAD_EXTRAS_SCHEDULE: %s' % cfg.get('extras_schedule'))
        validate_aggregate(cfg, keys)
        validate_review_config(cfg)
        return cfg, None
    except Exception as error:  # noqa: BLE001 - a bad profile must not cost the submission
        safe = dict(cfg, review_mode='off', **PRODUCTION_PROFILE)
        safe.pop('aggregator', None)
        safe.pop('aggregate_keys', None)
        return safe, '%s: %s' % (type(error).__name__, error)


def read_scores(path, exact_only=False):
    """-> ({key: log-odds}, rows without a score, rows with a bounded (inexact) score, stage events).
    Primary records only; extra-score records ({"extra": true}) are read by read_question_scores."""
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
            if 'key' not in item or item.get('extra') or item.get('review'):
                continue
            if item.get('score') is None:
                missing += 1
            elif exact_only and (item.get('exact') is not True or not isinstance(item['score'], (int, float))
                                 or isinstance(item['score'], bool) or not math.isfinite(item['score'])):
                missing += 1
                inexact += item.get('exact') is not True
            else:
                scores[int(item['key'])] = float(item['score'])
                inexact += not item.get('exact', False)
    return scores, missing, inexact, events


def read_question_scores(path):
    """-> {row: {score key: log-odds}}: primary record keys merged with later extra records of the same row.
    Only finite exact scores (bounded scores stay out)."""
    out = {}
    if not path or not Path(path).exists():
        return out
    with open(path, encoding='utf-8') as stream:
        for line in stream:
            try:
                item = json.loads(line)
            except ValueError:
                break
            if 'key' not in item or 'event' in item or not isinstance(item.get('scores'), dict):
                continue
            if not item.get('extra') and (item.get('score') is None or item.get('exact') is not True):
                continue
            row = out.setdefault(int(item['key']), {})
            for k, v in item['scores'].items():
                if (k not in (item.get('bounded') or {}) and isinstance(v, (int, float))
                        and not isinstance(v, bool) and math.isfinite(v)):
                    row[k] = float(v)
    return out


def read_review_scores(path):
    """-> {row: final log-odds}: finite exact scores of review records {'review': 'final'} only."""
    out, seen = {}, set()
    if not path or not Path(path).exists():
        return out
    with open(path, encoding='utf-8', newline='') as stream:
        lines = stream.read().split('\n')
    for line in lines:
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except ValueError:
            break  # torn last line of a killed writer
        value = item.get('final_score')
        if item.get('review') != 'final':
            continue
        key = item.get('key')
        if isinstance(key, bool) or not isinstance(key, int) or key < 0 or key in seen:
            return {}  # an ambiguous row invalidates the final ranking globally
        seen.add(key)
        if (item.get('exact') is True
                and isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)):
            out[key] = float(value)
    return out


def effective_scores(scores, question, cfg, features):
    """-> (scores used for ranking, aggregate actually used, rows lacking aggregate inputs)."""
    mode = cfg.get('aggregate', 'primary')
    if mode == 'max_logit':
        matrix = exact_max_inputs(scores, question, cfg, len(features))
        used = combine(matrix, cfg)
        lacking = sum(any(name not in matrix.get(i, {}) for name in aggregate_inputs(cfg)) for i in range(len(features)))
        return used, 'max_logit', lacking
    if mode == 'primary' or not scores:
        return scores, 'primary', 0
    lacking = complete_inputs(question, list(scores), cfg)
    if lacking:
        return scores, 'primary(aggregate_incomplete)', len(lacking)
    merged = combine({i: question[i] for i in scores}, cfg, {i: features[i] for i in scores})
    if set(merged) != set(scores):
        return scores, 'primary(aggregate_incomplete)', len(set(scores) - set(merged))
    return merged, mode, 0


def exact_max_inputs(scores, question, cfg, n):
    """Allowed exact question scores plus the exact primary fallback; stable input positions only."""
    names = aggregate_inputs(cfg)
    matrix = {}
    for i, values in question.items():
        if isinstance(i, bool) or not isinstance(i, int) or not 0 <= i < n:
            continue
        matrix[i] = {name: float(values[name]) for name in names
                     if isinstance(values.get(name), (int, float)) and not isinstance(values[name], bool)
                     and math.isfinite(values[name])}
    primary = score_keys(cfg)[0][0]
    for i, value in scores.items():
        if (isinstance(i, int) and not isinstance(i, bool) and 0 <= i < n and primary in names
                and isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)):
            matrix.setdefault(i, {})[primary] = float(value)
    return matrix


def id_shape(identifier):
    return re.sub(r'[A-Za-z]+', 'a', re.sub(r'\d+', '9', str(identifier)))[:40]


def quantiles(values, points=(0.1, 0.25, 0.5, 0.75, 0.9)):
    xs = sorted(values)
    if not xs:
        return {}
    return {str(p): round(xs[min(len(xs) - 1, int(p * len(xs)))], 4) for p in points}


def file_size(path):
    try:
        return Path(path).stat().st_size if path else -1
    except OSError:
        return -1


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
    cfg, config_error = normalize_profile(cfg)
    if config_error:
        log(clock, 'CONFIG_INVALID', error=config_error, using=PRODUCTION_PROFILE)
    rows = read_input(input_path)
    ids, n = [row['id'] for row in rows], len(rows)
    log(clock, 'input', rows=n, profile=PROFILE, unique_ids=len(set(ids)),
        max_prompt_chars=max([len(r['prompt']) for r in rows] or [0]), positive_rate=cfg['positive_rate'],
        keys=[k for k, _, _ in score_keys(cfg)], aggregate=cfg['aggregate'],
        id_shapes=Counter(id_shape(i) for i in ids).most_common(5))
    if not rows:
        write_labels(output, [], [])
        return 0

    strict = bool(cfg.get('hard_unknown_identifier', False))
    findings = [analyze(r['prompt'], r['response'], strict) for r in rows]
    hard = {i for i, f in enumerate(findings) if f.hard}
    kinds = Counter(item.split()[0] for f in findings for item in f.hard)
    log(clock, 'mechanical', hard_rows=len(hard), hard_kinds=dict(kinds),
        rows_with_hints=sum(1 for f in findings if f.hints),
        hint_kinds=dict(Counter(item.split()[0] for f in findings for item in list(f.strong) + list(f.weak))))
    if n and len(hard) > float(cfg.get('hard_rate_warning', 0.2)) * n:
        log(clock, 'HARD_RATE_HIGH', hard_rows=len(hard), rows=n, hard_kinds=dict(kinds),
            incomplete_catalog_rows=sum(not f.features.get('catalog_complete', False) for f in findings),
            analysis_errors=sum('analysis_error' in f.features for f in findings))
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
    features = [f.features for f in findings]
    state = dict(scored=0, positives=None, labels=None, scores={}, used={}, writes=0, aggregate='primary',
                 lacking=0, size=-1)
    scores_path = None

    def publish(scores):
        question = read_question_scores(scores_path) if cfg['aggregate'] != 'primary' else {}
        used, mode, lacking = effective_scores(scores, question, cfg, features)
        if cfg.get('review_mode', 'off') != 'off':
            # final only when EVERY input row has a finite exact final score; else primary for all rows
            used, mode, lacking = select_ranking(used, read_review_scores(scores_path), list(range(n)))
        labels = decide(n, hard, used, rate)
        write_labels(output, ids, labels)
        state.update(scored=len(scores), positives=sum(labels), labels=labels, scores=scores, used=used,
                     writes=state['writes'] + 1, aggregate=mode, lacking=lacking)

    publish({})
    log(clock, 'baseline_written', positives=state['positives'])

    status, gone, stage_error, process, work_dir = 'NOT_STARTED', None, None, None, None

    def refresh():
        try:
            size = file_size(scores_path)
            if size != state['size']:
                state['size'] = size
                publish(read_scores(scores_path, exact_only=cfg['aggregate'] == 'max_logit')[0])
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
        scores, missing, inexact, events = read_scores(scores_path, exact_only=cfg['aggregate'] == 'max_logit')
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
    question = {}
    if work_dir is not None:
        stage_log = work_dir / 'stage.log'
        if stage_log.exists():
            tail = stage_log.read_text(encoding='utf-8', errors='replace')[-4000:]
            print('=== GUARDIAN JUDGE STAGE LOG TAIL ===\n' + tail, file=sys.stderr, flush=True)
        try:
            question = read_question_scores(scores_path)
            with (work_dir / 'decisions.jsonl').open('w', encoding='utf-8') as stream:
                for i in range(n):
                    source = 'hard' if i in hard else ('model' if i in state['used'] else 'fallback_zero')
                    stream.write(json.dumps(dict(key=i, id=ids[i], label=state['labels'][i], source=source,
                                                 hard=findings[i].hard, strong=findings[i].strong,
                                                 weak=findings[i].weak, features=findings[i].features,
                                                 prompt_sha256=hashlib.sha256(rows[i]['prompt'].encode('utf-8')).hexdigest(),
                                                 response_sha256=hashlib.sha256(rows[i]['response'].encode('utf-8')).hexdigest(),
                                                 score=state['scores'].get(i), scores=question.get(i),
                                                 ranked_by=state['used'].get(i))) + '\n')
        except Exception as error:
            log(clock, 'decisions_write_error', error=type(error).__name__)
    probs = [1.0 / (1.0 + math.exp(-max(-60.0, min(60.0, s)))) for s in state['scores'].values()]
    done = events.get('done') or {}
    log(clock, 'final', status=status, group_gone=gone, rows=n, scored=state['scored'], coverage=round(coverage, 4),
        coverage_low=low, fallback_rows=n - len(state['used']), no_score_rows=missing, inexact_rows=inexact,
        ranked_rows=len(state['used']), ranked_coverage=round(len(state['used']) / n, 4),
        question_coverage={key: sum(key in values for values in question.values()) for key in aggregate_inputs(cfg)},
        hard_rows=len(hard), positives=state['positives'], writes=state['writes'], aggregate=state['aggregate'],
        aggregate_lacking_rows=state['lacking'], rows_with_extra_scores=sum(1 for v in question.values() if len(v) > 1),
        primary_p_quantiles=quantiles(probs), stage_primary=done.get('primary'), stage_extras=done.get('extras'), stage_review=events.get('review_done'),
        tokens_per_second=done.get('tokens_per_second'), config_error=config_error, stage_error=stage_error,
        stage_failed=events.get('failed'), work=str(work_dir))
    return 0
