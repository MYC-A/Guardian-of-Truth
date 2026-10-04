"""Packet families built only from U2 units and the original row.

* complementary: next U2 packet with the first packet's units excluded (shared anchors kept)
* specialized:   policy-heavy NORM packet / history-heavy EVIDENCE packet
* gap_packet:    complementary packet whose query is extended with gap text
* oracle_packet: DIAGNOSTIC ONLY - built from gold reference spans
* unify:         re-identify records of several packets with one row-global SourceStore
"""
import hashlib
from dataclasses import replace

from guardian_truth.evidence_packer import PackerConfig, pack
from guardian_truth.evidence_packer.packer import _native_ref, build_units, merge_records, reference_store, resolve
from guardian_truth.source_search.store import SourceStore

NORM_CFG = dict(policy_max_share=0.95, provenance_share=0.05, segment_share=0.15, user_share=0.1,
                anchors=('last_user', 'last_assistant', 'policy_root', 'current_segment'))
EVIDENCE_CFG = dict(policy_max_share=0.12, whole_policy_if_fits=False, provenance_share=0.45, segment_share=0.5,
                    user_share=0.4)


def complementary(row, first, budget=20000, extra_queries=(), base=None, *, shared_normative=False):
    """Second packet: U2 ranking with every unit of `first` excluded as primary unit.
    Call/result partners and shared anchors may repeat (controlled overlap).
    Independent reviewers can retain normative context: policy units are then
    eligible for the ordinary U2 policy allocation, within the same budget.
    This does not select policy from another review's interpretation or gold."""
    excluded = set(first['selected_units'])
    if shared_normative:
        units, _, _, _ = build_units(row, base or PackerConfig())
        excluded -= {u['uid'] for u in units if u['category'] == 'POLICY'}
    cfg = replace(base or PackerConfig(), budget_bytes=budget, extra_queries=tuple(extra_queries),
                  exclude_uids=frozenset(excluded))
    packet = pack(row, cfg)
    packet['shared_normative'] = shared_normative
    return packet


def gap_packet(row, read_units, queries, budget=20000):
    """Gap-directed packet: same U2 machinery, query extended with gap text, already-read units excluded."""
    cfg = PackerConfig(budget_bytes=budget, extra_queries=tuple(q for q in queries if q),
                       exclude_uids=frozenset(read_units))
    return pack(row, cfg)


def specialized(row, role, budget=20000):
    return pack(row, PackerConfig(budget_bytes=budget, **(NORM_CFG if role == 'NORM' else EVIDENCE_CFG)))


def oracle_packet(row, reference, base_budget=None):
    """DIAGNOSTIC ORACLE: targets/declarations from U2 plus exactly the gold-referenced spans,
    expressed as whole U2 units overlapping them (so IDs stay native)."""
    p = pack(row, PackerConfig(budget_bytes=base_budget or 10 ** 9))
    units, _, _, _ = build_units(row, PackerConfig())
    spans = [(s['document'], s['start'], s['end']) for s in reference['required_normative_sources'] + reference['required_history_sources']]
    keep = [u['uid'] for u in units if u['category'] in ('POLICY', 'HISTORY')
            and any(d == u['document'] and a < u['end'] and u['start'] < b for d, a, b in spans)]
    # always keep the last user turn (same required anchor as every arm)
    last_user = p['anchors'].get('last_user', {}).get('units', [])
    p['selected_units'] = sorted(set(keep) | set(last_user), key=lambda u: [x['uid'] for x in units].index(u))
    chosen = [next(x for x in units if x['uid'] == u) for u in p['selected_units']]
    p['read_sources'] = merge_records(reference_store(row, chosen, []), chosen)
    p['mode'] = 'ORACLE_EVIDENCE'
    p['uncovered'] = [dict(category='ORACLE', reason='GOLD_REFERENCE_SPANS_ONLY')]
    return p


def _store(row, spans):
    store = SourceStore({'prompt': row['prompt'], 'response': row['response']})
    native = {(v['document'], v['start'], v['end']) for v in store.sources.values() if v['kind'] != 'raw'}
    for span in sorted(set(spans) - native):
        store.quote_id(*span)
    return store


def _records(p):
    return p['read_sources'] + p['current_targets'] + p['declarations']


