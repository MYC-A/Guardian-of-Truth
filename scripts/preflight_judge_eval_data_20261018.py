"""CPU token/parser preflight using production legacy rendering, no model load.

Cap is the maximum quality-run cap, not the competition's adaptive time plan.
Notes have not been generated, so actual notes delivery is not tested here.
"""
import argparse
import csv
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'src')]

from scripts.prepare_judge_eval_data_20261018 import sha, write_json, write_jsonl
from guardian_truth.judge import answer_review, blind_review as br
from guardian_truth.judge.mechanical import analyze
from guardian_truth.judge.prompting import build_prompt
from guardian_truth.transcript import parse_document


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--data', type=Path, required=True)
    p.add_argument('--tokenizer', type=Path, required=True)
    p.add_argument('--config', type=Path, default=ROOT/'submission/JUDGE_OPEN_REVIEW40.json')
    a = p.parse_args()
    import transformers
    tok = transformers.AutoTokenizer.from_pretrained(str(a.tokenizer), local_files_only=True, trust_remote_code=False)
    cfg = json.loads(a.config.read_text(encoding='utf-8'))
    settings = br.validate_review_config(cfg)
    max_len = cfg['max_model_len']
    cap = max_len - 8 - settings['review_input_reserve_tokens']
    hard_cap = max_len - 2
    csv.field_size_limit(2**31-1)
    manifest = json.loads((a.data/'MANIFEST.json').read_bytes())
    summaries = {}
    for suite in manifest['suites']:
        folder = a.data/suite['path']
        assert sha((folder/'inputs.csv').read_bytes()) == suite['files']['inputs.csv']['sha256']
        with (folder/'inputs.csv').open(encoding='utf-8', newline='') as stream:
            rows = list(csv.DictReader(stream))
        records = []
        for position, row in enumerate(rows):
            parsed = parse_document(row['prompt'])
            if not any(m.role == 'system' for m in parsed.messages):
                raise ValueError('SYSTEM_MISSING: '+row['id'])
            finding = analyze(row['prompt'], row['response'], cfg['hard_unknown_identifier'])
            text, n, trimmed, policy_trimmed = build_prompt(tok, dict(row, hints=finding.hints), cap)
            rec = dict(position=position, id=row['id'], primary_input_tokens=n,
                primary_input_sha256=br.sha(text), primary_token_ids_sha256=br.token_sha(tok, text),
                trimmed=trimmed, policy_trimmed=policy_trimmed, over_planned_cap=n>cap,
                primary_over_model=n+1>max_len, mechanical_hard=list(finding.hard),
                parsed_history_messages=len(parsed.messages))
            saved = dict(text=text, trimmed=trimmed, policy_trimmed=policy_trimmed)
            try:
                pre = answer_review.prepare(tok, saved, settings, max_len-8)
                rec.update(prepass_input_tokens=pre['n'], prepass_input_sha256=br.sha(pre['text']),
                    prepass_token_ids_sha256=br.token_sha(tok, pre['text']))
            except ValueError as error:
                rec['prepass_error'] = str(error)
            try:
                final, fin_n, _, _ = br.final_prompt(tok, text, '', hard_cap)
                rec.update(final_without_notes_tokens=fin_n, final_without_notes_sha256=br.sha(final),
                    final_without_notes_token_ids_sha256=br.token_sha(tok, final),
                    final_remaining_input_tokens=hard_cap-fin_n)
            except ValueError as error:
                rec['final_error'] = str(error)
            records.append(rec)
        path = folder/'TOKEN_PREFLIGHT.jsonl'
        write_jsonl(path, records)
        summary = dict(rows=len(records), cap=cap, hard_cap=hard_cap,
            max_primary_input=max(r['primary_input_tokens'] for r in records),
            max_prepass_input=max([r.get('prepass_input_tokens', 0) for r in records]),
            counts={k:sum(bool(r.get(k)) for r in records) for k in
                ('trimmed', 'policy_trimmed', 'over_planned_cap', 'primary_over_model', 'prepass_error', 'final_error', 'mechanical_hard')},
            preflight_sha256=sha(path.read_bytes()))
        summaries[suite['path']] = summary
        print(json.dumps({suite['path']: summary}), flush=True)
    files = sorted(set(a.tokenizer.glob('tokenizer*')) | {a.tokenizer/'config.json', a.tokenizer/'special_tokens_map.json'})
    result = dict(schema='guardian-eval-token-preflight-v1', config_sha256=sha(a.config.read_bytes()),
        transformers_version=transformers.__version__, tokenizer_files={f.name: sha(f.read_bytes()) for f in files if f.is_file()},
        parser_module=sys.modules['guardian_truth.transcript'].__file__, suites=summaries, model_loaded=False,
        settings=dict(max_model_len=max_len, primary_cap=cap, hard_cap=hard_cap, prepass_max_tokens=settings['prepass_max_tokens']),
        limitations=['No generated notes; delivery and actual final-with-notes tokens unmeasured.',
          'Maximum fixed quality cap, not deadline-adaptive production trimming or target-GPU compatibility.'])
    write_json(a.data/'TOKEN_PREFLIGHT.json', result)


if __name__ == '__main__':
    main()
