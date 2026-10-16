"""CPU comparison of U2 packer options on the same rows. No Qwen, no F1, labels never read.

    python experiments/u2_action_policy_20261016/compare_anchors.py --input valid.parquet --out runs/u2-options \
        [--encoder models/encoder] \
        [--anchors experiments/encoder_ab_20261016/results/inspected-evidence-anchors.json]

Arms: u2 (as measured), u2+action; with --encoder also u2_dense (as in 6d70314), dense_v1 (action + remainder +
policy scope + query split 400) and dense_v2 (dense_v1 + token-window pieces for queries and passages). Diagnostic
arms, not approved for production: u2+action+synonyms and dense_v2+synonyms. The earlier synonym regression
motivated direct-match priority; source selection and model quality still need independent evaluation.
Every dense arm gets its own encoder instance (cold application cache).

Writes, under --out:
  summary.json   per arm: modes, reasons, rankings, dense fallbacks, attempt and FINAL action coverage, timing,
                 rows changed against u2; anchor checks if --anchors
  rows.jsonl     per row and arm: mode, reason, sizes, quoted spans (prompt offsets reported by the packer itself,
                 never re-located by text search), context hash, action matches with final coverage and the texts
                 of missing blocks, dense window statistics
  diffs.jsonl    per row and arm whose context differs from u2: every added and removed prompt range WITH its text
  contexts/<arm>/<row>.txt   the exact context the stage would show (u2 packet text or the full prompt)
--anchors quotes were chosen after inspecting an earlier run: regression checks, NOT an unbiased evidence recall.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / 'src')):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from guardian_truth.judge import u2_context  # noqa: E402

ACTION = dict(action_policy=True)
ACTION_SYN = dict(action_policy=True, action_synonyms=True)
DENSE_V1 = dict(action_policy=True, dense_fusion='remainder', dense_scope='policy', dense_query_chars=400)
DENSE_V2 = dict(DENSE_V1, dense_passage_pieces=True)
DENSE_V2_SYN = dict(DENSE_V2, action_synonyms=True)


def read_rows(path):
    import pyarrow.parquet as pq
    table = pq.read_table(path, columns=['prompt', 'response'])
    return [dict(prompt=str(p or ''), response=str(r or ''))
            for p, r in zip(table.column('prompt').to_pylist(), table.column('response').to_pylist())]


def context_text(record, row):
    """Context the stage would show instead of the transcript; None when the legacy builder decides it."""
    if record.get('mode') == 'u2':
        return record.get('text')
    return row['prompt'] if record.get('mode') == 'full_input' else None


def quoted_spans(record, prompt):
    """Evidence ranges exactly as the packer reports them (context_for(with_spans=True)). Re-emitted role headers
    and diagnostic markers are outside these evidence ranges. A repeated quote is never attributed to an earlier
    identical text. None for legacy rows (the legacy builder decides)."""
    if record.get('mode') == 'full_input':
        return [(0, len(prompt))]
    if record.get('mode') != 'u2':
        return None
    return [tuple(s) for s in record['spans']]


def minus(a, b):
    """Ranges of a not covered by b (both sorted, disjoint)."""
    out = []
    for lo, hi in a:
        start = lo
        for blo, bhi in b:
            if bhi <= start or blo >= hi:
                continue
            if blo > start:
                out.append((start, blo))
            start = max(start, bhi)
        if start < hi:
            out.append((start, hi))
    return [(x, y) for x, y in out if y > x]


def run_arm(rows, options, encoder_dir, per_row, total):
    encoder, load = None, 0.0
    if encoder_dir:
        from guardian_truth.judge.dense_encoder import LocalEncoder
        t0 = time.perf_counter()
        encoder = LocalEncoder(encoder_dir)
        load = time.perf_counter() - t0
    records, started = [], time.perf_counter()
    dense_until = time.time() + total
    for row in rows:
        embedder, fallback = None, None
        if encoder is not None and time.time() >= dense_until:
            fallback = 'EMBED_TOTAL_BUDGET'
        elif encoder is not None:
            encoder.deadline = min(time.time() + per_row, dense_until)
            embedder = encoder
        records.append(u2_context.context_for(row['prompt'], row['response'], embedder=embedder,
                                              dense_fallback=fallback, options=options, with_spans=True))
    seconds = time.perf_counter() - started
    return records, dict(load_seconds=round(load, 3), pass_seconds=round(seconds, 3),
                         seconds_per_row=round(seconds / max(len(rows), 1), 4),
                         encoder_stats=getattr(encoder, 'stats', None))


def action_detail(record, row):
    """Per match as reported by context_for (attempt status, sections, final coverage) plus the exact texts of the
    matched policy blocks that are absent from the final context."""
    out = []
    for m in record.get('action_policy') or []:
        item = dict(m)
        item['missing_text'] = [row['prompt'][a:b] for a, b in m.get('missing_spans') or []]
        out.append(item)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--input', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--encoder', default=None)
    ap.add_argument('--anchors', default=None)
    ap.add_argument('--embed-seconds-per-row', type=float, default=5.0)
    ap.add_argument('--embed-total-seconds', type=float, default=300.0)
    a = ap.parse_args(argv)
    rows = read_rows(a.input)
    arms = [('u2', {}, None), ('u2+action', ACTION, None), ('diag:u2+action+synonyms', ACTION_SYN, None)]
    if a.encoder:
        arms += [('u2_dense', {}, a.encoder), ('dense_v1', DENSE_V1, a.encoder), ('dense_v2', DENSE_V2, a.encoder),
                 ('diag:dense_v2+synonyms', DENSE_V2_SYN, a.encoder)]
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    results, summary = {}, dict(rows=len(rows), input=str(a.input), arms={},
                                input_sha256=hashlib.sha256(Path(a.input).read_bytes()).hexdigest(),
                                scope='CPU packing only; no Qwen, no F1; anchors are post-hoc diagnostic checks')
    for name, options, encoder in arms:
        records, timing = run_arm(rows, options, encoder, a.embed_seconds_per_row, a.embed_total_seconds)
        results[name] = records
        matches = [m for r in records for m in r.get('action_policy') or []]
        summary['arms'][name] = dict(
            options=options, modes=dict(Counter(r['mode'] for r in records)),
            reasons=dict(Counter(r['reason'] for r in records)),
            rankings=dict(Counter(r.get('ranking') for r in records if r.get('ranking'))),
            dense_fallbacks=dict(Counter(r['dense_fallback'] for r in records if r.get('dense_fallback'))),
            action_statuses=dict(Counter(m['status'] for m in matches)),
            action_final_coverage=dict(Counter(m.get('coverage') for m in matches)),
            rows_with_incomplete_action=sum(1 for r in records if r.get('action_complete') is False),
            action_anchor_attempt=dict(Counter(str(r.get('action_anchor')) for r in records if 'action_policy' in r)),
            dense_windows={k: sum((r.get('dense_windows') or {}).get(k) or 0 for r in records)
                           for k in ('queries', 'unfit_queries', 'passages', 'unfit_passages', 'prefix_trimmed_units')},
            **timing)
    spans = {name: [quoted_spans(r, row['prompt']) for r, row in zip(results[name], rows)]
             for name in results}
    base = [context_text(r, row) for r, row in zip(results['u2'], rows)]
    for name in results:
        texts = [context_text(r, row) for r, row in zip(results[name], rows)]
        summary['arms'][name]['changed_vs_u2'] = sum(1 for x, y in zip(texts, base) if x != y)
        folder = out / 'contexts' / re.sub(r'[^\w.+-]', '_', name)
        folder.mkdir(parents=True, exist_ok=True)
        for i, text in enumerate(texts):
            if text is not None:
                (folder / ('%02d.txt' % i)).write_text(text, encoding='utf-8')
    if a.anchors:
        checks = json.loads(Path(a.anchors).read_text(encoding='utf-8'))['checks']
        summary['anchor_checks'] = []
        for check in checks:
            i = int(check['row'])
            present = {}
            for name in results:
                text = context_text(results[name][i], rows[i])
                present[name] = None if text is None else check['text'] in text
            summary['anchor_checks'].append(dict(row=i, anchor=check.get('anchor'), present=present))
    with open(out / 'rows.jsonl', 'w', encoding='utf-8') as stream, \
            open(out / 'diffs.jsonl', 'w', encoding='utf-8') as diffs:
        for i, row in enumerate(rows):
            item = dict(row=i)
            for name in results:
                r = results[name][i]
                text = context_text(r, row)
                item[name] = dict(mode=r['mode'], reason=r['reason'], ranking=r.get('ranking'),
                                  dense_fallback=r.get('dense_fallback'), source_bytes=r.get('source_bytes'),
                                  quoted_chars=r.get('quoted_chars'), policy_mode=r.get('policy_mode'),
                                  spans=spans[name][i],
                                  context_sha256=None if text is None else hashlib.sha256(
                                      text.encode('utf-8', 'surrogatepass')).hexdigest(),
                                  changed_vs_u2=text != base[i], action=action_detail(r, row),
                                  action_complete=r.get('action_complete'), action_anchor=r.get('action_anchor'),
                                  dense_windows=r.get('dense_windows'))
                if name != 'u2' and text != base[i]:
                    mine, ref = spans[name][i], spans['u2'][i]
                    if mine is None or ref is None:
                        diffs.write(json.dumps(dict(row=i, arm=name, comparable=False, mode=r['mode'],
                                                    base_mode=results['u2'][i]['mode']), ensure_ascii=False) + '\n')
                        continue
                    added = [dict(start=x, end=y, text=row['prompt'][x:y]) for x, y in minus(mine, ref)]
                    removed = [dict(start=x, end=y, text=row['prompt'][x:y]) for x, y in minus(ref, mine)]
                    diffs.write(json.dumps(dict(row=i, arm=name, comparable=True, added=added, removed=removed,
                                                added_chars=sum(d['end'] - d['start'] for d in added),
                                                removed_chars=sum(d['end'] - d['start'] for d in removed)),
                                           ensure_ascii=False) + '\n')
            stream.write(json.dumps(item, ensure_ascii=False) + '\n')
    (out / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
