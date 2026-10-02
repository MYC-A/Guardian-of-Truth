"""Offline replay of the saved V2 proposals (assignment 7.A, cheap tails).

Every LLM stage call is served from the archived paid cache (all modular
namespaces plus the original ta_llm cache) instead of the network: a replay
must not create new API attempts. A cache miss means the original live call
FAILED (failed answers are never cached), so the miss is served as a
deterministic failure-shaped answer reproducing the journaled None outcome;
the strict field-by-field comparison with the saved pilot_v2 journal remains
the correctness gate — a miss that mattered shows up as a MISMATCH.

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
    not part of the key, exactly as in the live client. A miss corresponds to
    a call whose original live attempt failed (llm.chat never caches failed
    answers), so it is served as the same failure shape the original pipeline
    saw: content=None -> parsed=None -> journaled stage raw None.
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
    return {'content': None, 'usage': {}, 'cached': False, 'model': model,
            'elapsed': 0.0, 'transport_attempts': 0,
            'error_type': 'ReplayArchiveMiss',
            'error': 'archived answer absent: the original live call failed'}


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
        except Exception as exc:
            failures.append({'id': row['id'], 'error': str(exc)})
            cases.append(case)
            continue
        replayed, original = _normalize(result), _normalize(saved[row['id']]['result'])
        proposal_fields = ('step1', 'step3', 'step4', 'contract_proposals')
        proposals_ok = all(sha(replayed.get(f)) == sha(original.get(f)) for f in proposal_fields)
        native_diffs = [f for f in ('step2', 'native_fact_count', 'source_pairing_issues')
                        if sha(replayed.get(f)) != sha(original.get(f))]
        case.update(proposals_replayed=proposals_ok,
                    proposals_fields=list(proposal_fields),
                    native_layer_evolution={
                        'native_fact_count_saved': saved[row['id']]['result'].get('native_fact_count'),
                        'native_fact_count_replayed': result['native_fact_count'],
                        'pairing_field_in_saved_journal': 'source_pairing_issues' in saved[row['id']]['result'],
                        'differing_native_fields': native_diffs,
                        'note': 'native Steps 2-4 recomputed with the current binding/trust/pairing layer; '
                                'the saved journal predates those code fixes (pairing fix, typed bindings)'})
        cases.append(case)
    report = {'scope': 'Offline replay of saved V2 proposals: archived LLM answers re-served by exact cache key, proposals verified bit-identical, native Steps 2-4 recomputed with current code; differences vs the saved journal are native-layer code evolution, not replay errors.',
              'kind': 'v2-replay', 'ids': V2_IDS, 'git_head': revision,
              'archive_roots': [str(p) for p in ARCHIVE_ROOTS],
              'cache_answers_served': STATS['served'],
              'cache_misses_reproducing_journaled_failures': len(STATS['misses']),
              'miss_semantics': 'a miss reproduces the original live-call failure (failed answers are never cached); the journaled None outcome is what the saved pipeline recorded',
              'new_api_attempts': 0, 'budget_phase_charged': None,
              'proposals_replayed_cases': sum(1 for c in cases if c.get('proposals_replayed')),
              'per_case': cases, 'failures': failures,
              'limits': ['Replay verifies deterministic reproduction of the archived proposals, not new model quality.',
                         'A cache namespace change does not invalidate this replay: keys are content-based and every namespace is searched.',
                         'Failed original calls cannot be re-measured here; only their journaled None outcome is reproduced.',
                         'Native Steps 2-4 in the saved journal predate the pairing/typed-binding fixes; the replay does not overwrite pilot_v2 history.']}
    write(folder / 'replay.json', report)
    state = 'SUCCEEDED' if not failures and all(c.get('proposals_replayed') for c in cases) else 'MISMATCH'
    write(folder / 'status.json', {'state': state, 'proposals_replayed': report['proposals_replayed_cases'],
                                   'n': len(V2_IDS), 'served': STATS['served'],
                                   'journaled_failures_reproduced': len(STATS['misses']),
                                   'elapsed_seconds': time.monotonic() - began})
    print(json.dumps({'state': state, 'proposals_replayed': report['proposals_replayed_cases'],
                      'n': len(V2_IDS), 'served': STATS['served'],
                      'journaled_failures_reproduced': len(STATS['misses']),
                      'failures': failures}))

if __name__ == '__main__':
    run()
