"""Data model of a parsed transcript (prompt) or agent turn (response).

Every event keeps an exact span into the original string, so a consumer can always quote the
source verbatim. Nothing here interprets meaning: it records structure only.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass(frozen=True)
class Span:
    doc: str      # 'prompt' or 'response'
    start: int
    end: int


@dataclass
class Event:
    index: int
    kind: str                     # 'text' | 'call' | 'result'
    role: str                     # role of the enclosing message: system | user | assistant | unknown
    owner: str                    # who acts: assistant | user | system | unknown
    message: int                  # index of the enclosing Message, -1 before the first header
    span: Span                    # raw span, marker included for calls and results
    body: str                     # text, call arguments, or result payload without transport indent
    tool: Optional[str] = None
    status: Optional[str] = None  # results: 'OK', 'ERROR' or the bracket tag as written (upper case)
    value: Any = None             # decoded JSON (call arguments, JSON result payloads)
    is_json: bool = False
    nested: dict = field(default_factory=dict)   # argument key -> decoded JSON-string argument
    pair: Optional[int] = None    # call <-> result event index
    dialect: str = 'arrow'        # 'arrow' (-> / <- lines), 'header' (official _TOOL_CALL headers), 'text'
    diagnostics: list = field(default_factory=list)

    @property
    def is_error(self) -> bool:
        return self.kind == 'result' and self.status not in (None, 'OK')


@dataclass
class Message:
    index: int
    role: str
    header: str                   # text inside the brackets as written
    number: Optional[int]         # 'ход N' / 'turn N'
    span: Span                    # header start .. next header start
    body_start: int               # first character after the header
    events: list = field(default_factory=list)


@dataclass
class Document:
    doc: str
    text: str
    messages: list
    events: list
    diagnostics: list = field(default_factory=list)

    def calls(self, owner=None):
        return [e for e in self.events if e.kind == 'call' and (owner is None or e.owner == owner)]

    def results(self):
        return [e for e in self.events if e.kind == 'result']

    def texts(self, role=None):
        return [e for e in self.events if e.kind == 'text' and (role is None or e.role == role)]

    def message_body(self, message):
        return self.text[message.body_start:message.span.end]

    def last(self, kind=None, role=None, owner=None, before=None):
        for e in reversed(self.events if before is None else self.events[:before]):
            if (kind is None or e.kind == kind) and (role is None or e.role == role) and \
                    (owner is None or e.owner == owner):
                return e
        return None
