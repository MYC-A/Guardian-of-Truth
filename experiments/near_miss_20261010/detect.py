"""Near-Miss step B (offline code): a mutating call in the current turn whose policy-stated
information need was not covered by an earlier successful read of the same entity.

Lenient on every doubt (unknown pairing, missing argument, unparsable call) -> requirement counts as
satisfied, so the check only fires with explicit evidence. Code never asserts "no violation".
"""
import json

from experiments.contract_lint_20261010.lint import CALL, RESP, blocks


def events(body):
    """[(name, args|None, ok|None, text)] for calls of one block; text = args + paired response body."""
    calls, resps, cur = [], [], None
    for line in body.splitlines():
        s = line.strip()
        m = CALL.match(s)
        if m:
            try:
                args = json.loads(m.group(2))
            except ValueError:
                args = None
            calls.append([m.group(1), args, m.group(2)])
            cur = None
            continue
        r = RESP.match(s)
        if r:
            cur = [r.group(1), not r.group(2), s[r.end():]]
            resps.append(cur)
            continue
        if cur is not None:
            cur[2] += '\n' + s                    # multi-line response body
    paired = len(calls) == len(resps) and all(c[0] == r[0] for c, r in zip(calls, resps))
    return [(c[0], c[1], resps[i][1] if paired else None, c[2] + '\n' + (resps[i][2] if paired else ''))
            for i, c in enumerate(calls)]


def history(prompt):
    out = []
    for role, body in blocks(prompt):
        if role != 'USER':
            out.extend(events(body))
    return out


def as_text(value):
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def needles(value):
    """Scalar texts that must all occur in a covering read; [] means nothing checkable (abstain)."""
    if isinstance(value, list):
        if not all(isinstance(v, (str, int, float)) and not isinstance(v, bool) for v in value):
            return []
        return [as_text(v) for v in value if as_text(v)]
    if isinstance(value, (str, int, float)) and not isinstance(value, bool):
        return [as_text(value)]
    return []


def near_miss(prompt, response, tool_map):
    """Findings for the current turn given a voted map {'mutating': [...], 'requires': [...]}."""
    if not tool_map:
        return []
    prior = history(prompt)
    findings = []
    for name, args, _, _ in events(response):
        reqs = [r for r in tool_map['requires'] if r['tool'] == name]
        if name in tool_map['mutating'] and reqs and isinstance(args, dict):
            for r in reqs:
                value = args.get(r['entity_arg']) if r['entity_arg'] else None
                wanted = needles(value) if r['entity_arg'] else None
                if r['entity_arg'] and not wanted:
                    continue                      # nothing checkable: abstain
                # every element must be covered by some successful read (not necessarily the same one)
                hit = all(any(p[0] in r['satisfied_by'] and p[2] is not False and (w is None or w in p[3])
                              for p in prior) for w in (wanted or [None]))
                needle = wanted
                if not hit:
                    findings.append(dict(check='NEAR_MISS', tool=name, entity_arg=r['entity_arg'], value=needle,
                                         satisfied_by=r['satisfied_by'], policy_quote=r['policy_quote']))
        prior.append((name, args, None, as_text(args)))  # earlier calls of this turn: response unknown
    return findings
