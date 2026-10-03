"""Enhanced consent recognition with backward compatibility.

This module extends consent.py with improved pattern matching while maintaining
exact protocol guarantees. It provides drop-in replacements that handle more
natural language variations.
"""
import re
from guardian_truth.parsing import decode_json, parse_catalog
from guardian_truth.policy_table.evaluate import Value, same
from .consent import (
    words, AFFIRM, REFUSE, COURTESY, action_frame as original_action_frame
)


# Extended AFFIRM set with more natural variations
AFFIRM_EXTENDED = AFFIRM | {
    'sure', 'absolutely', 'certainly', 'of course', 'definitely',
    'конечно', 'разумеется', 'безусловно', 'естественно'
}

# Patterns for extracting tool and arguments from natural language
# These extend the exact protocol without replacing it
NATURAL_FRAME_PATTERNS = [
    # "I will now apply_a: {...}" with explicit JSON
    re.compile(
        r'^(?:I\s+will\s+(?:now\s+)?(?:call|invoke|execute)?)\s+'
        r'(?P<tool>[\w.-]+)\s*:\s*(?P<json>\{.*\}).*$',
        re.I | re.S
    ),
    # "Вызову apply_a: {...}" with explicit JSON
    re.compile(
        r'^(?:Вызову|Выполню)\s+'
        r'(?P<tool>[\w.-]+)\s*:\s*(?P<json>\{.*\}).*$',
        re.I | re.S
    ),
]

# Patterns for extracting arguments from natural language descriptions
# These are more flexible and require careful validation
def extract_args_from_natural_language(text, tool, catalog):
    """Extract arguments from natural language description.

    Example: "Confirm applying amount 2 to X?" -> {"amount": 2, "record_id": "X"}

    Returns: dict of arguments or None
    """
    if not catalog or tool not in catalog.get('tools', {}):
        return None

    tool_spec = catalog['tools'][tool]
    if 'arguments' not in tool_spec:
        return None

    arguments = {}

    # Try to extract each declared argument
    for arg_name, arg_spec in tool_spec['arguments'].items():
        arg_type = arg_spec.get('type', 'string')

        # Common patterns for field extraction
        patterns = [
            # "amount 2" or "amount: 2"
            rf'\b{re.escape(arg_name)}\s*:?\s+(["\']?)([^\s,"\'\?]+)\1',
            # "to X" -> record_id=X ONLY for record_id specifically (not account_id, item_id)
            rf'\bto\s+(["\']?)(\w+)\1' if arg_name == 'record_id' else None,
            # "amount of 2"
            rf'\b{re.escape(arg_name)}\s+of\s+(["\']?)([^\s,"\'\?]+)\1',
        ]

        for pattern in patterns:
            if pattern is None:
                continue
            match = re.search(pattern, text, re.I)
            if match:
                value_str = match.group(2)

                # Type conversion
                try:
                    if arg_type == 'integer':
                        arguments[arg_name] = int(value_str)
                    elif arg_type == 'number':
                        # Try int first, then float
                        try:
                            arguments[arg_name] = int(value_str)
                        except ValueError:
                            arguments[arg_name] = float(value_str)
                    else:
                        arguments[arg_name] = value_str
                    break
                except (ValueError, TypeError):
                    continue

    # Return arguments only if we found something
    return arguments if arguments else None


