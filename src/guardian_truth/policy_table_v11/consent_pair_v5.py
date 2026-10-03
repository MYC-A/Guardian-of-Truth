"""Offline development fix for mixed evidence trees and typed source JSON.

No policy/domain/tool-name rules and no target argument values enter the request.
V2's target authenticity, full argument equality, chronological checks, relevance
gate and consumable batch checks remain unchanged. The envelope is normalized;
it is never repaired by inventing missing source evidence or a missing plan.
"""
import json
import math

from guardian_truth.policy_table.evaluate import same
from guardian_truth.source_search.store import digest

from . import consent_pair_v2 as core
from . import consent_pair_v3 as tree
from . import consent_pair_v4 as frozen
from .consent_source_json import support_mode


INSTRUCTION = frozen.INSTRUCTION  # Only offline admission changes in this version.


def normalize_tree(node, depth=0, inherited=None):
    if depth > 40:
        raise ValueError('evidence_tree_too_deep')
    if isinstance(node, dict) and set(node) == {'value', 'span_ids'}:
        evidence = tree.Evidence.model_validate(node)
        # Inner explicit evidence replaces inherited evidence, including invalid
        # or temporally disallowed IDs; it must not be silently erased.
        return normalize_tree(evidence.value, depth + 1, evidence.span_ids)
    if isinstance(node, dict) and node:
        if any(not isinstance(key, str) for key in node):
            raise ValueError('parameter_key_not_string')
        return {key: normalize_tree(child, depth + 1, inherited)
                for key, child in node.items()}
    if isinstance(node, list) and node:
        return [normalize_tree(child, depth + 1, inherited) for child in node]
    if inherited is None:
        raise ValueError('bare_or_empty_leaf_without_evidence')
    if not (node is None or type(node) in (str, bool, int, float, dict, list)):
        raise ValueError('leaf_not_json_type')
    if type(node) is float and not math.isfinite(node):
        raise ValueError('nonfinite_parameter')
    return {'value': node, 'span_ids': list(inherited)}


def _admit_plans(response, store, target, proposal_sid):
    """Frozen V2's admission checks, with strict structured support per binding.

    Kept local to leave frozen versions and their results reproducible. No
    monkeypatching or substitution of source/target arguments takes place.
    """
    try:
        shown = core.packet(store, target, proposal_sid)
    except (ValueError, KeyError):
        return {'valid': False, 'proposal_source_id': proposal_sid, 'plans': [],
                'discarded': [], 'reason': 'proposal_unavailable', 'code_proof': False}
    sid = shown['proposal_source_id']
    def invalid(reason):
        return {'valid': False, 'proposal_source_id': sid, 'plans': [],
                'discarded': [], 'reason': reason, 'code_proof': False}
    if not isinstance(response, dict) or set(response) != {'proposal_source_id', 'kind', 'plans'}:
        return invalid('invalid_envelope')
    if response['proposal_source_id'] != sid or response['kind'] not in core.KINDS or not isinstance(response['plans'], list):
        return invalid('invalid_proposal_identity_or_kind')
    if response['kind'] not in ('ACTION_REQUEST', 'ACTION_DESCRIPTION') and response['plans']:
        return invalid('nonaction_has_plans')
    accepted, discarded, grounding = [], [], []
    spans = shown['spans']
    for ordinal, item in enumerate(response['plans']):
        try:
            plan = core.Plan.model_validate(item)
            if plan.tool not in shown['tool_declarations']:
                raise ValueError('undeclared_operation')
            for span_id in plan.action_span_ids:
                if span_id not in spans or spans[span_id]['purpose'] != 'PROPOSAL':
                    raise ValueError('action_span_outside_proposal')
            wanted = dict(core.leaves(plan.arguments)) if plan.arguments else {}
            paths = [binding.path for binding in plan.bindings]
            if set(paths) != set(wanted) or len(paths) != len(set(paths)):
                raise ValueError('leaf_inventory_mismatch')
            plan_grounding = []
            for binding in plan.bindings:
                if any(q not in spans or spans[q]['purpose'] not in ('CONTEXT', 'PROPOSAL')
                       for q in binding.span_ids):
                    raise ValueError('binding_source_not_before_reply')
                mode = support_mode(wanted[binding.path],
                    [spans[q]['text'] for q in binding.span_ids], plan.arguments, binding.path)
                plan_grounding.append({'path': binding.path, 'mode': mode})
            if shown['user_source_ids']:
                if plan.reply_kind == 'NONE':
                    raise ValueError('existing_reply_classified_absent')
                if plan.reply_kind in ('CONFIRM', 'REFUSE') and not plan.reply_span_ids:
                    raise ValueError('resolved_reply_without_evidence')
            elif plan.reply_kind != 'NONE' or plan.reply_span_ids:
                raise ValueError('invented_reply')
            if any(q not in spans or spans[q]['purpose'] != 'REPLY' for q in plan.reply_span_ids):
                raise ValueError('reply_span_outside_user_block')
            if any(p['tool'] == plan.tool and same(p['arguments'], plan.arguments) for p in accepted):
                raise ValueError('duplicate_plan')
            accepted.append({**plan.model_dump(), 'plan_id': sid + '.p' + str(ordinal)})
            grounding.append({'ordinal': ordinal, 'bindings': plan_grounding})
        except (ValueError, TypeError, RecursionError) as exc:
            discarded.append({'ordinal': ordinal, 'tool': item.get('tool') if isinstance(item, dict) else None,
                              'reason': str(exc).split('\n')[0]})
    # V3 treats an undeclared/malformed operation as potentially relevant.
    for rejected in discarded:
        tool = rejected.get('tool')
        if not isinstance(tool, str) or tool not in shown['tool_declarations']:
            rejected['original_tool'], rejected['tool'] = tool, None
    return {'valid': True, 'proposal_source_id': sid, 'kind': response['kind'],
            'plans': accepted, 'discarded': discarded, 'user_source_ids': shown['user_source_ids'],
            'packet_sha256': digest(shown), 'grounding': grounding, 'code_proof': False}


