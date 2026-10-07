"""Finite, supervised continuation: wait for existing Distill, publish, run Lynx, publish.

Never restarts the preceding model circle or changes production. A native-lane
failure is published explicitly. Waiting uses Linux pidfd, not repeated polling.
"""
import json
import os
import select
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from guardian_truth.file_lock import process_lock

ROOT = Path(__file__).resolve().parents[2]
BASE = Path('/workspace/guardian')
BRANCH = 'research/guardian-local-a100-20261007-1'
DISTILL = 'qwen3.8-27b-opus-distill-v2@64d56b13ea8d:Q8_0:llamacpp-b11459'
LYNX = 'llama-3-patronus-lynx-70b@581017200918:IQ4_XS:llamacpp-b11459'
OUTPUT = ROOT / 'outputs/guardian_local_a100/continuation_20261007'


def event(status, **fields):
    value = dict(status=status, utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), **fields)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with (OUTPUT / 'events.jsonl').open('a', encoding='utf-8') as handle:
        handle.write(json.dumps(value) + '\n')
        handle.flush()
        os.fsync(handle.fileno())
    tmp = OUTPUT / 'state.tmp'
    tmp.write_text(json.dumps(value, indent=2), encoding='utf-8')
    tmp.replace(OUTPUT / 'state.json')
    print(json.dumps(value), flush=True)


def run(args, timeout=240, capture=False):
    r = subprocess.run(args, cwd=ROOT, check=False, timeout=timeout,
                       stdout=subprocess.PIPE if capture else None,
                       stderr=subprocess.PIPE if capture else None, text=True)
    if r.returncode:
        raise RuntimeError(f'COMMAND_FAILED:{args[0]}:{r.returncode}')
    return r.stdout if capture else None


def publish(paths, message):
    staged = run(['git', 'diff', '--cached', '--name-only'], capture=True)
    if staged.strip():
        raise RuntimeError('FOREIGN_STAGED_CHANGES_REFUSED')
    present = [str(p.relative_to(ROOT)) for p in paths if p.exists()]
    run(['git', 'add', '--', *present])
    delta = subprocess.run(['git', 'diff', '--cached', '--quiet'], cwd=ROOT)
    if delta.returncode == 1:
        run(['git', 'commit', '-m', message], capture=True)
    elif delta.returncode:
        raise RuntimeError('STAGED_DIFF_FAILED')
    run(['git', 'push', '--quiet', 'origin', 'HEAD:refs/heads/' + BRANCH], capture=True)
    head = run(['git', 'rev-parse', 'HEAD'], capture=True).strip()
    remote = run(['git', 'ls-remote', '--exit-code', 'origin', 'refs/heads/' + BRANCH], capture=True).split()[0]
    if remote != head:
        raise RuntimeError('REMOTE_SHA_MISMATCH')
    print('PUSH_VERIFIED ' + head, flush=True)


def matching_processes(fragment):
    out = []
    for p in Path('/proc').iterdir():
        if not p.name.isdigit() or int(p.name) == os.getpid():
            continue
        try:
            args = (p / 'cmdline').read_bytes().split(b'\0')
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
        if any(fragment == s.decode('utf-8', 'replace') for s in args):
            out.append(int(p.name))
    return out


def wait_process(pid, seconds):
    try:
        fd = os.pidfd_open(pid)
    except ProcessLookupError:
        return
    try:
        if not select.select([fd], [], [], seconds)[0]:
            raise TimeoutError('EXISTING_PROCESS_DEADLINE')
    finally:
        os.close(fd)


