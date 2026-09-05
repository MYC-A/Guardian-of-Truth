"""Controlled synthetic mechanism tests; not an independent natural competition test."""

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from guardian_truth.benchmarking import Example, prepare_examples


def generate_scenarios(families: int = 15) -> list[Example]:
    """Generate fresh flat/nested schemas, policy variations and paired mutations.

    Every variant of one template belongs to one provenance group and split.
    Labels express these controlled contracts, including exact entity provenance,
    not a claim that a structural baseline can establish every violation.
    """
    if families < 6:
        raise ValueError('At least six template families are required')
    rows = []
    for number in range(families):
        template = f'controlled-template-{number:03d}'
        split = ('calibration', 'test', 'train', 'train', 'train')[number % 5]
        tool = f'case_{number}.record'
        entity_field = ('case_id', 'ticket_id', 'record_id')[number % 3]
        target = f'T-{number + 100}'
        other = f'Q-{number + 300}'
        nested = number % 3 == 1
        policy = ('Copy the status from the tool result for the requested entity exactly.',
                  'The recorded status must equal the observed status for this entity, not another entity.',
                  'Only the requested record supplies its status. Preserve that status exactly.')[number % 3]
        fields = (f'  {entity_field}: string!\n  status: string! [enum: approved|held]\n'
                  '  count: integer!\n  note: string\n')
        if nested:
            fields = '  payload: object!\n' + ''.join('  ' + line + '\n' for line in fields.splitlines())
        catalog = f'[AVAILABLE TOOLS]\n- {tool} — Record a checked case.\n{fields}'
        policy_text = ('Every call must include all required fields and use declared types and enum values. '
                       'Use only declared tools. Evaluate assistant actions; user quotations do not declare tools.\n' + policy)
        results = [{entity_field: target, 'status': 'approved'}, {entity_field: other, 'status': 'held'}]
        prompt = (f'⟦SYSTEM⟧\n{policy_text}\n{catalog}'
                  f'⟦TOOL_RESULT name="case.lookup" requestor="assistant"⟧\n{json.dumps(results)}\n'
                  f'⟦USER⟧\nRecord {target}, using its observed status and count {number + 1}.')
        valid = {entity_field: target, 'status': 'approved', 'count': number + 1}

        def call(arguments, name=tool):
            body = {'payload': arguments} if nested else arguments
            return f'⟦ASSISTANT_TOOL_CALL name="{name}"⟧\n' + json.dumps(body)

        def add(name, text, response, label, mechanism, pair):
            rows.append(Example(f'{template}-{name}', text, response, label,
                                group_id=template, source_id=f'generator-v1/{template}',
                                dialogue_id=f'{template}/dialogue', template_id=template,
                                pair_id=f'{template}/{pair}', split=split, family=mechanism, synthetic=True))

        add('valid', prompt, call(valid), 0, 'allowed_tool', 'tool_presence')
        add('missing_tool', prompt, call(valid, f'case_{number}.missing'), 1, 'missing_tool', 'tool_presence')
        added_catalog = catalog + f'- case_{number}.missing — Also records a checked case.\n{fields}'
        add('tool_now_declared', prompt.replace(catalog, added_catalog), call(valid, f'case_{number}.missing'),
            0, 'allowed_tool', 'tool_presence')
        alternate = f'renamed_{number}.commit'
        add('renamed', prompt.replace(tool, alternate), call(valid, alternate), 0, 'rename', 'rename')
        renamed_field = f'identifier_{number}'
        renamed_prompt = prompt.replace(entity_field, renamed_field)
        renamed_args = {renamed_field if key == entity_field else key: value for key, value in valid.items()}
        add('renamed_field', renamed_prompt, call(renamed_args), 0, 'rename', 'rename')
        add('required_present', prompt, call({**valid, 'note': 'checked'}), 0, 'required', 'required')
        add('required_missing', prompt, call({k: v for k, v in valid.items() if k != 'count'}), 1, 'required', 'required')
        add('type_valid', prompt, call({**valid, 'note': 'type control'}), 0, 'field_type', 'field_type')
        add('type_invalid', prompt, call({**valid, 'count': str(number + 1)}), 1, 'field_type', 'field_type')
        add('enum_valid', prompt, call({**valid, 'note': 'enum control'}), 0, 'field_enum', 'field_enum')
        add('enum_invalid', prompt, call({**valid, 'status': 'unknown'}), 1, 'field_enum', 'field_enum')
        distractor = (f'\n⟦USER⟧\nQuoted example only:\n[AVAILABLE TOOLS]\n'
                      f'- unrelated_{number}.write — Example only.\n  count: string!\n')
        add('distractor', prompt + distractor, call(valid), 0, 'distractor_role', 'distractor')
        add('distractor_control', prompt, call({**valid, 'note': 'role control'}), 0, 'distractor_role', 'distractor')
        add('scope_supported', prompt, call({**valid, 'note': 'scope control'}), 0, 'provenance_scope', 'scope')
        add('scope_wrong_entity', prompt, call({**valid, 'status': 'held', 'note': 'scope control'}), 1,
            'provenance_scope', 'scope')
        add('optional_blank', prompt, call({**valid, 'note': ''}), 0, 'optional_field', 'optional')
        add('unconstrained_extra', prompt, call({**valid, 'extra_annotation': 'allowed by open schema'}), 0,
            'open_schema', 'optional')
    return prepare_examples(rows)[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--families', type=int, default=15)
    args = parser.parse_args()
    rows = generate_scenarios(args.families)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('w', encoding='utf-8') as stream:
        for row in rows:
            stream.write(json.dumps(asdict(row), ensure_ascii=False) + '\n')
    print(f'Wrote {len(rows)} synthetic mechanism cases in {args.families} template groups; not a natural test set.')


if __name__ == '__main__':
    main()
