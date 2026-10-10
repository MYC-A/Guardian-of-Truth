"""Build a per-policy checklist with the model, then validate and vote in code.

Universal by construction: nothing domain-specific; one checklist per unique (policy, catalog) pair of
the input rows, generated at runtime through the same client that serves the review.
Every kept item cites a verbatim policy quote; the checklist is a MODEL_HYPOTHESIS for the reviewer,
never evidence and never a label.
"""
import hashlib
import json
import re

HEADER = re.compile(r'^\[AVAILABLE TOOLS\][ \t]*$', re.M)
SECTION = re.compile(r'^(?:\[[A-Z][A-Z _]{2,40}\]|⟦|</?[a-z_]+>)', re.M)
TOOL_LINE = re.compile(r'^- ([\w.\-]+) —', re.M)
POLICY = re.compile(r'<policy>(.*?)</policy>', re.S)
ANY = 'ANY'
VERSION = 'policy-checklist-v1'
SEEDS = (1, 2, 3)
QUORUM = 2
MAX_ITEMS = 60
MIN_QUOTE = 15

SYSTEM = (
    'You turn an operating policy for a tool-using customer-service agent into a checklist that a reviewer '
    'will use to judge ONE move of the agent. For every tool in the catalog, list the policy conditions a call '
    'of that tool must satisfy: preconditions on facts that must hold, constraints on argument values, required '
    'prior steps or confirmations, limits and exceptions. Also list, with tool "ANY", the policy rules that apply '
    'to any move, including plain messages: when the agent must refuse or must not refuse, when to transfer or '
    'escalate, what it must not claim, disclose or invent. Each item: "tool" (catalog name or "ANY"), "check" '
    '(one short, concrete, verifiable condition, phrased as what must be true), "policy_quote" (an exact, '
    'verbatim span copied from the policy that states it; copy characters exactly). Use only what the policy '
    'states; do not invent rules; do not merge unrelated rules into one item. Return the JSON schema.')


def split(prompt):
    """(policy_text, catalog_text, tool_names) or None when the catalog block is missing/ambiguous."""
    if not isinstance(prompt, str):
        return None
    headers = list(HEADER.finditer(prompt))
    if len(headers) != 1:
        return None
    rest = prompt[headers[0].end():]
    end = SECTION.search(rest)
    if end is None:
        return None                               # unterminated (possibly truncated) catalog
    catalog = rest[:end.start()].strip()
    tools = TOOL_LINE.findall(catalog)
    if not tools or len(tools) != len(set(tools)):
        return None
    head = prompt[:headers[0].start()]
    found = POLICY.findall(head)
    policy = (found[0] if len(found) == 1 else head).strip()
    return (policy, catalog, tools) if len(norm(policy)) >= MIN_QUOTE else None


def key(policy, catalog):
    return hashlib.sha256((policy + '\0' + catalog).encode('utf-8')).hexdigest()


def norm(text):
    return re.sub(r'\s+', ' ', text).strip().casefold()


def schema(tools):
    item = dict(type='object', additionalProperties=False, required=['tool', 'check', 'policy_quote'],
                properties=dict(tool=dict(type='string', enum=list(tools) + [ANY]),
                                check=dict(type='string'), policy_quote=dict(type='string')))
    return dict(type='object', additionalProperties=False, required=['items'],
                properties=dict(items=dict(type='array', items=item)))


def request(model, policy, catalog, tools, seed, max_tokens=4000):
    user = f'<policy>\n{policy}\n</policy>\n\n[AVAILABLE TOOLS]\n{catalog}\n'
    return dict(model=model, temperature=0.7, top_p=0.95, seed=seed, max_tokens=max_tokens,
                messages=[dict(role='system', content=SYSTEM), dict(role='user', content=user)],
                response_format=dict(type='json_schema',
                                     json_schema=dict(name='policy_checklist', strict=True, schema=schema(tools))))


def validate(content, policy, tools):
    """Items with a known tool, a non-empty check and a verbatim (normalised) policy quote; None if unparsable."""
    try:
        data = json.loads(content) if isinstance(content, str) else None
    except ValueError:
        return None
    items = data.get('items') if isinstance(data, dict) else None
    if not isinstance(items, list):
        return None
    npol, out, seen = norm(policy), [], set()
    for it in items:
        if not isinstance(it, dict):
            continue
        tool, check, quote = it.get('tool'), it.get('check'), it.get('policy_quote')
        if tool not in tools and tool != ANY:
            continue
        if not isinstance(check, str) or not check.strip() or not isinstance(quote, str):
            continue
        nq = norm(quote)
        if len(nq) < MIN_QUOTE or nq not in npol or (tool, nq) in seen:
            continue
        seen.add((tool, nq))
        out.append(dict(tool=tool, check=check.strip()[:400], policy_quote=quote.strip()))
    return out


def _words(text):
    return set(re.findall(r'\w+', norm(text)))


def same(a, b):
    """Two items state the same rule: same tool and overlapping quotes."""
    if a['tool'] != b['tool']:
        return False
    qa, qb = norm(a['policy_quote']), norm(b['policy_quote'])
    if qa in qb or qb in qa:
        return True
    wa, wb = _words(qa), _words(qb)
    return bool(wa | wb) and len(wa & wb) / len(wa | wb) >= 0.5


def vote(samples, quorum=QUORUM):
    """Keep rules supported by >= quorum samples; representative = first occurrence (sample order)."""
    ok = [s for s in samples if s is not None]
    clusters = []                                 # [representative, set(sample indices)]
    for i, items in enumerate(ok):
        for it in items:
            for c in clusters:
                if same(c[0], it):
                    c[1].add(i)
                    break
            else:
                clusters.append([it, {i}])
    kept = [dict(c[0], votes=len(c[1])) for c in clusters if len(c[1]) >= quorum]
    return kept[:MAX_ITEMS]


def unique_policies(rows):
    policies = {}
    for row in rows:
        s = split(row.get('prompt'))
        if s is not None:
            policies.setdefault(key(s[0], s[1]), s)
    return policies


def _sample(client, model, policy, catalog, tools, seed, tag):
    try:
        r = client.call(request(model, policy, catalog, tools, seed), attempt=0, tag=tag)
    except Exception as error:                    # a failed sample is a missing vote, never a crash
        r = dict(transport=dict(status='EXC', error=type(error).__name__))
    ok = (r.get('transport') or {}).get('status') == 200 and r.get('finish_reason') == 'stop'
    items = validate(r.get('content'), policy, tools) if ok else None
    return items, dict(seed=seed, status=(r.get('transport') or {}).get('status'), finish=r.get('finish_reason'),
                       valid=items is not None, items=None if items is None else len(items))


def build(client, model, rows, tag='checklist', workers=1):
    """{key: {'items', 'samples', 'valid_samples'}} for every unique policy of `rows`."""
    from concurrent.futures import ThreadPoolExecutor
    policies = unique_policies(rows)
    jobs = [(k, seed) for k in policies for seed in SEEDS]
    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        results = list(ex.map(lambda j: _sample(client, model, *policies[j[0]], j[1], tag), jobs))
    out = {}
    for k in policies:
        got = [res for (kk, _), res in zip(jobs, results) if kk == k]   # seed order preserved
        samples = [g[0] for g in got]
        out[k] = dict(version=VERSION, items=vote(samples), samples=[g[1] for g in got],
                      valid_samples=sum(s is not None for s in samples))
    return out