def main():
    os.environ.update(PYTHONPATH=str(ROOT / 'src') + ':' + str(ROOT), PYTHONDONTWRITEBYTECODE='1',
                      GUARDIAN_DATA_ROOT=str(BASE / 'data_root_403d811e'),
                      LOCAL_LLAMACPP_ENDPOINT='http://127.0.0.1:8081/v1/chat/completions',
                      GIT_TERMINAL_PROMPT='0')
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with process_lock(OUTPUT / 'queue.lock'):
        if (OUTPUT / 'done.json').exists():
            print('ALREADY_DONE', flush=True)
            return
        owned = None
        distill_root = ROOT / 'outputs/guardian_local_a100/llamacpp' / DISTILL
        lynx_root = ROOT / 'outputs/guardian_local_a100/llamacpp' / LYNX
        try:
            if (OUTPUT / 'distill_stopped_by_owner.json').exists():
                event('DISTILL_PARTIAL_STOPPED_BY_OWNER')
                publish([distill_root, OUTPUT], 'local-a100: preserve owner-stopped partial Distill B2 before Lynx')
            else:
                parents = matching_processes('scripts_a100/distill_first_circle.sh')
                if len(parents) > 1:
                    raise RuntimeError('MULTIPLE_EXISTING_DISTILL_JOBS')
                if parents:
                    event('WAITING_EXISTING_DISTILL', pid=parents[0], deadline_seconds=10800)
                    wait_process(parents[0], 10800)
                event('DISTILL_OFFLINE_SCORE')
                score = distill_root / 'score_first_circle_qa.json'
                if not score.exists():
                    run([sys.executable, '-X', 'utf8', '-m', 'experiments.guardian_local_a100.score_local',
                         '--backend', 'llamacpp', '--model-id', DISTILL, '--sets', 'dev,contrast,valid46', '--json', str(score)])
                summaries = json.loads(score.read_text(encoding='utf-8'))['summary']
                for name, count in [('dev', 10), ('contrast', 14), ('valid46', 46)]:
                    for arm in ['A_rep1', 'M_rep1', 'B2_rep1']:
                        item = summaries[name][arm]
                        if item['rows'] != count or item.get('missing'):
                            raise RuntimeError('DISTILL_INCOMPLETE_CELL')
                event('DISTILL_COMPLETE_70_AM_B2')
                publish([distill_root, OUTPUT], 'local-a100: preserve completed Distill 70-row circle and QA score')
            server_pids = matching_processes(str(BASE / 'models/Qwen3.8-27B-Opus-Distill-v2-Q8_0.gguf'))
            for pid in server_pids:
                event('STOPPING_SAVED_DISTILL_SERVER', pid=pid)
                os.kill(pid, signal.SIGTERM)
                wait_process(pid, 60)
            event('LYNX_LOADING')
            server = BASE / 'llamacpp-src/build/bin/llama-server'
            weights = BASE / 'models/Llama-3-Patronus-Lynx-70B-Instruct-IQ4_XS.gguf'
            if not weights.is_file():
                raise RuntimeError('LYNX_WEIGHTS_NOT_AVAILABLE')
            with (BASE / 'logs/llamaserver_lynx_v2.log').open('a') as log:
                owned = subprocess.Popen([str(server), '-m', str(weights), '--alias', LYNX,
                                          '--host', '127.0.0.1', '--port', '8081', '-ngl', '999',
                                          '-c', '64000', '-np', '8', '--jinja', '--no-context-shift', '-fa', 'on'],
                                         stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
            deadline = time.monotonic() + 300
            while time.monotonic() < deadline:
                if owned.poll() is not None:
                    raise RuntimeError('LYNX_SERVER_EXITED')
                try:
                    with urllib.request.urlopen('http://127.0.0.1:8081/health', timeout=2) as response:
                        if response.status == 200:
                            break
                except Exception:
                    time.sleep(2)
            else:
                raise TimeoutError('LYNX_SERVER_READY_DEADLINE')
            event('LYNX_NATIVE_SMOKE_AND_70_GROUNDING')
            run([sys.executable, '-X', 'utf8', '-m', 'experiments.guardian_local_a100.lynx_native_v2',
                 '--model-id', LYNX, '--accuse-run-root', str(distill_root / 'runs'),
                 '--sets', 'dev,contrast,valid46', '--arms', 'A,B2',
                 '--workers', '8', '--max-tokens', '600', '--allow-partial-accusations'], timeout=5400)
            event('LYNX_COMPLETE')
            publish([lynx_root, OUTPUT], 'local-a100: preserve Lynx native JSON grounding receipts on 70 fixed inputs')
            report = OUTPUT / 'first_circle_comparison_qa.json'
            if not report.exists():
                run([sys.executable, '-X', 'utf8', '-m', 'experiments.guardian_local_a100.first_circle_qa', '--output', str(report)])
            event('DONE', comparison=str(report.relative_to(ROOT)))
            with (OUTPUT / 'done.json').open('x') as handle:
                json.dump(dict(status='DONE', quality_claim='diagnostic only; native grounding is not policy classification'), handle)
            publish([OUTPUT], 'local-a100: publish first-circle coverage QA and separate A/B2 model rankings')
        except Exception as error:
            event('BLOCKED', error=type(error).__name__, detail=str(error)[:250])
            try:
                publish([OUTPUT, distill_root, lynx_root], 'local-a100: preserve continuation failure and partial receipts')
            except Exception as publication:
                print('PUBLICATION_FAILED ' + type(publication).__name__, flush=True)
            raise
        finally:
            if owned is not None and owned.poll() is None:
                owned.terminate()
                try:
                    owned.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    owned.kill()
                    owned.wait(timeout=10)


if __name__ == '__main__':
    main()
