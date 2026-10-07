"""Explicit expected IDs and legal technical-retry chains for research phases."""
import json
import hashlib
from pathlib import Path


def charged_usage(data, estimated_input, estimated_output):
    """Partial/malformed usage cannot release the conservative reservation."""
    usage = (data or {}).get('usage')
    if isinstance(usage, dict):
        values = [usage.get('prompt_tokens'), usage.get('completion_tokens')]
        if all(type(value) is int and value >= 0 for value in values):
            return values[0], values[1], False
    return estimated_input, estimated_output, True


def failed_record(record):
    """Primary inference failure controls whole-row retry.

    Optional layer/verifier failures are retained by technical_gaps instead;
    a valid fallback decision must not trigger endless full-row reruns.
    """
    if record.get('error'):
        return True
    steps = list(record.get('pre_steps') or []) + list(((record.get('rec') or {}).get('A') or {}).get('steps') or [])
    for step in steps:
        if step.get('admission') in ('INVALID_JSON', 'INVALID_SCHEMA', 'TRANSPORT_FAILURE', 'NOT_EXECUTED'):
            return True
        validation = step.get('schema_validation') or {}
        if validation.get('status') in ('INVALID_JSON', 'INVALID_SCHEMA', 'TRANSPORT_FAILURE'):
            return True
        if step.get('parsed_ok') is False or ('parsed' in step and step['parsed'] is None):
            return True
        if step.get('raw_content') is None and str((step.get('transport') or {}).get('status')) != '200':
            return True
    return False


def technical_gaps(record):
    """Expose terminal incomplete work without counting resolved first replies."""
    gaps = []
    def visit(value, path):
        if isinstance(value, dict):
            admission = value.get('admission')
            verification = value.get('verification_status')
            schema = (value.get('schema_validation') or {}).get('status')
            status = next((x for x in (admission, verification, schema) if isinstance(x, str) and
                           (x.startswith('INVALID_') or x in ('TRANSPORT_FAILURE', 'COMPLETION_FAILURE',
                            'TECHNICAL_FAILURE', 'NOT_EXECUTED', 'MISSING_REQUEST_SCHEMA'))), None)
            if status:
                gaps.append(dict(path=path, status=status))
                return
            transport = (value.get('transport') or {}).get('status')
            if value.get('content', value.get('raw_content')) is None and isinstance(transport, str) and transport.startswith('NOT_EXECUTED'):
                gaps.append(dict(path=path, status=transport))
                return
            for key, child in value.items():
                if key not in ('first_invalid', 'technical_gaps'):
                    visit(child, path + '/' + str(key))
        elif isinstance(value, list):
            for index, child in enumerate(value):
                visit(child, path + '/' + str(index))
    visit(record, '')
    return gaps


def expected_manifest(path, ids):
    ids = list(ids)
    if len(set(ids)) != len(ids):
        raise ValueError('DUPLICATE_EXPECTED_IDS')
    path = Path(path).with_suffix('.expected.json')
    if path.exists():
        if json.loads(path.read_text(encoding='utf-8')) != ids:
            raise ValueError('EXPECTED_IDS_CHANGED: ' + str(path))
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('x', encoding='utf-8', newline='\n') as handle:
            json.dump(ids, handle, ensure_ascii=False)
            handle.write('\n')
    return ids


def load_records(path, expected_ids, *, allow_missing=False):
    path = Path(path)
    expected_ids = list(expected_ids)
    expected = set(expected_ids)
    if len(expected) != len(list(expected_ids)):
        raise ValueError('DUPLICATE_EXPECTED_IDS')
    result, chains = {}, {}
    if path.exists():
        for line in path.read_text(encoding='utf-8').splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            identifier = row.get('id')
            if identifier not in expected:
                raise ValueError('UNEXPECTED_ID: ' + str(identifier))
            if not isinstance(identifier, str) or not identifier:
                raise ValueError('INVALID_RECORD_ID')
            if not failed_record(row) and (type(row.get('binary')) is not int or row['binary'] not in (0, 1)):
                raise ValueError('INVALID_BINARY_RECORD: ' + identifier)
            if identifier in result and not failed_record(result[identifier]):
                raise ValueError('RECORD_AFTER_SUCCESS: ' + str(identifier))
            result[identifier] = row
            chains[identifier] = chains.get(identifier, 0) + 1
    missing = sorted(expected - set(result))
    if missing and not allow_missing:
        raise ValueError('MISSING_IDS: ' + ','.join(missing))
    return result, dict(expected=len(expected), observed=len(result), missing=missing,
                        retry_chains={i: n for i, n in chains.items() if n > 1})


def expected_for_score(path, gold_ids, overrides=None):
    path = Path(path)
    manifest = path.with_suffix('.expected.json')
    if overrides and path.stem in overrides:
        expected = list(overrides[path.stem])
    elif manifest.exists():
        expected = json.loads(manifest.read_text(encoding='utf-8'))
    else:
        expected = list(gold_ids)
    if not set(expected) <= set(gold_ids):
        raise ValueError('EXPECTED_IDS_OUTSIDE_GOLD')
    return expected


def freeze_phase(path, root, config, inputs):
    """A resume may reuse successful rows only under the exact same code/config/input."""
    path, root = Path(path), Path(root)
    files = sorted((root / 'src/guardian_truth').rglob('*.py'))
    for study in ('guardian_semantic', 'guardian_addons'):
        files += sorted((root / 'experiments' / study).glob('*.py'))
    files.append(root / 'experiments/research_records.py')
    code = hashlib.sha256()
    for filename in sorted(files):
        code.update(str(filename.relative_to(root)).replace('\\', '/').encode('utf-8'))
        code.update(filename.read_bytes())
    identity = dict(version='contract-phase-v1', config=config, code_sha256=code.hexdigest(),
                    input_sha256=hashlib.sha256(json.dumps(inputs, sort_keys=True, ensure_ascii=False).encode('utf-8')).hexdigest())
    manifest = path.with_suffix('.phase.json')
    if manifest.exists():
        if json.loads(manifest.read_text(encoding='utf-8')) != identity:
            raise ValueError('PHASE_FINGERPRINT_CHANGED')
    elif path.exists():
        raise ValueError('UNVERSIONED_OUTPUT_REFUSED')
    else:
        manifest.parent.mkdir(parents=True, exist_ok=True)
        with manifest.open('x', encoding='utf-8', newline='\n') as handle:
            json.dump(identity, handle, sort_keys=True, ensure_ascii=False, indent=2)
            handle.write('\n')
    return identity
