"""Output-only recovery, separate from policy/cause admission and strict decision."""
import copy

from guardian_truth.integrated.reviewer import decode_reply

VERSION = 'submission-output-recovery-1'


def recover_output(trace):
    """Valid strict results are immutable; unresolved rows receive explicit output.

    A complete top-level model enum can classify a row whose explanation failed
    admission. It cannot issue a supported accusation. No enum is inferred from
    fragments, nested keys, keyword occurrences, failed HTTP or failed completion.
    """
    if type(trace.get('binary')) is int and trace['binary'] in (0, 1) and not trace.get('error'):
        return trace
    revised = copy.deepcopy(trace)
    for field in ('output_recovery', 'technical_error'):
        revised.pop(field, None)
    receipt = revised.get('primary_receipt') or {}
    primary = next((s for s in ((revised.get('rec') or {}).get('A') or {}).get('steps', [])
                    if s.get('tag') == 'review'), {})
    # Use actual primary receipt; source-specific admission remains untouched.
    if not receipt:
        receipt = dict(primary, content=primary.get('raw_content'))
    value, decoded, _ = decode_reply(receipt.get('content'))
    label = None
    if ((receipt.get('transport') or {}).get('status') == 200
            and receipt.get('finish_reason') not in ('error', 'refusal', 'content_filter')
            and decoded and isinstance(value, dict)
            and value.get('decision') in ('ERROR', 'NO_ERROR', 'UNKNOWN')):
        label = value['decision']
    mode = 'RAW_MODEL_DECISION' if label is not None else 'DEFAULT_ZERO'
    revised.update(binary=int(label == 'ERROR') if label is not None else 0,
                   owner=mode, accusation=None,
                   output_recovery=dict(version=VERSION, mode=mode, strict_binary=trace.get('binary'),
                                        model_decision=label, cause_status='NOT_VALIDATED',
                                        fallback_label=0 if label is None else None))
    if revised.get('error'):
        revised['technical_error'] = revised.pop('error')
    return revised
