import base64
import hashlib
import json
from pathlib import Path

from guardian_truth.vnext.integrity import digest, file_digest, prediction_seal


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'outputs/vnext'


def load(suffix):
    return json.loads((OUTPUT / ('claim_graph_v1_' + suffix + '.json')).read_text(encoding='utf-8'))


def test_claim_predictions_and_exact_frozen_source_archive_are_sealed():
    freeze, rows, seal, archive = map(load, ('freeze', 'predictions', 'prediction_seal', 'source_archive'))
    assert len(rows) == len(freeze['case_ids']) == 41
    assert seal == prediction_seal(rows, freeze['case_ids'], architecture_commit=freeze['architecture_commit'],
        configuration_sha256=digest(freeze))
    assert archive['freeze_sha256'] == file_digest(OUTPUT / 'claim_graph_v1_freeze.json')
    assert archive['architecture_commit'] == freeze['architecture_commit']
    assert len(archive['sources']) == 100
    assert set(archive['sources']) == set(freeze['source_sha256'])
    for path, expected in freeze['source_sha256'].items():
        archived = archive['sources'][path]
        assert archived['sha256'] == expected
        assert hashlib.sha256(base64.b64decode(archived['bytes_base64'], validate=True)).hexdigest() == expected


def test_claim_report_preserves_transport_exclusions_and_failed_admission():
    result = load('results')
    assert result['case_count'] == 41
    assert result['provider']['C2']['attempts'] == 41
    assert result['provider']['vnext']['attempts'] == 410
    assert result['provider']['vnext']['transport_success'] == 409
    assert result['provider']['vnext']['schema_valid'] == 409
    assert result['admission']['span_gate'] is True
    assert result['admission']['shared_typed_gain_gate'] is False
    kind = result['field_metrics']['vnext']['kind']
    assert (kind['correct'], kind['denominator'], kind['excluded_transport_schema']) == (31, 37, 1)
    assert result['field_metrics']['C2']['actor']['accuracy'] is None
    assert result['provider']['vnext']['cost'] == 'NOT_AUDITED'


def test_detailed_claim_audit_links_immutable_report_and_all_cases():
    audit = load('detailed_audit')
    assert audit['source_report_sha256'] == file_digest(OUTPUT / 'claim_graph_v1_results.json')
    assert audit['prediction_seal_sha256'] == file_digest(OUTPUT / 'claim_graph_v1_prediction_seal.json')
    assert len(audit['cases']) == audit['case_count'] == 41
    assert sum(len(case['field_mismatches']) for case in audit['cases']) == 92
    assert sum(len(case['failed_requests']) for case in audit['cases']) == 1
    assert all(item['interpretation'] == 'EXACT_ANNOTATION_MISMATCH_SEMANTIC_EQUIVALENCE_NOT_ADJUDICATED'
        for case in audit['cases'] for item in case['field_mismatches'])
