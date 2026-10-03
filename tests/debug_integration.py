"""Debug integration test to see what's happening."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from guardian_truth.source_search.store import SourceStore
from guardian_truth.source_search.id_contract import native_target_inventory
from guardian_truth.policy_table_v11.consent_enhanced import explicit_confirmation_enhanced, enhanced_action_frame
from guardian_truth.policy_table_v11.witness import timeline
from guardian_truth.parsing import parse_catalog


def debug_test(test_id):
    """Debug a specific test case."""
    data_path = ROOT / 'outputs/searh_23/v11/rescue_probe/retained_pilot_re_admission.json'
    data = json.loads(data_path.read_text(encoding='utf-8'))

    test = [t for t in data['synthetic'] if t['id'] == test_id][0]

    print("=" * 80)
    print(f"DEBUG: {test_id}")
    print("=" * 80)

    # Create store directly from fixture
    s = SourceStore({
        'prompt': test['fixture']['prompt'],
        'response': test['fixture']['response']
    })

    # Get target
    targets = native_target_inventory(s)
    if not targets:
        print("ERROR: No targets found!")
        return
    t = targets[0]

    events = timeline(s, t)

    print(f"\nTarget: {t}")
    print(f"\nEvents count: {len(events)}")

    print("\n" + "=" * 80)
    print("RAW PROMPT:")
    print("=" * 80)
    print(s.raw['prompt'])
    print("\n" + "=" * 80)

    # Parse catalog
    catalog = parse_catalog(s.history_events, s.raw['prompt'])
    catalog_dict = {
        'tools': {
            name: {
                'arguments': {
                    field.name: {
                        'type': field.kind,
                        'required': field.required
                    }
                    for field in tool.fields
                }
            }
            for name, tool in catalog.tools.items()
        }
    }

    print(f"\nCatalog tools: {list(catalog.tools.keys())}")
    print(f"\nCatalog dict tools: {list(catalog_dict['tools'].keys())}")
    print(f"\nCatalog for apply_a: {catalog_dict['tools'].get('apply_a', {})}")

    print("\n" + "=" * 80)
    print("EVENTS TIMELINE:")
    print("=" * 80)

    for i, (sid, e) in enumerate(events):
        print(f"\n{i}. [{sid}] {e.role:10} {e.kind:10}")
        if e.kind == 'text':
            print(f"   Text: {e.text[:100]}")

            if e.role == 'assistant':
                # Try to extract frame
                frame = enhanced_action_frame(e.text, catalog, catalog_dict)
                if frame:
                    print(f"   ✓ FRAME: tool={frame['tool']}, args={frame['arguments']}, method={frame.get('method')}, request={frame.get('request')}")
                else:
                    print(f"   ✗ NO FRAME")

    print("\n" + "=" * 80)
    print("RUNNING explicit_confirmation_enhanced:")
    print("=" * 80)

    result = explicit_confirmation_enhanced(s, t, events)

    print(f"\nResult status: {result.status}")
    print(f"Result value: {result.value}")
    print(f"Result reason: {result.reason if hasattr(result, 'reason') else 'N/A'}")

    print(f"\nExpected: {test['expected']}")
    print(f"Actual: [{result.status}, {result.value}]")
    print(f"Match: {[result.status, result.value] == test['expected']}")


if __name__ == '__main__':
    # Debug the first failing test
    debug_test('restatement_keeps_yes')
