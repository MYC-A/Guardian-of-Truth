"""Offline replay of the saved V2 proposals (assignment 7.A, cheap tails).

Every LLM stage call is served from the archived paid cache (all modular
namespaces plus the original ta_llm cache) instead of the network: a replay
must not create new API attempts, and a missing archive entry is a loud
failure — never a silent live call. Native Steps 2-4 then recompute on the
same frozen inputs and are compared field-by-field with the saved
pilot_v2 journal.

No budget install: the replay path never touches transport, so there are no
reservations to account; the receipt records new_api_attempts=0 explicitly.
"""
import json
import subprocess
import sys
import time
import types
from pathlib import Path

from modular_common import HERE, ROOT, RESULTS, load_input, sha, source_sha, write

import llm

V2_IDS = ['dev_nested_gate::00', 'dev_negative_scope::00',
          'dev_refusal_inventory::00', 'dev_refusal_inventory::01']
ORIGINAL_CACHE = Path(llm.CACHE_DIR)


def _archive_roots():
    """Every paid-answer archive the replay may serve from: the original
    ta_llm cache plus all modular cache namespaces (content-keyed, so any
    namespace may hold the answer regardless of the git revision that paid
    for it)."""
    roots = [ORIGINAL_CACHE]
    cache_dir = RESULTS / 'cache'
    if cache_dir.exists():
        roots += sorted(p for p in cache_dir.iterdir() if p.is_dir())
    return roots


ARCHIVE_ROOTS = _archive_roots()

STATS = {'served': 0, 'misses': []}


def _replay_chat(model, messages, **kwargs):
    """Serve one archived answer by exact cache key; never touch transport.

    Reproduces llm.chat's cache-key construction verbatim (max_tokens,
    temperature, json_mode, optional seed/top_p); caller and retry flags are
    not part of the key, exactly as in the live client.
    """
    kw = {"max_tokens": kwargs.get("max_tokens", 4000),
          "temperature": kwargs.get("temperature", 0.0),
          "json_mode": kwargs.get("json_mode", True)}
    if kwargs.get("seed") is not None:
        kw["seed"] = kwargs["seed"]
    if kwargs.get("top_p") is not None:
        kw["top_p"] = kwargs["top_p"]
    key = llm._cache_key(model, messages, **kw)
    for root in ARCHIVE_ROOTS:
        path = root / key[:2] / (key + '.json')
        if path.exists():
            payload = json.loads(path.read_text(encoding='utf-8'))
            STATS['served'] += 1
            return dict(payload, cached=True)
    STATS['misses'].append(key)
    raise RuntimeError('replay_archive_miss:' + key[:16])


def _stub_llm():
    return types.SimpleNamespace(chat=_replay_chat, extract_json=llm.extract_json,
                                 MODEL_REGISTRY=llm.MODEL_REGISTRY,
                                 DEFAULT_MISTRAL_MODEL=llm.DEFAULT_MISTRAL_MODEL)


def _normalize(result):
    """Strip live-call metadata (cached/elapsed/transport_attempts) from the
    embedded raw answers; keep content and the deterministic parsed value."""
    out = json.loads(json.dumps(result, ensure_ascii=False))
    for step in ('step1', 'step3', 'step4'):
        raw = out.get(step, {}).get('raw')
        if isinstance(raw, dict):
            out[step]['raw'] = {k: raw.get(k) for k in ('content', 'parsed') if k in raw}
    return out


def run():
    folder = RESULTS / 'v2_replay'
    folder.mkdir(parents=True, exist_ok=True)
    revision = subprocess.check_output(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], text=True).strip()
    saved = {r['id']: r for r in map(json.loads, (RESULTS / 'pilot_v2/predictions.jsonl').read_text(encoding='utf-8').splitlines())}
    from v2_pipeline import run as v2_run
    began = time.monotonic()
    cases, failures = [], []
    for row in load_input(ids=V2_IDS):
        if row['id'] not in saved:
            raise ValueError('replay_target_missing_from_journal:' + row['id'])
        case = {'id': row['id'], 'source_sha256': source_sha(row)}
        try:
            result = v2_run(_stub_llm(), llm.DEFAULT_MISTRAL_MODEL, row)
        except RuntimeError as exc:
            failures.append({'id': row['id'], 'error': str(exc)})
            cases.append(case)
            continue
        replayed, original = _normalize(result), _normalize(saved[row['id']]['result'])
        differing = [field for field in
                     ('module', 'step1', 'step2', 'step3', 'step4', 'native_fact_count',
                      'contract_proposals', 'source_pairing_issues', 'trust', 'promotion')
                     if sha(replayed.get(field)) != sha(original.get(field))]
        case.update(identical=not differing, differing_fields=differing,
                    native_fact_count=result['native_fact_count'])
        cases.append(case)
    report = {'scope': 'Offline replay of saved V2 proposals: archived LLM answers re-served by exact cache key, native Steps 2-4 recomputed and compared to the frozen pilot_v2 journal.',
              'kind': 'v2-replay', 'ids': V2_IDS, 'git_head': revision,
              'archive_roots': [str(p) for p in ARCHIVE_ROOTS],
              'cache_answers_served': STATS['served'], 'archive_misses': len(STATS['misses']),
              'new_api_attempts': 0, 'budget_phase_charged': None,
              'identical_cases': sum(1 for c in cases if c.get('identical')),
              'per_case': cases, 'failures': failures,
              'limits': ['Replay verifies deterministic reproduction from archived answers, not new model quality.',
                         'A cache namespace change does not invalidate this replay: keys are content-based and every namespace is searched.']}
    write(folder / 'replay.json', report)
    state = 'SUCCEEDED' if not failures and all(c.get('identical') for c in cases) else 'MISMATCH'
    write(folder / 'status.json', {'state': state, 'identical': report['identical_cases'],
                                   'n': len(V2_IDS), 'served': STATS['served'],
                                   'misses': len(STATS['misses']), 'elapsed_seconds': time.monotonic() - began})
    print(json.dumps({'state': state, 'identical': report['identical_cases'], 'n': len(V2_IDS),
                      'served': STATS['served'], 'misses': len(STATS['misses']),
                      'failures': failures}))


if __name__ == '__main__':
    run()
