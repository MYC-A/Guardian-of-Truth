"""Integration test: Run enhanced consent on retained_pilot cases."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from guardian_truth.source_search.store import SourceStore
from guardian_truth.source_search.id_contract import native_target_inventory
from guardian_truth.policy_table_v11.consent_enhanced import explicit_confirmation_enhanced
from guardian_truth.policy_table_v11.witness import timeline


def main():
    """Test enhanced consent on retained_pilot_re_admission cases."""
    data_path = ROOT / 'outputs/searh_23/v11/rescue_probe/retained_pilot_re_admission.json'

    if not data_path.exists():
        print(f"Error: {data_path} not found")
        return 1

    data = json.loads(data_path.read_text(encoding='utf-8'))

    synthetic_tests = data.get('synthetic', [])

    print("=" * 80)
    print("ENHANCED CONSENT INTEGRATION TEST")
    print("=" * 80)
    print(f"\nTesting on {len(synthetic_tests)} retained_pilot cases\n")

    passed = 0
    failed = 0
    results = []

    for test in synthetic_tests:
        test_id = test['id']
        expected = test['expected']
        fixture = test['fixture']

        # Create store directly from fixture
        s = SourceStore({
            'prompt': fixture['prompt'],
            'response': fixture['response']
        })

        # Get target
        targets = native_target_inventory(s)
        if not targets:
            print(f"✗ FAIL {test_id} - No targets found")
            failed += 1
            continue

        t = targets[0]
        events = timeline(s, t)

        # Run enhanced consent
        result = explicit_confirmation_enhanced(s, t, events)

        actual = [result.status, result.value]

        # Compare
        match = actual == expected
        if match:
            passed += 1
            status = "✓ PASS"
        else:
            failed += 1
            status = "✗ FAIL"

        results.append({
            'id': test_id,
            'status': status,
            'expected': expected,
            'actual': actual,
            'reason': result.reason if hasattr(result, 'reason') else None
        })

        print(f"{status} {test_id}")
        if not match:
            print(f"    Expected: {expected}")
            print(f"    Actual:   {actual}")
            print(f"    Reason:   {result.reason if hasattr(result, 'reason') else 'N/A'}")

    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"Passed: {passed}/{len(synthetic_tests)}")
    print(f"Failed: {failed}/{len(synthetic_tests)}")
    print(f"Success rate: {passed/len(synthetic_tests)*100:.1f}%")

    if failed > 0:
        print("\n" + "=" * 80)
        print("FAILED TESTS DETAIL")
        print("=" * 80)
        for r in results:
            if r['status'].startswith('✗'):
                print(f"\n{r['id']}:")
                print(f"  Expected: {r['expected']}")
                print(f"  Actual:   {r['actual']}")
                print(f"  Reason:   {r['reason']}")

    return 0 if failed == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
