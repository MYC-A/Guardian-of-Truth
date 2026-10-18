"""Prepare pinned, label-isolated evaluation files. No models or paid APIs.

External code is read as source evidence, never imported/executed. CompliBench is
adapted to prefix/current-turn judging, not its original full-conversation metric.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
import gzip
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import unicodedata
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / 'docs/judge_20261013/eval_data_20261018'
SEED = 'guardian-eval-family-v1-20261018'
NEAR_THRESHOLD = .85
GOLDS = {
    'ext_tau2': 'outputs/verification_v4/external/tau2v2/GOLD_eval_only.json',
    'hold_tau2h': 'outputs/universal_repair/holdout/tau2h/GOLD_frozen.json',
    'hold_holdout2': 'outputs/guardian_v6/holdout2/GOLD_frozen.json',
    'lb_long': 'outputs/verification_v2/lockbox/long/GOLD_eval_only.json',
    'lb2_long': 'outputs/verification_v2/lockbox2/long/GOLD_eval_only.json',
    'lb3_long': 'outputs/verification_v2/lockbox3/long/GOLD_eval_only.json',
}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def digest(obj):
    return sha(canonical(obj).encode('utf-8'))


def write_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(obj, indent=2, ensure_ascii=False) + '\n').encode('utf-8'))


def write_jsonl(path, rows):
    # Literal Unicode separators stay escaped; LF is the only record delimiter.
    path.write_bytes((''.join(json.dumps(r, ensure_ascii=True, sort_keys=True) + '\n'
                              for r in rows)).encode('utf-8'))


def fetch(record, cache, allow_download):
    path = cache / record['filename']
    if not path.exists():
        if not allow_download:
            raise FileNotFoundError(f'{path}: supply --download for pinned public data')
        request = urllib.request.Request(record['url'], headers={'User-Agent': 'Guardian-eval-data/1'})
        with urllib.request.urlopen(request, timeout=60) as response:
            raw = response.read(record['bytes'] + 1)
        if len(raw) != record['bytes'] or sha(raw) != record['sha256']:
            raise ValueError('SOURCE_DOWNLOAD_HASH_OR_LENGTH_MISMATCH: ' + path.name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    raw = path.read_bytes()
    if len(raw) != record['bytes'] or sha(raw) != record['sha256']:
        raise ValueError('SOURCE_HASH_OR_LENGTH_MISMATCH: ' + path.name)
    return raw


def role_block(role, content):
    return '\u27e6' + role.upper() + '\u27e7\n' + content + '\n'


def compli_rows(doc, source_path, source_sha, group):
    """Allowlist only oracle Cat2/3 policy + earlier role/content; gold stays aside."""
    policy = {k: v for k, v in doc['assistant_guidelines'].items()
              if k.lower().startswith(('category 2', 'category 3'))}
    if len(policy) != 2:
        raise ValueError('COMPLI_POLICY_CATEGORIES')
    system = ('You are a customer-service assistant. Follow the operational policy below.\n'
              '<policy>\n' + json.dumps(policy, ensure_ascii=False, indent=2) + '\n</policy>')
    messages = doc['message_list']
    indices = [m['turn_index'] for m in messages]
    if len(indices) != len(set(indices)) or indices != sorted(indices):
        raise ValueError('COMPLI_TURN_ORDER')
    mistakes = {m['turn_index']: m for m in doc['mistakes']}
    if len(mistakes) != len(doc['mistakes']):
        raise ValueError('COMPLI_DUPLICATE_GOLD_TURN')
    assistant_indices = {m['turn_index'] for m in messages if m['role'] == 'assistant'}
    if not set(mistakes) <= assistant_indices:
        raise ValueError('COMPLI_GOLD_NOT_ASSISTANT')
    history = role_block('system', system)
    rows = []
    for message in messages:
        role, content = message['role'], message['content']
        if role not in ('assistant', 'user') or not isinstance(content, str):
            raise ValueError('COMPLI_UNSUPPORTED_MESSAGE')
        if role == 'assistant':
            if not message.get('category') or not message.get('key'):
                raise ValueError('COMPLI_ASSISTANT_WITHOUT_UPSTREAM_GOLD')
            if not message['category'].lower().startswith(('category 2', 'category 3')):
                raise ValueError('COMPLI_UNSCOPED_CATEGORY')
            ti = message['turn_index']
            rows.append(dict(id='compli:' + source_path + ':t' + str(ti), prompt=history,
                response=role_block('assistant', content), label=int(ti in mistakes),
                group=group, conversation=source_path, domain=source_path.split('/')[1],
                turn_index=ti, source_path=source_path, source_sha256=source_sha,
                label_provenance='upstream metrics.build_truth: assistant annotation + mistakes membership',
                oracle_scope='Category2/3 only; prefix adaptation; materiality not re-adjudicated',
                upstream_annotation=mistakes.get(ti, {k: message[k] for k in ('category', 'key', 'phase')
                                                    if k in message})))
        history += role_block(role, content)
    return rows


def shingles(messages):
    text = ' '.join(m['role'] + ' ' + m['content'] for m in messages)
    text = unicodedata.normalize('NFKC', text).casefold()
    words = re.findall(r'\w+', re.sub(r'\d+', ' NUM ', text))
    return {tuple(words[i:i+5]) for i in range(max(0, len(words)-4))}


def near_pairs(conversations):
    """Exact Jaccard on normalized full-dialogue 5-word shingles, no model results."""
    sets = [shingles(d['message_list']) for _, d in conversations]
    pairs = []
    for i, a in enumerate(sets):
        if not a:
            continue
        for j in range(i):
            b = sets[j]
            if not b or min(len(a), len(b)) / max(len(a), len(b)) < NEAR_THRESHOLD:
                continue
            intersection = len(a & b)
            score = intersection / (len(a) + len(b) - intersection)
            if score >= NEAR_THRESHOLD:
                pairs.append(dict(left=conversations[j][0], right=conversations[i][0], jaccard=score))
    return pairs


def make_split(conversations, pairs, inspected=()):
    family = {path: 'compli:' + path.split('/')[1] + ':' + d['intent_name']
              for path, d in conversations}
    parent = {v: v for v in family.values()}
    def find(x):
        if parent[x] != x:
            parent[x] = find(parent[x])
        return parent[x]
    for pair in pairs:
        a, b = sorted((find(family[pair['left']]), find(family[pair['right']])))
        parent[b] = a
    groups = {path: find(f) for path, f in family.items()}
    domain_groups = defaultdict(set)
    for path, group in groups.items():
        domain_groups[path.split('/')[1]].add(group)
    split = {}
    for domain, gs in sorted(domain_groups.items()):
        ordered = sorted(gs, key=lambda g: digest([SEED, g]))
        if len(ordered) < 4:
            raise ValueError('TOO_FEW_FAMILY_GROUPS: ' + domain)
        for group in inspected:
            if group in ordered:
                ordered.remove(group)
                ordered.insert(1, group)  # schema-inspected family is development only
        for i, group in enumerate(ordered):
            value = 'pilot' if i == 0 else 'dev' if i <= 2 else 'eval'
            if group in split and split[group] != value:
                raise ValueError('CROSS_DOMAIN_NEAR_DUPLICATE_SPLIT_REQUIRES_REVIEW')
            split[group] = value
    return groups, split


def select_pilot(rows, n=24):
    # Label-blind length coverage, with at most one target turn per conversation.
    representatives = {}
    for r in rows:
        key = r['conversation']
        if key not in representatives or digest([SEED, r['id']]) < digest([SEED, representatives[key]['id']]):
            representatives[key] = r
    ordered = sorted(representatives.values(), key=lambda r: (len(r['prompt'])+len(r['response']), r['id']))
    if len(ordered) < 16:
        raise ValueError('INSUFFICIENT_UNIQUE_PILOT_CONVERSATIONS')
    n = min(n, len(ordered))
    return [ordered[(i * (len(ordered)-1)) // (n-1)] for i in range(n)]


def write_set(out, name, rows, purpose):
    folder = out / name
    folder.mkdir(parents=True, exist_ok=True)
    inputs = [{k: r[k] for k in ('id', 'prompt', 'response')} for r in rows]
    with (folder/'inputs.csv').open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=('id', 'prompt', 'response'), lineterminator='\n')
        writer.writeheader(); writer.writerows(inputs)
    labels = [dict(position=i, **{k: v for k, v in r.items() if k not in ('prompt', 'response')},
                   source_pair_sha256=digest([r['prompt'], r['response']])) for i, r in enumerate(rows)]
    write_jsonl(folder/'labels.jsonl', labels)
    chars = sorted(len(r['prompt'])+len(r['response']) for r in rows)
    result = dict(path=name, purpose=purpose, rows=len(rows), groups=len({r['group'] for r in rows}),
        conversations=len({r['conversation'] for r in rows}), classes=dict(Counter(str(r['label']) for r in rows)),
        domains=dict(Counter(r['domain'] for r in rows)),
        chars=dict(min=chars[0], median=chars[len(chars)//2], max=chars[-1]),
        tokens='NOT_COUNTED; use pinned target tokenizer before GPU run; no trimming in this builder',
        files={f: dict(bytes=(folder/f).stat().st_size, sha256=sha((folder/f).read_bytes()))
               for f in ('inputs.csv', 'labels.jsonl')})
    write_json(folder/'MANIFEST.json', result)
    return result


def historical_rows(lock):
    evidence = []
    def blob(rev, path):
        raw = subprocess.check_output(['git', 'show', rev+':'+path], cwd=ROOT)
        evidence.append(dict(revision=rev, path=path, sha256=sha(raw), bytes=len(raw)))
        return raw
    rev, goldrev = lock['historical_inputs_revision'], lock['historical_gold_revision']
    manifest = json.loads(blob(rev, 'outputs/guardian_complementarity/inputs/MANIFEST.json'))
    validgold = json.loads((SPEC/'valid46_labels.json').read_text(encoding='utf-8'))
    rows, excluded = [], []
    for dataset, expected in manifest.items():
        raw = blob(rev, 'outputs/guardian_complementarity/inputs/'+dataset+'.csv')
        source = list(csv.DictReader(io.StringIO(raw.decode('utf-8-sig'), newline='')))
        assert sha(raw) == expected['sha256'] and len(source) == expected['rows']
        gold = ({r['id']: r for r in validgold['labels']} if dataset == 'valid46' else
                json.loads(blob(goldrev, GOLDS[dataset])))
        for position, r in enumerate(source):
            if r['id'] not in gold:
                excluded.append(dict(dataset=dataset, position=position, id=r['id'], reason='NO_CURRENT_TURN_GOLD'))
                continue
            label = gold[r['id']]['label']
            if label not in (0, 1):
                raise ValueError('HISTORICAL_LABEL')
            rows.append(dict(id='seen:'+dataset+':'+r['id'], prompt=r['prompt'], response=r['response'],
                label=int(label), original_id=r['id'], dataset=dataset, original_position=position,
                group='seen-prompt-proxy:'+sha(r['prompt'].encode()), conversation=dataset+':'+r['id'].split('::')[0],
                domain=dataset, label_provenance='previously used frozen current-turn gold; not re-adjudicated',
                previous_use='SEEN_RESEARCH_REGRESSION_ONLY'))
    assert len(rows) == 397 and len(excluded) == 2
    return rows, excluded, evidence


def prepare(out, cache, download=False):
    csv.field_size_limit(2**31-1)
    if (out/'MANIFEST.json').exists():
        raise FileExistsError('Use a fresh output directory; existing frozen suite is not overwritten')
    out.mkdir(parents=True, exist_ok=True)
    lock = json.loads((SPEC/'SOURCES.lock.json').read_text(encoding='utf-8'))
    raw = fetch(lock['compli'], cache, download)
    archive = zipfile.ZipFile(io.BytesIO(raw))
    prefix = archive.namelist()[0].split('/')[0]+'/'
    conversations, upstream_manifests = [], {}
    for entry in sorted(archive.namelist()):
        path = entry.removeprefix(prefix)
        if path.startswith('data/') and path.endswith('.json'):
            doc = json.loads(archive.read(entry))
            if 'message_list' in doc:
                conversations.append((path, doc))
            else:
                upstream_manifests[path] = doc
    assert len(conversations) == 306
    pairs = near_pairs(conversations)
    groups, assignments = make_split(conversations, pairs, lock['preparation_inspected_families'])
    pools = defaultdict(list)
    for path, doc in conversations:
        rows = compli_rows(doc, path, sha(archive.read(prefix+path)), groups[path])
        pools[assignments[groups[path]]].extend(rows)
    pilot = select_pilot(pools['pilot'])
    suites = [write_set(out, 'compli_pilot', pilot, 'LABEL_BLIND_TECHNICAL_PILOT_NO_MODEL_RESULT_SELECTION')]
    for name in ('dev', 'eval'):
        rows = sorted(pools[name], key=lambda r: digest([SEED, r['id']]))
        suites.append(write_set(out, 'compli_'+name, rows,
            'EXTERNAL_PREFIX_ADAPTATION_'+name.upper()+'_NOT_GUARDIAN_PLATFORM_ESTIMATE'))
    seen, excluded, history_evidence = historical_rows(lock)
    suites.append(write_set(out, 'regression_seen', seen, 'SEEN_REGRESSION_NOT_FRESH_HOLDOUT'))
    unique_long = {}
    for r in sorted(seen, key=lambda r: (-len(r['prompt'])-len(r['response']), r['id'])):
        unique_long.setdefault(r['conversation'], r)
    long_pilot = list(unique_long.values())[:8]
    suites.append(write_set(out, 'pilot32', pilot+long_pilot,
        'TECHNICAL_ONLY: 24 external rows + 8 longest unique historical conversations; overlaps regression intentionally'))
    # Whole-trajectory gold stays in a separate schema, never in current-turn CSV.
    policy_raw = fetch(lock['policy'], cache, download)
    policy = json.loads(policy_raw)
    assert len(policy) == 12000 and {r['output'] for r in policy} == {'violation', 'no_violation'}
    selected = sorted(range(len(policy)), key=lambda i: digest([SEED, 'policy', i]))[:300]
    aux = out/'auxiliary_policyguard'
    aux.mkdir(exist_ok=True)
    write_jsonl(aux/'trajectories.jsonl', [dict(id='policy-test:'+str(i), policy_and_trajectory=policy[i]['input']) for i in selected])
    write_jsonl(aux/'labels.jsonl', [dict(position=j, id='policy-test:'+str(i), label=policy[i]['output'],
                  scope='WHOLE_TRAJECTORY_NOT_CURRENT_TURN', original_test_position=i) for j, i in enumerate(selected)])
    auxiliary = dict(path='auxiliary_policyguard', rows=300,
        classes=dict(Counter(policy[i]['output'] for i in selected)),
        status='PREPARED_AUXILIARY_ONLY_EXCLUDED_FROM_MAIN_QUALITY_RUN',
        files={p.name: dict(bytes=p.stat().st_size, sha256=sha(p.read_bytes())) for p in sorted(aux.glob('*.jsonl'))})
    (out/'NOTICE_PolicyGuardBench.txt').write_text(
        'PolicyGuardBench test subset, Rakancorle1/PolicyGuardBench.\n'
        'Source: '+lock['policy']['repository']+'\nRevision: '+lock['policy']['revision']+'\n'
        'Dataset card declares Apache-2.0; license text accompanies this bundle.\n'
        'Input and original trajectory labels retained separately; no turn-level labels inferred.\n', encoding='utf-8')
    (out/'LICENSE_CompliBench').write_bytes(archive.read(prefix+'LICENSE'))
    (out/'CompliBench_README.md').write_bytes(archive.read(prefix+'README.md'))
    for path, doc in upstream_manifests.items():
        write_json(out/'upstream_audit'/Path(path).name, doc)
    write_json(out/'SOURCE_LOCK.json', lock)
    write_json(out/'EXCLUSIONS.json', excluded)
    write_json(out/'SPLITS.json', dict(seed=SEED, grouping='domain+intent; all workflows and all turns together; near-dialogue components merged',
        assignments=assignments, conversations=groups, near_threshold=NEAR_THRESHOLD, near_pairs=pairs,
        preparation_inspected_families=lock['preparation_inspected_families'],
        pilot_family_unused_turns=len(pools['pilot'])-len(pilot)))
    # Verify no group, conversation, or exact input crosses any main partition.
    checks = defaultdict(set)
    exact_owners = defaultdict(set)
    for name, rows in [('compli_pilot', pilot), ('compli_dev', pools['dev']), ('compli_eval', pools['eval'])]:
        for r in rows:
            checks[r['group']].add(name)
            exact_owners[digest([r['prompt'], r['response']])].add(name)
    assert all(len(v) == 1 for v in checks.values()), 'GROUP_LEAKAGE'
    assert all(len(v) == 1 for v in exact_owners.values()), 'EXACT_INPUT_LEAKAGE'
    old_hashes = {digest([r['prompt'], r['response']]) for r in seen}
    assert not old_hashes.intersection(exact_owners), 'HISTORICAL_EXACT_OVERLAP'
    result = dict(schema='guardian-eval-suite-v1', seed=SEED, suites=suites, auxiliary=auxiliary,
        source_lock_sha256=sha((SPEC/'SOURCES.lock.json').read_bytes()), historical_evidence=history_evidence,
        source_conversations=306, source_assistant_turns=sum(len(v) for v in pools.values()),
        split_counts={k: dict(rows=len(v), groups=len({r['group'] for r in v})) for k, v in pools.items()},
        checks=dict(group_overlap=0, exact_input_overlap=0, historical_exact_overlap=0,
            near_method='conversation 5-word shingles; NFKC/casefold/numbers masked; exact Jaccard >= .85',
            near_pairs=len(pairs), model_result_based_selection=False, current_response_separated=True),
        limitations=['All historical data SEEN; not an independent holdout.',
          'Compli labels are synthetic/upstream-generated; prefix and Guardian materiality differ from original full-conversation task.',
          'Insurance upstream selection_manifest prefers GPT-5-correct cases and removes model-selected cases; preserved in upstream_audit.',
          'Intent-separated within domains; shared conditional policies mean this is not domain-independent.',
          'No cross-source semantic duplicate guarantee; no near-duplicate method proves statistical independence.',
          'PolicyGuardBench labels are whole-trajectory and are excluded from current-turn quality metrics.',
          'Tau3 fresh per-turn labels require separate annotation; no paid rollouts or labels inferred from trajectory reward.',
          'Actual tokenizer caps, model quality, coverage and GPU timing not measured by preparation.'],
        inference_calls=0, label_changes=0, production_changes=False)
    write_json(out/'MANIFEST.json', result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--out', type=Path)
    mode.add_argument('--verify', type=Path)
    mode.add_argument('--pack', type=Path, help='verify and create a deterministic data-only tar.gz')
    parser.add_argument('--archive', type=Path)
    parser.add_argument('--source-cache', type=Path)
    parser.add_argument('--download', action='store_true')
    args = parser.parse_args()
    if args.verify:
        print(json.dumps(verify(args.verify), indent=2))
        return
    if args.pack:
        if args.archive is None:
            parser.error('--archive is required with --pack')
        verify(args.pack)
        args.archive.parent.mkdir(parents=True, exist_ok=True)
        with args.archive.open('xb') as stream, gzip.GzipFile(filename='', mode='wb', fileobj=stream, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode='w') as archive:
                for path in sorted(args.pack.rglob('*')):
                    if not path.is_file() or path.resolve() == args.archive.resolve():
                        continue
                    raw = path.read_bytes()
                    info = tarfile.TarInfo('guardian-judge-eval-data-v1/'+path.relative_to(args.pack).as_posix())
                    info.size = len(raw); info.mode = 0o644; info.mtime = 0
                    archive.addfile(info, io.BytesIO(raw))
        print(json.dumps(dict(archive=str(args.archive), bytes=args.archive.stat().st_size,
                              sha256=sha(args.archive.read_bytes())), indent=2))
        return
    if args.source_cache is None:
        parser.error('--source-cache is required when building')
    result = prepare(args.out, args.source_cache, args.download)
    print(json.dumps({r['path']: dict(rows=r['rows'], groups=r['groups'], classes=r['classes'])
                      for r in result['suites']}, indent=2))


def verify(root):
    csv.field_size_limit(2**31-1)
    manifest = json.loads((root/'MANIFEST.json').read_bytes())
    checked = {}
    by_partition = {}
    for suite in manifest['suites']:
        folder = root/suite['path']
        for filename, expected in suite['files'].items():
            raw = (folder/filename).read_bytes()
            assert sha(raw) == expected['sha256'] and len(raw) == expected['bytes'], (suite['path'], filename)
        with (folder/'inputs.csv').open(encoding='utf-8', newline='') as stream:
            reader = csv.DictReader(stream)
            assert reader.fieldnames == ['id', 'prompt', 'response'], 'INPUT_COLUMN_LEAKAGE'
            rows = list(reader)
        labels = [json.loads(line) for line in (folder/'labels.jsonl').read_bytes().split(b'\n') if line]
        assert len(rows) == len(labels) == suite['rows']
        for position, (r, gold) in enumerate(zip(rows, labels)):
            assert gold['position'] == position and gold['id'] == r['id'], 'POSITION_ID_MISMATCH'
            assert gold['label'] in (0, 1)
            assert gold['source_pair_sha256'] == digest([r['prompt'], r['response']]), 'SOURCE_PAIR_CHANGED'
        if suite['path'] in ('compli_pilot', 'compli_dev', 'compli_eval'):
            by_partition[suite['path']] = {g['group'] for g in labels}
        assert dict(Counter(str(g['label']) for g in labels)) == suite['classes']
        checked[suite['path']] = len(rows)
    names = sorted(by_partition)
    for i, name in enumerate(names):
        for other in names[:i]:
            assert not by_partition[name] & by_partition[other], 'FAMILY_SPLIT_LEAKAGE'
    for filename, expected in manifest['auxiliary']['files'].items():
        raw = (root/manifest['auxiliary']['path']/filename).read_bytes()
        assert sha(raw) == expected['sha256'] and len(raw) == expected['bytes']
    token_path = root/'TOKEN_PREFLIGHT.json'
    if token_path.exists():
        tokens = json.loads(token_path.read_bytes())
        for name, info in tokens['suites'].items():
            assert sha((root/name/'TOKEN_PREFLIGHT.jsonl').read_bytes()) == info['preflight_sha256']
    return dict(status='VERIFIED', suites=checked, input_columns=['id', 'prompt', 'response'],
                labels_isolated=True, disjoint_compli_family_partitions=True)


if __name__ == '__main__':
    main()