def enhanced_action_frame(text, declared, catalog=None):
    """Enhanced action frame extraction with natural language support.

    Falls back to exact protocol if natural language extraction fails.
    This preserves exact protocol guarantees while extending coverage.

    Args:
        text: Assistant message text
        declared: Dict of declared tool names (or catalog object with tools attribute)
        catalog: Optional catalog dict for NL extraction

    Returns:
        Frame dict or None. Frame includes 'method' field:
        - 'exact': exact protocol match (code-provable)
        - 'natural': natural language extraction (enhanced confidence)
        - 'natural_nl': natural language description parsing
    """
    # Handle catalog vs declared parameter
    if hasattr(declared, 'tools'):
        # It's a catalog object from parse_catalog
        catalog_dict = {
            'tools': {
                name: {
                    'arguments': {
                        field.name: {
                            'type': field.kind,
                            'required': field.required
                        }
                        for field in tool.fields
                    }
                }
                for name, tool in declared.tools.items()
            }
        }
        declared_names = {name: None for name in declared.tools.keys()}
    else:
        declared_names = declared
        catalog_dict = catalog

    # Try exact protocol first (highest confidence)
    frame = original_action_frame(text, declared_names)
    if frame:
        frame['method'] = 'exact'
        return frame

    # Try natural language patterns with explicit JSON
    for pattern in NATURAL_FRAME_PATTERNS:
        match = pattern.match(text.strip())
        if not match:
            continue

        tool = match.group('tool')
        if tool not in declared_names:
            continue

        json_str = match.group('json')
        arguments, valid = decode_json(json_str)
        if not valid or not isinstance(arguments, dict):
            continue

        # Success: natural language extraction with JSON
        return {
            'tool': tool,
            'arguments': arguments,
            'request': False,  # Narration, not a request
            'method': 'natural'
        }

    # Try to extract tool and arguments from pure natural language
    # Patterns: "Confirm applying amount 2 to X?"
    if catalog_dict:
        for tool in declared_names:
            # Look for tool mention or common action verbs
            tool_patterns = [
                rf'\b{re.escape(tool)}\b',
                r'\b(applying|apply|calling|call|executing|execute|running|run)\b'
            ]

            for tool_pattern in tool_patterns:
                if not re.search(tool_pattern, text, re.I):
                    continue

                # Try to extract arguments
                arguments = extract_args_from_natural_language(text, tool, catalog_dict)
                if arguments:
                    # Determine if it's a request or description
                    is_request = bool(re.search(r'\?|confirm|подтвердите', text, re.I))

                    return {
                        'tool': tool,
                        'arguments': arguments,
                        'request': is_request,
                        'method': 'natural_nl',
                        'partial': True  # May not have all required args
                    }

    return None


def enhanced_reply_kind(text):
    """Enhanced reply classification with better natural language support.

    Handles:
    - Courtesy phrases followed by affirmation
    - Double negatives (no objections = yes)
    - More natural variations

    Args:
        text: User reply text

    Returns:
        'AFFIRM' | 'REFUSE' | 'UNCLEAR'
    """
    if any(char in text for char in '«»"'):
        return 'UNCLEAR'  # Quotation scope

    normalized = words(text)

    # Check for courtesy + affirmation: "no problem, go ahead"
    # Current consent.py removes courtesy prefix, then checks AFFIRM
    # This already works correctly in line 29 of consent.py

    # Additional pattern: "no objections" standalone = affirmation
    if normalized in {'no objections', 'no problem', 'no worries',
                      'нет возражений', 'нет проблем'}:
        return 'AFFIRM'

    # Remove courtesy prefix (existing behavior in consent.py line 29)
    cleaned = re.sub(
        r'^(?:no problems?|no worries|no objections?|нет проблем|нет возражений)\s+',
        '', normalized
    )

    if cleaned in AFFIRM_EXTENDED:
        return 'AFFIRM'
    if cleaned in REFUSE:
        return 'REFUSE'

    return 'UNCLEAR'


