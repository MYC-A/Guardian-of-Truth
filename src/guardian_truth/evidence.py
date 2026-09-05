"""Small evidence packets backed by original spans; not a replacement for context."""

import re

from .types import Event, Observation, Source


def leaves(value, path=()):
    if isinstance(value, dict):
        for key, item in value.items(): yield from leaves(item, (*path, key))
    elif isinstance(value, list):
        for index, item in enumerate(value): yield from leaves(item, (*path, index))
    else:
        yield list(path), value


def observations(events: list[Event]) -> list[Observation]:
    result = []
    for index, event in enumerate(events):
        if event.kind == "result" and event.json_valid:
            for path, value in leaves(event.value):
                result.append(Observation(index, event.name or "", path, value, event.source))
    # Preserve all versions and their source event; do not merge unrelated entities.
    return result


def retrieve(events: list[Event], prompt: str, response: str, max_chars: int = 12000) -> list[Source]:
    terms = set(re.findall(r'[\w#@.-]{3,}', response.casefold()))
    candidates = []
    for event in events:
        # Chunks preserve exact offsets even inside a long result.
        for start in range(event.source.start, event.source.end, 1600):
            end = min(start + 2000, event.source.end)
            text = prompt[start:end].casefold()
            score = len(terms & set(re.findall(r'[\w#@.-]{3,}', text)))
            if score:
                candidates.append((score, Source(event.source.document, start, end)))
    candidates.sort(key=lambda item: (-item[0], item[1].start))
    selected, used = [], 0
    for _, source in candidates:
        length = source.end - source.start
        if used + length <= max_chars:
            selected.append(source)
            used += length
    return sorted(selected, key=lambda source: source.start)
