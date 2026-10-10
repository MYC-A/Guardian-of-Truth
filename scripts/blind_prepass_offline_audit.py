"""Measure frozen blind2 payloads; never generate shortened model predictions."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import socket
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT)]


def compact(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def strings(value):
    if isinstance(value, str):
        return len(value.encode('utf-8'))
    if isinstance(value, list):
        return sum(map(strings, value))
    if isinstance(value, dict):
        return sum(strings(v) for v in value.values())
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--input', type=Path, required=True)
    ap.add_argument('--calls', type=Path, required=True)
    ap.add_argument('--traces', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--candidate-accounting', action='store_true',
                    help='Measure new wires only; saved replies are NOT new-profile predictions')
    a = ap.parse_args()
    if a.output.exists():
        raise ValueError('OUTPUT_EXISTS')
    def deny(*args, **kwargs):
        raise RuntimeError('NETWORK_FORBIDDEN')
    socket.create_connection = socket.socket.connect = socket.socket.connect_ex = deny
    from guardian_truth.integrated.transport import sha, wire_body
    from guardian_truth.submission.cli import MODEL, finalize_trace, predict_one, read_rows
    from guardian_truth.submission.recovery import recover_output
    from guardian_truth.v6fix.pipeline import Layers
    from experiments.guardian_semantic.variants import CONTEXT_ADDENDUM
    if a.candidate_accounting:
        from guardian_truth.submission.blind_compact import construct_compact_request, deduplicate_request, expand_sources
    rows = read_rows(a.input)
    saved = [json.loads(s) for s in a.traces.read_text(encoding='utf-8').splitlines() if s.strip()]
    expected = {r['id']: r for r in saved}
    records_list = json.loads(a.calls.read_text(encoding='utf-8'))
    records = {r['key']: r for r in records_list}
    if len(records) != len(records_list) or len(expected) != len(saved) or set(expected) != {r['id'] for r in rows}:
        raise ValueError('DUPLICATE_OR_MISSING_IDS_KEYS')
    class Client:
        model = MODEL
        def __init__(self):
            self.requests = []
            self.missing = []
        def call(self, request, attempt=0, tag=''):
            key = sha(dict(model=MODEL, request=request, attempt=attempt))
            self.requests.append((tag, copy.deepcopy(request)))
            if key not in records:
                self.missing.append(tag)
                raise ValueError('EXACT_REQUEST_NOT_FOUND')
            r = records[key]
            if r['request_sha256'] != sha(request) or r['tag'] != tag or r['attempt'] != attempt or r['model'] != MODEL:
                raise ValueError('REQUEST_METADATA_MISMATCH')
            return copy.deepcopy(r)
    client = Client()
    layers = Layers(client, MODEL, budget=20000, attempts=(0, 1), frules_max_tokens=700, tolerate_component_errors=True)
    fields = ('requirements', 'entities', 'computed_values', 'expected_actions', 'uncertainties')
    total = dict(raw_utf8_bytes=0, minified_utf8_bytes=0, string_bytes={f: 0 for f in fields},
                 quote_string_bytes=0, requirement_string_bytes=0, why_string_bytes=0,
                 pre_completion_tokens=0, discarded_completion_tokens=0, injected=0,
                 parsed_ok=0, mismatches=0, actual_http_calls=0)
    per_case = []
    for row in rows:
        start = len(client.requests)
        fresh = predict_one(row, client, layers)
        prior = recover_output(finalize_trace(expected[row['id']]))
        if any(fresh.get(k) != prior.get(k) for k in ('binary', 'owner', 'accusation')):
            total['mismatches'] += 1
        steps = [s for s in fresh['pre_steps'] if s['tag'] == 'pre_blind']
        if len(steps) != 1:
            raise ValueError('EXPECTED_ONE_BLIND_STEP')
        st = steps[0]
        raw = st.get('raw_content') or ''
        tokens = (st.get('usage') or {}).get('completion_tokens', 0)
        total['pre_completion_tokens'] += tokens
        total['raw_utf8_bytes'] += len(raw.encode('utf-8'))
        total['parsed_ok'] += bool(st.get('parsed_ok'))
        total['injected'] += bool(st.get('injected'))
        if not st.get('injected'):
            total['discarded_completion_tokens'] += tokens
        if st.get('parsed_ok'):
            v = json.loads(raw)
            total['minified_utf8_bytes'] += len(compact(v).encode('utf-8'))
            for f in fields:
                total['string_bytes'][f] += strings(v[f])
            for r in v['requirements']:
                for f in ('quote', 'requirement', 'why'):
                    total[f + '_string_bytes'] += strings(r[f])
        reviews = [r for t, r in client.requests[start:] if t == 'review']
        pres = [r for t, r in client.requests[start:] if t == 'pre_blind']
        if len(reviews) != 1:
            raise ValueError('EXPECTED_ONE_REVIEW_REQUEST')
        req = reviews[0]
        p = json.loads(req['messages'][1]['content'])
        b = p.get('blind_analysis_sources')
        case = dict(id=row['id'], injected=bool(st.get('injected')), pre_completion_tokens=tokens,
                    reviewer_wire_bytes=len(wire_body(req)))
        # A lower bound using all required arrays empty. Above the cap even this
        # cannot be delivered; skipping pre-generation preserves base fallback.
        base = {k: v for k, v in p.items() if k not in ('blind_analysis', 'blind_analysis_sources')}
        system = req['messages'][0]['content']
        add = CONTEXT_ADDENDUM['blind']
        if b and not system.endswith(add):
            raise ValueError('UNEXPECTED_REVIEW_ADDENDUM')
        if b:
            system = system[:-len(add)]
        pre_user = json.loads(pres[0]['messages'][1]['content'])
        lower_req = copy.deepcopy(req)
        lower_req['messages'][0]['content'] = system + add
        lower_req['messages'][1]['content'] = compact(dict(base, blind_analysis={f: [] for f in fields},
                                                        blind_analysis_sources=pre_user))
        case['minimum_injection_wire_bytes'] = len(wire_body(lower_req))
        case['necessarily_undeliverable_with_existing_sources'] = case['minimum_injection_wire_bytes'] > 60000
        if a.candidate_accounting:
            if not st.get('parsed_ok'):
                raise ValueError('CANDIDATE_ACCOUNTING_REQUIRES_VALID_OLD_PRE')
            # Same historical pre proposal, changed reviewer wire. These bytes
            # do not authorize reuse of the old reviewer reply or its metric.
            dedup_base = copy.deepcopy(req)
            dedup_base['messages'][0]['content'] = system + add
            dedup_base['messages'][1]['content'] = compact(base)
            dq, dr = deduplicate_request(dedup_base, pre_user, json.loads(raw))
            dview = json.loads(dq['messages'][1]['content'])['blind_analysis_sources']
            if expand_sources(base, dview) != pre_user:
                raise ValueError('SOURCE_ROUNDTRIP_MISMATCH')
            cq, units = construct_compact_request(pre_user, MODEL)
            compact_base = copy.deepcopy(req)
            compact_base['messages'][0]['content'] = system
            compact_base['messages'][1]['content'] = compact(base)
            minimum, _ = deduplicate_request(compact_base, pre_user, {f: [] for f in fields}, units)
            case['candidate_accounting'] = dict(
                scope='new wire size only; no new prediction',
                legacy_pre_wire_bytes=len(wire_body(pres[0])),
                dedup_reviewer_wire_bytes=len(wire_body(dq)), dedup_alias_count=dr['alias_count'],
                dedup_saved_proposal_fits_byte_cap=len(wire_body(dq)) <= 60000,
                dedup_request_sha256=sha(dq), compact_pre_wire_bytes=len(wire_body(cq)),
                compact_pre_fits_byte_cap=len(wire_body(cq)) <= 60000, compact_pre_sha256=sha(cq),
                compact_minimum_reviewer_wire_bytes=len(wire_body(minimum)),
                compact_minimum_fits_byte_cap=len(wire_body(minimum)) <= 60000,
                compact_unit_count=len(units), full_source_roundtrip=True)
        if b:
            # Exact text equality measures duplication only; it is not a semantic/source certificate.
            base_texts = {s['text'] for k in ('normative_sources', 'declarations', 'history') for s in p.get(k, [])}
            sources = [s for k in ('normative_sources', 'declarations', 'history') for s in b.get(k, [])]
            case.update(blind_source_count=len(sources),
                        exact_duplicate_count=sum(s['text'] in base_texts for s in sources),
                        blind_text_utf8_bytes=sum(strings(s['text']) for s in sources),
                        exact_duplicate_text_utf8_bytes=sum(strings(s['text']) for s in sources if s['text'] in base_texts))
        per_case.append(case)
    if client.missing or total['mismatches']:
        raise ValueError(f"REPLAY_FAILED: missing={client.missing}, mismatches={total['mismatches']}")
    report = dict(scope='frozen payload accounting; no new inference, tokenizer timing, or quality claim',
                  candidate_accounting=a.candidate_accounting,
                  input_sha256=hashlib.sha256(a.input.read_bytes()).hexdigest(),
                  calls_sha256=hashlib.sha256(a.calls.read_bytes()).hexdigest(),
                  traces_sha256=hashlib.sha256(a.traces.read_bytes()).hexdigest(), rows=len(rows), totals=total,
                  cases=per_case)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    with a.output.open('x', encoding='utf-8') as h:
        json.dump(report, h, ensure_ascii=False, indent=2)
    print(json.dumps(dict(rows=len(rows), totals=total), ensure_ascii=False))


if __name__ == '__main__':
    main()
