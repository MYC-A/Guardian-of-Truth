"""Counterfactual final-only ablation on frozen generated notes; no gold input.

Not an independent end-to-end repeat: generation is reused, all final scores
are fresh. Same source, exact scoring, batch size and final checklist in 3 arms.
"""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'src')]
from guardian_truth.judge import answer_review, blind_review as br, partial_audit
from guardian_truth.judge.review_stage import PrimaryInputs
from scripts import judge_stage as stage

ARMS = ('no_notes', 'strict', 'partial')


def read(path):
    return [json.loads(x) for x in path.read_bytes().splitlines() if x.strip()]


def unique(rows):
    out = {}
    for row in rows:
        if type(row['key']) is not int or row['key'] in out:
            raise ValueError('DUPLICATE_OR_INVALID_KEY')
        out[row['key']] = row
    return out


def close_source(run):
    cfg = json.loads((run / 'judge_config.json').read_bytes())
    settings = br.validate_review_config(cfg)
    if settings['review_content'] != 'answer_audit':
        raise ValueError('ANSWER_AUDIT_ONLY')
    rows = unique(read(run / 'stage_input.jsonl'))
    records = read(run / 'scores.jsonl')
    pre = unique([r for r in records if r.get('review') == 'prepass'])
    finals = [r for r in records if r.get('review') == 'final']
    final = unique(finals)
    spools = list(run.glob('primary-inputs-*.jsonl'))
    if len(spools) != 1:
        raise ValueError('ONE_DURABLE_PRIMARY_SPOOL_REQUIRED')
    saved = unique(read(spools[0]))
    if not (set(rows) == set(pre) == set(final) == set(saved) == set(range(len(rows)))):
        raise ValueError('SOURCE_COVERAGE')
    digest = hashlib.sha256((run / 'stage_input.jsonl').read_bytes()).hexdigest()
    for key, row in rows.items():
        s = saved[key]
        if (s['input_sha256'] != digest or s['row_sha256'] != PrimaryInputs.row_sha(row)
                or br.sha(s['text']) != s['model_input_sha256']
                or final[key]['base_sha256'] != s['model_input_sha256']):
            raise ValueError('SAVED_SOURCE_IDENTITY')
    return cfg, settings, pre, final, saved, [r['key'] for r in finals]


def final_input(tok, base, notes, pre, settings, hard_cap):
    block, state, reason = '', 'NOT_DELIVERED', 'NOTES_NOT_VALID'
    if notes is not None:
        block = partial_audit.render_notes(notes, pre, settings)
        state, reason = None, None
        if stage.count_tokens(tok, block) > settings['notes_max_tokens']:
            block, state, reason = '', 'DROPPED_SIZE', 'NOTES_OVER_ALLOWANCE'
    text, n, delivered, why = br.final_prompt(tok, base, block, hard_cap)
    delivered = state or delivered
    reason = why or (None if delivered == 'DELIVERED' else reason)
    return dict(text=text, tokens=n, input_sha256=br.sha(text),
                input_token_sha256=br.token_sha(tok, text), delivery=delivered, delivery_reason=reason)


