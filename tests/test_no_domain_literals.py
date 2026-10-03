"""Scan new algorithm/prose; input data and audit reports are intentionally separate."""
import ast
from pathlib import Path
import re
from guardian_truth.parsing import parse_catalog
from guardian_truth.source_search.store import SourceStore

ROOT = Path(__file__).resolve().parents[1]


def test_new_policy_algorithm_has_no_domain_case_or_examined_tool_constants():
    import json
    rows = [json.loads(s) for s in (ROOT / 'outputs/searh_23/source_search_20261002/comparison_ids_v5/inputs.jsonl').read_text(encoding='utf-8').splitlines()]
    names = set()
    for row in rows:
        store = SourceStore(row)
        names.update(parse_catalog(store.history_events, row['prompt']).tools)
    files = list((ROOT / 'src/guardian_truth/policy_table').glob('*.py'))
    for file in files:
        text = file.read_text(encoding='utf-8')
        assert not re.search(r'\b(?:airline|retail|banking|telecom)\b', text, re.I), file
        # Names are checked in string literals rather than function identifiers
        # such as compile/evaluate. All domain values must enter through input.
        for node in ast.walk(ast.parse(text)):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                for name in names:
                    assert not re.search(r'(?<!\w)' + re.escape(name) + r'(?!\w)', node.value), (file, name)
