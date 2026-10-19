"""Opt-in bounded turn-shape candidate. Disabled unless explicitly configured.

Recognizes a small source grammar; UNKNOWN never forces a decision. Passing this
gate is not a proof of general natural-language policy applicability.
"""
import re
from guardian_truth.transcript import parse_document, parse_system

MAX = re.compile(r'you (?:should|must|shall) (?:(?:only|at most) make|make (?:only|at most|no more than)) '
                 r'(?:one|1) (?:tool|function) call at a time',re.I)
NO_TEXT = re.compile(r'(?:if|when) you (?:make|take) a (?:tool|function) call,\s*'
    r'you (?:should|must|shall) not (?:respond|reply) to the user (?:at the same time|simultaneously|in the same turn)'
    r'|(?:if|when) you (?:respond|reply) to the user,\s*you (?:should|must|shall) not '
    r'(?:make|take) a (?:tool|function) call (?:at the same time|in the same turn)', re.I)
EITHER = re.compile(r'^In each turn you can either:\s*\n- Send a message to the user\.\s*\n'
                    r'- Make a tool call\.\s*\nYou cannot do both at the same time\.[ \t]*$', re.I|re.M)
RELATED = re.compile(r'\b(?:one|1|two|multiple|several|more than|at most|only)\b.{0,25}'
    r'\b(?:tool|function) calls?\b|\b(?:tool|function) calls?\b.{0,90}\b(?:same time|same turn|at a time|per turn|parallel|simultaneous)'
    r'|\b(?:respond|reply)\b.{0,70}\b(?:same time|simultaneous)|cannot do both',re.I)
SCOPE = re.compile(r'\b(?:if|when|before|after|during|unless|except|only for|only when|'
                   r'authentication|unauthenticated|unverified|payment tools)\b',re.I)
MODIFIER = re.compile(r'\b(?:except|unless|exempt|override|overridden|revoked|obsolete|supersed|'
                      r'previous rule|quoted rule|this rule|above rule|following rule)\w*\b',re.I)
THOUGHT = re.compile(r'<(think|analysis)>.*?</\1>',re.I|re.S)


def unknown(reason, **facts):
    return dict(status='UNKNOWN', reason=reason, violations=[], **facts)