def prepare(run, tok):
    cfg, settings, pre, old_final, saved, order = close_source(run)
    plans, counts = {}, {arm: Counter() for arm in ARMS}
    for key in order:
        s, raw = saved[key], pre[key]
        if br.token_sha(tok, s['text']) != s['input_token_sha256']:
            raise ValueError('PRIMARY_TOKENIZER_CHANGED')
        prepared = answer_review.prepare(tok, s, settings, cfg['max_model_len'] - 8)
        if (br.sha(prepared['source']) != raw['source_sha256'] or len(prepared['units']) != raw['units']
                or br.sha(prepared['text']) != raw['input_sha256']
                or br.token_sha(tok, prepared['text']) != raw['input_token_sha256']):
            raise ValueError('PREPASS_SOURCE_OR_TOKENIZER_CHANGED')
        strict = answer_review.parse_notes(raw['raw'], raw['finish_reason'], br.citable(prepared['units']), settings)
        partial = partial_audit.parse_notes(raw['raw'], raw['finish_reason'], br.citable(prepared['units']), settings)
        if strict[0] != raw['status'] or strict[1] != raw['notes']:
            raise ValueError('STRICT_PARSE_CHANGED')
        per = {}
        for arm, parsed in (('no_notes', ('NOT_RUN', None, {})), ('strict', strict), ('partial', partial)):
            status, notes, report = parsed
            plan = final_input(tok, s['text'], notes, prepared, settings, cfg['max_model_len'] - 2)
            plan.update(key=key, arm=arm, admission=status, base_sha256=s['model_input_sha256'])
            if arm == 'strict' and any(plan[k] != old_final[key][k] for k in
                    ('input_sha256', 'input_token_sha256', 'delivery', 'delivery_reason')):
                raise ValueError('STRICT_FINAL_NOT_BYTE_IDENTICAL')
            if arm == 'partial' and strict[0] == 'VALID' and plan['input_sha256'] != per['strict']['input_sha256']:
                raise ValueError('VALID_NOTES_CHANGED')
            counts[arm]['admission:' + status] += 1
            counts[arm]['delivery:' + plan['delivery']] += 1
            per[arm] = plan
        plans[key] = per
    return cfg, plans, order, {k: dict(v) for k, v in counts.items()}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--run', type=Path, required=True)
    ap.add_argument('--model', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--plan-only', action='store_true')
    a = ap.parse_args()
    weights = json.loads((a.model / 'VERIFIED.json').read_bytes())
    if (weights['repository'] != 'cyankiwi/Qwen3.6-35B-A3B-AWQ-4bit'
            or weights['revision'] != '00fcea2d3bcf5389b518d4fc082e5590e0ba4844'):
        raise ValueError('WEIGHT_REVISION_CHANGED')
    a.out.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    from transformers import AutoTokenizer
    tok = AutoTokenizer.from_pretrained(str(a.model), local_files_only=True, trust_remote_code=False)
    cfg, plans, order, counts = prepare(a.run, tok)
    receipt = dict(schema='guardian-note-admission-replay-v1', rows=len(order), source_run=a.run.name,
        arms=ARMS, admission=counts, generation_reused=True, generation_calls_added=0,
        weight_repository=weights['repository'], weight_revision=weights['revision'],
        independent_repeat=False, thresholds_fitted=0, rates=[.3, .4], batch=cfg['chunk'],
        source_files_sha256={p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in
            [a.run / 'judge_config.json', a.run / 'stage_input.jsonl', a.run / 'scores.jsonl',
             *a.run.glob('primary-inputs-*.jsonl')]},
        arm_schedule='same keys/batch per arm; arm order rotated by batch; APC enabled; not competition timing')
    (a.out / 'plan.json').write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
    with (a.out / 'prompts.jsonl').open('w', encoding='utf-8') as f:
        for key in order:
            for arm in ARMS:
                f.write(json.dumps(plans[key][arm], ensure_ascii=True) + '\n')
    print(json.dumps(dict(event='plan', **receipt)), flush=True)
    if a.plan_only:
        return
    from vllm import LLM, SamplingParams
    kwargs, dropped = stage.engine_kwargs(str(a.model), cfg)
    if dropped:
        raise ValueError('ENGINE_ARGUMENTS_DROPPED')
    llm = LLM(**kwargs)
    if br.token_sha(llm.get_tokenizer(), plans[order[0]]['strict']['text']) != plans[order[0]]['strict']['input_token_sha256']:
        raise ValueError('ENGINE_TOKENIZER_CHANGED')
    yes, no = stage.answer_ids(llm.get_tokenizer())
    params = SamplingParams(temperature=1., top_p=1., max_tokens=1, logprobs=20, seed=0,
                            allowed_token_ids=sorted(yes | no))
    exact, info = stage.probe(llm, llm.get_tokenizer(), params, yes, no)
    if not exact:
        raise ValueError('EXACT_PROBE_FAILED')
    usage = {arm: stage.Usage() for arm in ARMS}
    with (a.out / 'scores.jsonl').open('w', encoding='utf-8', buffering=1) as stream:
        for batch_index, offset in enumerate(range(0, len(order), cfg['chunk'])):
            keys = order[offset:offset + cfg['chunk']]
            shift = batch_index % len(ARMS)
            for arm in ARMS[shift:] + ARMS[:shift]:
                prompts = [plans[k][arm]['text'] for k in keys]
                t = time.monotonic()
                outputs = llm.generate(prompts, params, use_tqdm=False)
                stage.check_order(outputs, prompts)
                usage[arm].add(outputs, time.monotonic() - t)
                for key, output in zip(keys, outputs):
                    score, exact = stage.answer_score(output, yes, no)
                    if not exact or score is None or not math.isfinite(score):
                        raise ValueError('INCOMPLETE_EXACT_REPLAY')
                    rec = {k: v for k, v in plans[key][arm].items() if k != 'text'}
                    rec.update(final_score=score, exact=True)
                    stream.write(json.dumps(rec) + '\n')
            print(json.dumps(dict(event='batch', done=min(offset + len(keys), len(order)),
                                  of=len(order), seconds=round(time.monotonic() - started, 1))), flush=True)
    receipt.update(usage={arm: u.report() for arm, u in usage.items()},
                   wall_seconds=round(time.monotonic() - started, 2), exact_scored=len(order) * len(ARMS))
    (a.out / 'DONE.json').write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(event='done', **receipt)), flush=True)


if __name__ == '__main__':
    main()