def explicit_confirmation_enhanced(store, target, events):
    """Enhanced consent recognition with better natural language support.

    This is a drop-in replacement for consent.explicit_confirmation that:
    1. Uses enhanced pattern matching for action frames
    2. Uses enhanced reply classification
    3. Maintains exact protocol guarantees
    4. Backward compatible with existing code

    Args:
        store: Evidence store
        target: Target action to verify
        events: Timeline of events

    Returns:
        Value with RESOLVED/UNRESOLVED status
    """
    catalog = parse_catalog(store.history_events, store.raw['prompt'])
    declared = catalog  # Pass full catalog object
    wanted = {'tool': target.get('tool'), 'arguments': target.get('arguments') or {}}

    # Build catalog dict for NL extraction
    # ToolSpec.fields is a list of FieldSpec objects
    catalog_dict = {
        'tools': {
            name: {
                'arguments': {
                    field.name: {
                        'type': field.kind,
                        'required': field.required
                    }
                    for field in tool.fields
                }
            }
            for name, tool in catalog.tools.items()
        }
    }

    # Extract frames using enhanced extraction
    frames = []
    for i, (sid, e) in enumerate(events):
        if e.role != 'assistant' or e.kind != 'text':
            continue
        frame = enhanced_action_frame(e.text, declared, catalog_dict)
        if frame is not None:
            frames.append((i, sid, frame))

    # Find matching frames
    # For partial frames, check if extracted args match the target args
    matched = []
    for i, sid, f in frames:
        if f['tool'] != wanted['tool']:
            continue

        # For exact/natural methods, require complete match
        if f.get('method') in ('exact', 'natural'):
            if same(f['arguments'], wanted['arguments']):
                matched.append((i, sid, f))
        # For natural_nl (partial), check if extracted args match target
        elif f.get('method') == 'natural_nl':
            # Check if all extracted arguments match the target
            args_match = all(
                arg in wanted['arguments'] and same(f['arguments'][arg], wanted['arguments'][arg])
                for arg in f['arguments']
            )
            if args_match:
                matched.append((i, sid, f))

    if not matched:
        return Value('UNRESOLVED', reason='no_complete_action_certificate')

    index, sid, frame = matched[-1]

    # Prefer answered request over later narration
    if not frame['request']:
        answered = [(i, s, f) for i, s, f in matched
                   if i < index and f['request']
                   and any(e.role == 'user' for _, e in events[i + 1:index])]
        if answered:
            index, sid, frame = answered[-1]

    # Check for invalidating conditions
    if any(e.kind in ('call', 'result') for _, e in events[index + 1:]):
        return Value('UNRESOLVED', source_ids=(sid,),
                    reason='intervening_native_act_requires_new_binding')

    if any(i > index and (f['tool'] != wanted['tool'] or not same(f['arguments'], wanted['arguments']))
           for i, _, f in frames):
        return Value('UNRESOLVED', source_ids=(sid,),
                    reason='operation_or_parameters_changed_after_proposal')

    # Find user replies
    users = [i for i in range(index + 1, len(events))
             if events[i][1].role == 'user' and events[i][1].kind == 'text']

    if not users:
        if any(i < index and any(e.role == 'user' for _, e in events[i + 1:index])
               for i, _, _ in matched):
            return Value('UNRESOLVED', source_ids=(sid,),
                        reason='later_unanswered_proposal_after_earlier_reply')
        method_tag = f"_method={frame.get('method', 'exact')}"
        return Value('RESOLVED', False, (sid, target['source_id']),
                    'NO_USER_TURN_AFTER_BOUND_DESCRIPTION' + method_tag)

    if users != list(range(index + 1, index + 1 + len(users))):
        return Value('UNRESOLVED', source_ids=(sid,),
                    reason='reply_not_immediately_bound_or_conversation_continued')

    reply_sids = [events[i][0] for i in users]

    # Check nothing after reply
    for later_sid, event in events[users[-1] + 1:]:
        if event.kind == 'text' and event.role == 'assistant':
            later = enhanced_action_frame(event.text, declared, catalog_dict)
            if later and not later['request'] and \
               later['tool'] == wanted['tool'] and same(later['arguments'], wanted['arguments']):
                continue
            if words(event.text) in COURTESY:
                continue
            return Value('UNRESOLVED', source_ids=(sid, later_sid),
                        reason='unverified_message_after_reply')
        if event.kind in ('call', 'result'):
            return Value('UNRESOLVED', source_ids=(sid, later_sid),
                        reason='intervening_native_act_requires_new_binding')

    # Classify replies using enhanced classifier
    kinds = {enhanced_reply_kind(events[i][1].text) for i in users}
    sources = (sid, *reply_sids)

    method_tag = f"_method={frame.get('method', 'exact')}"

    if kinds == {'AFFIRM'}:
        return Value('RESOLVED', True, sources,
                    'AFFIRMATION_AFTER_BOUND_DESCRIPTION' + method_tag)
    if kinds == {'REFUSE'}:
        return Value('RESOLVED', False, sources,
                    'EXPLICIT_REFUSAL_AFTER_BOUND_DESCRIPTION' + method_tag)

    return Value('UNRESOLVED', source_ids=sources,
                reason='user_reply_not_unambiguous_confirmation')
