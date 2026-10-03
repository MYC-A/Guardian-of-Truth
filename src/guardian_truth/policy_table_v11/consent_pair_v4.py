"""Normalize container evidence into independently checked scalar evidence.

Only the evidence representation changes. Source, full native arguments, actor,
operation, reply scope and consumable batch rules remain those of frozen v3.
Sharing a citation does not establish the semantic role of a value or consent.
"""
import copy
import json

from . import consent_pair_v3 as previous


INSTRUCTION = previous.INSTRUCTION.replace(
    'Nonempty containers cannot be wrapped in a single\nvalue: support EACH leaf independently.',
    'A container may be wrapped as {"value": array_or_object, "span_ids": [...]};\n'
    'code will distribute these citations to its leaves and independently check\n'
    'EVERY leaf. Prefer smaller field-specific citations when the source has them.')


def supported_tree(value, spans, depth):
    if depth > 40:
        raise ValueError('evidence_tree_too_deep')
    if isinstance(value, dict) and value:
        if any(not isinstance(key, str) for key in value):
            raise ValueError('parameter_key_not_string')
        return {key: supported_tree(child, spans, depth + 1)
                for key, child in value.items()}
    if isinstance(value, list) and value:
        return [supported_tree(child, spans, depth + 1) for child in value]
    return {'value': value, 'span_ids': list(spans)}


def normalize_tree(node, depth=0):
    if depth > 40:
        raise ValueError('evidence_tree_too_deep')
    if isinstance(node, dict) and set(node) == {'value', 'span_ids'}:
        evidence = previous.Evidence.model_validate(node)
        json.dumps(evidence.value, allow_nan=False)
        return supported_tree(evidence.value, evidence.span_ids, depth)
    if isinstance(node, dict) and node:
        if any(not isinstance(key, str) for key in node):
            raise ValueError('parameter_key_not_string')
        return {key: normalize_tree(child, depth + 1) for key, child in node.items()}
    if isinstance(node, list) and node:
        return [normalize_tree(child, depth + 1) for child in node]
    raise ValueError('bare_or_empty_leaf_without_evidence')


def request(store, target, proposal_sid=None):
    return [{'role': 'system', 'content': INSTRUCTION},
            {'role': 'user', 'content': json.dumps(packet(store, target, proposal_sid),
                ensure_ascii=False, separators=(',', ':'))}]


def admit(response, store, target, proposal_sid=None):
    if (not isinstance(response, dict) or set(response) != {'proposal_source_id', 'plans'}
            or not isinstance(response['plans'], list)):
        return previous.admit(response, store, target, proposal_sid)
    normalized = copy.deepcopy(response)
    failures = []
    for ordinal, plan in enumerate(normalized['plans']):
        if not isinstance(plan, dict) or not isinstance(plan.get('parameters'), dict):
            continue  # v3 retains and rejects malformed plans with their scope.
        try:
            # Keep the root field inventory: a wrapper cannot replace all arguments.
            plan['parameters'] = {key: normalize_tree(value, 1)
                                  for key, value in plan['parameters'].items()}
        except (ValueError, TypeError, RecursionError) as exc:
            failures.append({'ordinal': ordinal, 'tool': plan.get('tool'),
                             'reason': str(exc).split('\n')[0]})
            # Preserve operation identity and block relevant resolution.
            plan['parameters'] = None
    admitted = previous.admit(normalized, store, target, proposal_sid)
    admitted['normalization_failures'] = failures
    admitted['evidence_representation'] = 'CONTAINER_DISTRIBUTED_TO_EACH_LEAF'
    return admitted


packet = previous.packet
selected_proposal = previous.selected_proposal
verdict = previous.verdict
agreement = previous.agreement
