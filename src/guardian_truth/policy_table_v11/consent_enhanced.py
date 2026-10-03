"""Certified protocol extensions; free prose belongs in consent_pair_v4.

An unbound natural-language candidate never establishes consent. In particular,
finding only some arguments, an action word or an entity prefix is insufficient.
The semantic parser is measured separately and never promoted to a code witness.
"""
import re
from dataclasses import replace

from guardian_truth.parsing import parse_catalog
from guardian_truth.policy_table.evaluate import Value, same
from .consent import action_frame, explicit_confirmation, reply_kind, words
from .witness import timeline


def canonical_description(text):
    # A closed syntax extension of the existing explicit tool+JSON protocol.
    # No business verb, argument name, entity or effect is inferred here.
    return re.sub(r'^I\s+will\s+now\s+call\s+', 'I will call ', text.strip(),
                  count=1, flags=re.I)


def enhanced_action_frame(text, declared, catalog=None):
    names = declared.tools if hasattr(declared, 'tools') else declared
    frame = action_frame(canonical_description(text), names)
    if frame is None:
        return None
    return {**frame, 'method': 'CERTIFIED_EXPLICIT_TOOL_JSON'}


def extract_args_from_natural_language(text, tool, catalog):
    """Compatibility entry point: ambiguous prose has no certified arguments."""
    return None


def enhanced_reply_kind(text):
    # Inspect the complete reply; never strip an uninspected free-text tail.
    classified = reply_kind(text)
    if classified != 'UNCLEAR':
        return classified
    if any(char in text for char in '«»"'):
        return 'UNCLEAR'
    if words(text) in {'no objections', 'no problem', 'no worries',
                       'нет возражений', 'нет проблем', 'sure', 'absolutely',
                       'certainly', 'of course', 'definitely', 'конечно',
                       'разумеется', 'безусловно', 'естественно'}:
        return 'AFFIRM'
    return 'UNCLEAR'


def explicit_confirmation_enhanced(store, target, events):
    """Check a genuine native call using the unchanged full-argument protocol.

    Free-prose extraction is available through consent_pair_v4.admit/verdict and
    retains SHADOW_MODEL_SEMANTICS. It cannot feed this code-only Value resolver.
    """
    source = store.sources.get(target.get('source_id'))
    if not source or source['kind'] != 'call' or source['role'] != 'assistant':
        return Value('UNRESOLVED', reason='target_not_native_assistant_call')
    actual = (store.history_events if source['document'] == 'prompt'
              else store.target_events)[source['event']]
    if (not actual.json_valid or not isinstance(actual.value, dict)
            or actual.name != target.get('tool')
            or not same(actual.value, target.get('arguments'))):
        return Value('UNRESOLVED', reason='target_arguments_invalid_or_changed')
    original = timeline(store, target)
    if events != original:
        return Value('UNRESOLVED', reason='timeline_not_native_source')
    declarations = parse_catalog(store.history_events, store.raw['prompt']).tools
    normalized = []
    for sid, event in original:
        text = event.text
        if event.role == 'assistant' and event.kind == 'text':
            if enhanced_action_frame(text, declarations) is not None:
                text = canonical_description(text)
        elif event.role == 'user' and event.kind == 'text':
            classification = enhanced_reply_kind(text)
            if classification in ('AFFIRM', 'REFUSE'):
                text = 'Yes' if classification == 'AFFIRM' else 'No'
        normalized.append((sid, replace(event, text=text)))
    return explicit_confirmation(store, target, normalized)
