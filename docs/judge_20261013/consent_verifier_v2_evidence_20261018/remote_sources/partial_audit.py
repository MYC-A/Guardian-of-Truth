"""Research-only per-entry admission. Production strict parser is unchanged.

Only complete JSON envelopes are eligible. Each retained entry must pass the
existing strict parser with the actual citable source IDs. Admission proves
structure/references only, never truth, applicability or completeness.
"""
import json

from guardian_truth.judge import answer_review


def parse_notes(text, finish_reason, valid_ids, settings):
    status, notes, report = answer_review.parse_notes(text, finish_reason, valid_ids, settings)
    if status != 'INVALID':
        return status, notes, report
    original_report = report
    try:
        obj = json.loads(text)
        if (not isinstance(obj, dict) or set(obj) != {'checks', 'unknowns'}
                or not isinstance(obj['checks'], list) or len(obj['checks']) > 3
                or not isinstance(obj['unknowns'], list) or len(obj['unknowns']) > 3):
            return status, notes, report
    except (ValueError, TypeError):
        return status, notes, report
    checks, unknowns, accepted, rejected = [], [], [], []
    for index, check in enumerate(obj['checks']):
        entry_status, entry, entry_report = answer_review.parse_notes(
            json.dumps(dict(checks=[check], unknowns=[])), finish_reason, valid_ids, settings)
        if entry_status == 'VALID':
            checks.extend(entry['checks'])
            accepted.append(index)
        else:
            rejected.append(dict(kind='check', index=index, reason=entry_report['reason']))
    if not checks:
        return 'INVALID', None, original_report
    for index, unknown in enumerate(obj['unknowns']):
        entry_status, entry, entry_report = answer_review.parse_notes(
            json.dumps(dict(checks=[], unknowns=[unknown])), finish_reason, valid_ids, settings)
        if entry_status == 'VALID':
            unknowns.extend(entry['unknowns'])
        else:
            rejected.append(dict(kind='unknown', index=index, reason=entry_report['reason']))
    entry_status, notes, _ = answer_review.parse_notes(
        json.dumps(dict(checks=checks, unknowns=unknowns)), finish_reason, valid_ids, settings)
    if entry_status != 'VALID' or not rejected:
        raise ValueError('PARTIAL_ADMISSION_INTERNAL_CONTRACT')
    notes['admission'] = dict(status='PARTIAL', retained_original_check_indices=accepted,
                             rejected_entries=len(rejected), semantic_validation=False,
                             completeness_proven=False)
    return 'PARTIAL', notes, dict(empty=False, checks=len(checks), rejected=rejected,
                                 original_reason=original_report['reason'], semantic_validation=False)


def render_notes(notes, pre, settings):
    # The code-owned admission metadata is inside the existing MODEL_HYPOTHESIS
    # envelope. Unchanged VALID notes render identically to the strict baseline.
    return answer_review.render_notes(notes, pre, settings)
