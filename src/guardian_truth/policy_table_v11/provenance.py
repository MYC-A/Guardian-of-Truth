"""Checked native observations. A tool result alone is not an observation receipt."""
from dataclasses import dataclass
from guardian_truth.policy_table.evaluate import same


@dataclass(frozen=True)
class Observation:
    call_sid: str | None
    result_sid: str
    call: object
    result: object
    reason: str | None

    @property
    def valid(self): return self.reason is None


def observations(events, name):
    pending = []
    for sid, event in events:
        if event.name != name: continue
        if event.kind == 'call':
            pending.append((sid, event)); continue
        if event.kind != 'result': continue
        call_sid, call = pending[0] if len(pending) == 1 else (None, None)
        reason = None
        if len(pending) != 1: reason = 'result_without_unique_call'
        elif call.role != 'assistant': reason = 'call_actor_not_assistant'
        elif not call.json_valid or not isinstance(call.value, dict): reason = 'call_arguments_invalid'
        # Native result markers inherit assistant role in our trace format.
        if event.role != 'assistant': reason = 'result_actor_not_assistant'
        yield Observation(call_sid, sid, call, event, reason)
        pending = []


def target_is_assistant(store, target):
    source = store.sources.get(target.get('source_id'))
    if not source or source['role'] != 'assistant': return False
    if source['document'] not in ('prompt', 'response') or source['kind'] != 'call': return False
    events = store.history_events if source['document'] == 'prompt' else store.target_events
    event = events[source['event']]
    return (event.json_valid and isinstance(event.value, dict) and event.name == target.get('tool')
            and same(event.value, target.get('arguments')))


def lineage_matches(arguments, identity, layers, required):
    """No overwriting parent identities; every available anchor must agree.

    `layers` are dictionaries on one traversal path, never a union of siblings.
    Read-call arguments can prove identity but cannot overwrite a contradictory result.
    """
    proven = set()
    for layer in [arguments, *layers]:
        for key in set(identity) & set(layer):
            if not same(identity[key], layer[key]): return False
            proven.add(key)
    return required <= proven
