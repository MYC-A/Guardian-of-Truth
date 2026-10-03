"""Offline-compiled, signed policy-table bundle (Phase 2).

Policy tables are assembled ahead of time (CI) from *stored* proposer replies:
no LLM is ever called at runtime. The bundle is a single canonical JSON
document with a manifest of per-table SHA-256 digests and a bundle signature:

* ``HMAC-SHA256`` when ``GUARDIAN_BUNDLE_KEY`` is set (CI secret), or
* ``SHA256`` content digest (integrity only) when no key is configured.

``load_bundle`` re-verifies the signature, every table digest and the
3-proposer agreement of every table (``verify_table``). Any mismatch raises
``BundleError``; the runtime then falls back to schema/provenance invariants
and reports ``POLICY_TABLE_REJECTED``/``NO_POLICY_TABLE`` instead of trusting
a tampered table.
"""
import hashlib
import hmac
import json
import os
from pathlib import Path

from .compile import assemble, verify_table

SCHEMA = 'guardian-policy-bundle/1'
KEY_ENV = 'GUARDIAN_BUNDLE_KEY'


class BundleError(ValueError):
    pass


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()


def _sha(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def _signature(body, key):
    if key:
        return {'algorithm': 'HMAC-SHA256', 'value': hmac.new(key.encode(), canonical(body), hashlib.sha256).hexdigest()}
    return {'algorithm': 'SHA256', 'value': _sha(body)}


def build_bundle(tables, *, coverage=None, key=None):
    """``tables``: iterable of assembled V11 tables. ``coverage``: per-policy
    report for policies that could not be compiled (kept, never hidden)."""
    tables = sorted(tables, key=lambda t: t['policy']['policy_sha256'])
    for t in tables: verify_table(t)
    by_policy = {t['policy']['policy_sha256']: t for t in tables}
    if len(by_policy) != len(tables): raise BundleError('duplicate_policy_table')
    body = {'schema_version': SCHEMA, 'tables': by_policy,
            'manifest': {h: {'sha256': _sha(t), 'atoms': len(t['atoms']),
                             'decisive': sum(a['status'] == 'DECISIVE' for a in t['atoms'])} for h, t in by_policy.items()},
            'coverage': coverage or {}}
    return {**body, 'signature': _signature(body, key if key is not None else os.environ.get(KEY_ENV))}


def verify_bundle(bundle, *, key=None, require_hmac=False):
    if not isinstance(bundle, dict) or bundle.get('schema_version') != SCHEMA: raise BundleError('bundle_schema')
    body = {k: v for k, v in bundle.items() if k != 'signature'}
    key = key if key is not None else os.environ.get(KEY_ENV)
    sig = bundle.get('signature') or {}
    if sig.get('algorithm') == 'HMAC-SHA256':
        if not key: raise BundleError('bundle_key_required')
    elif require_hmac or sig.get('algorithm') != 'SHA256': raise BundleError('bundle_signature_algorithm')
    expected = _signature(body, key if sig.get('algorithm') == 'HMAC-SHA256' else None)
    if not hmac.compare_digest(expected['value'], str(sig.get('value', ''))): raise BundleError('bundle_signature_mismatch')
    for h, table in bundle['tables'].items():
        if table['policy']['policy_sha256'] != h: raise BundleError('table_policy_key_mismatch')
        if bundle['manifest'].get(h, {}).get('sha256') != _sha(table): raise BundleError('table_digest_mismatch')
        try: verify_table(table)
        except ValueError as exc: raise BundleError(f'table_agreement:{exc}') from exc
    return bundle


def load_bundle(path, **kw):
    with Path(path).open(encoding='utf-8') as stream: return verify_bundle(json.load(stream), **kw)


def write_bundle(bundle, path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(bundle, ensure_ascii=False, sort_keys=True, indent=1) + '\n', encoding='utf-8')


def table_for(bundle, policy_sha256):
    return None if bundle is None else bundle['tables'].get(policy_sha256)


def compile_from_replies(policies, replies, *, family_fallback=False):
    """Deterministically assemble tables from stored replies (no network).

    ``policies``: {policy_sha256: policy dict}. ``replies``: records with
    ``policy, trigger, proposer, family, response``. A policy is compiled only
    when exactly three distinct proposers answered; otherwise it is reported
    in coverage with the reason, never padded with fabricated proposals."""
    grouped = {}
    for r in replies: grouped.setdefault(r['policy'], []).append(r)
    tables, coverage = [], {}
    for h in sorted(set(policies) | set(grouped)):
        rows = grouped.get(h, [])
        proposers = sorted({r['proposer'] for r in rows})
        if h not in policies:
            coverage[h] = {'compiled': False, 'reason': 'policy_text_missing', 'proposers': proposers}; continue
        if len(proposers) != 3:
            coverage[h] = {'compiled': False, 'reason': f'needs_3_proposers_have_{len(proposers)}', 'proposers': proposers}
            continue
        proposals = [{'proposer': r['proposer'], 'family': r['family'], 'trigger': r['trigger'], 'response': r['response']}
                     for r in sorted(rows, key=lambda r: (r['proposer'], json.dumps(r['trigger'], sort_keys=True)))]
        table = assemble(policies[h], proposals, family_fallback=family_fallback)
        tables.append(table)
        coverage[h] = {'compiled': True, 'atoms': len(table['atoms']), 'proposers': proposers}
    return tables, coverage
