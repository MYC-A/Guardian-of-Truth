import json
import unittest

from guardian_truth.judge import answer_review, partial_audit


def check(**changes):
    return dict(dict(action='a', fact='f', rule='r', exception='e', support=['u0'],
                     counter=[], assessment='CONCERN'), **changes)


class PartialAuditTests(unittest.TestCase):
    def parse(self, checks, unknowns=None, **kw):
        return partial_audit.parse_notes(json.dumps(dict(checks=checks, unknowns=unknowns or [])),
                                        kw.get('finish', 'stop'), ['u0'], {})

    def test_valid_baseline_is_unchanged(self):
        raw = json.dumps(dict(checks=[check()], unknowns=[]))
        self.assertEqual(partial_audit.parse_notes(raw, 'stop', ['u0'], {}),
                         answer_review.parse_notes(raw, 'stop', ['u0'], {}))

    def test_retains_valid_entry_without_repairing_unsupported_claim(self):
        good = check()
        bad = check(support=[])
        status, notes, report = self.parse([bad, good])
        self.assertEqual(status, 'PARTIAL')
        self.assertEqual(notes['checks'], [good])
        self.assertEqual(notes['admission']['retained_original_check_indices'], [1])
        self.assertEqual(report['rejected'][0]['reason'], 'AUDIT_SUPPORT_REQUIRED')
        self.assertFalse(notes['admission']['semantic_validation'])
        self.assertEqual(bad['assessment'], 'CONCERN')

    def test_invented_reference_is_dropped_not_rewritten(self):
        status, notes, _ = self.parse([check(support=['u999']), check()])
        self.assertEqual(status, 'PARTIAL')
        self.assertEqual(notes['checks'], [check()])

    def test_all_invalid_is_not_delivered_as_empty_success(self):
        self.assertEqual(self.parse([check(support=[])])[0:2], ('INVALID', None))

    def test_truncated_json_and_finish_length_are_never_recovered(self):
        self.assertEqual(self.parse([check()], finish='length')[0:2], ('TRUNCATED', None))
        self.assertEqual(partial_audit.parse_notes('{"checks":[', 'stop', ['u0'], {})[0:2],
                         ('INVALID', None))

    def test_envelope_schema_and_count_limits_stay_strict(self):
        self.assertEqual(self.parse([check()] * 4)[0], 'INVALID')
        raw = json.dumps(dict(checks=[check()], unknowns=[], unexpected=True))
        self.assertEqual(partial_audit.parse_notes(raw, 'stop', ['u0'], {})[0], 'INVALID')

    def test_unknown_entry_can_be_dropped_with_explicit_partial_metadata(self):
        status, notes, report = self.parse([check()], unknowns=['x' * 161, 'not known'])
        self.assertEqual(status, 'PARTIAL')
        self.assertEqual(notes['unknowns'], ['not known'])
        self.assertEqual(report['rejected'][0]['kind'], 'unknown')


if __name__ == '__main__':
    unittest.main()
