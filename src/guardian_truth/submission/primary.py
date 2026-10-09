"""Unchanged B2 requests; narrowly repair a missing JSON root close only."""
import json

from experiments.guardian_addons.variants2 import Hook2
from guardian_truth.integrated.transport import sha
from guardian_truth.verification.admission import interpret_receipt_v2

JSON_WS = ' \t\r\n'


class PrimaryReviewHook(Hook2):
    review_request = None
    first_receipt = None

    def _send(self, request, attempt=0, tag=''):
        if tag == 'review':
            self.review_request = request
        receipt = super()._send(request, attempt=attempt, tag=tag)
        if tag != 'review':
            return receipt
        self.first_receipt = receipt
        content = receipt.get('content')
        if ((receipt.get('transport') or {}).get('status') != 200 or receipt.get('finish_reason') != 'length'
                or not isinstance(content, str) or not content.lstrip(JSON_WS).startswith('{')):
            return receipt
        packet = json.loads(request['messages'][1]['content'])
        if interpret_receipt_v2(receipt, packet)['admission'] != 'INVALID_JSON':
            return receipt
        # Append no values, fields, quotes, or arbitrary balancing delimiters.
        # All required fields and references must pass the original admission.
        repaired = dict(receipt, content=content + '}')
        if interpret_receipt_v2(repaired, packet)['admission'] != 'ADMITTED':
            return receipt
        self.log.append(dict(tag='primary_root_close', admission='ADMITTED',
                             normalization='MISSING_ROOT_CLOSE_ADDED',
                             first_invalid=dict(receipt, admission='INVALID_JSON'),
                             request_sha256=sha(request), attempt=attempt))
        return repaired
