"""Bounded operator-only CI→runtime→verified full ZIP completion, without SSH."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = '.github/workflows/qwen-submission-runtime.yml'
TRANSPORT_NAMES = {
    'guardian-qwen-a100-runtime.tar.gz', 'guardian-qwen-a100-runtime.tar.gz.sha256',
    'RUNTIME_MANIFEST.json', 'BUILD_PROVENANCE.json', 'runtime-attestation.sigstore.json',
    'tests.log', 'cpu-smoke.json', 'offline_pip_install.log', 'public_empty_entrypoint.log',
    'bundled_native_imports.log', 'rebuilt_llama_version.log', 'docker-cpu-smoke.log',
    'bench-baseline-20261008-cpu-replay.json', 'bench-speed16-20261008-cpu-replay.json',
    'bench-baseline-20261008-bundled-docker-replay.json', 'bench-speed16-20261008-bundled-docker-replay.json',
}


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / (name + '.py'))
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def check_run(run, sha):
    if run.get('head_sha') != sha or run.get('path', '').split('@', 1)[0] != WORKFLOW:
        raise ValueError('EXACT_COMMIT_AND_RUNTIME_WORKFLOW_REQUIRED')
    if run.get('status') == 'completed' and run.get('conclusion') != 'success':
        raise RuntimeError('CI_TERMINAL_FAILURE_NO_AUTOMATIC_RERUN')
    return run.get('status') == 'completed' and run.get('conclusion') == 'success'


def publish_verified(source, destination):
    """Expose a completed archive without replacing another operator's file."""
    source, destination = Path(source), Path(destination)
    if os.name == 'nt':
        source.rename(destination)  # Windows rename refuses an existing target.
    else:
        os.link(source, destination)
        source.unlink()


def verify_local_artifact(path, artifact):
    """Adopt browser bytes only against independent authenticated CI metadata."""
    path = Path(path)
    expected = artifact.get('digest', '')
    if not isinstance(expected, str) or not re.fullmatch(r'sha256:[0-9a-f]{64}', expected):
        raise ValueError('AUTHORITATIVE_CI_ARTIFACT_DIGEST_REQUIRED')
    if path.is_symlink() or not path.is_file() or path.stat().st_size != artifact['size_in_bytes']:
        raise ValueError('COMPLETE_LOCAL_CI_ARTIFACT_SIZE_REQUIRED')
    before = path.stat()
    value = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(8 * 1024 * 1024), b''):
            value.update(chunk)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
        raise ValueError('LOCAL_CI_ARTIFACT_CHANGED_DURING_VERIFICATION')
    if 'sha256:' + value.hexdigest() != expected:
        raise ValueError('AUTHORITATIVE_LOCAL_CI_ARTIFACT_HASH_MISMATCH')
    return dict(path=str(path.resolve()), bytes=after.st_size, sha256=value.hexdigest(),
                artifact_id=artifact['id'], identity_source='authenticated GitHub CI metadata')


