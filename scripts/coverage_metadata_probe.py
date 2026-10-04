"""Research-only, offline probe of duplicated coverage source-record metadata.

This monkeypatch is not a production selector or a frozen experiment arm.
It removes exactly three per-record fields while retaining packet-level parent
and receipt diagnostics. No models, transport, frozen requests or gold-derived
queries are used. References enter only the scorer after selection.
"""
from argparse import ArgumentParser
from collections import defaultdict
import hashlib
import json
from pathlib import Path
from unittest.mock import patch

from experiments.retrieval_bakeoff_v1.corpus import build_corpus
from experiments.retrieval_bakeoff_v1.dataset import load_cases
from experiments.retrieval_bakeoff_v1.scoring import covered, score_reference
from guardian_truth.coverage_v2 import selector

ROOT = Path(__file__).resolve().parents[1]
FIELDS = ('parent_source_length', 'explicit_window', 'parent_coverage')
BUDGETS = (20000, 40000, 48000, 80000)


def source_bytes(packet):
    sources = packet['read_sources'] + packet['current_targets'] + packet['declarations']
    return len(json.dumps(sources, ensure_ascii=False, separators=(',', ':')).encode('utf-8'))


def invariants(corpus, packet, budget):
    corpus.assert_integrity()
    reads = packet['read_sources']
    units = selector.build_units(corpus)  # Called after the compact patch is restored.
    expected_units = {u['source_id']: u for u in units}
    all_sources = reads + packet['current_targets'] + packet['declarations']

    def original_span(s):
        native = (corpus.store.sources.get(s.get('source_id'))
                  or corpus.store.quotes.get(s.get('source_id'))
                  or corpus.graph.refs.get(s.get('source_id')))
        document, start, end = (s.get(k) for k in ('document', 'start', 'end'))
        return (native is not None and document in corpus.store.raw
                and type(start) is int and type(end) is int
                and 0 <= start < end <= len(corpus.store.raw[document])
                and all(s.get(k) == native.get(k) for k in ('document', 'start', 'end'))
                and corpus.store.raw[document][start:end] == s.get('text'))

    exact = all(original_span(s) for s in all_sources)
    # Quotes carry intervals, not actors. Bind their actor/event to the original
    # event parent as well as to the unmodified catalog-derived unit.
    metadata = True
    for s in reads:
        expected = expected_units.get(s.get('source_id'))
        parent = corpus.store.sources.get(s.get('parent_source_id'))
        metadata = metadata and (expected is not None and parent is not None
            and all(s.get(k) == v for k, v in expected.items() if k not in FIELDS)
            and s['document'] == parent['document']
            and parent['start'] <= s['start'] < s['end'] <= parent['end']
            and all(s.get(k) == parent.get(k) for k in ('role', 'kind', 'tool', 'event'))
            and s['category'] == ('POLICY' if parent['role'] == 'system' else 'HISTORY'))
    mandatory = (packet['current_targets'] == corpus.current_targets
                 and packet['declarations'] == corpus.declarations)
    read_ids = [s['source_id'] for s in reads]
    identity = (metadata and mandatory and len(set(read_ids)) == len(read_ids)
                and packet['selected_ids'] == read_ids)
    charged = len(json.dumps(packet['current_targets'] + packet['declarations'],
        ensure_ascii=False, separators=(',', ':')).encode('utf-8')) + sum(
        len(json.dumps(s, ensure_ascii=False, separators=(',', ':')).encode('utf-8')) + 1
        for s in reads)
    cost_ok = (packet['cost']['source_utf8_bound'] == charged
               and charged >= source_bytes(packet)
               and packet['cost']['budget'] == budget
               and packet['cost']['reads'] == len(reads))
    if packet['failure'] == 'MANDATORY_SOURCES_EXCEED_BUDGET':
        budget_ok = not reads and source_bytes(packet) > budget
    else:
        budget_ok = source_bytes(packet) <= budget
    parent_ids = {s['parent_source_id'] for s in reads}
    qualified = {s['parent_source_id'] for s in reads
                 if s['parent_source_id'] in corpus.pairs
                 and corpus.store.sources[s['parent_source_id']]['kind'] == 'result'}
    atomic = all(covered(corpus.store.sources[parent], reads)
                 and covered(corpus.store.sources[corpus.pairs[parent]], reads)
                 for parent in qualified)
    latest_users = [s for s in corpus.store.sources.values()
                    if s['document'] == 'prompt' and s['role'] == 'user' and s['kind'] == 'text']
    latest = max(latest_users, key=lambda s: s['event']) if latest_users else None
    anchor = latest is None or covered(latest, reads) or packet['failure'] in (
        'LATEST_USER_BUDGET_SKIPPED', 'MANDATORY_SOURCES_EXCEED_BUDGET')
    by_parent = defaultdict(list)
    for unit in units:
        by_parent[unit['parent_source_id']].append(unit)
    parents = packet['parent_coverage']
    receipts = packet['receipt_dependencies']
    diagnostics = (len(parents) == len(by_parent)
        and {p['parent_source_id'] for p in parents} == set(by_parent)
        and len(receipts) == len(corpus.receipt_diagnostics)
        and {r['result_source_id'] for r in receipts}
            == {r['result_source_id'] for r in corpus.receipt_diagnostics}
        and all(r['status'] != 'PARTIAL_RECEIPT' for r in receipts))
    # Verify each parent status from interval coverage of the original event,
    # independently of selector unit counts and the removed metadata fields.
    truthful = True
    for p in parents:
        parent = p['parent_source_id']
        group = by_parent.get(parent, [])
        status = ('COMPLETE_PARENT' if parent in corpus.store.sources and covered(
                      corpus.store.sources[parent], reads)
                  else 'PARTIAL_PARENT' if parent in parent_ids else 'NOT_READ')
        truthful = truthful and (bool(group) and p['status'] == status
            and p['category'] == group[0]['category']
            and p['read_spans'] == [[u['start'], u['end']] for u in group if u['source_id'] in read_ids]
            and p['omitted_ids'] == [u['source_id'] for u in group if u['source_id'] not in read_ids])
    receipt_truthful = True
    for r, native in zip(receipts, corpus.receipt_diagnostics):
        result_id = native['result_source_id']
        call = corpus.pairs.get(result_id)
        read = result_id in parent_ids
        complete = bool(call) and read and covered(corpus.store.sources[result_id], reads) and covered(
            corpus.store.sources[call], reads)
        status = ('QUALIFIED_COMPLETE' if complete else 'UNQUALIFIED_RESULT' if read and not call
                  else 'PARTIAL_RECEIPT' if read else 'NOT_READ')
        required = by_parent.get(result_id, []) + (by_parent.get(call, []) if call else [])
        receipt_truthful = receipt_truthful and (r['result_source_id'] == result_id
            and r['call_source_id'] == call and r['qualified'] == bool(call)
            and r['status'] == status and r['reason'] == native['reason']
            and r['omitted_ids'] == [u['source_id'] for u in required if u['source_id'] not in read_ids])
    result = dict(exact_serialized_budget=budget_ok, charged_bound_matches_records=cost_ok,
                  original_spans=exact, source_parent_actor_identity=identity,
                  qualified_dependencies_atomic=atomic, latest_user_text_whole_or_failure=anchor,
                  packet_diagnostics_retained=diagnostics, parent_diagnostics_truthful=truthful,
                  receipt_diagnostics_truthful=receipt_truthful)
    if not all(result.values()):
        raise AssertionError(result)
    return result


