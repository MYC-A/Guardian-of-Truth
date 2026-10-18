"""Review phase of judge_stage (opt-in, review_mode != off).

Default: after all primary rows. Opt-in per_chunk: after each durable primary portion.

Per chunk: [prepass generate -> validate -> durable prepass records] -> final scoring -> durable final records.
The engine, tokenizer, score params, generate_rows and answer_score are the stage's own objects, injected so
that this module is testable with a fake engine and never builds a second supervisor or scoring path.
Records: {"key", "review": "prepass"|"final", "arm", ...}; the event {"event": "review_done"} closes the phase.
Primary records are never rewritten. No new model call starts at or after stop_at.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import json
import os
from pathlib import Path
import time
from typing import Any, Callable

from guardian_truth.judge import blind_review as br
from guardian_truth.judge.prompting import count_tokens


@dataclass
class ReviewContext:
    llm: Any
    tok: Any
    rows: list
    order: list
    settings: dict
    score_params: Any
    gen_params: Any
    yes_ids: set
    no_ids: set
    answer_score: Callable
    generate_rows: Callable
    healthy: Callable
    emit: Callable
    stop_at: float
    hard_cap: int
    prepass_cap: int
    chunk: int
    log: Callable
    usage: Callable
    primary_seconds_per_row: float
    primary_inputs: Any = None
    clock: Callable = time.time
    timing: Any = None
    primary_tokens_per_row: float = 1.0
    defer_on_budget: bool = False


def _err(error):
    return ('%s: %s' % (type(error).__name__, error))[:300]


def merge_review_stats(parts, required, settings):
    """Combine disjoint per-chunk receipts; unknown cache counters stay unavailable."""
    out = dict(arm=settings['review_mode'], content=settings['review_content'],
               schedule='per_chunk', required=required, portions=len(parts))
    for name in ('prepass_attempted', 'notes_empty', 'delivered_empty', 'final_exact', 'final_inexact',
                 'final_missing', 'final_deadline', 'final_row_errors', 'prepass_transcript_trimmed',
                 'prepass_response_trimmed'):
        out[name] = sum(p.get(name, 0) for p in parts)
    for name in ('prepass_status', 'delivery', 'base_modes'):
        counts = Counter()
        for part in parts:
            counts.update(part.get(name, {}))
        out[name] = dict(counts)
    for name in ('prepass', 'final'):
        reports = [p[name] for p in parts if name in p]
        report = {k: sum(r[k] for r in reports) for k in ('prompts', 'prompt_tokens', 'generated_tokens', 'wall_seconds')}
        known = bool(reports) and all(isinstance(r['cached_tokens'], int) for r in reports)
        report['cached_tokens'] = sum(r['cached_tokens'] for r in reports) if known else 'unavailable'
        report['uncached_tokens'] = report['prompt_tokens'] - report['cached_tokens'] if known else 'unavailable'
        report['cache_hit'] = (round(report['cached_tokens'] / report['prompt_tokens'], 4)
                               if known and report['prompt_tokens'] else 'unavailable')
        out[name] = report
    out['review_complete'] = out['final_exact'] == required
    out['unattempted_rows'] = max(0, required - sum(p['required'] for p in parts))
    return out


class PrimaryInputs:
    """Run-local, durable snapshots of actual primary inputs; only byte offsets live in RAM.

    This is an audit spool, not a cross-run result cache. Reads verify the run, input file,
    position, row content and actual rendered input before the final can use it.
    """

    def __init__(self, path, run_id, input_sha256):
        self.path, self.run_id, self.input_sha256 = Path(path), run_id, input_sha256
        self.stream = self.path.open('xb')
        self.offsets = {}

    @staticmethod
    def row_sha(row):
        return br.sha(json.dumps([row['prompt'], row['response']], ensure_ascii=False))

    def put(self, row, text, tok, cap, trimmed, policy_trimmed):
        key = row['key']
        if key in self.offsets:
            raise ValueError('DUPLICATE_PRIMARY_INPUT')
        record = dict(schema='primary-input-v1', run_id=self.run_id, input_sha256=self.input_sha256,
                      key=key, row_sha256=self.row_sha(row), text=text, model_input_sha256=br.sha(text),
                      input_token_sha256=br.token_sha(tok, text), cap=cap,
                      trimmed=bool(trimmed), policy_trimmed=bool(policy_trimmed))
        offset = self.stream.tell()
        self.stream.write((json.dumps(record, ensure_ascii=False, allow_nan=False) + '\n').encode('utf-8'))
        self.offsets[key] = offset
        return {k: record[k] for k in ('model_input_sha256', 'input_token_sha256', 'row_sha256')}

    def flush(self):
        self.stream.flush()
        os.fsync(self.stream.fileno())

    def get(self, row, tok):
        offset = self.offsets.get(row['key'])
        if offset is None:
            raise ValueError('PRIMARY_INPUT_UNAVAILABLE')
        with self.path.open('rb') as source:
            source.seek(offset)
            line = source.readline()
        if not line.endswith(b'\n'):
            raise ValueError('PRIMARY_INPUT_INTERRUPTED')
        record = json.loads(line)
        if (record.get('schema') != 'primary-input-v1' or record.get('run_id') != self.run_id
                or record.get('input_sha256') != self.input_sha256 or record.get('key') != row['key']
                or record.get('row_sha256') != self.row_sha(row)
                or record.get('model_input_sha256') != br.sha(record.get('text'))
                or record.get('input_token_sha256') != br.token_sha(tok, record.get('text'))):
            raise ValueError('PRIMARY_INPUT_INTEGRITY')
        return record

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.stream.close()


def final_base(ctx, row):
    """The exact input used by primary, including its actual adaptive trimming and hints.

    No second build_prompt call is allowed. If checklist cannot fit, final_prompt fails
    this row explicitly; notes never displace source context.
    """
    if ctx.primary_inputs is None:
        raise ValueError('PRIMARY_INPUT_UNAVAILABLE')
    source = ctx.primary_inputs.get(row, ctx.tok)
    text = source['text']
    return (text, count_tokens(ctx.tok, text), source['trimmed'], source['policy_trimmed'], 'saved_primary')


def run_review(ctx):
    s, mode = ctx.settings, ctx.settings['review_mode']
    if mode == 'off':
        return None
    pre_use, fin_use = ctx.usage(), ctx.usage()
    gen, delivery, finals = Counter(), Counter(), Counter()
    audit = s.get('review_content') == 'answer_audit'
    if audit:
        from guardian_truth.judge import answer_review
    stats = dict(arm=mode, rows=len(ctx.order), required=len(ctx.order), prepass_attempted=0, notes_empty=0,
                 delivered_empty=0, final_exact=0, final_inexact=0, final_missing=0, final_deadline=0,
                 final_row_errors=0, prepass_transcript_trimmed=0, prepass_response_trimmed=0,
                 hard_cap=ctx.hard_cap, prepass_cap=ctx.prepass_cap, base_modes=Counter(), deferred_rows=0)
    position = 0
    while position < len(ctx.order):
        batch = ctx.order[position:position + ctx.chunk]
        per_row = ((pre_use.wall / pre_use.prompts if pre_use.prompts else 0.0) +
                   (fin_use.wall / fin_use.prompts if fin_use.prompts else 0.0))
        if not fin_use.prompts:  # pessimistic before the first measurement
            per_row = ctx.primary_seconds_per_row * (3.0 if mode in br.PREPASS_MODES else 1.2)
        need = per_row * len(batch)
        prepared_audit = {}
        if audit:
            final_tokens = 0
            for i in batch:
                try:
                    saved = ctx.primary_inputs.get(ctx.rows[i], ctx.tok)
                    final_tokens += count_tokens(ctx.tok, saved['text']) + s['notes_max_tokens']
                    prepared_audit[i] = answer_review.prepare(ctx.tok, saved, s, ctx.prepass_cap)
                except Exception:
                    pass  # the normal row path records the specific build error
            pre_tokens = sum(p['n'] for p in prepared_audit.values())
            measured = ctx.timing or {}
            if all(measured.get(role, {}).get('prompts') for role in ('prepass', 'final')):
                # Conservative projection from real input/output counts and wall.
                # Charging each component the observed wall avoids assuming free APC.
                need = 0.0
                for role, inputs, outputs in (('prepass', pre_tokens, len(batch)*s['prepass_max_tokens']),
                                              ('final', final_tokens, len(batch))):
                    r = measured[role]
                    need += r['wall_seconds'] * (inputs/max(r['prompt_tokens'],1)
                                                  + outputs/max(r['generated_tokens'],1))
            else:
                # Initial prior only. No actual decode-speed measurement exists yet.
                need *= max(1.0, (pre_tokens + final_tokens) / max(
                    2.0 * len(batch) * ctx.primary_tokens_per_row, 1.0))
            ctx.log('review_projection', input_tokens=pre_tokens+final_tokens,
                    reserved_output_tokens=len(batch)*(s['prepass_max_tokens']+1),
                    projected_seconds=round(need*1.15,2), measured=bool(measured))
        if ctx.clock() + need * 1.15 >= ctx.stop_at - 10:
            rest = ctx.order[position:]
            if ctx.defer_on_budget:
                stats['deferred_rows'] += len(rest)
                break
            stats['final_deadline'] += len(rest)
            ctx.emit([dict(key=ctx.rows[i]['key'], review='final', arm=mode, final_score=None, exact=False,
                           error='DEADLINE') for i in rest])
            ctx.log('review_deadline', remaining=len(rest))
            break
        notes = {}
        if mode in br.PREPASS_MODES:
            records, prompts, metas = [], [], []
            for i in batch:
                row = ctx.rows[i]
                stats['prepass_attempted'] += 1
                try:
                    if audit:
                        pre = prepared_audit.get(i)
                        if pre is None:
                            saved = ctx.primary_inputs.get(row, ctx.tok)
                            pre = answer_review.prepare(ctx.tok, saved, s, ctx.prepass_cap)
                        text, n, rtrim = pre['text'], pre['n'], row['response'] not in pre['source']
                    else:
                        pre = br.prepass_transcript(ctx.tok, row['prompt'], s, ctx.prepass_cap)
                        text, n, rtrim = br.prepass_prompt(ctx.tok, pre, row['response'] if mode == 'open' else None, s)
                    if n + s['prepass_max_tokens'] > ctx.prepass_cap:
                        raise ValueError('PREPASS_TOO_LONG')
                except Exception as error:  # noqa: BLE001 - this row only
                    gen['ERROR'] += 1
                    records.append(dict(key=row['key'], review='prepass', arm=mode, status='ERROR',
                                        error='PREPASS_BUILD_ERROR', detail=_err(error)))
                    continue
                stats['prepass_transcript_trimmed'] += pre['trimmed']
                stats['prepass_response_trimmed'] += rtrim
                prompts.append(text)
                metas.append((i, pre, text, n, rtrim))
            if prompts:
                t0 = ctx.clock()
                outputs, batch_error = ctx.generate_rows(ctx.llm, prompts, ctx.gen_params, ctx.stop_at, ctx.healthy)
                pre_use.add([o for o in outputs if not isinstance(o, Exception)], ctx.clock() - t0)
                if batch_error is not None:
                    ctx.log('prepass_chunk_error', error=_err(batch_error))
                for (i, pre, text, n, rtrim), o in zip(metas, outputs):
                    base = dict(key=ctx.rows[i]['key'], review='prepass', arm=mode,
                                version=answer_review.VERSION if audit else br.VERSION, tokens=n,
                                input_sha256=br.sha(text), input_token_sha256=br.token_sha(ctx.tok, text),
                                source_sha256=br.sha(pre['source']), units=len(pre['units']),
                                transcript_trimmed=pre['trimmed'], response_trimmed=rtrim)
                    if isinstance(o, Exception):
                        gen['ERROR'] += 1
                        records.append(dict(base, status='ERROR', error=type(o).__name__, detail=_err(o)))
                        continue
                    try:
                        sample = o.outputs[0]
                        parser = answer_review.parse_notes if audit else br.parse_notes
                        status, parsed, report = parser(sample.text, sample.finish_reason, br.citable(pre['units']), s)
                        generated_tokens = len(sample.token_ids or [])
                    except Exception as error:  # a malformed output must cost only its own row
                        gen['ERROR'] += 1
                        records.append(dict(base, status='ERROR', error='PREPASS_OUTPUT_ERROR', detail=_err(error)))
                        continue
                    gen[status] += 1
                    stats['notes_empty'] += bool(report.get('empty'))
                    records.append(dict(base, status=status, finish_reason=sample.finish_reason,
                                        generated_tokens=generated_tokens, raw=sample.text,
                                        notes=parsed, report=report))
                    if status == 'VALID':
                        notes[i] = (parsed, pre, bool(report.get('empty')))
            ctx.emit(records)
        records, prompts, metas = [], [], []
        for i in batch:
            row = ctx.rows[i]
            try:
                base_text, base_n, trimmed, policy_trimmed, base_mode = final_base(ctx, row)
                block, reason = '', ('NO_PREPASS' if mode == 'none' else 'NOTES_NOT_VALID')
                if i in notes:
                    renderer = answer_review.render_notes if audit else br.render_notes
                    block = renderer(notes[i][0], notes[i][1], s)
                    if count_tokens(ctx.tok, block) > s['notes_max_tokens']:
                        block, reason = '', 'NOTES_OVER_ALLOWANCE'
                        state = 'DROPPED_SIZE'
                    else:
                        state = None
                else:
                    state = 'NOT_DELIVERED'
                text, n, delivered, why = br.final_prompt(ctx.tok, base_text, block, ctx.hard_cap)
                delivered = state or delivered
                reason = why or (None if delivered == 'DELIVERED' else reason)
            except Exception as error:  # noqa: BLE001 - this row only
                stats['final_row_errors'] += 1
                records.append(dict(key=row['key'], review='final', arm=mode, final_score=None, exact=False,
                                    error='FINAL_BUILD_ERROR', detail=_err(error)))
                delivery['NOT_DELIVERED'] += 1
                continue
            prompts.append(text)
            stats['base_modes'][base_mode] += 1
            metas.append((i, text, n, delivered, reason, base_text, trimmed, policy_trimmed, base_mode))
        if prompts:
            t0 = ctx.clock()
            outputs, batch_error = ctx.generate_rows(ctx.llm, prompts, ctx.score_params, ctx.stop_at, ctx.healthy)
            fin_use.add([o for o in outputs if not isinstance(o, Exception)], ctx.clock() - t0)
            if batch_error is not None:
                ctx.log('final_chunk_error', error=_err(batch_error))
            for (i, text, n, delivered, reason, base_text, trimmed, policy_trimmed, base_mode), o in zip(metas, outputs):
                rec = dict(key=ctx.rows[i]['key'], review='final', arm=mode, tokens=n, delivery=delivered,
                           delivery_reason=reason, input_sha256=br.sha(text), base_sha256=br.sha(base_text),
                           input_token_sha256=br.token_sha(ctx.tok, text),
                           base_mode=base_mode, context_trimmed=bool(trimmed), policy_trimmed=bool(policy_trimmed),
                           response_trimmed=ctx.rows[i]['response'] not in text)
                if isinstance(o, Exception):
                    late = type(o).__name__ == 'RowDeadline'
                    stats['final_deadline' if late else 'final_row_errors'] += 1
                    delivery['NOT_DELIVERED'] += 1
                    rec.update(delivery='NOT_DELIVERED', delivery_reason='MODEL_OUTPUT_UNAVAILABLE')
                    records.append(dict(rec, final_score=None, exact=False,
                                        error='DEADLINE' if late else 'GENERATE_ERROR', detail=_err(o)))
                    continue
                delivery[delivered] += 1
                stats['delivered_empty'] += bool(delivered == 'DELIVERED' and notes[i][2])
                try:
                    score, exact = ctx.answer_score(o, ctx.yes_ids, ctx.no_ids)
                    if score is not None and not br._finite(score):
                        raise ValueError('NON_FINITE_SCORE')
                except Exception as error:  # a malformed score must not discard the rest of the chunk
                    stats['final_row_errors'] += 1
                    records.append(dict(rec, final_score=None, exact=False, error='FINAL_SCORE_ERROR', detail=_err(error)))
                    continue
                if score is None:
                    stats['final_missing'] += 1
                    records.append(dict(rec, final_score=None, exact=False))
                elif exact is not True:
                    stats['final_inexact'] += 1
                    records.append(dict(rec, final_score=None, bounded_score=score, exact=False, error='INEXACT_SCORE'))
                else:
                    stats['final_exact'] += 1
                    records.append(dict(rec, final_score=score, exact=True))
        ctx.emit(records)
        position += len(batch)
        ctx.log('review_chunk', done=position, of=len(ctx.order), arm=mode)
    stats['base_modes'] = dict(stats['base_modes'])
    stats.update(prepass_status=dict(gen), delivery=dict(delivery), prepass=pre_use.report(), final=fin_use.report(),
                 review_complete=stats['final_exact'] == len(ctx.order))
    if ctx.timing is not None:
        for role in ('prepass', 'final'):
            values = ctx.timing.setdefault(role, dict(prompts=0,prompt_tokens=0,generated_tokens=0,wall_seconds=0.0))
            for key in values:
                values[key] += stats[role][key]
    stats['truncation_rate_attempted'] = (round(gen['TRUNCATED'] / stats['prepass_attempted'], 4)
                                          if stats['prepass_attempted'] else None)
    ctx.emit([dict(event='review_done', **stats)])
    ctx.log('review_done', **stats)
    return stats