def scan(prompt, response):
    p = parse_document(prompt or '')
    r = parse_document(response or '', 'response')
    systems = [m for m in p.messages if m.role=='system']
    if len(systems)!=1 or p.diagnostics or r.diagnostics:
        return unknown('SOURCE_OR_TARGET_PARSE_AMBIGUOUS')
    if len(r.messages)!=1 or r.messages[0].role!='assistant':
        return unknown('NOT_ONE_CURRENT_ASSISTANT_MESSAGE')
    system = parse_system(p)
    if 'SEVERAL_POLICY_TAGS' in system.issues:
        return unknown('MULTIPLE_POLICY_FRAMES')
    calls = r.calls(owner='assistant')
    if any(c.tool=='transfer_to_human_agents' for c in calls):
        return unknown('TRANSFER_SEQUENCE_EXCEPTION_UNRESOLVED')
    visible = []
    for event in r.texts(role='assistant'):
        body = event.body
        cleaned = THOUGHT.sub('',body)
        if re.search(r'</?(?:think|analysis)>',cleaned,re.I) or '```' in cleaned:
            return unknown('TARGET_REASONING_OR_QUOTATION_UNRESOLVED')
        if cleaned.strip():
            visible.append(dict(start=event.span.start,end=event.span.end,text=cleaned))
    facts = dict(n_calls=len(calls),has_visible_text=bool(visible),
                 call_spans=[[c.span.start,c.span.end] for c in calls],text=visible)
    stop = system.catalog.start if system.catalog.present else system.end
    source = prompt[system.start:stop]
    transfer_names=set(re.findall(r'\bTo transfer, first make a tool call to ([A-Za-z_][A-Za-z_0-9]*),',source,re.I))
    if any(c.tool in transfer_names or (isinstance(c.value,dict) and
           c.value.get('agent_tool_name') in (transfer_names|{'transfer_to_human_agents'})) for c in calls):
        return unknown('SOURCE_TRANSFER_SEQUENCE_EXCEPTION_UNRESOLVED',facts=facts)
    if '```' in source:
        return unknown('SOURCE_QUOTED_CODE_UNRESOLVED',facts=facts)
    admitted = []
    masked = source
    for match in EITHER.finditer(source):
        prefix = source[:match.start()].splitlines()
        if any(SCOPE.search(line) and (line.strip().endswith(':') or line.lstrip().startswith('#')) for line in prefix):
            return unknown('EITHER_BLOCK_INHERITED_SCOPE',facts=facts)
        prior = next((line.strip() for line in reversed(prefix) if line.strip()),'')
        if prior.endswith(':') and not re.fullmatch(r'(?:general |interaction |turn shape )?(?:policy|rules):',prior,re.I):
            return unknown('EITHER_BLOCK_QUOTATION_OR_SCOPE',facts=facts)
        admitted.append(dict(kind='NO_TEXT_WITH_CALL',quote=match.group(),
                             span=[system.start+match.start(),system.start+match.end()]))
    masked = EITHER.sub(lambda m: ''.join('\n' if c=='\n' else ' ' for c in m.group()),masked)
    previous = ''; headings = []; offset = 0
    for line in masked.splitlines(keepends=True):
        clean = line.strip(); related = bool(RELATED.search(clean))
        # Explicit exceptions and revocations in a linked or standalone fragment
        # block admission. Unrelated eligibility/compensation conditions are not
        # silently treated as turn-shape exceptions.
        if MODIFIER.search(clean) and (related or re.match(r'^(?:except|unless)\b',clean,re.I)
                or re.search(r'\b(?:rule|restriction|read.only|lookups?|calls?|messages?|parallel)\b',clean,re.I)):
            return unknown('LINKED_EXCEPTION_OR_RULE_REVISION',facts=facts)
        if clean.startswith('#'):
            depth = len(clean)-len(clean.lstrip('#'))
            headings = [(n,h) for n,h in headings if n<depth]+[(depth,clean)]
        if related:
            if any(SCOPE.search(h) for _,h in headings):
                return unknown('INHERITED_HEADING_SCOPE',facts=facts)
            if previous.endswith(':') and not re.fullmatch(r'(?:general |interaction |turn shape )?(?:policy|rules):',previous,re.I):
                return unknown('INHERITED_LINE_SCOPE',facts=facts)
            parts = [re.sub(r'^[-*]\s*','',x.strip()) for x in
                     re.split(r'[.!]\s*|,\s*and\s+(?=(?:if|when) you\b)',clean,flags=re.I) if x.strip()]
            if not parts or any(not (MAX.fullmatch(x) or NO_TEXT.fullmatch(x)) for x in parts):
                return unknown('UNSUPPORTED_RELATED_CLAUSE',facts=facts)
            for part in parts:
                admitted.append(dict(kind='MAX_ONE_CALL' if MAX.fullmatch(part) else 'NO_TEXT_WITH_CALL',
                    quote=clean,span=[system.start+offset,system.start+offset+len(line.rstrip('\r\n'))]))
        if clean and not re.fullmatch(r'</?(?:policy|instructions)>',clean,re.I):
            previous = clean
        offset += len(line)
    violations = []
    for rule in admitted:
        if ((rule['kind']=='MAX_ONE_CALL' and len(calls)>1) or
                (rule['kind']=='NO_TEXT_WITH_CALL' and calls and visible)):
            if not any(v['kind']==rule['kind'] for v in violations):
                violations.append(rule)
    return dict(status='BOUNDED_RESEARCH_CANDIDATE' if admitted else 'NO_SUPPORTED_RULE',
                violations=violations, admitted=admitted, facts=facts,
                general_semantic_proof=False,production_enabled=False)