def run(out):
    cases = load_cases()
    references = json.loads((ROOT / 'experiments/retrieval_bakeoff_v1/fixtures/references.json').read_text(encoding='utf-8'))
    original = selector.build_units

    def compact_units(*args, **kwargs):
        units = original(*args, **kwargs)
        return [{k: v for k, v in unit.items() if k not in FIELDS} for unit in units]

    result_rows = []
    for case in cases:
        corpus = build_corpus(case)
        for budget in BUDGETS:
            for variant in ('corrected_verbose', 'research_compact_metadata'):
                if variant == 'corrected_verbose':
                    packet = selector.select_evidence(corpus, budget)
                else:
                    with patch.object(selector, 'build_units', compact_units):
                        packet = selector.select_evidence(corpus, budget)
                checks = invariants(corpus, packet, budget)
                if variant == 'research_compact_metadata':
                    assert all(not set(FIELDS).intersection(s) for s in packet['read_sources'])
                result_rows.append(dict(id=case['id'], split=case['split'], budget=budget, variant=variant,
                    score=score_reference(references[case['id']], packet), failure=packet['failure'],
                    exact_source_bytes=source_bytes(packet), charged_source_bound=packet['cost']['source_utf8_bound'],
                    selected_ids=packet['selected_ids'], policy_whole=packet['policy_whole'],
                    invariants=checks, parent_coverage=packet['parent_coverage'],
                    receipt_dependencies=packet['receipt_dependencies']))
    assert selector.build_units is original
    grouped = defaultdict(list)
    for row in result_rows:
        grouped[row['variant'], row['budget']].append(row)
    summary = []
    for (variant, budget), group in grouped.items():
        summary.append(dict(variant=variant, budget=budget, n=len(group),
            complete=sum(r['score']['complete_evidence_set_success'] and not r['failure'] for r in group),
            policy_found=sum(r['score']['categories']['policy']['found'] for r in group),
            policy_required=sum(r['score']['categories']['policy']['required'] for r in group),
            history_found=sum(r['score']['categories']['history']['found'] for r in group),
            history_required=sum(r['score']['categories']['history']['required'] for r in group),
            failures=sum(bool(r['failure']) for r in group), all_invariants_passed=all(
                all(r['invariants'].values()) for r in group)))
    artifact = dict(status='RESEARCH_ONLY_OFFLINE_MONKEYPATCH_NOT_FROZEN_MODEL_ARM', inference_http=0,
        removed_source_record_fields=list(FIELDS), preserved_packet_diagnostics=['parent_coverage', 'receipt_dependencies'],
        selector_sha256=hashlib.sha256(Path(selector.__file__).read_bytes().replace(b'\r\n', b'\n')).hexdigest(),
        interpretation='Known 15-reference diagnostic, no held-out generalization, no LLM replay, no semantic proof.',
        summary=summary, rows=result_rows)
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(summary, indent=2))
    print('RESEARCH_ONLY; inference_http=0; monkeypatch restored')
    return artifact


if __name__ == '__main__':
    parser = ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=ROOT / 'outputs/retrieval_corrections_v2/metadata_probe_verified.json')
    run(parser.parse_args().out)