def extract_transport(source, destination):
    """Extract only the flat known CI artifact; no links, traversal or ZIP bomb."""
    destination = Path(destination)
    if destination.exists():
        raise ValueError('TRANSPORT_EXTRACTION_PATH_ALREADY_EXISTS')
    with zipfile.ZipFile(source) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError('DUPLICATE_TRANSPORT_ZIP_ENTRIES')
        if not {'guardian-qwen-a100-runtime.tar.gz', 'guardian-qwen-a100-runtime.tar.gz.sha256',
                'RUNTIME_MANIFEST.json'} <= set(names):
            raise ValueError('REQUIRED_RUNTIME_TRANSPORT_MEMBERS_MISSING')
        total = 0
        for entry in archive.infolist():
            path = PurePosixPath(entry.filename)
            if (entry.filename not in TRANSPORT_NAMES or len(path.parts) != 1
                    or '\\' in entry.filename or ':' in entry.filename or entry.is_dir()
                    or stat.S_ISLNK(entry.external_attr >> 16)):
                raise ValueError('UNSAFE_OR_UNAPPROVED_RUNTIME_TRANSPORT_ENTRY')
            total += entry.file_size
        if total > 4_000_000_000 or len(names) > len(TRANSPORT_NAMES):
            raise ValueError('RUNTIME_TRANSPORT_EXTRACTION_BOUND_EXCEEDED')
        destination.mkdir(parents=True)
        for entry in archive.infolist():
            with archive.open(entry) as source_file, (destination / entry.filename).open('xb') as target:
                while chunk := source_file.read(8 * 1024 * 1024):
                    target.write(chunk)  # ZipFile enforces CRC on complete read.


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--sha', required=True)
    parser.add_argument('--run', type=int)
    parser.add_argument('--repo', default='MYC-A/Guardian-of-Truth')
    parser.add_argument('--model', type=Path, required=True)
    parser.add_argument('--local-artifact', type=Path)
    parser.add_argument('--phase', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=Path('A:/Guardian-submissions/guardian-qwen-b2-rebuilt.zip'))
    parser.add_argument('--timeout-minutes', type=int, default=90)
    args = parser.parse_args()
    args.model, args.phase, args.output = (p.resolve() for p in (args.model, args.phase, args.output))
    if not re.fullmatch('[0-9a-f]{40}', args.sha) or not re.fullmatch(r'[\w.-]+/[\w.-]+', args.repo):
        raise ValueError('FULL_COMMIT_SHA_AND_GITHUB_REPOSITORY_REQUIRED')
    if not 1 <= args.timeout_minutes <= 90:
        raise ValueError('COMPLETION_TIMEOUT_MUST_BE_1_TO_90_MINUTES')
    partial = args.output.with_suffix(args.output.suffix + '.partial')
    if args.output.exists() or partial.exists() or args.phase.exists():
        raise ValueError('FRESH_PHASE_AND_NONEXISTENT_FINAL_ZIP_REQUIRED')
    if not args.model.is_file():
        raise ValueError('COMPLETE_MODEL_SOURCE_REQUIRED')
    args.phase.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    deadline = started + args.timeout_minutes * 60
    context = dict(pid=os.getpid(), expected_commit=args.sha, run_id=args.run,
                   model_path=str(args.model.resolve()), final_path=str(args.output.resolve()),
                   GPU_INFERENCE='NOT_EXECUTED_FOR_REBUILT_RUNTIME')

    def save(state, **fields):
        content = dict(context, state=state, elapsed_seconds=time.monotonic() - started, **fields)
        temporary = args.phase / 'status.json.new'
        temporary.write_text(json.dumps(content, indent=2), encoding='utf-8')
        os.replace(temporary, args.phase / 'status.json')

    def left():
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('BOUNDED_COMPLETION_DEADLINE_EXCEEDED')
        return remaining

    def command(label, parameters):
        result = subprocess.run([sys.executable, '-X', 'utf8', *map(str, parameters)], cwd=ROOT,
                                capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=left(),
                                env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONUTF8='1'))
        text = result.stdout + result.stderr
        # Provider exceptions can include signed redirect URLs; no such URL is retained.
        text = re.sub(r'https?://[^\s<>\"\']+', '[REDACTED_URL]', text)
        (args.phase / (label + '.log')).write_text(text, encoding='utf-8')
        if result.returncode:
            raise RuntimeError('COMPLETION_STEP_FAILED: ' + label)

    try:
        github = module('github_runtime_artifacts')
        token = github.credential()
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), github.NoRedirect())
        def api(path):
            request = urllib.request.Request('https://api.github.com/repos/' + args.repo + '/' + path,
                                             headers={'Authorization': 'Bearer ' + token,
                                                      'Accept': 'application/vnd.github+json',
                                                      'User-Agent': 'Guardian-bounded-completion'})
            with opener.open(request, timeout=min(30, left())) as response:
                return json.load(response)
        save('WAITING_FOR_EXACT_CI_RUN')
        while True:
            if not context['run_id']:
                rows = api('actions/runs?' + urllib.parse.urlencode(dict(head_sha=args.sha, per_page=100)))['workflow_runs']
                matching = [r for r in rows if r.get('head_sha') == args.sha
                            and r.get('path', '').split('@', 1)[0] == WORKFLOW]
                if len(matching) > 1:
                    raise ValueError('AMBIGUOUS_EXACT_COMMIT_CI_RUN_SPECIFY_RUN_ID')
                if matching:
                    context['run_id'] = matching[0]['id']
            if context['run_id']:
                run = api('actions/runs/' + str(context['run_id']))
                if check_run(run, args.sha):
                    break
                save('WAITING_FOR_EXACT_CI_RUN', ci_status=run.get('status'))
            time.sleep(min(60, left()))
        if args.local_artifact:
            save('VERIFYING_LOCAL_RUNTIME_ARTIFACT')
            artifacts = api('actions/runs/' + str(context['run_id']) + '/artifacts')['artifacts']
            matching = [item for item in artifacts
                        if item['name'] == 'guardian-qwen-a100-runtime-' + args.sha]
            if len(matching) != 1:
                raise ValueError('ONE_EXACT_COMMIT_CI_ARTIFACT_REQUIRED')
            adopted = verify_local_artifact(args.local_artifact, matching[0])
            (args.phase / 'local-artifact-verification.json').write_text(
                json.dumps(adopted, indent=2), encoding='utf-8')
            transport_zip = args.local_artifact
        else:
            save('DOWNLOADING_VERIFIED_EXACT_COMMIT_RUNTIME')
            transport_dir = args.phase / 'download'
            command('runtime-download', [ROOT / 'scripts/github_runtime_artifacts.py', '--repo', args.repo,
                                         '--sha', args.sha, '--run', context['run_id'], '--directory', transport_dir])
            transport_zip = transport_dir / ('guardian-qwen-a100-runtime-' + args.sha + '.zip')
        transport = args.phase / 'transport'
        extract_transport(transport_zip, transport)
        checksum_line = (transport / 'guardian-qwen-a100-runtime.tar.gz.sha256').read_text(encoding='utf-8').strip()
        match = re.fullmatch(r'([0-9a-f]{64})\s+guardian-qwen-a100-runtime\.tar\.gz', checksum_line)
        if not match:
            raise ValueError('EXACT_RUNTIME_TAR_CHECKSUM_LINE_REQUIRED')
        save('VERIFYING_AND_EXTRACTING_RUNTIME')
        runtime = module('rebuild_qwen_runtime')
        stage = args.phase / 'runtime'
        runtime.extract(transport / 'guardian-qwen-a100-runtime.tar.gz', stage, match.group(1))
        manifest = runtime.verify(stage)
        if manifest['commit'] != args.sha:
            raise ValueError('EXTRACTED_RUNTIME_COMMIT_MISMATCH')
        if runtime.digest(stage / 'MANIFEST.json') != runtime.digest(transport / 'RUNTIME_MANIFEST.json'):
            raise ValueError('EXTRACTED_AND_EXTERNAL_RUNTIME_MANIFEST_MISMATCH')
        left()
        save('VERIFYING_FULL_MODEL_AND_ASSEMBLING')
        assembled = args.phase / 'submission-stage'
        command('assemble', [ROOT / 'scripts/rebuild_qwen_runtime.py', 'assemble', '--runtime', stage,
                             '--model', args.model, '--destination', assembled])
        save('BUILDING_FULL_SUBMISSION_ZIP')
        args.output.parent.mkdir(parents=True, exist_ok=True)
        command('archive', [ROOT / 'scripts/build_qwen_submission.py', 'zip', '--stage', assembled,
                            '--destination', partial])
        save('VERIFYING_ALL_ZIP_BYTES_AND_PACKAGING')
        raw_receipt = args.phase / 'prepublication-packaging-verification.json'
        command('final-verification', [ROOT / 'scripts/verify_qwen_submission.py', '--archive', partial,
                                       '--receipt', raw_receipt])
        final = json.loads(raw_receipt.read_text(encoding='utf-8'))
        if final['source_commit'] != args.sha:
            raise ValueError('FINAL_ZIP_COMMIT_MISMATCH')
        publish_verified(partial, args.output)
        final.update(verified_before_publication_path=final['path'],
                     path=str(args.output.resolve()), publication='atomic_after_complete_verification')
        receipt = args.phase / 'final-packaging-verification.json'
        with receipt.open('x', encoding='utf-8') as handle:
            json.dump(final, handle, indent=2)
        save('READY_VERIFIED_PACKAGING', zip_sha256=final['zip_sha256'], bytes=final['bytes'],
             receipt=str(receipt.resolve()), quality='NEW_GPU_INFERENCE_NOT_EXECUTED')
        print((args.phase / 'status.json').read_text(encoding='utf-8'))
    except BaseException as error:
        # No provider text/URLs/credential-bearing exception representation.
        save('FAILED', error_class=type(error).__name__)
        raise RuntimeError('BOUNDED_SUBMISSION_COMPLETION_FAILED: ' + type(error).__name__) from None


if __name__ == '__main__':
    main()