def unify(row, packets):
    """One SourceStore for the row: quote IDs registered over the union of all spans in sorted order,
    so the same span has the same ID in every packet and different spans never share an ID."""
    spans = {(r['document'], r['start'], r['end']) for p in packets for r in _records(p)}
    store = _store(row, spans)
    out = []
    for p in packets:
        q = dict(p)
        for key in ('read_sources', 'current_targets', 'declarations'):
            q[key] = []
            for r in p[key]:
                r = dict(r)
                r['source_id'], r['parent_source_id'] = _native_ref(store, r)
                q[key].append(r)
        out.append(q)
    return out, store


def resolve_global(packets, row):
    spans = {(r['document'], r['start'], r['end']) for p in packets for r in _records(p)}
    store = _store(row, spans)
    for p in packets:
        # Quote indices differ between a union registry and a packet-local one.
        # Re-id a copy for the structural resolver; keep every metadata field
        # unchanged so tampering with categories, parents, tools, hashes or
        # actors still fails. Then verify the original union IDs separately.
        local = _store(row, {(r['document'], r['start'], r['end']) for r in _records(p)})
        canonical = dict(p)
        for key in ('read_sources', 'current_targets', 'declarations'):
            canonical[key] = [dict(r, source_id=_native_ref(local, r)[0]) for r in p[key]]
        resolve(canonical, row)
        for r in _records(p):
            if store.raw[r['document']][r['start']:r['end']] != r['text']:
                raise ValueError('SOURCE_SPAN_CHANGED')
            sid, parent = _native_ref(store, r)
            if sid != r['source_id']:
                raise ValueError('SOURCE_ID_NOT_GLOBAL')
            if parent != r.get('parent_source_id'):
                raise ValueError('SOURCE_PARENT_NOT_GLOBAL')
    return True


def union_view(packets):
    """Union of read sources by span (for coverage scoring only)."""
    seen, rs = set(), []
    for p in packets:
        for r in p['read_sources']:
            k = (r['document'], r['start'], r['end'])
            if k not in seen:
                seen.add(k); rs.append(r)
    return dict(read_sources=rs, current_targets=packets[0]['current_targets'], declarations=packets[0]['declarations'])


def _bytes(units_by, uids):
    return sum(units_by[u]['end'] - units_by[u]['start'] for u in uids)


def overlap_stats(row, packets):
    units, _, _, _ = build_units(row, PackerConfig())
    by = {u['uid']: u for u in units}
    sets = [set(p['selected_units']) for p in packets]
    union = set().union(*sets)
    out = dict(units=[len(s) for s in sets], union_units=len(union),
               new_units_per_packet=[len(s - set().union(*sets[:i])) for i, s in enumerate(sets)],
               repeated_units=sum(len(s) for s in sets) - len(union),
               new_source_chars_per_packet=[_bytes(by, s - set().union(*sets[:i])) for i, s in enumerate(sets)])
    return out


def reference_spans_covered(reference, view):
    """Full reference-span coverage by the union of reads (corrected eval only).

    Partial overlap remains a separate diagnostic and never sets complete.
    Adjacent original excerpts can jointly cover one required reference span.
    """
    rs = view['read_sources'] + view['current_targets'] + view['declarations']
    def overlaps(s):
        return any(r['document'] == s['document'] and r['start'] < s['end'] and s['start'] < r['end'] for r in rs)
    def hit(s):
        cursor = s['start']
        if cursor >= s['end']:
            return False
        for r in sorted((r for r in rs if r['document'] == s['document']
                         and r['start'] < s['end'] and s['start'] < r['end']), key=lambda r: r['start']):
            if r['start'] > cursor:
                return False
            cursor = max(cursor, r['end'])
            if cursor >= s['end']:
                return True
        return False
    nor = [hit(s) for s in reference['required_normative_sources']]
    his = [hit(s) for s in reference['required_history_sources']]
    return dict(norm_found=sum(nor), norm_required=len(nor), hist_found=sum(his), hist_required=len(his),
                complete=all(nor) and all(his), coverage_contract='FULL_REFERENCE_SPAN_UNION_V2',
                norm_overlap_found=sum(overlaps(s) for s in reference['required_normative_sources']),
                hist_overlap_found=sum(overlaps(s) for s in reference['required_history_sources']))


def sha(obj):
    import json
    return hashlib.sha256(json.dumps(obj, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