def admit(response, store, target, proposal_sid=None):
    if (not isinstance(response, dict) or set(response) != {'proposal_source_id', 'plans'}
            or not isinstance(response['plans'], list)):
        return _admit_plans(None, store, target, proposal_sid)
    adapted = {'proposal_source_id': response['proposal_source_id'],
               'kind': 'ACTION_REQUEST', 'plans': []}
    failures = []
    for ordinal, plan in enumerate(response['plans']):
        try:
            if not isinstance(plan, dict) or set(plan) != {'tool', 'actor', 'kind', 'parameters',
                    'action_span_ids', 'reply_kind', 'reply_span_ids'}:
                raise ValueError('invalid_evidence_plan_fields')
            if plan['kind'] != 'ACTION_REQUEST' or plan['actor'] != 'ASSISTANT':
                raise ValueError('not_an_assistant_action_request')
            if not isinstance(plan['parameters'], dict):
                raise ValueError('parameters_not_object')
            normalized = {key: normalize_tree(value, 1) for key, value in plan['parameters'].items()}
            arguments, bindings = tree.unpack(normalized) if normalized else ({}, [])
            adapted['plans'].append({key: value for key, value in plan.items() if key not in ('parameters', 'kind')} |
                                    {'arguments': arguments, 'bindings': bindings})
        except (ValueError, TypeError, RecursionError) as exc:
            tool = plan.get('tool') if isinstance(plan, dict) else None
            adapted['plans'].append({'tool': tool, 'malformed_evidence_tree': True})
            failures.append({'ordinal': ordinal, 'tool': tool, 'reason': str(exc).split('\n')[0]})
    admitted = _admit_plans(adapted, store, target, proposal_sid)
    admitted['tree_failures'] = failures
    admitted['evidence_representation'] = 'MIXED_TREE_INHERITED_CITATIONS_WITH_TYPED_JSON_SOURCE'
    return admitted


packet = core.packet
selected_proposal = core.selected_proposal
verdict = core.verdict
agreement = core.agreement


def request(store, target, proposal_sid=None):
    return [{'role': 'system', 'content': INSTRUCTION},
            {'role': 'user', 'content': json.dumps(packet(store, target, proposal_sid),
                ensure_ascii=False, separators=(',', ':'))}]
