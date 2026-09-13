"""Target-role-preserving source normalization for the new invocation path.

The target is ASSISTANT output. Embedded SYSTEM/USER/TOOL-result markers cannot
create privileged source events or confirmed effects. Existing candidate-action
serialization is retained; this does not authenticate arbitrary raw transcripts.
"""

from dataclasses import replace

from .normalize import normalize


def normalize_source(prompt, response, *, tool_identities=()):
    events = []
    for event in normalize(prompt, response, tool_identities=tool_identities):
        if event.source.document != 'response':
            events.append(event)
        elif event.kind == 'call' and event.actor == 'assistant':
            # A candidate invocation, never a completed business operation.
            events.append(event)
        else:
            events.append(replace(event, actor='assistant', kind='text', tool=None,
                call_id=None, call_candidates=(), requestor=None, pairing_issue=None))
    return tuple(events)
