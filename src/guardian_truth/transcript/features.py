"""Structural facts about the agent turn under review.

Three tiers, so that code never pretends to judge meaning:
  hard     provable from structure alone (tool absent from a complete catalog and never run
           successfully, schema violation, arguments not an object). Each kind must still have
           its precision measured on labelled data before it may force a label.
  strong   specific, usually decisive facts (identical retry of a call that returned an error,
           argument value found only inside another token or only in catalog examples, ...).
  weak     context for a judge (refusal wording, completion claim, numbers not found, ...).
Every finding is also a feature (flat dict) for a trained aggregator, and a one-line English
hint for an LLM judge. Wording patterns cover Russian (dialogue language) and English.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .catalog import validate_arguments
from .parser import document_stats, parse_document
from .provenance import ContextIndex
from .system import current_time, parse_system
from .values import extract_identifiers, parse_dates, parse_numbers, value_kind

REFUSAL = re.compile(
    '\u043a\\s+\u0441\u043e\u0436\u0430\u043b\u0435\u043d\u0438\u044e|\u043d\u0435\\s+\u043c\u043e\u0433\u0443|\u043d\u0435\\s+\u0441\u043c\u043e\u0433\u0443|\u043d\u0435\u0432\u043e\u0437\u043c\u043e\u0436\u043d\u043e|\u043d\u0435\\s+\u0443\u0434\u0430\u0441\u0442\u0441\u044f|'
    '\u043d\u0435\\s+\u043f\u043e\u043b\u0443\u0447\u0438\u0442\u0441\u044f|\u043d\u0435\u0442\\s+\u0432\u043e\u0437\u043c\u043e\u0436\u043d\u043e\u0441\u0442\u0438|\u043d\u0435\\s+\u0438\u043c\u0435\u044e\\s+\u0432\u043e\u0437\u043c\u043e\u0436\u043d\u043e\u0441\u0442\u0438|'
    '\u043d\u0435\\s+\u0440\u0430\u0437\u0440\u0435\u0448\u0435\u043d|\u043d\u0435\\s+\u0434\u043e\u043f\u0443\u0441\u043a\u0430\u0435\u0442\u0441\u044f|\u043d\u0435\\s+\u043f\u0440\u0435\u0434\u0443\u0441\u043c\u043e\u0442\u0440\u0435\u043d|\u043d\u0435\\s+\u043f\u043e\u0434\u043b\u0435\u0436\u0438\u0442|\u043d\u0435\u043b\u044c\u0437\u044f|'
    "unable\\s+to|cannot|can't|can\\s+not|not\\s+able\\s+to|not\\s+possible|not\\s+eligible|unfortunately|"
    "i'm\\s+afraid|not\\s+allowed|not\\s+permitted", re.I)
DONE = re.compile(
    '\u0443\u0441\u043f\u0435\u0448\u043d\u043e|(?:\u044f\\s+)?(?:\u043e\u0442\u043c\u0435\u043d\u0438\u043b|\u0438\u0437\u043c\u0435\u043d\u0438\u043b|\u043e\u0431\u043d\u043e\u0432\u0438\u043b|\u043e\u0444\u043e\u0440\u043c\u0438\u043b|\u0437\u0430\u0431\u0440\u043e\u043d\u0438\u0440\u043e\u0432\u0430\u043b|\u0432\u0435\u0440\u043d\u0443\u043b|\u0432\u044b\u043f\u043e\u043b\u043d\u0438\u043b|'
    '\u043e\u0442\u043f\u0440\u0430\u0432\u0438\u043b|\u0437\u0430\u0431\u043b\u043e\u043a\u0438\u0440\u043e\u0432\u0430\u043b|\u0440\u0430\u0437\u0431\u043b\u043e\u043a\u0438\u0440\u043e\u0432\u0430\u043b|\u0430\u043a\u0442\u0438\u0432\u0438\u0440\u043e\u0432\u0430\u043b|\u0437\u0430\u043a\u0440\u044b\u043b|\u043e\u0442\u043a\u0440\u044b\u043b|\u043f\u0435\u0440\u0435\u0432\u0435\u043b|\u043f\u0435\u0440\u0435\u0432\u0451\u043b|'
    '\u043f\u043e\u0434\u0430\u043b|\u043f\u0440\u0438\u043c\u0435\u043d\u0438\u043b|\u0441\u043f\u0438\u0441\u0430\u043b|\u0437\u0430\u0447\u0438\u0441\u043b\u0438\u043b|\u0432\u043e\u0437\u043e\u0431\u043d\u043e\u0432\u0438\u043b)\\w*|'
    '(?:\u043e\u0442\u043c\u0435\u043d\u0435\u043d|\u043e\u0442\u043c\u0435\u043d\u0451\u043d|\u0438\u0437\u043c\u0435\u043d\u0435\u043d|\u0438\u0437\u043c\u0435\u043d\u0451\u043d|\u043e\u0431\u043d\u043e\u0432\u043b\u0435\u043d|\u043e\u0431\u043d\u043e\u0432\u043b\u0451\u043d|\u043e\u0444\u043e\u0440\u043c\u043b\u0435\u043d|\u0437\u0430\u0431\u0440\u043e\u043d\u0438\u0440\u043e\u0432\u0430\u043d|\u0432\u044b\u043f\u043e\u043b\u043d\u0435\u043d|\u043e\u0442\u043f\u0440\u0430\u0432\u043b\u0435\u043d|'
    '\u0437\u0430\u0431\u043b\u043e\u043a\u0438\u0440\u043e\u0432\u0430\u043d|\u0440\u0430\u0437\u0431\u043b\u043e\u043a\u0438\u0440\u043e\u0432\u0430\u043d|\u0430\u043a\u0442\u0438\u0432\u0438\u0440\u043e\u0432\u0430\u043d|\u043f\u043e\u0434\u0430\u043d|\u0437\u0430\u0447\u0438\u0441\u043b\u0435\u043d|\u0441\u043f\u0438\u0441\u0430\u043d|\u0432\u043e\u0437\u043e\u0431\u043d\u043e\u0432\u043b\u0435\u043d)[\u0430-\u044f]*|'
    "has\\s+been|have\\s+been|successfully|is\\s+now|are\\s+now", re.I)
CONFIRM = re.compile(
    '^\\W*(?:\u0434\u0430|\u0430\u0433\u0430|\u0443\u0433\u0443|\u043a\u043e\u043d\u0435\u0447\u043d\u043e|\u043f\u043e\u0434\u0442\u0432\u0435\u0440\u0436\u0434\u0430\u044e|\u0441\u043e\u0433\u043b\u0430\u0441\u0435\u043d|\u0441\u043e\u0433\u043b\u0430\u0441\u043d\u0430|\u0432\u0435\u0440\u043d\u043e|\u043f\u0440\u0430\u0432\u0438\u043b\u044c\u043d\u043e|\u0434\u0430\u0432\u0430\u0439\u0442\u0435|'
    '\u0445\u043e\u0440\u043e\u0448\u043e|\u043e\u043a|\u043e\u043a\u0435\u0439|yes|yeah|yep|sure|ok|okay|correct|confirm|go\\s+ahead|please\\s+proceed|proceed)\\b|'
    '\u043f\u043e\u0434\u0442\u0432\u0435\u0440\u0436\u0434\u0430\u044e|\u0434\u0430,\\s|i\\s+confirm|yes,\\s', re.I)
DENY = re.compile('^\\W*(?:\u043d\u0435\u0442|no|nope|\u043d\u0435\\s+\u043d\u0430\u0434\u043e|\u043e\u0442\u043c\u0435\u043d\u0430|cancel\\s+that)\\b', re.I)
WRITE_NAME = re.compile(r'^(?:cancel|modify|update|book|exchange|return|create|delete|change|apply|close|open|'
                        r'transfer_funds|send|make|resume|suspend|enable|disable|refuel|reset|set|toggle|file|'
                        r'freeze|unfreeze|order|replace|add|remove|pay|activate|deactivate|lift|issue|log_)', re.I)
UNLOCK, CALL_DISC = 'unlock_discoverable_agent_tool', 'call_discoverable_agent_tool'
FREE_TEXT_KEYS = re.compile(r'(?:summary|reason|message|note|description|comment|query|pattern|expression|text)$', re.I)


@dataclass
class ArgCheck:
    path: str
    key: str
    value: object
    kind: str
    grounding: str


@dataclass
class CallCheck:
    event: object
    name: str
    availability: str
    schema_issues: list = field(default_factory=list)
    repeat_of: object = None            # earlier identical assistant call event
    repeat_status: str = None           # 'ok' | 'error' | 'no_result'
    args: list = field(default_factory=list)
    discoverable: dict = field(default_factory=dict)


@dataclass
class TurnAnalysis:
    prompt: object
    response: object
    system: object
    calls: list
    reply: str
    hard: list
    strong: list
    weak: list
    hints: list
    features: dict


def _flatten(value, path='$', key=None):
    if isinstance(value, dict):
        for k, v in value.items():
            yield from _flatten(v, path + '.' + str(k), k)
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield from _flatten(v, '%s[%d]' % (path, i), key)
    else:
        yield path, key, value


def _unlocked(prompt_doc):
    names = set()
    for e in prompt_doc.events:
        if e.kind == 'call' and e.tool == UNLOCK and e.owner == 'assistant' and isinstance(e.value, dict):
            result = prompt_doc.events[e.pair] if e.pair is not None else None
            if result is not None and not result.is_error:
                names.add(str(e.value.get('agent_tool_name')))
    return names


def classify_tool(name, catalog, prompt_doc, index):
    """catalog | history_ok | user_tool | discoverable_unlocked_direct | mentioned_not_declared |
    failed_before | undeclared."""
    if catalog.present and name in catalog.tools:
        return 'catalog'
    calls = [e for e in prompt_doc.events if e.kind == 'call' and e.tool == name]
    for e in calls:
        if e.owner == 'assistant' and e.pair is not None and not prompt_doc.events[e.pair].is_error:
            return 'history_ok'
    if any(e.owner == 'user' for e in calls):
        return 'user_tool'
    if name in _unlocked(prompt_doc):
        return 'discoverable_unlocked_direct'
    if any(e.owner == 'assistant' for e in calls):
        return 'failed_before'
    own = {e.pair for e in calls if e.pair is not None}
    if any(h.bounded and h.kind in ('tool_result', 'policy') and h.event not in own for h in index.locate(name)):
        return 'mentioned_not_declared'
    return 'undeclared'


def _last_user_text(prompt_doc):
    e = prompt_doc.last(kind='text', role='user')
    return e.body if e is not None else ''


def analyze_turn(prompt, response):
    p = parse_document(prompt, 'prompt')
    r = parse_document(response, 'response')
    system = parse_system(p)
    index = ContextIndex(p, system)
    cat = system.catalog
    hard, strong, weak, hints = [], [], [], []
    calls = []
    unlocked = _unlocked(p)
    for e in r.calls():
        name = e.tool
        check = CallCheck(e, name, classify_tool(name, cat, p, index) if e.owner == 'assistant' else 'not_agent')
        calls.append(check)
        if e.owner != 'assistant':
            weak.append('non_agent_call_in_response %s' % name)
            continue
        if not e.is_json:
            strong.append('call_arguments_not_json %s' % name)
            hints.append('The arguments of %s are not valid JSON.' % name)
            continue
        if not isinstance(e.value, dict):
            hard.append('arguments_not_object %s' % name)
            continue
        if check.availability != 'catalog' and e.owner == 'assistant':
            if check.availability == 'history_ok':
                weak.append('tool_outside_catalog_but_ran_before %s' % name)
            elif cat.complete:
                hard.append('unavailable_tool %s (%s)' % (name, check.availability))
                hints.append('Tool "%s" is not in [AVAILABLE TOOLS] (%s).' % (name, check.availability.replace('_', ' ')))
            else:
                strong.append('unlisted_tool %s (%s)' % (name, check.availability))
                hints.append('Tool "%s" was not found in the parsed tool list; check it is available.' % name)
        spec = cat.get(name)
        if spec is not None:
            check.schema_issues = validate_arguments(spec, e.value)
            hard.extend('schema %s: %s' % (name, i) for i in check.schema_issues if not i.startswith('UNEXPECTED'))
            strong.extend('schema %s: %s' % (name, i) for i in check.schema_issues if i.startswith('UNEXPECTED'))
        for prior in p.calls(owner='assistant'):
            if prior.tool == name and prior.is_json and prior.value == e.value:
                check.repeat_of = prior
                res = p.events[prior.pair] if prior.pair is not None else None
                check.repeat_status = 'no_result' if res is None else ('error' if res.is_error else 'ok')
        if check.repeat_status == 'error':
            strong.append('repeat_of_failed_call %s' % name)
            hints.append('%s repeats an identical earlier call that returned an error.' % name)
        elif check.repeat_status == 'ok':
            weak.append('repeat_of_successful_call %s' % name)
        if name == CALL_DISC:
            inner = str(e.value.get('agent_tool_name'))
            check.discoverable = dict(tool=inner, unlocked=inner in unlocked,
                                      args_ok=not isinstance(e.nested.get('arguments'), Exception))
            if inner not in unlocked:
                strong.append('discoverable_not_unlocked %s' % inner)
                hints.append('call_discoverable_agent_tool uses "%s", which was not unlocked earlier.' % inner)
        for path, key, value in _flatten(e.value):
            if value is None or isinstance(value, bool) or (isinstance(value, str) and not value.strip()):
                continue
            kind = value_kind(key, value)
            if kind in ('text', 'flag') or (key and FREE_TEXT_KEYS.search(str(key))):
                continue
            if spec is not None:
                param = spec.param(str(key)) if key else None
                if param is not None and param.enum:
                    continue
            g = index.grounded(value)
            check.args.append(ArgCheck(path, key, value, kind, g))
            if str(key).lower().startswith('new') or (name.startswith(('create', 'open', 'book')) and kind == 'name'):
                continue
            if g == 'failed_result_only':
                strong.append('arg_failed_result_only %s %s=%r' % (name, path, value))
                hints.append('%s.%s = "%s" is only mentioned in a failed tool result, not a successful '
                             'result; verify what that failure actually establishes.' % (name, path[2:], value))
            elif g in ('inside_token', 'catalog_only'):
                strong.append('arg_%s %s %s=%r' % (g, name, path, value))
                hints.append('%s.%s = "%s" appears in the context only %s.' % (
                    name, path[2:], value, 'inside another token' if g == 'inside_token' else 'as a catalog example'))
            elif g == 'absent' and kind in ('id', 'email', 'phone', 'date'):
                strong.append('arg_absent %s %s=%r' % (name, path, value))
                hints.append('%s.%s = "%s" appears nowhere in the context.' % (name, path[2:], value))
            elif g == 'absent' and kind == 'number' and not index.number_derivable(frozenset([round(float(value), 4)])):
                weak.append('arg_number_not_derivable %s %s=%r' % (name, path, value))
        if (spec is not None and spec.requires_confirmation) or WRITE_NAME.match(name):
            last_user = _last_user_text(p)
            if not CONFIRM.search(last_user[:200]) or DENY.search(last_user[:60]):
                weak.append('write_without_explicit_confirmation %s' % name)
                hints.append('%s changes data; the last user message is not an explicit confirmation.' % name)
    reply = '\n'.join(t.body for t in r.texts(role='assistant'))
    feats_reply = {}
    if reply.strip():
        if REFUSAL.search(reply):
            weak.append('refusal_wording')
            hints.append('The turn refuses or says something is impossible: check that no permitted action remains.')
        last_result = p.last(kind='result')
        if DONE.search(reply) and not r.calls():
            if last_result is not None and last_result.is_error:
                strong.append('completion_claim_after_error')
                hints.append('The turn claims an action was completed, but the latest tool result is an error.')
            else:
                weak.append('completion_claim')
        odd = [nm.raw for nm in parse_numbers(reply)
               if (max(abs(v) for v in nm.values) >= 10 or nm.money) and not index.number_derivable(nm.values)]
        if odd:
            weak.append('reply_numbers_not_derivable %s' % ','.join(odd[:5]))
            hints.append('Numbers in the reply not found in the context (nor a simple sum or multiple): %s.' % ', '.join(odd[:5]))
        ids = [tok for tok, _, _ in extract_identifiers(reply) if index.grounded(tok) in ('absent', 'catalog_only')]
        if ids:
            strong.append('reply_identifiers_absent %s' % ','.join(ids[:5]))
            hints.append('Identifiers in the reply that appear nowhere in the context: %s.' % ', '.join(ids[:5]))
        feats_reply = dict(reply_numbers=len(parse_numbers(reply)), reply_dates=len(parse_dates(reply)),
                           reply_chars=len(reply))
    if system.transfer_phrase and system.transfer_phrase.lower() in reply.lower() and \
            not any(c.name == 'transfer_to_human_agents' for c in calls):
        prev = p.last(kind='call', owner='assistant')
        if prev is None or prev.tool != 'transfer_to_human_agents':
            strong.append('transfer_message_without_transfer_call')
    if any(c.name == 'transfer_to_human_agents' for c in calls):
        weak.append('transfer_to_human')
        hints.append('The turn transfers to a human: check the policy requires it now and no permitted action remains.')
    agent_calls = [c for c in calls if c.event.owner == 'assistant']
    if system.one_call_rule and len(agent_calls) > 1:
        weak.append('several_calls_against_policy')
        hints.append('The policy asks for one tool call at a time and this turn makes several: '
                     'judge only whether this changes the outcome.')
    if system.exclusive_rule and agent_calls and reply.strip():
        weak.append('text_and_calls_against_policy')
        hints.append('The policy separates messages and tool calls and this turn does both: '
                     'judge only whether this changes the outcome.')
    last_hist = p.events[-1] if p.events else None
    features = dict(
        n_calls=len(calls), has_text=bool(reply.strip()), text_and_calls=bool(reply.strip()) and bool(calls),
        turn_number=r.messages[0].number if r.messages else None,
        history_messages=len(p.messages), history_calls=len(p.calls()), history_errors=sum(e.is_error for e in p.events),
        last_event_is_error=bool(last_hist is not None and last_hist.is_error),
        catalog_tools=len(cat.tools), catalog_complete=cat.complete, policy_tagged=system.policy_tagged,
        one_call_rule=system.one_call_rule, exclusive_rule=system.exclusive_rule,
        current_time=(current_time(p, system) or {}).get('date'),
        n_hard=len(hard), n_strong=len(strong), n_weak=len(weak), **feats_reply)
    for tier, items in (('hard', hard), ('strong', strong), ('weak', weak)):
        for item in items:
            key = tier + ':' + item.split()[0]
            features[key] = features.get(key, 0) + 1
    features.update({'prompt_' + k: v for k, v in document_stats(p).items()})
    features.update({'response_' + k: v for k, v in document_stats(r).items()})
    return TurnAnalysis(p, r, system, calls, reply, hard, strong, weak, list(dict.fromkeys(hints))[:10], features)


@dataclass
class Findings:
    """Drop-in for guardian_truth.judge.mechanical.Findings (hard + hints), plus tiers and features."""
    hard: list = field(default_factory=list)
    hints: list = field(default_factory=list)
    strong: list = field(default_factory=list)
    weak: list = field(default_factory=list)
    features: dict = field(default_factory=dict)


def analyze(prompt, response, hard_unknown_identifier=False, **_):
    """Accept the former third positional argument. Unknown references remain hints even if the legacy
    experimental flag is set. Failures are visible in analysis_error."""
    try:
        t = analyze_turn(prompt or '', response or '')
    except Exception as error:  # noqa: BLE001 - one bad row must not stop a submission
        return Findings(features={'analysis_error': type(error).__name__})
    if hard_unknown_identifier:
        t.features['legacy_strict_requested'] = True
    return Findings([h for h in t.hard], [h[:220] for h in t.hints], t.strong, t.weak, t.features)
