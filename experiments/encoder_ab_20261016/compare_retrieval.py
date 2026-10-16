"""Frozen CPU comparison of lexical U2 and shipping MiniLM U2 on valid46.

Labels and explanations are used only in the post-retrieval inspection file.
Neither retriever receives them. This measures retrieval changes, not classifier F1.
"""
import argparse
import collections
import hashlib
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time
import zipfile
from unittest.mock import patch

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
OUT = None
sys.path[:0] = [str(REPO / 'src'), str(REPO)]
from guardian_truth.judge.dense_encoder import LocalEncoder
from guardian_truth.judge.u2_context import context_for
from guardian_truth.evidence_packer import packer


def dump(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding='utf-8')


def effective(record, row):
    return record['text'] if record['mode'] == 'u2' else row['prompt']


def run_pass(name, rows, cfg, encoder=None):
    original = packer.pack
    captured = {}
    def record_packet(*args, **kwargs):
        result = original(*args, **kwargs)
        captured['packet'] = result
        return result
    started = time.perf_counter()
    dense_until = time.time() + cfg['u2_embed_total_seconds']
    results = []
    with (OUT / (name + '.jsonl')).open('x', encoding='utf-8') as stream, patch.object(packer, 'pack', record_packet):
        for k, row in enumerate(rows):
            captured.clear()
            embedder, fallback = encoder, None
            if encoder:
                if time.time() >= dense_until:
                    embedder, fallback = None, 'EMBED_TOTAL_BUDGET'
                else:
                    encoder.deadline = min(time.time() + cfg['u2_embed_seconds_per_row'], dense_until)
            record = context_for(row['prompt'], row['response'], embedder=embedder, dense_fallback=fallback)
            value = dict(row=k, id=row['id'], record=record, packet=captured.get('packet'))
            stream.write(json.dumps(value, ensure_ascii=False) + '\n')
            stream.flush()
            os.fsync(stream.fileno())
            results.append(value)
            print(json.dumps(dict(event='row', method=name, row=k, mode=record['mode'], ranking=record.get('ranking'),
                                  fallback=record.get('dense_fallback'), seconds=record['seconds'])), flush=True)
    return results, round(time.perf_counter() - started, 3)


def main():
    global OUT
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--input', type=Path, default=REPO / 'valid.parquet')
    ap.add_argument('--encoder-dir', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True, help='New directory; existing results are never overwritten')
    ap.add_argument('--source-zip', type=Path, default=None, help='Read the exact shipping JUDGE_CONFIG.json from this ZIP')
    ap.add_argument('--config', type=Path, default=REPO / 'submission/JUDGE_CONFIG.json')
    a = ap.parse_args()
    OUT = a.output
    OUT.mkdir(parents=True, exist_ok=False)
    source = a.input
    frame = pd.read_parquet(source)
    rows = [dict(id=str(r['id']), prompt=str(r['prompt']), response=str(r['response'])) for _, r in frame.iterrows()]
    if a.source_zip:
        with zipfile.ZipFile(a.source_zip) as z:
            cfg = json.loads(z.read('JUDGE_CONFIG.json'))
        if cfg.get('context_mode') != 'u2_dense':
            raise ValueError('SOURCE_ZIP_IS_NOT_DENSE')
    else:
        cfg = json.loads(a.config.read_text(encoding='utf-8'))
        cfg['context_mode'] = 'u2_dense'  # Experiment only; do not change the repository default.
    cfg.setdefault('u2_embed_seconds_per_row', 5.0)
    cfg.setdefault('u2_embed_total_seconds', 300.0)
    dump(OUT / 'input-provenance.json', dict(source=str(source), source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
         commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=REPO, text=True).strip(), rows=len(rows),
         config=cfg, labels_in_retrieval=False))
    start = time.perf_counter()
    encoder = LocalEncoder(a.encoder_dir)
    load_seconds = round(time.perf_counter() - start, 3)
    dense, dense_seconds = run_pass('dense', rows, cfg, encoder)
    encoder_stats = dict(encoder.stats)
    lexical, lexical_seconds = run_pass('lexical', rows, cfg)

    comparisons = []
    for k, (row, base, added) in enumerate(zip(rows, lexical, dense)):
        lp, dp = base['packet'] or {}, added['packet'] or {}
        left, right = set(lp.get('selected_units', [])), set(dp.get('selected_units', []))
        units, _, _, _ = packer.build_units(row, packer.PackerConfig())
        unit_map = {u['uid']: u for u in units}
        def fragments(ids):
            return [{key: unit_map[uid][key] for key in ('uid', 'category', 'kind', 'role', 'tool', 'start', 'end', 'text')}
                    for uid in sorted(ids) if uid in unit_map]
        comparisons.append(dict(row=k, id=row['id'],
            context_changed=effective(base['record'], row) != effective(added['record'], row),
            selection_jaccard=len(left & right) / len(left | right) if left | right else 1.0,
            lexical_units=len(left), dense_units=len(right), added_units=len(right-left), removed_units=len(left-right),
            lexical_context_chars=len(effective(base['record'], row)), dense_context_chars=len(effective(added['record'], row)),
            prompt_chars=len(row['prompt']), lexical_mode=base['record']['mode'], dense_mode=added['record']['mode'],
            dense_ranking=added['record'].get('ranking'), dense_fallback=added['record'].get('dense_fallback'),
            lexical_uncovered=base['record'].get('uncovered'), dense_uncovered=added['record'].get('uncovered'),
            label=int(frame.iloc[k]['label']), explanation=str(frame.iloc[k]['explanation']), response=row['response'],
            additions=fragments(right-left), removals=fragments(left-right)))
    dump(OUT / 'paired-selection-inspection.json', comparisons)
    valid_pairs=[x for x in comparisons if x['dense_ranking']=='dense' and x['dense_mode']=='u2']
    summary=dict(rows=len(rows), encoder_load_seconds=load_seconds, dense_pass_seconds=dense_seconds,
        lexical_pass_seconds=lexical_seconds, encoder_stats=encoder_stats,
        effective_context_changed=sum(c['context_changed'] for c in comparisons),
        effective_context_unchanged=sum(not c['context_changed'] for c in comparisons),
        changed_by_label={str(label):sum(c['context_changed'] for c in comparisons if c['label']==label) for label in (0,1)},
        mode_counts=dict(collections.Counter(c['dense_mode'] for c in comparisons)),
        dense_fallback_counts=dict(collections.Counter(c['dense_fallback'] for c in comparisons if c['dense_fallback'])),
        actual_dense_compressed_rows=len(valid_pairs),
        mean_selection_jaccard_compressed=round(statistics.mean(c['selection_jaccard'] for c in valid_pairs),4) if valid_pairs else None,
        total_added_units=sum(c['added_units'] for c in comparisons), total_removed_units=sum(c['removed_units'] for c in comparisons),
        scope='CPU-only paired retrieval experiment; no Qwen, no F1, no gold evidence annotations, no 500-row timing proof')
    dump(OUT / 'summary.json', summary)
    for c in comparisons:
        print(json.dumps({key:c[key] for key in ('row','id','context_changed','selection_jaccard','added_units','removed_units','dense_fallback')},ensure_ascii=False),flush=True)
    print(json.dumps(summary, ensure_ascii=False),flush=True)


if __name__ == '__main__':
    main()
