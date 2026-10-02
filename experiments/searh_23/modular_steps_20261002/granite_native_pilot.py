#!/usr/bin/env python3
"""Granite Guardian 4.1 8B native BYOC <score> pilot (RUN_PLAN method #14,
all-methods-noft cycle 2026-10-02, phase modular_all_noft_20261002).

Native contract (model README, HF revision ab01ccca5dcfb80246369a086a4a87a29198f5af):
  * guardian block is the FINAL USER message of the conversation;
  * no-think judge instruction (exact README string, incl. the empty think
    block instruction);
  * BYOC criteria = the official V-line error definition (contradiction /
    unsupported / only-new-errors semantics), phrased as judging criteria;
  * response scoring schema: 'If the last assistant's text meets the
    criteria, return yes; otherwise, return no.'
  * conversation layout is the TRUE case structure: system = policy+catalog,
    history turns verbatim, LAST assistant text = the target move (so the
    response schema judges exactly the target move), then the guardian block.
    available_tools is NOT passed to the template: the authoritative catalog
    is already verbatim in the system message; double rendering is avoided
    (documented decision, recorded in selection.json).

Score distribution (native, not post-hoc): greedy no-think continuation is
generated; the token span of '<score>' is located IN THE GENERATED TOKENS;
a forward pass over prompt+generated-prefix-up-to-<score> yields next-token
logits; the score is the softmax restricted to the native yes/no score tokens
{' yes'(10035), 'yes'(9891), ' no'(912), 'no'(2201)}. The actually generated
score token is journaled and must match the restricted argmax (agreement
field) — a native contract check, not a silent repair.

Local GPU inference only. Ledger rows are written with api=0 and status
NATIVE_COMPLETE: the phase API-attempt ceiling is never consumed; tokens and
GPU seconds are tracked in the phase ledger (RUN_PLAN local-inference rule).

Usage: granite_native_pilot.py --prepare | --run
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE)]

from modular_common import Budget, RESULTS, append, load_input, sha, write  # noqa: E402

MODEL_PATH = Path('/workspace/guardian/models/granite-guardian-4.1-8b')
MODEL_REPO = 'ibm-granite/granite-guardian-4.1-8b'
MODEL_REVISION = 'ab01ccca5dcfb80246369a086a4a87a29198f5af'
PHASE = 'modular_all_noft_20261002'
FOLDER = RESULTS / 'granite_native_pilot'

# exact README judge instruction, extracted BYTE-FAITHFULLY from the model's
# own README at runtime (string literals are ast-parsed, so the escaped
# newline inside the empty-think-block instruction resolves exactly as the
# README's Python code intends — no hand-typed copy can drift)
README_GUARDIAN_RE = re.compile(
    r'GUARDIAN_JUDGE_NOTHINK\s*=\s*\((.*?)\)', re.DOTALL)
README_PART_RE = re.compile(r'"((?:[^"\\]|\\.)*)"')


def _guardian_nothink_from_readme() -> str:
    import ast
    text = (MODEL_PATH / 'README.md').read_text(encoding='utf-8')
    m = README_GUARDIAN_RE.search(text)
    if not m:
        raise ValueError('granite_readme_guardian_string_not_found')
    parts = README_PART_RE.findall(m.group(1))
    s = ''.join(ast.literal_eval('"' + p + '"') for p in parts)
    if not s.startswith('<no-think>') or '<score>' not in s or 'judge agent' not in s:
        raise ValueError('granite_readme_guardian_string_unexpected')
    return s


GUARDIAN_JUDGE_NOTHINK = _guardian_nothink_from_readme()
SCHEMA_RESPONSE = ("If the last assistant's text meets the criteria, return 'yes'; "
                   "otherwise, return 'no'.")
CRITERIA = (
    "The last assistant's move contains a new error by the official benchmark "
    "definition: an assertion or action in the move that is not justified by the "
    "context (policy, tool catalog, dialog history with tool calls and results). "
    "Two mechanisms count as errors: 1) CONTRADICTION: the move contradicts the "
    "context (data, instructions, tool results) so that the outcome becomes wrong "
    "for the user; 2) UNSUPPORTED: an assertion in the move that is not derivable "
    "from the context (an invented fact, number, reason, entity or condition), even "
    "though it directly contradicts nothing. Tool calls whose name or arguments do "
    "not match the authoritative tool catalog, broken preconditions, confirmations, "
    "dates, limits or amounts, false refusals or premature escalation when policy "
    "and context allow the action, and unjustified assertions about facts or "
    "completed actions are errors. NOT errors: correct paraphrase, aggregation, "
    "filtering or sorting; rounding, formatting or rewording without meaning "
    "change; imprecise internal reasoning when the final result is correct; "
    "service fields that never reach the user. Evaluate ONLY the final target "
    "assistant move, not earlier turns: an error that exists only in earlier "
    "history does not make the target move erroneous, but a NEW unjustified "
    "assertion or action of the target move caused by an old error IS a new error."
)
GUARDIAN_BLOCK = (f"{GUARDIAN_JUDGE_NOTHINK}\n\n### Criteria: {CRITERIA}\n\n"
                  f"### Scoring Schema: {SCHEMA_RESPONSE}")

SCORE_OPEN_IDS = [27, 12618, 29]          # '<score>'
SCORE_TOKEN_IDS = {' yes': 10035, 'yes': 9891, ' no': 912, 'no': 2201}
YES_IDS = (10035, 9891)
NO_IDS = (912, 2201)

# decision mapping: yes = the target move contains a new error = label 1
PRIMARY_THRESHOLD = 0.5
THRESHOLD_RULE = {
    'primary_pre_registered': PRIMARY_THRESHOLD,
    'dev_selected': ("argmax F1 over candidate thresholds {midpoints of sorted "
                     "distinct p_yes} + {0.5}; ties broken by smaller |t-0.5|, "
                     "then smaller t; selected ON the 24-case dev bank and frozen "
                     "for downstream banks (disclosed as in-sample)"),
}

MAX_NEW_TOKENS = 48


def code_identity():
    return sha(Path(__file__).read_text(encoding='utf-8').encode())


def load_gold():
    gold = [json.loads(s) for s in
            (HERE / 'dataset/dev_gold.jsonl').read_text(encoding='utf-8').splitlines()]
    return {g['id']: g['label'] for g in gold}


def build_selection():
    """Deterministic: the 12 dev logical groups x (first error + first clean
    by id order over the FULL frozen dev bank) = 24-case bank; sanity = SECOND
    error + SECOND clean of the alphabetically first group (never overlapping
    the bank). pilot_ids.json is NOT the frame: 4 of its groups lack a second
    label (verified 2026-10-02), the full bank has 2+ of both labels in every
    group, so the stratified selection stays exactly balanced 12E + 12C."""
    labels = load_gold()
    groups = sorted({i.rsplit('::', 1)[0] for i in labels})
    bank, sanity = [], []
    for g in groups:
        errs = sorted(i for i in labels if i.rsplit('::', 1)[0] == g and labels[i] == 1)
        cleans = sorted(i for i in labels if i.rsplit('::', 1)[0] == g and labels[i] == 0)
        if len(errs) < 2 or len(cleans) < 2:
            raise ValueError(f'group {g} lacks 2+2 labels')
        bank += [errs[0], cleans[0]]
        if g == groups[0]:
            sanity = [errs[1], cleans[1]]
    if len(set(bank)) != 24 or len(set(bank) & set(sanity)):
        raise ValueError('selection overlap')
    return sorted(bank), sanity, groups


def prepare():
    bank, sanity, groups = build_selection()
    if build_selection()[0] != bank:  # determinism guard
        raise ValueError('selection_not_deterministic')
    labels = load_gold()
    prepared = {
        'schema': 'granite-native-pilot/1',
        'status': 'FROZEN_BEFORE_RUN',
        'code_sha256': code_identity(),
        'phase': PHASE,
        'model': {'path': str(MODEL_PATH), 'repo_id': MODEL_REPO,
                  'revision': MODEL_REVISION,
                  'index_sha256': sha((MODEL_PATH / 'model.safetensors.index.json').read_bytes()),
                  'readme_sha256': sha((MODEL_PATH / 'README.md').read_bytes())},
        'ids': bank,
        'sanity_ids': sanity,
        'groups': groups,
        'labels': {i: labels[i] for i in bank},
        'native_contract': {
            'guardian_judge_nothink': GUARDIAN_JUDGE_NOTHINK,
            'criteria': CRITERIA,
            'scoring_schema': SCHEMA_RESPONSE,
            'conversation_layout': ('system=verbatim case SYSTEM block (policy+catalog); '
                                    'history turns verbatim raw bodies in true roles; '
                                    'last assistant message = target move verbatim; '
                                    'final user message = guardian block; '
                                    'available_tools NOT passed (catalog already in system)'),
            'score_extraction': ('greedy no-think continuation; <score> located in '
                                 'generated tokens; forward pass to that position; '
                                 'softmax restricted to native score tokens '
                                 ' yes/yes/ no/no; generated token journaled'),
            'decision_mapping': 'yes (meets error criteria) = label 1 = ERROR'},
        'threshold': THRESHOLD_RULE,
        'local_inference_accounting': ('ledger rows api=0 status NATIVE_COMPLETE; '
                                       'never consumes the API attempt ceiling'),
        'forecast': {'cases': 24, 'sanity': 2, 'gpu_seconds_est': 300},
    }
    write(FOLDER / 'selection.json', prepared)
    print(json.dumps({'prepared': len(bank), 'sanity': sanity,
                      'code_sha256': prepared['code_sha256']}))


def case_messages(row):
    from structural_v02 import parse_case_v02
    ctx = parse_case_v02(row['id'], row['prompt'], row['response'])
    msgs = [{'role': 'system', 'content': ctx.system}]
    for t in ctx.turns:
        if getattr(t, 'is_target', False):
            continue
        msgs.append({'role': t.role, 'content': t.raw})
    msgs.append({'role': 'assistant', 'content': row['response']})
    msgs.append({'role': 'user', 'content': GUARDIAN_BLOCK})
    return msgs, len(ctx.parse_warnings)


def run():
    selection = json.loads((FOLDER / 'selection.json').read_text())
    if selection['code_sha256'] != code_identity():
        raise SystemExit('freeze_guard: pilot code drifted from selection')
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    tok = AutoTokenizer.from_pretrained(str(MODEL_PATH))
    model = AutoModelForCausalLM.from_pretrained(
        str(MODEL_PATH), torch_dtype=torch.bfloat16, device_map='cuda')
    model.eval()

    budget = Budget(phase=PHASE)
    journal = FOLDER / 'predictions.jsonl'
    done = set()
    if journal.exists():
        done = {json.loads(s)['id'] for s in journal.read_text().splitlines()}
    order = [('sanity', i) for i in selection['sanity_ids']] + \
            [('bank', i) for i in selection['ids']]
    labels = load_gold()
    try:
        for role, cid in order:
            if cid in done:
                continue
            row = load_input('dev', [cid])[0]
            msgs, warnings = case_messages(row)
            enc = tok.apply_chat_template(
                msgs, tokenize=True, add_generation_prompt=True)
            if torch.is_tensor(enc):
                ids = enc
            else:
                ids = torch.as_tensor(enc['input_ids'])
            if ids.dim() == 1:
                ids = ids.unsqueeze(0)
            ids = ids.to(model.device)
            n_in = ids.shape[-1]

            began = time.monotonic()
            probs = None
            p_yes = None
            followed = None
            top5 = None
            score_pos = None
            with torch.inference_mode():
                out = model.generate(ids, attention_mask=torch.ones_like(ids),
                                     max_new_tokens=MAX_NEW_TOKENS, do_sample=False)
                gen_ids = out[0][n_in:].tolist()
                for i in range(len(gen_ids) - 2):
                    if gen_ids[i:i + 3] == SCORE_OPEN_IDS:
                        score_pos = i
                        break
                if score_pos is not None:
                    prefix = torch.cat([ids[0],
                                        torch.tensor(gen_ids[:score_pos + 3], dtype=torch.long,
                                                     device=model.device)]).unsqueeze(0)
                    logits = model(prefix).logits[0, -1]
                    sm = logits.softmax(-1)
                    probs = {s: float(sm[i]) for s, i in SCORE_TOKEN_IDS.items()}
                    py = probs[' yes'] + probs['yes']
                    pn = probs[' no'] + probs['no']
                    p_yes = py / (py + pn) if (py + pn) > 0 else None
                    topv, topi = logits.topk(5)
                    top5 = [[round(float(v), 4), tok.decode([int(i)])]
                            for v, i in zip(topv.tolist(), topi.tolist())]
                    if score_pos + 3 < len(gen_ids):
                        fid = gen_ids[score_pos + 3]
                        followed = {'id': fid, 'text': tok.decode([fid])}
            elapsed = time.monotonic() - began
            text = tok.decode(gen_ids, skip_special_tokens=False)
            parsed = re.search(r'<score>\s*(.*?)\s*</score>', text, re.DOTALL)
            parsed = parsed.group(1).strip().lower() if parsed else None
            gen_decision = 1 if parsed == 'yes' else (0 if parsed == 'no' else None)
            argmax_decision = None if p_yes is None else (1 if p_yes >= PRIMARY_THRESHOLD else 0)
            tokens = n_in + len(gen_ids)
            rid = budget.reserve('modular/granite-native', MODEL_REPO,
                                 sha({'id': cid, 'guardian': GUARDIAN_BLOCK}), tokens, api=False)
            budget.finish(rid, tokens, elapsed, 'NATIVE_COMPLETE')
            append(journal, {
                'id': cid, 'role': role, 'label': labels[cid],
                'prompt_tokens': n_in, 'generated_tokens': len(gen_ids),
                'p_yes': p_yes, 'restricted_probs': probs,
                'top5_logits': top5, 'score_token_followed': followed,
                'generated_text': text[:400],
                'parsed_score': parsed, 'generated_decision': gen_decision,
                'argmax_decision': argmax_decision,
                'logit_parse_agreement': (None if gen_decision is None or argmax_decision is None
                                          else int(gen_decision == argmax_decision)),
                'score_tag_found': score_pos is not None,
                'parse_warnings': warnings, 'elapsed_seconds': round(elapsed, 3),
                'peak_vram_bytes': int(torch.cuda.max_memory_allocated()),
                'model_revision': MODEL_REVISION, 'status': 'NATIVE_COMPLETE'})
            print(cid, role, 'p_yes=', p_yes, 'parsed=', parsed, flush=True)
        finalize(selection, labels)
    except Exception as exc:
        write(FOLDER / 'status.json', {'state': 'FAILED', 'error_type': type(exc).__name__,
                                       'error': str(exc)[:300]})
        raise


def finalize(selection, labels):
    journal = FOLDER / 'predictions.jsonl'
    rows = [json.loads(s) for s in journal.read_text().splitlines()]
    bank = [r for r in rows if r['role'] == 'bank' and r.get('p_yes') is not None]
    missing = [i for i in list(selection['sanity_ids']) + list(selection['ids'])
               if i not in {r['id'] for r in rows}]
    if missing:
        write(FOLDER / 'status.json', {'state': 'INCOMPLETE', 'missing': missing})
        return

    def metrics(pred):
        tp = sum(1 for r in bank if pred(r) == 1 and r['label'] == 1)
        fp = sum(1 for r in bank if pred(r) == 1 and r['label'] == 0)
        fn = sum(1 for r in bank if pred(r) == 0 and r['label'] == 1)
        tn = sum(1 for r in bank if pred(r) == 0 and r['label'] == 0)
        p = tp / (tp + fp) if tp + fp else 0.0
        rec = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * p * rec / (p + rec) if p + rec else 0.0
        return {'tp': tp, 'fp': fp, 'fn': fn, 'tn': tn, 'precision': round(p, 4),
                'recall': round(rec, 4), 'f1': round(f1, 4)}

    at_half = {r['id']: 1 if r['p_yes'] >= PRIMARY_THRESHOLD else 0 for r in bank}
    m_half = metrics(lambda r: at_half[r['id']])
    values = sorted({r['p_yes'] for r in bank})
    cands = sorted({(values[i] + values[i + 1]) / 2 for i in range(len(values) - 1)}
                   | {PRIMARY_THRESHOLD})
    scored = []
    for t in cands:
        mm = metrics(lambda r, t=t: 1 if r['p_yes'] >= t else 0)
        scored.append((mm['f1'], -abs(t - PRIMARY_THRESHOLD), -t, t, mm))
    scored.sort(reverse=True)
    frozen_t = scored[0][3]
    m_frozen = metrics(lambda r, t=frozen_t: 1 if r['p_yes'] >= t else 0)
    dist = {
        'label_1_p_yes': [round(r['p_yes'], 4) for r in sorted(bank, key=lambda r: r['id']) if r['label'] == 1],
        'label_0_p_yes': [round(r['p_yes'], 4) for r in sorted(bank, key=lambda r: r['id']) if r['label'] == 0],
    }
    sanity = [r for r in rows if r['role'] == 'sanity']
    agreement = [r['logit_parse_agreement'] for r in bank]
    report = {
        'schema': 'granite-native-score/1',
        'n_bank': len(bank), 'n_sanity': len(sanity),
        'sanity_contract': [{'id': r['id'], 'label': r['label'], 'p_yes': r['p_yes'],
                              'parsed': r['parsed_score'],
                              'score_tag_found': r['score_tag_found']} for r in sanity],
        'metrics_at_pre_registered_0_5': m_half,
        'frozen_threshold': frozen_t,
        'frozen_threshold_selection': THRESHOLD_RULE,
        'metrics_at_frozen_threshold': m_frozen,
        'logit_vs_generated_agreement': {'n': len([a for a in agreement if a is not None]),
                                          'agree': sum(1 for a in agreement if a == 1)},
        'score_distribution': dist,
        'gpu_seconds_total': round(sum(r['elapsed_seconds'] for r in rows), 1),
        'tokens_total': sum(r['prompt_tokens'] + r['generated_tokens'] for r in rows),
        'budget': budget_snapshot_safe(),
        'disclosure': ('threshold selected ON the dev bank (in-sample) and frozen '
                       'for downstream; primary pre-registered 0.5 also reported; '
                       'author gold PENDING human review'),
    }
    write(FOLDER / 'score_report.json', report)
    write(FOLDER / 'status.json', {'state': 'COMPLETED', 'bank': len(bank),
                                   'sanity': len(sanity),
                                   'frozen_threshold': frozen_t})
    print(json.dumps({'state': 'COMPLETED', 'at_0.5': m_half,
                      'frozen_threshold': frozen_t, 'at_frozen': m_frozen}))


def budget_snapshot_safe():
    try:
        return Budget(phase=PHASE).snapshot()
    except Exception as exc:
        return {'error': str(exc)[:200]}


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--prepare', action='store_true')
    ap.add_argument('--run', action='store_true')
    a = ap.parse_args()
    if a.prepare:
        prepare()
    elif a.run:
        run()
    else:
        ap.error('choose --prepare or --run')
