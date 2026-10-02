"""Versioned bank: crucial SYSTEM dependency AND observation move in history.

The additional system instruction is authoritative for the TARGET move and is
explicitly labelled as such. This tests multiple-system-message handling too;
it is not claimed to be the contest's typical single-system-message layout.
"""
import json
from pathlib import Path
from modular_common import sha, write
from build_long_context import tool_result

HERE = Path(__file__).resolve().parent


def make(size, position, error, family):
    response = '→ TOOL_CALL change: {"item_id":"E-70"}'
    head = ('⟦SYSTEM⟧\nchange requires inspected=true AND approved=true for the same item.\n'
            '[AVAILABLE TOOLS]\n- observe — Reads state.\n    item_id: string!\n'
            '- change — Changes item.\n    item_id: string!\n'
            '⟦USER⟧\nChange E-70.\n⟦ASSISTANT⟧\n')
    rule = ('For the target move: emergency=true waives approved, NEVER inspected.\n' if family == 'exception'
            else 'For the target move: no exception. Largest version is current, regardless of arrival.\n')
    observations = (tool_result('E-70', not error, False, True, 3) if family == 'exception'
                    else tool_result('E-70', True, not error, False, 4) + tool_result('E-70', True, error, False, 2))
    dependency = '⟦SYSTEM⟧\n' + rule + '⟦ASSISTANT⟧\n' + observations
    competitors, index = [], 0
    while True:
        block = tool_result('E-' + str(71 + index % 23), bool(index % 2), bool(index % 3), bool(index % 5), index + 1)
        if len(head) + sum(map(len, competitors)) + len(block) + len(dependency) + len(response) > size:
            break
        competitors.append(block)
        index += 1
    assert len(competitors) >= 2
    slot = {'begin': 0, 'middle': len(competitors) // 2, 'end': len(competitors)}[position]
    records = competitors[:slot] + [dependency] + competitors[slot:]
    prompt = head + ''.join(records)
    padding = size - len(prompt) - len(response)
    assert 0 <= padding < 160
    prompt += '\n' * padding
    cid = f'long_v2_{family}_{size}_{position}_' + ('error' if error else 'clean')
    rule_start = prompt.index(rule)
    observation_start = prompt.index(observations)
    gold = {'id': cid, 'author_label': int(error), 'logical_group': 'long_v2/' + family,
            'expected_operational_status': 'UNKNOWN_CONTEXT_LIMIT' if size > 12000 else 'SEMANTIC_CHECK_REQUIRED',
            'policy_dependency_span': {'source_id': 'prompt', 'quote': rule, 'start': rule_start, 'end': rule_start + len(rule)},
            'history_dependency_span': {'source_id': 'prompt', 'quote': observations, 'start': observation_start, 'end': observation_start + len(observations)},
            'policy_relative_position': rule_start / len(prompt), 'observation_relative_position': observation_start / len(prompt),
            'competing_observations': len(competitors), 'padding': padding, 'human_reviewed': False}
    return {'id': cid, 'prompt': prompt, 'response': response}, gold


def main():
    rows = [make(size, position, error, family)
            for size in (1000, 4000, 8000, 12000, 12001)
            for position in ('begin', 'middle', 'end')
            for error in (False, True) for family in ('exception', 'version')]
    assert len({r['prompt'] + '\0' + r['response'] for r, _ in rows}) == len(rows)
    from structural_v02 import parse_case_v02
    from modular_common import exact_quotes
    for row, gold in rows:
        ctx = parse_case_v02(row['id'], row['prompt'], row['response'])
        assert gold['policy_dependency_span']['quote'].strip() in ctx.policy_text
        assert set(ctx.catalog.tools) == {'observe', 'change'}
        assert exact_quotes([gold['policy_dependency_span'], gold['history_dependency_span']], {'prompt': row['prompt']})
    folder = HERE / 'dataset/long_context_v2'
    folder.mkdir(parents=True, exist_ok=True)
    manifest = {'schema': 'long-context/2', 'n': len(rows), 'no_model_calls': True,
                'previous_bank_changed': False, 'role': 'stress and operating boundary, not heldout leaderboard',
                'target_size_includes_response': True,
                'format_caveat': 'Two authoritative SYSTEM messages. Original parser accepts both; this is an explicit stress layout.',
                'positions_move_both_crucial_system_rule_and_observations_across_source': True, 'splits': {}}
    for name, slot in [('input', 0), ('author_gold', 1)]:
        blob = ''.join(json.dumps(r[slot], ensure_ascii=False, sort_keys=True) + '\n' for r in rows).encode()
        (folder / (name + '.jsonl')).write_bytes(blob)
        manifest['splits'][name] = sha(blob)
    write(folder / 'manifest.json', manifest)
    print(json.dumps({'n': len(rows), 'all_rule_spans_retained_by_original_parser': True, 'examples_at_12000': [g['policy_relative_position'] for r, g in rows if r['id'].startswith('long_v2_exception_12000_')]}))


if __name__ == '__main__':
    main()
