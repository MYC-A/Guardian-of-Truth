"""Encode frozen TRAIN with production tokenizer/renderer before changing train runtime."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'src'), str(ROOT / 'scripts')]
from v5_35b_common import BASE_ID, BASE_REVISION, FROZEN_SHA256, TRAIN_SHA256, read, sha, verify_frozen, write
from v4_data import judge_input
from guardian_truth.judge.mechanical import analyze
from guardian_truth.judge.prompting import build_prompt, render
from scripts.judge_stage import answer_ids


def source_request(row):
    request = judge_input(row)
    finding = analyze(request['prompt'], request['response'], False, bounded_turn_shape=True)
    return dict(id=request['id'], prompt=request['prompt'], response=request['response'], hints=finding.hints)


def encode(tok, row):
    request = source_request(row)
    text, count, trimmed, policy_trimmed = build_prompt(tok, request, 49152)
    if trimmed or policy_trimmed or text != render(tok, request['prompt'], request['response'], request['hints']):
        raise ValueError('TRAIN_TRIMMING_OR_RENDER_DRIFT')
    ids = tok.encode(text, add_special_tokens=False)
    if len(ids) != count:
        raise ValueError('TRAIN_TOKEN_COUNT_DRIFT')
    return request, dict(id=row['id'], ids=ids, tokens=count, label=int(row['label']),
                        text_sha256=hashlib.sha256(text.encode('utf-8')).hexdigest(),
                        tokens_sha256=hashlib.sha256(json.dumps(ids, separators=(',', ':')).encode()).hexdigest())


def main():
    p = argparse.ArgumentParser()
    for name in ('data', 'model', 'out'):
        p.add_argument('--' + name, type=Path, required=True)
    a = p.parse_args()
    a.out.mkdir(exist_ok=False)
    verify_frozen(a.data)
    import transformers
    from transformers import AutoTokenizer
    if transformers.__version__ != '5.8.0':
        raise ValueError('PREPROCESS_REQUIRES_PRODUCTION_TRANSFORMERS_5_8')
    tok = AutoTokenizer.from_pretrained(a.model, local_files_only=True, trust_remote_code=False)
    yes, no = answer_ids(tok)
    rows = read(a.data / 'train.jsonl')
    if len(rows) != 1458 or len({r['id'] for r in rows}) != len(rows):
        raise ValueError('TRAIN_ROW_SET_DRIFT')
    lengths = []; pilot = []
    with (a.out / 'train_tokens.jsonl').open('w', encoding='utf-8') as out:
        for row in rows:
            request, record = encode(tok, row)
            out.write(json.dumps(record, ensure_ascii=True) + '\n')
            lengths.append(record['tokens'])
            pilot.append((record, request))
            if len(lengths) % 100 == 0:
                print(json.dumps(dict(event='encoded_train', rows=len(lengths), total=len(rows))), flush=True)
    pilot = sorted(pilot, key=lambda pair: (-pair[0]['tokens'], pair[0]['id']))[:3]
    with (a.out / 'pilot_tokens.jsonl').open('w', encoding='utf-8') as out:
        for record, _ in pilot:
            out.write(json.dumps({k: record[k] for k in ('id', 'ids', 'tokens', 'text_sha256', 'tokens_sha256')}) + '\n')
    with (a.out / 'pilot_inputs.jsonl').open('w', encoding='utf-8') as out:
        for _, request in pilot:
            out.write(json.dumps(request, ensure_ascii=True) + '\n')
    write(a.out / 'DONE.json', dict(complete=True, rows=len(rows), tokens=sum(lengths), max_tokens=max(lengths),
        answer_ids=dict(yes=sorted(yes), no=sorted(no)), base_id=BASE_ID, base_revision=BASE_REVISION,
        frozen_sha256=FROZEN_SHA256, train_source_sha256=TRAIN_SHA256,
        train_tokens_sha256=sha(a.out / 'train_tokens.jsonl'), pilot_tokens_sha256=sha(a.out / 'pilot_tokens.jsonl'),
        renderer='production overall, mechanical hints on, legacy, explicit current assistant header',
        context_trimmed=False, gold_in_text=False, human_reviewed=False,
        status='EXPLORATORY_ONLY_HUMAN_UNVERIFIED', transformers=transformers.__version__,
        source_sha256={name: sha(Path(__file__).with_name(name)) for name in
                       ('v5_35b_prepare.py', 'v5_35b_common.py', 'v4_data.py', 'v3_data.py')}))
    print(json.dumps(json.loads((a.out / 'DONE.json').read_bytes())), flush=True)


if __name__ == '__main__':
    main()
