"""Where does a value occur in the context, and in what kind of source.

Source kinds: preamble | policy | catalog | user_text | assistant_text | assistant_call |
user_call | tool_result (agent's tools) | user_tool_result (user's own device tools) | other.
A value that occurs only in the catalog (the '#W0000000' examples) or only inside another
token ('3019' in an e-mail address) is not grounded; consumers decide what that means.
"""
from __future__ import annotations

import bisect
from dataclasses import dataclass

from .values import compact, find_token, parse_numbers

GROUNDING_KINDS = frozenset({'user_text', 'tool_result', 'user_tool_result', 'policy', 'user_call'})


@dataclass(frozen=True)
class Hit:
    kind: str
    pos: int
    bounded: bool
    event: int


def _event_kind(e):
    if e.kind == 'text':
        return {'user': 'user_text', 'assistant': 'assistant_text'}.get(e.role, 'other')
    if e.kind == 'call':
        return {'user': 'user_call', 'assistant': 'assistant_call'}.get(e.owner, 'other')
    if e.is_error:
        return 'failed_tool_result'
    return 'user_tool_result' if e.owner == 'user' else 'tool_result'


class ContextIndex:
    def __init__(self, document, system):
        self.doc, self.system = document, system
        self.text = document.text
        self.lower = self.text.lower()
        self._starts = [e.span.start for e in document.events]
        self._compact = None
        self._numbers = None

    def kind_at(self, pos):
        region = self.system.region_of(pos) if self.system is not None else None
        if region:
            return region, -1
        i = bisect.bisect_right(self._starts, pos) - 1
        if i >= 0:
            e = self.doc.events[i]
            if e.span.start <= pos < e.span.end:
                return _event_kind(e), e.index
        return 'other', -1

    def locate(self, value, limit=200):
        hits = []
        for pos, bounded in find_token(self.lower, str(value), limit):
            kind, event = self.kind_at(pos)
            hits.append(Hit(kind, pos, bounded, event))
        return hits

    def grounded(self, value, kinds=GROUNDING_KINDS):
        """Occurrence category, not proof of semantic support or entity identity."""
        hits = self.locate(value)
        good = [h for h in hits if h.kind in kinds]
        if any(h.bounded for h in good):
            return 'bounded'
        if good:
            return 'inside_token'
        if hits and all(h.kind == 'catalog' for h in hits):
            return 'catalog_only'
        if any(h.kind == 'failed_tool_result' and h.bounded for h in hits):
            return 'failed_result_only'
        if any(h.kind in ('assistant_text', 'assistant_call') and h.bounded for h in hits):
            return 'assistant_only'
        c = compact(value)
        if len(c) >= 4:
            if self._compact is None:
                self._compact = compact(self.text)
            if c in self._compact:
                return 'compact'
        return 'absent'

    def numbers(self):
        """{value: set(kinds)} for every number in grounding sources."""
        if self._numbers is None:
            found = {}
            for e in self.doc.events:
                kind = _event_kind(e)
                if kind not in GROUNDING_KINDS:
                    continue
                for nm in parse_numbers(e.body):
                    for v in nm.values:
                        found.setdefault(v, set()).add(kind)
            if self.system is not None and self.system.policy:
                for nm in parse_numbers(self.system.policy_text(self.text)):
                    for v in nm.values:
                        found.setdefault(v, set()).add('policy')
            self._numbers = found
        return self._numbers

    def number_derivable(self, values, pair_pool=150):
        """True when one reading of the number occurs in grounding sources, or is a sum/difference of
        two of them, or a small multiple of one. This does not establish semantic support."""
        known = self.numbers()
        if any(v in known for v in values):
            return True
        pool = sorted(known)[:pair_pool] if len(known) > pair_pool else list(known)
        for v in values:
            for a in known:
                for k in (2, 3, 4, 5, 6, 7, 8, 9, 10):
                    if abs(a * k - v) < 0.006:
                        return True
            for i, a in enumerate(pool):
                for b in pool[i:]:
                    if abs(a + b - v) < 0.006 or abs(abs(a - b) - v) < 0.006:
                        return True
        return False
