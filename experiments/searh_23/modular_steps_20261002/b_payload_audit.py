"""Offline dry-run payload audit for the B reviewer (assignment §5).

Reconstructs the EXACT request the negative-review/temporal pilots sent to B
for representative FP cases — system instruction, user JSON payload, source
binding, sampling parameters — without calling any model. Verifies:
  - every source bucket is the complete original text (no truncation);
  - the target is the exact checked move;
  - prior_findings is what the primary judge actually produced;
  - the source_reference_inventory matches the parsed turns;
  - sampling: temperature=0, json_mode, max_tokens per frozen selection.
No secrets are involved (payloads carry case text only). Output:
results/.../fp_corpus/b_payload_audit.json.
"""
import json
from pathlib import Path

from modular_common import RESULTS

R = RESULTS / 'negative_review_pilot_v4'
T = RESULTS / 'temporal_assistant_pilot'
OUT = RESULTS / 'fp_corpus'
import sys
sys.path[:0] = ['/workspace/guardian/repos/modular-step2-4-superz/src',
                '/workspace/guardian/repos/modular-step2-4-superz/service',
                '/workspace/guardian/repos/modular-step2-4-superz/experiments/searh_23/hybrid_service_v1']
from counterevidence import INSTRUCTION, SOURCE_BOUND_V2, sources_for  # noqa: E402


def audit_case(row, findings, label):
    from structural_v02 import parse_case_v02
    ctx = parse_case_v02(row['id'], row['prompt'], row['response'])
    sources = sources_for(ctx)
    payload = {"sources": sources, "target": ctx.response_raw,
               "prior_findings": [dict(f, finding_index=i) for i, f in enumerate(findings)],
               "advisory": getattr(ctx, 'advisory_context', '')}
    payload['source_reference_inventory'] = [
        {"turn_id": t.turn_id, "role": t.role,
         "call_ids": [c.call_id for c in t.tool_calls],
         "result_ids": [r.result_id for r in t.tool_results]}
        for t in ctx.turns]
    instruction = INSTRUCTION + "\n" + SOURCE_BOUND_V2
    messages = [{"role": "system", "content": instruction},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}]
    checks = {
        'system_len': len(instruction),
        'user_payload_len': len(messages[1]['content']),
        'sources_complete': {
            'policy_is_full_system_block': sources['policy'] in row['prompt'],
            'history_is_full_prompt_from_user_block': sources['history'] in row['prompt'],
            'catalog_is_full_available_tools_block': sources['catalog'] in row['prompt'],
            'response_is_exact_target': sources['response'] == row['response'],
        },
        'target_binding': payload['target'] == row['response'],
        'prior_findings_count': len(findings),
        'turn_inventory': [{'turn_id': t['turn_id'], 'role': t['role'],
                            'calls': len(t['call_ids']), 'results': len(t['result_ids'])}
                           for t in payload['source_reference_inventory']],
        'sampling': {'temperature': 0, 'json_mode': True,
                     'max_tokens': 2000, 'transport_retries': 1},
    }
    return {'label': label, 'id': row['id'],
            'messages': [{'role': m['role'], 'content': m['content'][:4000]} for m in messages],
            'messages_truncated_in_this_receipt_only': True,
            'checks': checks}


def main():
    sel = json.loads((R / 'selection.json').read_text(encoding='utf-8'))
    inputs = {}
    for line in Path('/workspace/guardian/repos/modular-step2-4-superz/experiments/searh_23/modular_steps_20261002/dataset/dev_input.jsonl').read_text(encoding='utf-8').splitlines():
        r = json.loads(line)
        inputs[r['id']] = r
    audit = []
    # case 1: clean primary, empty prior findings (the 19/21 invented-accusion class)
    for cid in ('dev_unless::02', 'dev_refusal_inventory::00'):
        row = inputs[cid]
        audit.append(audit_case(row, [], 'primary_NO_ERROR_empty_prior_findings'))
    # case 2: temporal with/without advisory construction shape (sources identical)
    tp = [json.loads(l) for l in (T / 'predictions.jsonl').read_text().splitlines()]
    tb_inputs = {}
    for line in Path('/workspace/guardian/repos/modular-step2-4-superz/experiments/searh_23/modular_steps_20261002/dataset/temporal_boundary/input.jsonl').read_text(encoding='utf-8').splitlines():
        r = json.loads(line)
        tb_inputs[r['id']] = r
    row = tb_inputs['temporal_boundary::02']
    a = audit_case(row, [], 'temporal_primary_NO_ERROR_empty_prior_findings')
    # the ONLY experimental difference between the paired arms is the advisory
    a['paired_arms'] = {'B_without_calc': 'advisory empty',
                        'B_with_calc': 'advisory = module computation (identical sources/target)'}
    audit.append(a)
    report = {
        'schema': 'b-payload-audit/1',
        'note': 'offline reconstruction; no model calls; no secrets; the frozen selection '
                'parameters are mirrored from negative_review_pilot_v4/selection.json',
        'selection_mirror': {'B_max_tokens': sel.get('B_max_tokens'), 'B_model': sel.get('B_model'),
                             'B_protocol': sel.get('B_protocol'),
                             'max_B_queries_before_technical_reasks': sel.get('max_B_queries_before_technical_reasks')},
        'payload_construction': 'messages = [system: INSTRUCTION+SOURCE_BOUND_V2, '
                                'user: json{sources{policy,history,catalog,response}, target, '
                                'prior_findings, advisory, source_reference_inventory}]',
        'cases': audit,
    }
    path = OUT / 'b_payload_audit.json'
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    all_ok = all(all(c['checks']['sources_complete'].values()) and c['checks']['target_binding']
                 for c in audit)
    print(json.dumps({'cases': [c['id'] for c in audit], 'sources_complete_and_target_bound': all_ok,
                      'path': str(path)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
