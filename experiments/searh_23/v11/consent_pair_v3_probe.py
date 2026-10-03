"""New frozen v3; common v2 runner/ledger, unchanged previous replies and code."""
from pathlib import Path

import consent_pair_v2_probe as runner
from consent_pair_v2_extra import cases as v2_cases
from consent_pair_v3_extra import cases as prospective_cases
from guardian_truth.policy_table_v11 import consent_pair_v3

runner.RUN = runner.ROOT / 'outputs/searh_23/v11/consent_pair_v3_probe'
runner.VERSION = 'consent-pair-probe/3'
runner.semantic = consent_pair_v3
runner.extra_cases = lambda: v2_cases() + prospective_cases()
original_freeze = runner.freeze


def freeze():
    value = original_freeze()
    path = runner.RUN / 'freeze.json'
    frozen = runner.read(path)
    for source in (Path(__file__), Path(__file__).with_name('consent_pair_v3_extra.py'),
                   runner.ROOT / 'tests/test_policy_table_v11_consent_pair_v3.py'):
        frozen['sources'][source.relative_to(runner.ROOT).as_posix()] = runner.blob(source)
    frozen['previous_completed_comparison'] = '75536434/consent-pair-probe/2'
    frozen['prospective_case_ids'] = ['new/' + c['id'] for c in prospective_cases()]
    frozen['changes'] = ['EVIDENCE_ATTACHED_TO_LEAVES', 'PER_OPERATION_KIND_AND_EXECUTOR',
                         'EXPLICIT_EXECUTOR_VS_AUTHORIZER_INSTRUCTION']
    runner.write(path, frozen)
    return value


runner.freeze = freeze
if __name__ == '__main__':
    runner.main()
