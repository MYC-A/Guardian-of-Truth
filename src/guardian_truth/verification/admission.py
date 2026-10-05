"""Admission v2 for the frozen I4 reply (offline ablation of the receipt-actor contract, summary §3.3).

v1 rejects a whole reply when an evidence item's actor differs from the packet role; tool results are
packet role 'assistant' and models often label them 'system'. v2 accepts, for evidence citing a TOOL
RESULT record only, actor in {assistant, system, unknown} and records ACTOR_NORMALISED. Every other check
is identical to v1 (reviewer.admit). The request is unchanged, so v2 is replayable from cache."""
from __future__ import annotations

from ..integrated import reviewer
from ..integrated.reviewer import Reply, decode_reply, sources

TOOL_RESULT_ACTORS = {'assistant', 'system', 'unknown'}


def admit_v2(value, packet):
    value = Reply.model_validate(value).model_dump()
    ss = sources(packet)
    notes = []
    for e in value['supporting_evidence']:
        src = ss.get(e['source_id'])
        if src is not None and src.get('kind') == 'result' and e['actor'] != src.get('role') and e['actor'] in TOOL_RESULT_ACTORS:
            notes.append(e['source_id'])
    fixed = dict(value, supporting_evidence=[dict(e, actor=ss[e['source_id']]['role']) if e['source_id'] in notes else e
                                            for e in value['supporting_evidence']])
    return reviewer.admit(fixed, packet), notes


def interpret_v2(content, packet):
    value, valid, norm = decode_reply(content)
    out = dict(parsed=value if valid else None, normalization=norm,
               raw_decision=value.get('decision') if valid and isinstance(value, dict) else None, actor_normalised=[])
    if content is None:
        out.update(admission='TRANSPORT_FAILURE', admitted=None)
    elif not valid:
        out.update(admission='INVALID_JSON', admitted=None)
    else:
        try:
            a, notes = admit_v2(value, packet)
            out.update(admitted=a, admission='ADMITTED', actor_normalised=notes)
        except Exception as e:
            out.update(admitted=None, admission=f'REJECTED:{type(e).__name__}:{e}'[:160])
    out['decision'] = (out['admitted'] or {}).get('decision')
    return out
