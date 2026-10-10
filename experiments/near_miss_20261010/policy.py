"""Near-Miss step A helpers: per-policy tool map prompt, validation and voting.

A map is built once per unique (policy text, tool catalog) pair, keyed by sha256. Nothing here
is domain-specific: the model reads the policy and catalog of the row it is given.
"""
import hashlib
import json
import re
from collections import Counter

from experiments.contract_lint_20261010.lint import HEADER, catalog_text, parse_catalog

POLICY = re.compile(r'<policy>(.*?)</policy>', re.S)

SYSTEM = """You analyse an operating policy for a tool-using customer-service agent.
For every tool in the catalog decide:
1. "mutating": true if calling the tool changes state (creates, updates, cancels, pays, books, transfers, sends, modifies anything); false if it only reads/looks up information.
2. "requires": ONLY for mutating tools. List the facts the policy says the agent must have checked/verified/looked up BEFORE calling this tool, where the fact can be obtained from a read (non-mutating) tool in the catalog. For each:
   - "need": short description of the fact,
   - "satisfied_by": names of the read tools from the catalog that provide this fact,
   - "entity_arg": the parameter of THIS mutating tool that identifies the entity the fact is about (e.g. the id that must have been looked up), or null if none,
   - "policy_quote": an exact, verbatim sentence or clause copied from the policy that states this requirement.
Do not include requirements that come from the user (confirmation, consent, information the user tells), or that no catalog read tool can provide. Do not invent requirements that the policy does not state; an empty list is fine.
Answer with JSON only: {"tools": {"<tool name>": {"mutating": true|false, "requires": [ ... ]}}}"""


def split(prompt):
    """(policy_text, catalog_text) or None if the row has no unambiguous catalog."""
    headers = list(HEADER.finditer(prompt))
    if len(headers) != 1 or parse_catalog(prompt) is None:
        return None
    head = prompt[:headers[0].start()]
    m = POLICY.findall(head)
    policy = m[0] if len(m) == 1 else head
    return policy.strip(), catalog_text(prompt).strip()


def key(policy, catalog):
    return hashlib.sha256((policy + '\0' + catalog).encode()).hexdigest()


def messages(policy, catalog):
    user = f'<policy>\n{policy}\n</policy>\n\n[AVAILABLE TOOLS]\n{catalog}\n'
    return [dict(role='system', content=SYSTEM), dict(role='user', content=user)]


def norm(text):
    return re.sub(r'\s+', ' ', text).strip().casefold()


def parse_json(text):
    text = re.sub(r'^```(?:json)?\s*|\s*```$', '', text.strip())
    start, end = text.find('{'), text.rfind('}')
    try:
        return json.loads(text[start:end + 1]) if start >= 0 else None
    except ValueError:
        return None


def validate(raw, policy, catalog_entries):
    """Clean one sample. Returns ({tool: mutating}, [req]) with only verifiable requirements, or None."""
    data = parse_json(raw) if isinstance(raw, str) else raw
    tools = data.get('tools') if isinstance(data, dict) else None
    if not isinstance(tools, dict):
        return None
    mut = {t: v['mutating'] for t, v in tools.items()
           if t in catalog_entries and isinstance(v, dict) and isinstance(v.get('mutating'), bool)}
    reqs, npol, dropped = [], norm(policy), Counter()
    for tool, v in tools.items():
        if mut.get(tool) is not True:
            continue
        for r in v.get('requires') or []:
            if not isinstance(r, dict):
                dropped['not_object'] += 1
                continue
            reads = r.get('satisfied_by')
            reads = sorted({x for x in reads if isinstance(x, str)}) if isinstance(reads, list) else []
            arg, quote = r.get('entity_arg'), r.get('policy_quote')
            if not reads or any(x not in catalog_entries or x == tool or mut.get(x) is not False for x in reads):
                dropped['satisfied_by'] += 1
            elif arg is not None and arg not in catalog_entries[tool]['params']:
                dropped['entity_arg'] += 1
            elif not isinstance(quote, str) or len(norm(quote)) < 15 or norm(quote) not in npol:
                dropped['quote'] += 1
            else:
                reqs.append(dict(tool=tool, entity_arg=arg, satisfied_by=reads, need=str(r.get('need'))[:200],
                                 policy_quote=quote))
    return dict(mutating=mut, requires=reqs, dropped=dict(dropped))


def vote(samples, quorum=2):
    """Majority map from validated samples (None samples count as votes for nothing)."""
    ok = [s for s in samples if s is not None]
    tools = Counter(t for s in ok for t, m in s['mutating'].items() if m)
    mutating = sorted(t for t, n in tools.items() if n >= quorum)
    groups = {}
    for i, s in enumerate(ok):
        for r in s['requires']:
            g = groups.setdefault((r['tool'], r['entity_arg']), dict(votes=set(), reads=set(), quotes=[]))
            g['votes'].add(i)
            g['reads'].update(r['satisfied_by'])
            g['quotes'].append(r['policy_quote'])
    requires = [dict(tool=t, entity_arg=a, satisfied_by=sorted(g['reads']), votes=len(g['votes']),
                     policy_quote=Counter(g['quotes']).most_common(1)[0][0])
                for (t, a), g in sorted(groups.items(), key=lambda kv: (kv[0][0], str(kv[0][1])))
                if len(g['votes']) >= quorum and t in mutating]
    return dict(mutating=mutating, requires=requires, valid_samples=len(ok), samples=len(samples))
