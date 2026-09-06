"""Diagnostic reason precision; human/reference annotation, NOT judge self-rating.

The scope is accepted semantic-positive decisions. Unknown annotations stay
unknown; a correct label cannot stand in for a verified material reason.
"""

from collections import Counter
from dataclasses import dataclass


@dataclass(frozen=True)
class ReasonAnnotation:
    id: str
    label: int
    prediction: int
    decision_source: str  # semantic, mechanical, fallback
    material_valid_reason: bool | None = None
    cited_material_valid_reason: bool | None = None

    def __post_init__(self):
        if not isinstance(self.id, str) or not self.id.strip():
            raise ValueError('Reason annotation requires an ID')
        if any(type(value) is not int or value not in (0,1) for value in (self.label,self.prediction)):
            raise ValueError('Binary integer labels required')
        if self.decision_source not in ('semantic','mechanical','fallback'):
            raise ValueError('Unknown decision source')
        if any(value is not None and type(value) is not bool for value in (
                self.material_valid_reason,self.cited_material_valid_reason)):
            raise ValueError('Reason correctness must be true, false, or unadjudicated')
        if self.cited_material_valid_reason is True and self.material_valid_reason is not True:
            raise ValueError('A cited valid material reason must also be a valid material reason')


def _precision(values):
    good = sum(value is True for value in values)
    bad = sum(value is False for value in values)
    unknown = sum(value is None for value in values)
    total = len(values)
    return {'denominator':total, 'verified_correct':good, 'verified_wrong':bad,
            'unadjudicated':unknown,
            'verified_lower_bound':good/total if total else None,
            'possible_upper_bound':(good+unknown)/total if total else None,
            'audited_precision':good/(good+bad) if good+bad else None,
            'audit_coverage':(good+bad)/total if total else None}


def reason_metrics(annotations):
    rows = list(annotations)
    if not all(isinstance(row,ReasonAnnotation) for row in rows):
        raise ValueError('Expected ReasonAnnotation records')
    if len({row.id for row in rows}) != len(rows):
        raise ValueError('Duplicate reason annotation IDs')
    positives = [row for row in rows if row.prediction == 1 and row.decision_source == 'semantic']
    categories = Counter({'CORRECT_LABEL_CORRECT_REASON':0,
                          'CORRECT_LABEL_WRONG_REASON':0,'WRONG_LABEL':0,'UNADJUDICATED_REASON_TP':0})
    for row in positives:
        if row.label != row.prediction:
            categories['WRONG_LABEL'] += 1
        elif row.material_valid_reason is True:
            categories['CORRECT_LABEL_CORRECT_REASON'] += 1
        elif row.material_valid_reason is False:
            categories['CORRECT_LABEL_WRONG_REASON'] += 1
        else:
            categories['UNADJUDICATED_REASON_TP'] += 1
    return {'rows':len(rows), 'semantic_positive_decisions':len(positives),
            'reason_precision':_precision([row.material_valid_reason for row in positives]),
            'cited_reason_precision':_precision([row.cited_material_valid_reason for row in positives]),
            'semantic_positive_categories':dict(categories),
            'wrong_labels_all_decision_sources':sum(row.label != row.prediction for row in rows),
            'excluded_from_reason_precision':dict(Counter(
                row.decision_source + ('_negative' if row.prediction == 0 else '_positive')
                for row in rows if row not in positives)),
            'limitations':['Reason annotation is reference judgement, not model confidence or an F1 substitute.',
                           'Unknown annotations are bounded, never silently counted as verified errors.',
                           'Category counts apply to semantic-positive decisions; all-label errors reported separately.',
                           'Reason Precision does not establish hidden-test robustness on an inspected development set.']}
