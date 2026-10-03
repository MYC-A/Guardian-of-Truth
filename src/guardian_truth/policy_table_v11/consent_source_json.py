"""Strict structured source evidence; never infer action or consent semantics.

The stdlib decoder supplies typed values and the repository hooks reject duplicate
keys/nonfinite numbers. Parse whole containers, not substrings inside JSON strings
or a conveniently matching nested value. A conflicting complete object cannot be
overruled by finding each scalar somewhere in the same source.
"""
import json

from guardian_truth.parsing import finite_float, reject_constant, unique_object
from guardian_truth.policy_table.evaluate import same

from .consent_pair_v2 import _supported as lexical_supported


DECODER = json.JSONDecoder(object_pairs_hook=unique_object,
                          parse_constant=reject_constant, parse_float=finite_float)


def _end(text, start):
    stack, quoted, escaped = [], False, False
    for index in range(start, len(text)):
        char = text[index]
        if quoted:
            if escaped:
                escaped = False
            elif char == '\\':
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in '{[':
            stack.append(char)
        elif char in '}]':
            if not stack or (stack.pop(), char) not in (('{', '}'), ('[', ']')):
                raise ValueError('malformed_source_json_container')
            if not stack:
                return index + 1
    raise ValueError('incomplete_source_json_container')


def source_containers(text):
    """Complete outermost JSON containers with their exact character positions."""
    if len(text) > 200_000:
        raise ValueError('source_json_text_too_long')
    out, index = [], 0
    while index < len(text):
        if text[index] in '}]':
            raise ValueError('unmatched_source_json_closer')
        if text[index] not in '{[':
            index += 1
            continue
        end = _end(text, index)
        value, parsed_end = DECODER.raw_decode(text, index)
        if parsed_end != end:
            raise ValueError('source_json_boundary_mismatch')
        out.append({'value': value, 'start': index, 'end': end})
        if len(out) > 512:
            raise ValueError('too_many_source_json_containers')
        index = end  # Do not search nested objects or JSON-looking string values.
    return out


def _objects(value, depth=0):
    if depth > 40:
        raise ValueError('source_json_too_deep')
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _objects(child, depth + 1)
    elif isinstance(value, list):
        for child in value:
            yield from _objects(child, depth + 1)


def _ancestors(arguments, path):
    value = arguments
    yield value
    for part in path.split('/')[1:]:
        part = part.replace('~1', '/').replace('~0', '~')
        value = value[int(part)] if isinstance(value, list) else value[part]
        if isinstance(value, (dict, list)):
            yield value


def support_mode(value, texts, arguments, path):
    """Require typed full-object equality when a complete argument object is cited.

    Otherwise preserve the frozen lexical check. This fallback establishes only
    value occurrence, not parameter roles in prose. Consequently all admissions
    using this module remain SHADOW_MODEL_SEMANTICS / code_proof=false.
    """
    roots = [root['value'] for text in texts for root in source_containers(text)]
    per_root = [[node for node in _objects(root) if arguments and set(arguments).issubset(node)]
                for root in roots]
    complete = [node for nodes in per_root for node in nodes]
    if complete:
        # A partial replacement or another container on the same cited line
        # cannot be silently ignored. Span IDs identify whole source lines;
        # resolving which container overrides which requires finer source scope.
        if any(not nodes for nodes in per_root):
            raise ValueError('unreconciled_structured_source_container')
        if not all(same(root, arguments) for root in complete):
            raise ValueError('structured_argument_object_mismatch_or_ambiguity')
        return 'EXACT_TYPED_ARGUMENT_OBJECT'
    # A cited partial object may still give exact structural evidence for the
    # container enclosing this binding path. No business field names are assumed.
    ancestors = list(_ancestors(arguments, path))
    comparable = []
    for root in roots:
        candidates = [ancestor for ancestor in ancestors
            if (isinstance(root, dict) and isinstance(ancestor, dict) and root.keys() == ancestor.keys())
            or (isinstance(root, list) and isinstance(ancestor, list))]
        if candidates:
            if not all(same(root, ancestor) for ancestor in candidates):
                raise ValueError('structured_argument_ancestor_mismatch_or_ambiguity')
            comparable.append(root)
    if comparable:
        if len(comparable) != len(roots):
            raise ValueError('unreconciled_structured_source_container')
        return 'EXACT_TYPED_ARGUMENT_ANCESTOR_MODEL_BOUND_PREFIX'
    if lexical_supported(value, texts):
        return 'LEXICAL_VALUE_OCCURRENCE_ONLY'
    raise ValueError('leaf_value_not_source_supported')
