"""Tool-universe closure (contract 3): a closure sentence must be unconditional. The V3 regex made the NOT optional
('never call a tool that is on the list' matched) and accepted 'complete only for read operations'."""
from __future__ import annotations

import re

CLOSED = re.compile(
    r'(?:list|set|catalog(?:ue)?|inventory) of (?:the )?(?:available )?tools (?:above |below )?is (?:complete|exhaustive|closed)'
    r'|tools? list (?:above |below )?is (?:complete|exhaustive)|\bno other tools\b|there are no other tools'
    r'|never (?:call|use|invoke) (?:a|any) tool (?:that is|which is) not (?:on|in|listed)|never (?:call|use|invoke) (?:a|any) tool not (?:on|in|listed)'
    r'|(?:список|перечень) (?:доступных )?инструментов (?:является )?(?:полным|полный|исчерпывающ\w*|закрыт\w*)'
    r'|других инструментов нет|никаких других инструментов|не вызыва\w* инструмент\w*,? (?:которых|которого) нет', re.I)
QUALIFIED = re.compile(r'\bonly for\b|\bexcept\b|\bunless\b|\bbut\b|\bother (?:\w+ )?tools? (?:are|is|may be) (?:allowed|permitted|available)|'
                       r'\bfor (?:read|write)\b|только для|кроме|за исключением|\bно\b', re.I)


def closure_sentence(system_text):
    for sent in re.split(r'(?<=[.!?])\s+|\n+', system_text or ''):
        m = CLOSED.search(sent)
        if m and not QUALIFIED.search(sent):
            return sent.strip()
    return None
