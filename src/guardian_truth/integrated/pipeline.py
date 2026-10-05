"""Single public entry point:  review(prompt, response, config, client) -> ReviewResult (dict).

Execution graph (one SourceStore per trajectory, all current targets always enumerated):
  SourceStore + native inventory (framing diagnostics kept as gaps)
    -> declaration guard over EVERY current call (code-only, MECHANICAL_PROOF or gaps)
    -> corrected U2 packet (budgeted; resolve() verifies exact spans and inventory)
    -> [relations] deterministic scoped SOURCE_OBSERVATION facts + their exact cited spans
    -> direct reviewer (I4 decision-last, MODEL_HYPOTHESIS, code admission)
    -> [controller] at most ONE conditional verification pass (frozen trigger, below)
    -> ledger (every step with request sha, admission, usage) -> final decision -> binary projection

Authority: a mechanical guard finding is the only code-proven ERROR. Model decisions are hypotheses;
NO_ERROR is never certified by code. UNKNOWN and technical nulls project to binary 0 and are reported
separately (projection field). Labels/row IDs are never inputs.

Controller trigger (frozen before inference): first review ADMITTED and
  (a) decision UNKNOWN, or (b) decision NO_ERROR while decisive relation facts exist.
Technical failures never trigger it (no hidden retry). Final = verification decision if admitted,
else the first decision (fallback recorded).
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass

from ..evidence_packer import PackerConfig, pack, resolve
from ..source_search.store import SourceStore
from . import declarations, relations, reviewer
from .transport import sha

VERSION = 'guardian-integrated-v1'
EXTRA_SOURCE_BYTES = 8000
EXCERPT_RADIUS = 400
PROFILES = {
    'baseline': dict(guard=False, relations=False, controller=False, admission='v1'),
    'guard': dict(guard=True, relations=False, controller=False, admission='v1'),        # frozen A2 (integrated v1)
    'relations': dict(guard=True, relations=True, controller=False, admission='v1'),
    # FAILED experimental profiles (kept for reproducibility only; never the default):
    'integrated': dict(guard=True, relations=True, controller=True, admission='v1'),
    # SHADOW / post-hoc, development-only. Amendment 2 (post-hoc, designed after valid46 results): relation facts are sent only when at
    # least one decisive fact exists; otherwise the request is byte-identical to the baseline request.
    'integrated_gated': dict(guard=True, relations=True, controller=True, relation_gate=True, admission='v1'),
    # RECOMMENDED DEFAULT (verification v2, pre-registered rule 1 passed on lockbox LB2): 'guard' + admission v2
    # (tool-result evidence actor in {assistant, system, unknown} accepted and normalised; same request bytes, so
    # replayable from cache). See docs/verification_v2/FINAL_DECISION.md.
    'guard_adm2': dict(guard=True, relations=False, controller=False, admission='v2'),
}


@dataclass(frozen=True)
class ReviewConfig:
    provider: str = 'mistral'
    model: str = 'ministral-14b-2512'
    budget_bytes: int | None = 20000
    guard: bool = True             # defaults == PROFILES['guard_adm2'] (recommended); 'guard' = frozen A2 with admission v1
    relations: bool = False        # 'relations'/'integrated' are FAILED experimental profiles (valid46 F1 ~0.49)
    controller: bool = False
    relation_gate: bool = False    # True: send relation facts only if a decisive fact exists (amendment 2)
    admission: str = 'v2'          # 'v2' = verification-v2 receipt-actor normalisation; 'v1' = integrated-v1 contract
    attempt: int = 0               # repetition index (part of the cache key); fixed in the protocol
    max_tokens: int = 1700

    @classmethod
    def profile(cls, name, **kw):
        return cls(**{**PROFILES[name], **kw})


def _framing_gaps(store):
    out = []
    for doc, events in (('prompt', store.history_events), ('response', store.target_events)):
        for i, e in enumerate(events):
            for d in e.diagnostics:
                out.append(dict(code=d, origin='PARSER', source_id=('h' if doc == 'prompt' else 't') + str(i)))
    return out


def _extra_records(store, rel, present):
    """Exact original spans cited by relation facts that the packet does not already contain."""
    out, used, seen = [], 0, set(present)
    for ref in rel['source_refs']:
        sid = ref['source_id']
        if sid in seen:
            continue
        doc, start, end = ref['document'], ref['start'], ref['end']
        text = store.raw[doc][start:end]
        if len(text.encode()) > 2500:
            fact = next(f for f in rel['facts'] if ref in [f.get(k) for k in ('first', 'last', 'receipt', 'earlier_call', 'earlier_receipt')])
            value = fact.get('value')
            pos = text.find(value) if value else 0
            pos = max(pos, 0)
            a, b = max(0, pos - EXCERPT_RADIUS), min(len(text), pos + EXCERPT_RADIUS)
            start, end = start + a, start + b
            text = store.raw[doc][start:end]
            sid = f'x{ref["source_id"]}_{start}'
            if sid in seen:
                continue
        size = len(text.encode())
        if used + size > EXTRA_SOURCE_BYTES:
            break
        used += size
        seen.add(sid)
        event = int(ref['source_id'][1:])
        out.append(dict(source_id=sid, role=ref['role'], kind=ref['kind'], tool=ref['tool'], event=event, text=text,
                        document=doc, start=start, end=end, origin='RELATION_CITED_SPAN'))
    return out


def _fact_view(rel, id_map):
    view = []
    for f in rel['facts']:
        v = {k: f[k] for k in ('fact_id', 'kind', 'status', 'relation', 'decisive', 'target_id', 'tool', 'path', 'value',
                               'observed_in', 'events_before_move', 'same_tool_as_current_call', 'earlier_receipt_status', 'note') if k in f}
        for key in ('first', 'last', 'receipt', 'earlier_call', 'earlier_receipt'):
            if f.get(key):
                v[key + '_source_id'] = id_map.get(f[key]['source_id'], f[key]['source_id'])
        view.append(v)
    return view


def _step(client, request, packet, cfg, tag):
    t = time.time()
    rec = client.call(request, attempt=cfg.attempt, tag=tag)
    step = dict(tag=tag, request_sha256=sha(request), key=rec.get('key'), cached=rec.get('cached'),
                usage=rec.get('usage'), transport=rec.get('transport'), finish_reason=rec.get('finish_reason'),
                response_model=rec.get('response_model'), seconds=rec.get('seconds', round(time.time() - t, 3)),
                request_bytes=len(json.dumps(request, ensure_ascii=False).encode()), raw_content=rec.get('content'))
    if cfg.admission == 'v2':
        from ..verification.admission import interpret_v2      # lazy: verification imports integrated
        step.update(interpret_v2(rec.get('content'), packet))
    elif cfg.admission == 'v1':
        step.update(reviewer.interpret(rec.get('content'), packet))
    else:
        raise ValueError(f'unknown admission {cfg.admission!r}')
    return step


def review(prompt, response, config=ReviewConfig(), client=None):
    t0 = time.time()
    row = dict(prompt=prompt, response=response)
    store = SourceStore(row)
    gaps = _framing_gaps(store)
    guard = declarations.check(row)
    gaps += [dict(g, origin='GUARD') for g in guard['gaps']]
    targets = [dict(target_id=('t' + str(i)), role=e.role, kind=e.kind, tool=e.name, start=e.source.start, end=e.source.end)
               for i, e in enumerate(store.target_events)]
    steps, rel, packet, rp = [], None, None, None
    p = pack(row, PackerConfig(budget_bytes=config.budget_bytes))
    if not p.get('failure'):
        resolve(p, row)                                   # raises on any span / inventory inconsistency
        complete = p.get('mode') == 'FULL_INPUT'
        rp = reviewer.review_packet(p, complete)
        gaps += [dict(code='NOT_READ:' + u['category'], origin='PACKER', detail=u) for u in p.get('uncovered', [])]
    else:
        gaps.append(dict(code='PACKER_FAILURE', origin='PACKER', detail=p['failure']))
    addendum, extra = '', None
    if rp is not None and config.relations:
        rel = relations.compute(store)
    if rel is not None and not (config.relation_gate and not rel['decisive']):
        sent = rel
        if config.relation_gate:                          # decisive facts only (no reassuring confirmations)
            facts = [f for f in rel['facts'] if f['decisive']]
            sent = dict(rel, facts=facts, source_refs=[f[k] for f in facts for k in
                        ('first', 'last', 'receipt', 'earlier_call', 'earlier_receipt') if f.get(k)])
        present = set(reviewer.sources(rp))
        add = _extra_records(store, sent, present)
        if add:
            rp = dict(rp, history=sorted(rp['history'] + reviewer.slim(add), key=lambda r: (r['event'] if r['event'] is not None else -1)))
        id_map = {}
        for r in add:
            id_map.setdefault(f"h{r['event']}", r['source_id'])
        extra = dict(relation_facts=_fact_view(sent, id_map))
        addendum = reviewer.RELATIONS_ADDENDUM
        if rel['truncated']:
            gaps.append(dict(code='RELATION_FACTS_TRUNCATED', origin='RELATIONS'))
    first = final_step = None
    if rp is not None and client is not None:
        missing = 'NO_CURRENT_TARGET' if not rp['current_targets'] else 'NO_POLICY_RETRIEVED' if not rp['normative_sources'] else None
        if missing:
            steps.append(dict(tag='review', admission=f'SKIPPED:{missing}', admitted=None, decision=None))
        else:
            req = reviewer.body(rp, config.provider, config.model, addendum=addendum, extra=extra, max_tokens=config.max_tokens)
            first = final_step = _step(client, req, rp, config, 'review')
            steps.append(first)
            decisive = rel['decisive'] if rel else []
            trigger = None
            if config.controller and first['admission'] == 'ADMITTED':
                if first['decision'] == 'UNKNOWN':
                    trigger = 'FIRST_REVIEW_UNKNOWN'
                elif first['decision'] == 'NO_ERROR' and decisive:
                    trigger = 'NO_ERROR_WITH_DECISIVE_RELATION_FACTS'
            if trigger:
                facts = {f['fact_id']: f for f in extra['relation_facts']} if extra else {}
                checklist = [dict(item=f'relation fact {d}', fact=facts[d]) for d in decisive if d in facts]
                checklist += [dict(item='open question of earlier review', question=q) for q in first['admitted']['open_questions'][:4]]
                prior = {k: first['admitted'][k] for k in ('decision', 'regulated_action', 'applicable_norms', 'reason')}
                req2 = reviewer.body(rp, config.provider, config.model, addendum=addendum + reviewer.CONTROLLER_ADDENDUM,
                                     extra=dict(extra or {}, prior_review=prior, verification_checklist=checklist),
                                     max_tokens=config.max_tokens)
                second = _step(client, req2, rp, config, 'controller')
                second['trigger'] = trigger
                steps.append(second)
                if second['admission'] == 'ADMITTED':
                    final_step = second
                else:
                    first['fallback_after'] = 'controller_' + second['admission']
    elif rp is not None:
        steps.append(dict(tag='review', admission='NOT_EXECUTED:NO_MODEL_CLIENT', admitted=None, decision=None))
    model_decision = final_step['decision'] if final_step else None
    if config.guard and guard['mechanically_established_error']:
        final, proof, owner = 'ERROR', 'MECHANICAL_PROOF', 'guard'
    elif model_decision is not None:
        final, proof, owner = model_decision, 'MODEL_HYPOTHESIS', final_step['tag']
    else:
        final, proof, owner = None, 'NONE', None
    projection = {'ERROR': 'ERROR', 'NO_ERROR': 'NO_ERROR', 'UNKNOWN': 'UNKNOWN_PROJECTED_0', None: 'TECHNICAL_NULL_PROJECTED_0'}[final]
    if final is None and any(str(s.get('admission', '')).startswith(('NOT_EXECUTED', 'SKIPPED')) for s in steps):
        projection = 'NOT_EXECUTED_PROJECTED_0' if client is None else 'SKIPPED_PROJECTED_0'
    reasons = []
    if config.guard:
        reasons += [dict(origin='GUARD', status='MECHANICAL_PROOF', code=f['code'], target_id=f['target_id'], text=f['claim'],
                         source_refs=[r['source_id'] for r in f['source_refs']]) for f in guard['findings']]
    if final_step and final_step.get('admitted'):
        a = final_step['admitted']
        reasons.append(dict(origin=final_step['tag'], status='MODEL_HYPOTHESIS', decision=a['decision'],
                            target_id=a['regulated_action']['target_id'], text=a['reason'],
                            norms=[n['policy_source_id'] for n in a['applicable_norms']],
                            source_refs=[e['source_id'] for e in a['supporting_evidence']]))
        gaps += [dict(code='MODEL_OPEN_QUESTION', origin=final_step['tag'], detail=q) for q in a['open_questions']]
    usage = [s.get('usage') or {} for s in steps]
    return dict(
        version=VERSION, config=asdict(config), source_sha256=store.source_sha256,
        binary=int(final == 'ERROR'), final_decision=final, projection=projection, proof_status=proof,
        decision_owner=owner, model_decision=model_decision,
        first_model_decision=first['decision'] if first else None,
        guard=dict(established_error=guard['mechanically_established_error'], applied=config.guard,
                   findings=guard['findings'], coverage=guard['coverage'], catalog=guard['catalog']),
        relations=rel, checked_targets=targets, reasons=reasons, gaps=gaps,
        source_refs=sorted({r for x in reasons for r in x.get('source_refs', [])}),
        packet=dict(mode=p.get('mode'), budget_bytes=config.budget_bytes, failure=p.get('failure'),
                    sources=len(reviewer.sources(rp)) if rp else 0,
                    packet_sha256=sha(rp) if rp else None),
        steps=[{k: v for k, v in s.items() if k != 'parsed'} for s in steps],
        cost=dict(calls=sum(1 for s in steps if s.get('key')), http_calls=sum(1 for s in steps if s.get('key') and not s.get('cached')),
                  prompt_tokens=sum(u.get('prompt_tokens') or 0 for u in usage),
                  completion_tokens=sum(u.get('completion_tokens') or 0 for u in usage),
                  usage_unknown=sum(1 for s in steps if s.get('key') and not s.get('usage')),
                  model_seconds=round(sum(s.get('seconds') or 0 for s in steps), 2), wall_seconds=round(time.time() - t0, 2)))
