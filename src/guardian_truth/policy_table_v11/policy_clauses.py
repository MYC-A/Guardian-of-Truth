"""Turn-shape rules that the system policy states explicitly (no LLM, no dataset IDs).

A rule fires only when the policy text itself contains the clause; the verdict cites
the exact span. Policies without such wording are unaffected.

* MULTIPLE_TOOL_CALLS_IN_STEP: policy says "one tool call at a time" and the step
  under evaluation issues more than one tool call.
* CALL_WITH_USER_MESSAGE: policy says a tool call must not be combined with a
  message to the user, and the step does both.
"""
import re
from guardian_truth.policy_table.segment import system_text

_ONE_CALL = re.compile(r'[^\n.]*\b(?:only|at\s+most)\s+make\s+one\s+tool\s+call\s+at\s+a\s+time[^\n.]*', re.I)
_NO_BOTH = re.compile(r'[^\n.]*(?:\bif\s+you\s+(?:make|take)\s+a\s+tool\s+call,?\s+you\s+should\s+not\s+respond\s+to\s+the\s+user'
                      r'|\byou\s+cannot\s+do\s+both\s+at\s+the\s+same\s+time)[^\n.]*', re.I)


def _clause(pattern, text):
    m = pattern.search(text or '')
    return None if m is None else {'quote': m.group(0).strip(), 'span': [m.start(), m.end()]}


def turn_shape_violations(store, route):
    text = system_text(store)
    out = []
    calls = len(route.call_source_ids) + len(route.malformed_call_source_ids)
    if calls > 1:
        c = _clause(_ONE_CALL, text)
        if c: out.append({'code': 'MULTIPLE_TOOL_CALLS_IN_STEP', 'calls': calls, 'clause_quote': c['quote'],
                          'source_ids': list(route.call_source_ids)})
    if calls and route.prose_source_ids:
        c = _clause(_NO_BOTH, text)
        if c: out.append({'code': 'CALL_WITH_USER_MESSAGE', 'clause_quote': c['quote'],
                          'source_ids': list(route.call_source_ids) + list(route.prose_source_ids)})
    return out
