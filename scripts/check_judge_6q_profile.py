"""Check the selected six-question profile with the real tokenizer; never run model inference.

Use valid46 only as a technical cap/context regression, never to select an aggregator.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT)]

from scripts.judge_submission import normalize_profile, read_input
from scripts.judge_stage import answer_ids, build_row
from guardian_truth.judge.mechanical import analyze
from guardian_truth.judge.prompting import QUESTIONS, count_tokens, question_margin, score_keys, variant_text


def digest(data):
    return hashlib.sha256(data).hexdigest()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=ROOT / 'submission/JUDGE_6Q_SUBMISSION.json')
    parser.add_argument('--model', type=Path, required=True)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(argv)
    raw = args.config.read_bytes()
    cfg, error = normalize_profile(json.loads(raw))
    expected = ['overall', 'values', 'actions', 'tool_use', 'policy', 'refusal']
    if (error or cfg['questions'] != expected or cfg['aggregate'] != 'mean_z'
            or cfg['aggregate_keys'] != [q + '@on' for q in expected]
            or cfg['context_mode'] != 'legacy' or cfg['review_mode'] != 'off'):
        raise ValueError('NOT_THE_RELEASE_6Q_PROFILE:' + str(error))
    from transformers import AutoTokenizer
    tok = AutoTokenizer.from_pretrained(args.model, local_files_only=True)
    yes, no = answer_ids(tok)
    keys = score_keys(cfg)
    margin = question_margin(tok, keys)
    cap = cfg['max_model_len'] - 2 - margin
    rows, records = read_input(args.input), []
    for position, source in enumerate(rows):
        finding = analyze(source['prompt'], source['response'], cfg['hard_unknown_identifier'])
        row = dict(source, key=position, hints=finding.hints)
        base, _, trimmed, policy_trimmed, context = build_row(tok, row, cap)
        variants = {}
        for key, question, mode in keys:
            text = variant_text(base, question, mode)
            count = count_tokens(tok, text)
            if count + 1 > cfg['max_model_len']:
                raise ValueError('MODEL_CONTEXT_OVERFLOW:%d:%s' % (position, key))
            ids = tok(text, add_special_tokens=False)['input_ids']
            variants[key] = dict(tokens=count, model_input_sha256=digest(text.encode('utf-8')),
                                 token_sha256=digest(json.dumps(ids, separators=(',', ':')).encode()))
        records.append(dict(position=position, trimmed=trimmed, policy_trimmed=policy_trimmed,
                            context=context, variants=variants))
    result = dict(scope='TECHNICAL_TOKENIZER_ONLY_NO_MODEL_INFERENCE', config_sha256=digest(raw),
                  input_sha256=digest(args.input.read_bytes()), rows=len(rows), margin=margin, cap=cap,
                  max_model_len=cfg['max_model_len'], keys=[k for k, _, _ in keys],
                  questions=QUESTIONS, yes_ids=sorted(yes), no_ids=sorted(no),
                  trimmed=sum(r['trimmed'] for r in records),
                  max_actual_tokens=max((v['tokens'] for r in records for v in r['variants'].values()), default=0),
                  gpu_tested=False, records=records)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: v for k, v in result.items() if k not in ('records', 'questions')}, indent=2))
    return result


if __name__ == '__main__':
    main()
