"""Deterministic catalog-conformance pre-check over all 46 valid cases (v2).

Tree-aware schema validation:
- CALL_IN_CATALOG: every RESPONSE call's tool name must appear in the
  prompt's [AVAILABLE TOOLS] catalog.
- REQUIRED fields must be present (recursively: array items / object keys
  must carry their required children).
- ENUM-constrained values must come from the declared enum.

Reads labels ONLY for the post-hoc effect table (analysis after baseline).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path('/home/z/my-project/Guardian-of-Truth')
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / 'src'))
sys.path.insert(0, str(REPO / 'scripts'))

import pandas as pd

from real_valid_adapter import parse_tool_catalog
from real_valid_common import load_firewalled_rows
from guardian_truth.parsing import parse_events

rows = load_firewalled_rows()
frame = pd.read_parquet(REPO / 'valid.parquet')
gold = {str(r['id']): int(r['label']) for _, r in frame.iterrows()}


def validate_value(name: str, spec: dict, value, path: str, violations: list, tool: str):
    if spec.get('enum') and isinstance(value, str) and value not in spec['enum']:
        violations.append(f"{path}={value!r} not in enum {spec['enum']}")
    children = spec.get('children') or {}
    if not children:
        return
    if spec['type'] == 'array' and isinstance(value, list):
        for i, item in enumerate(value):
            _validate_fields(children, item, f"{path}[{i}]", violations, tool)
    elif spec['type'] == 'object' and isinstance(value, dict):
        _validate_fields(children, value, path, violations, tool)


def _validate_fields(fields: dict, container: dict, prefix: str, violations: list, tool: str):
    if not isinstance(container, dict):
        return
    for name, spec in fields.items():
        if spec.get('required') and name not in container:
            violations.append(f"{prefix}.{name} required but absent")
        if name in container:
            validate_value(name, spec, container[name], f"{prefix}.{name}", violations, tool)


violations = []
for row in rows:
    meta, schemas = parse_tool_catalog(row['prompt'])
    catalog = {tool['name'] for tool in meta}
    schema_by_name = {s['name']: s for s in schemas}
    resp_events = parse_events(row['response'], 'response')
    for event in resp_events:
        if event.kind != 'call' or not event.name or event.role == 'user':
            continue
        if event.name not in catalog:
            violations.append({'id': row['id'], 'label': gold[row['id']],
                               'type': 'TOOL_NOT_IN_CATALOG', 'tool': event.name, 'detail': ''})
            continue
        if not event.json_valid:
            violations.append({'id': row['id'], 'label': gold[row['id']],
                               'type': 'ARGUMENTS_NOT_JSON', 'tool': event.name,
                               'detail': event.text[:120]})
            continue
        schema = schema_by_name.get(event.name, {})
        problems = []
        _validate_fields(schema.get('parameters') or {}, event.value, event.name, problems, event.name)
        for problem in problems:
            violations.append({'id': row['id'], 'label': gold[row['id']],
                               'type': 'SCHEMA_VIOLATION', 'tool': event.name, 'detail': problem})

by_case = {}
for violation in violations:
    by_case.setdefault(violation['id'], []).append(violation)
print(f"cases with catalog-conformance violations: {len(by_case)}/{len(rows)}")
effect_tp = sum(1 for cid in by_case if gold[cid] == 1)
effect_fp = sum(1 for cid in by_case if gold[cid] == 0)
print(f"  on label=1 cases: {effect_tp} (potential TP gains)")
print(f"  on label=0 cases: {effect_fp} (potential FP risk!)")
for cid, items in sorted(by_case.items()):
    print(f"--- {cid} [label={gold[cid]}]")
    for item in items[:8]:
        print(f"    {item['type']}: {item['tool']} {item['detail'][:110]}")

out = REPO / 'outputs/vnext/real_valid/catalog_conformance_precheck.json'
out.write_text(json.dumps({'violations': violations,
                           'cases_with_violations': sorted(by_case),
                           'potential_tp': effect_tp, 'potential_fp': effect_fp},
                          ensure_ascii=False, indent=1), encoding='utf-8')
