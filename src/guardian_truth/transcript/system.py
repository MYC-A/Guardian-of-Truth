"""System block: preamble, <policy>, [AVAILABLE TOOLS] and the few facts code can read from it.

The preamble itself mentions '<policy>' inline ("according to the <policy> provided below"), so
only tags standing on their own line delimit the policy. Without such tags the policy is the
system text minus the catalog, and policy_tagged=False says so.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from .catalog import Catalog, find_catalog, parse_catalog

POLICY_OPEN = re.compile(r'^[ \t]*<policy>[ \t]*$', re.M | re.I)
POLICY_CLOSE = re.compile(r'^[ \t]*</policy>[ \t]*$', re.M | re.I)
CURRENT_TIME = re.compile(r'\bcurrent\s+(?:time|date)\s+is\s+(\d{4}-\d{2}-\d{2})(?:[ T](\d{1,2}:\d{2}(?::\d{2})?))?'
                          r'(?:\s*([A-Z]{2,5})\b)?', re.I)
ONE_CALL = re.compile(r'\bone\s+tool\s+call\s+at\s+a\s+time\b', re.I)
EXCLUSIVE = re.compile(r'cannot\s+do\s+both|should\s+not\s+respond\s+to\s+the\s+user\s+(?:at\s+the\s+same\s+time|'
                       r'simultaneously)|should\s+not\s+make\s+a\s+tool\s+call\s+at\s+the\s+same\s+time', re.I)
LANGUAGE = re.compile(r'communicate\s+with\s+the\s+user\s+in\s+([A-Za-z]+)', re.I)
TRANSFER_PHRASE = re.compile(r"send\s+the\s+message\s+'([^']+)'", re.I)


@dataclass
class SystemInfo:
    present: bool
    start: int
    end: int
    policy: Optional[tuple] = None          # (start, end) absolute
    policy_tagged: bool = False
    preamble: Optional[tuple] = None
    catalog: Catalog = field(default_factory=lambda: Catalog(False))
    current_time: Optional[dict] = None
    one_call_rule: bool = False
    exclusive_rule: bool = False
    language: Optional[str] = None
    transfer_phrase: Optional[str] = None
    issues: list = field(default_factory=list)

    def policy_text(self, prompt):
        return prompt[self.policy[0]:self.policy[1]] if self.policy else ''

    def region_of(self, pos):
        """'catalog' | 'policy' | 'preamble' | None for a position in the prompt."""
        if not self.present or not (self.start <= pos < self.end):
            return None
        if self.catalog.present and self.catalog.start <= pos < self.catalog.end:
            return 'catalog'
        if self.policy and self.policy[0] <= pos < self.policy[1]:
            return 'policy'
        return 'preamble'


def parse_system(document):
    """SystemInfo of a parsed prompt Document."""
    text = document.text
    system = next((m for m in document.messages if m.role == 'system'), None)
    if system is None:
        first = document.messages[0].span.start if document.messages else len(text)
        info = SystemInfo(False, 0, first, issues=['NO_SYSTEM_MESSAGE'])
        start, end = 0, first
    else:
        start, end = system.body_start, system.span.end
        info = SystemInfo(True, start, end)
    region = text[start:end]
    cat_at = find_catalog(text, start, end)
    po = list(POLICY_OPEN.finditer(region))
    pc = list(POLICY_CLOSE.finditer(region))
    if po and pc and pc[-1].start() > po[0].end():
        info.policy = (start + po[0].end(), start + pc[-1].start())
        info.policy_tagged = True
        info.preamble = (start, start + po[0].start())
        if len(po) > 1 or len(pc) > 1:
            info.issues.append('SEVERAL_POLICY_TAGS')
    else:
        info.policy = (start, cat_at if cat_at >= 0 else end)
        info.issues.append('POLICY_NOT_TAGGED')
    cat_end = end
    if cat_at >= 0 and info.policy_tagged and info.policy[0] <= cat_at < info.policy[1]:
        cat_end = info.policy[1]
        info.issues.append('CATALOG_INSIDE_POLICY')
    info.catalog = parse_catalog(text, cat_at, cat_end)
    system_text = text[start:end]
    m = CURRENT_TIME.search(system_text)
    if m:
        info.current_time = dict(date=m.group(1), time=m.group(2), zone=m.group(3), source='system',
                                 pos=start + m.start())
    info.one_call_rule = bool(ONE_CALL.search(system_text))
    info.exclusive_rule = bool(EXCLUSIVE.search(system_text))
    lm = LANGUAGE.search(system_text)
    info.language = lm.group(1).lower() if lm else None
    tm = TRANSFER_PHRASE.search(system_text)
    info.transfer_phrase = tm.group(1) if tm else None
    return info


def current_time(document, info):
    """Latest known 'current time': the last get_current_time-like result, else the system clock."""
    for e in reversed(document.events):
        if e.kind == 'result' and not e.is_error:
            m = CURRENT_TIME.search(e.body)
            if m:
                return dict(date=m.group(1), time=m.group(2), zone=m.group(3), source='tool:' + (e.tool or ''),
                            pos=e.span.start)
    return info.current_time
