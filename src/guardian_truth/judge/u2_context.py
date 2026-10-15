"""U2 exact-source context for the single-pass judge (modes u2 and u2_dense).

Adapter between the production transcript parser (guardian_truth.transcript) and the U2 evidence packer
(guardian_truth.evidence_packer, which reads the input through guardian_truth.parsing). The packer runs
unchanged; this module decides whether its packet may stand in for the transcript and renders it.

Parser agreement. Both parsers must produce the same event sequence in the prompt and in the turn under
review: same kinds, roles and tools at the same positions, the same call arguments (decoded JSON, or the
normalised text when not JSON), the same receipt and text contents and the same explicit result status
(a tag, a [TAG] body prefix or a status attribute; OK and a status only inferred from wording count as none). Normalisation only removes the
transport indent and blank lines (each line stripped); consecutive text events of one role are joined.
Anything else is a named fallback to the legacy context (PARSER_DISAGREEMENT). Example: an unindented
assistant sentence after a JSON receipt is a text event for the production parser but part of the receipt
for the packer's parser; such a row is not packed.

Packet admission (never decided by ranking scores): a packet with a failure, without read sources, or with a
record whose text is not the prompt at its offsets is not used (PACKET_FAILURE:<reason>, PACKET_EMPTY,
SPAN_MISMATCH); any exception is PACKER_ERROR. FULL_INPUT keeps the original transcript (byte-identical
to legacy). Protected outside ranking: the turn under review (not part of the packet text; the stage shows
it whole when it fits), declarations of called tools and the whole tool catalog (a false refusal can depend
on a tool the agent did not call; this addition is outside the measured U2, --no-full-catalog removes it).
The packer itself keeps the whole policy when it fits its policy share, adds parent headings and governing
section bodies to a chosen rule, keeps call/receipt groups together and reports what it did not read.

Rendering: the original prompt restricted to the packet spans, in source order. Each quoted message keeps
its original role header; every omitted stretch with content becomes one explicit marker; whitespace-only
gaps stay verbatim; every text between two markers is one contiguous substring of the prompt. A closing
notice states that parts are omitted and that an omitted part is not evidence either way. It is placed at
the end so that rows sharing a policy keep a common prompt prefix.

u2_dense: the same packer with a multilingual sentence encoder as one more ranking signal (lexical, entity
and recency signals stay). Encoder unavailable, row embedding budget or total embedding budget exhausted,
or an encoder error: that row is packed by lexical U2, with dense_fallback naming the reason.

Budget units: budget_bytes is the packer's own unit (UTF-8 bytes of the serialised packet records, metadata
included; default 20000 as in the U2 experiments; reported as packet_json_bytes). source_bytes is the UTF-8
size of the quoted prompt text. Rendered tokens are measured by the stage. Different units, never mixed.

CLI (started by judge_stage as its own CPU process, overlapping the model start-up):
    python -m guardian_truth.judge.u2_context --input stage_input.jsonl --output packets-<run>.jsonl \\
        --run-id <run> --deadline <epoch> [--dense-encoder model/encoder]
First line {"event": "start", run_id, input_sha256}; one line per row {key, row_sha256, mode, reason, ...}
(fsync per row); last line {"event": "done"}. The stage accepts a record only for the same run, the same
input file hash and the same row hash.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import time

from guardian_truth.transcript.parser import parse_document

VERSION = 'u2-context-2'
DEFAULT_BUDGET = 20000
OMIT = '\n[... {n} characters of the transcript are not quoted here; not proof that they are irrelevant ...]\n'
NOTICE = ('\n[Evidence selection: {q} of {t} characters of the transcript are quoted above, in their original '
          'order; omitted parts are marked. An omitted part is not evidence either way.]')


def row_digest(prompt, response):
    return hashlib.sha256((str(prompt) + '\x00' + str(response)).encode('utf-8', 'surrogatepass')).hexdigest()


def _norm(text):
    return '\n'.join(line.strip() for line in str(text or '').strip().splitlines() if line.strip())


def _status(status, diagnostics):
    """Explicit result status as written (tag before the colon, [TAG] body prefix, header attribute). OK and a
    status the production parser only inferred from the body wording count as no explicit status."""
    value = str(status).strip().upper() if status else None
    if value in (None, '', 'OK') or 'ERROR_INFERRED_FROM_BODY' in (diagnostics or ()):
        return None
    return value


def _canon(kind, role, tool, body, value, valid, status=None, diagnostics=()):
    if kind == 'call':
        payload = ('json', json.dumps(value, sort_keys=True, ensure_ascii=False)) if valid else ('text', _norm(body))
        return (kind, role, tool, payload, None)
    if kind == 'result':
        return (kind, role, tool, ('text', _norm(body)), _status(status, diagnostics))
    return ('text', role, None, ('text', _norm(body)), None)


def _joined(items):
    out = []
    for item in items:
        if item[0] == 'text' and not item[3][1]:
            continue
        if out and item[0] == 'text' and out[-1][0] == 'text' and out[-1][1] == item[1]:
            out[-1] = ('text', item[1], None, ('text', out[-1][3][1] + '\n' + item[3][1]), None)
        else:
            out.append(item)
    return out


def production_events(doc):
    return _joined([_canon(e.kind, e.role, e.tool, e.body, e.value, e.is_json, e.status, e.diagnostics)
                    for e in doc.events])


def packer_events(events):
    return _joined([_canon(e.kind, e.role, e.name, e.text, e.value, e.json_valid, getattr(e, 'status', None),
                           getattr(e, 'diagnostics', ())) for e in events])


def parsers_agree(prompt_doc, response_doc, prompt_events, response_events):
    """-> (agree, detail): event-by-event agreement of the two parsers on both documents."""
    for name, doc, events in (('prompt', prompt_doc, prompt_events), ('response', response_doc, response_events)):
        ours, theirs = production_events(doc), packer_events(events)
        for k, (a, b) in enumerate(zip(ours, theirs)):
            if a != b:
                field = next(f for f, x, y in zip(('kind', 'role', 'tool', 'content', 'status'), a, b) if x != y)
                return False, '%s event %d differs in %s (%s vs %s)' % (name, k, field, a[0], b[0])
        if len(ours) != len(theirs):
            return False, '%s events: production %d, packer %d' % (name, len(ours), len(theirs))
    return True, None


def merge_spans(spans):
    merged = []
    for a, b in sorted(spans):
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return [(a, b) for a, b in merged]


def render_packet(prompt, prompt_doc, spans):
    """-> (text, merged spans): the prompt restricted to `spans`, each message's original header re-emitted
    before its first quoted span, omitted stretches with content as OMIT markers."""
    merged = merge_spans(spans)
    messages = sorted(prompt_doc.messages, key=lambda m: m.span.start)
    out, cursor, current = [], 0, None

    def gap(lo, hi):
        piece = prompt[lo:hi]
        out.append(OMIT.format(n=hi - lo) if piece.strip() else piece)

    for a, b in merged:
        owner = next((m for m in messages if m.span.start <= a < m.span.end), None)
        if owner is not None and owner is not current and owner.span.start >= cursor and a >= owner.body_start:
            gap(cursor, owner.span.start)
            out.append(prompt[owner.span.start:owner.body_start])
            gap(owner.body_start, a)
        else:
            gap(cursor, a)
        out.append(prompt[a:b])
        cursor = b
        current = owner if owner is not None else current
    gap(cursor, len(prompt))
    return ''.join(out), merged


def _utf8(prompt, spans):
    return sum(len(prompt[a:b].encode('utf-8', 'surrogatepass')) for a, b in spans)


def context_for(prompt, response, budget_bytes=DEFAULT_BUDGET, full_catalog=True, embedder=None,
                dense_fallback=None):
    """-> record {mode: u2 | full_input | legacy, reason, ranking, text (u2 only), sizes, packet summary}.
    embedder: an encoder for u2_dense or None. Never raises."""
    started = time.perf_counter()
    info = dict(version=VERSION, budget_bytes=budget_bytes)

    def result(**values):
        return dict(info, seconds=round(time.perf_counter() - started, 3), **values)
    try:
        from guardian_truth.evidence_packer.packer import PackerConfig, pack
        from guardian_truth.judge.dense_encoder import EncoderBudgetExceeded
        from guardian_truth.parsing import parse_catalog, parse_events
        prompt_doc, response_doc = parse_document(prompt, 'prompt'), parse_document(response, 'response')
        prompt_events, response_events = parse_events(prompt, 'prompt'), parse_events(response, 'response')
        agree, detail = parsers_agree(prompt_doc, response_doc, prompt_events, response_events)
        if not agree:
            return result(mode='legacy', reason='PARSER_DISAGREEMENT', detail=detail)
        row, cfg, ranking = {'prompt': prompt, 'response': response}, PackerConfig(budget_bytes=budget_bytes), 'lexical'
        packet = None
        if embedder is not None:
            try:
                packet, ranking = pack(row, cfg, embedder), 'dense'
            except EncoderBudgetExceeded:
                dense_fallback = 'EMBED_ROW_BUDGET'
            except Exception as error:  # noqa: BLE001 - the row is packed lexically instead
                dense_fallback = ('EMBED_ERROR:%s: %s' % (type(error).__name__, error))[:200]
        if packet is None:
            packet = pack(row, cfg)
        summary = dict(ranking=ranking, dense_fallback=dense_fallback, packet_mode=packet.get('mode'),
                       policy_mode=packet.get('policy_mode'), failure=packet.get('failure'),
                       packet_json_bytes=(packet.get('cost') or {}).get('source_token_upper_bound'),
                       uncovered=sorted({str(u.get('category')) for u in packet.get('uncovered', [])}),
                       partial_receipt_groups=sum(1 for g in packet.get('receipt_groups', [])
                                                  if g.get('completeness') == 'PARTIAL'))
        if packet.get('failure'):
            return result(mode='legacy', reason='PACKET_FAILURE:%s' % packet['failure'], **summary)
        if packet.get('mode') == 'FULL_INPUT':
            return result(mode='full_input', reason='FULL_INPUT_FITS', **summary)
        if not packet.get('read_sources'):
            return result(mode='legacy', reason='PACKET_EMPTY', **summary)
        records = [r for r in packet['read_sources'] + packet.get('declarations', []) if r.get('document') == 'prompt']
        if any(prompt[r['start']:r['end']] != r['text'] for r in records):
            return result(mode='legacy', reason='SPAN_MISMATCH', **summary)
        spans = [(r['start'], r['end']) for r in records]
        base_bytes = _utf8(prompt, merge_spans(spans))
        catalog = parse_catalog(prompt_events, prompt) if full_catalog else None
        if catalog is not None and catalog.source is not None:
            spans.append((catalog.source.start, catalog.source.end))
        text, merged = render_packet(prompt, prompt_doc, spans)
        quoted = sum(b - a for a, b in merged)
        text += NOTICE.format(q=quoted, t=len(prompt))
        source_bytes = _utf8(prompt, merged)
        return result(mode='u2', reason='U2_SELECTED', text=text, source_bytes=source_bytes,
                      catalog_added_bytes=source_bytes - base_bytes, quoted_spans=len(merged), quoted_chars=quoted,
                      prompt_chars=len(prompt), context_chars=len(text), **summary)
    except Exception as error:  # noqa: BLE001 - one row's packing must not cost the others
        return result(mode='legacy', reason='PACKER_ERROR', detail=('%s: %s' % (type(error).__name__, error))[:300])


def read_rows(path):
    """stage_input records, split on LF only (see judge_stage.read_jsonl)."""
    with open(path, encoding='utf-8', newline='') as stream:
        return [json.loads(line) for line in stream.read().split('\n') if line.strip()]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--input', required=True)
    ap.add_argument('--output', required=True)
    ap.add_argument('--run-id', required=True)
    ap.add_argument('--deadline', type=float, required=True, help='wall-clock epoch; no row starts after it')
    ap.add_argument('--budget-bytes', type=int, default=DEFAULT_BUDGET)
    ap.add_argument('--no-full-catalog', action='store_true')
    ap.add_argument('--dense-encoder', default=None, help='local encoder directory: mode u2_dense')
    ap.add_argument('--embed-seconds-per-row', type=float, default=2.0)
    ap.add_argument('--embed-total-seconds', type=float, default=240.0)
    a = ap.parse_args(argv)
    started = time.time()
    with open(a.input, 'rb') as stream:
        input_sha256 = hashlib.sha256(stream.read()).hexdigest()
    rows = read_rows(a.input)
    encoder, encoder_status = None, None
    with open(a.output, 'x', encoding='utf-8') as out:
        def emit(record):
            out.write(json.dumps(record, ensure_ascii=False) + '\n')
            out.flush()
            os.fsync(out.fileno())
        emit(dict(event='start', version=VERSION, run_id=a.run_id, input_sha256=input_sha256, rows=len(rows),
                  dense=bool(a.dense_encoder)))
        if a.dense_encoder:
            try:
                from guardian_truth.judge.dense_encoder import LocalEncoder
                encoder, encoder_status = LocalEncoder(a.dense_encoder), 'LOADED'
            except Exception as error:  # noqa: BLE001 - every row falls back to lexical U2, named
                encoder_status = ('ENCODER_UNAVAILABLE:%s: %s' % (type(error).__name__, error))[:300]
        dense_until = time.time() + a.embed_total_seconds
        modes, rankings = {}, {}
        for row in rows:
            prompt, response = str(row.get('prompt') or ''), str(row.get('response') or '')
            if time.time() >= a.deadline:
                record = dict(version=VERSION, mode='legacy', reason='PACKING_DEADLINE')
            else:
                embedder, fallback = None, None
                if a.dense_encoder and encoder is None:
                    fallback = 'ENCODER_UNAVAILABLE'
                elif encoder is not None and time.time() >= dense_until:
                    fallback = 'EMBED_TOTAL_BUDGET'
                elif encoder is not None:
                    encoder.deadline = min(time.time() + a.embed_seconds_per_row, dense_until, a.deadline)
                    embedder = encoder
                record = context_for(prompt, response, a.budget_bytes, not a.no_full_catalog, embedder, fallback)
            record.update(key=row.get('key'), row_sha256=row_digest(prompt, response), run_id=a.run_id)
            modes[record['mode']] = modes.get(record['mode'], 0) + 1
            if record.get('ranking'):
                rankings[record['ranking']] = rankings.get(record['ranking'], 0) + 1
            emit(record)
        emit(dict(event='done', run_id=a.run_id, rows=len(rows), modes=modes, rankings=rankings,
                  encoder=encoder_status, encoder_stats=getattr(encoder, 'stats', None),
                  seconds=round(time.time() - started, 1)))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
