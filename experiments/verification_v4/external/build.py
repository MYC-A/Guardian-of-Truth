"""Build the external V4 evaluation set from tau2-bench official result trajectories (PROTOCOL §9 + amendment 1 §4).
  python -m experiments.verification_v4.external.build pool      -> outputs/verification_v4/external/tau2/pool.jsonl (+ review view)
  python -m experiments.verification_v4.external.build finalize  -> inputs.jsonl, GOLD_eval_only.json, MANIFEST.json
Gold oracle = code (task evaluation_criteria.actions, tau2 compare semantics, reward); manual review may only DROP
(DROPS below, each with a reason). Gold is never visible to Guardian (inputs.jsonl = id, prompt, response only)."""
import argparse, hashlib, importlib, json, re, sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TAU2 = Path('/data/ext/tau2')
TAU2_COMMIT = '5bfa7e37b36656b37dc6d022156be6563c1007f3'
OUTD = ROOT / 'outputs/verification_v4/external/tau2'
AGENTS = ['claude-3-7-sonnet-20250219', 'gpt-4.1-2025-04-14', 'gpt-4.1-mini-2025-04-14', 'o4-mini-2025-04-16']
DOMAINS = ['airline', 'retail', 'telecom']
VALID46_EXCL = {'airline': {'3', '5', '7', '8', '9', '10', '21', '23', '24', '44', '47'},
                'retail': {'12', '14', '27', '29', '36', '47', '48', '78', '87', '106', '108'}}
N_ERR, N_OK_WRITE, N_OK_MULTI = 35, 20, 15
B = 'agent executed exactly the change the user explicitly requested/confirmed; the conflict with gold stems from user-simulator-chosen values, not from a policy/execution error visible in context'
C = 'payment-method-only difference; the user did not clearly specify the payment method, so the gold choice is not determinable from context'
DROPS = {           # pool id -> reason (manual review, DROP only; reviewed in pool order)
    '07c47fa74742': B, '09f755b398b5': B, '0b8411b66828': B,
    '0e9c11608730': B, '0fc999703e92': B, '0fe3ed79f932': B,
    '059195611f5e': C, '066e2918aa32': C, '0c067fd31d09': C,
}
# Rule drop (applied to every candidate, recorded in MANIFEST): telecom gold has no assistant write actions, so an extra
# telecom write (send_payment_request / enable_roaming / refuel_data / resume_line ...) is not a policy violation per se.
RULE_DROPS = {'telecom_unauthorised_action': 'telecom unauthorised_action: gold-ambiguous (telecom gold lists no agent writes; extra writes are not policy violations per se)'}


def rule_drop(x):
    return 'telecom_unauthorised_action' if x['label'] == 1 and x['domain'] == 'telecom' and x['family'] == 'unauthorised_action' else None

sys.path.insert(0, str(TAU2 / 'src'))


def files():
    for a in AGENTS:
        for d in DOMAINS:
            hits = sorted((TAU2 / 'data/tau2/results/final').glob(f'{a}_{d}_*_4trials.json'))
            hits = [h for h in hits if re.fullmatch(rf'{re.escape(a)}_{d}_(default|base)_.*', h.name)]
            for h in hits:
                yield a, d, h


def env_info(domain):
    from tau2.environment.toolkit import get_tool_types
    e = importlib.import_module(f'tau2.domains.{domain}.environment').get_environment()
    tools = e.get_tools()
    types = {k: str(v).split('.')[-1] for k, v in get_tool_types(e.tools).items()}
    return [t.openai_schema for t in tools], types


def valid46_telecom_prefixes():
    import pandas as pd
    d = pd.read_parquet(ROOT / 'valid.parquet')
    return {i.split('::')[0][len('telecom__'):] for i in d.id if i.startswith('telecom__')}


def norm_tel(task_id):
    """tau2 telecom id '[mms_issue]a|b[PERSONA:None]' -> valid46 id form 'mms_issuea-b' (valid46 ids are truncated)."""
    t = re.sub(r'\[PERSONA:[^\]]*\]', '', str(task_id))
    return t.replace('[', '').replace(']', '').replace('|', '-')


def excluded(domain, task_id, tel):
    if domain in VALID46_EXCL:
        return str(task_id) in VALID46_EXCL[domain]
    k = norm_tel(task_id)
    return any(k.startswith(p) or p.startswith(k) for p in tel)


def match(call, gold):
    """tau2 compare_with_tool_call: same name and equal compare_args (all args if None)."""
    if call['name'] != gold['name']:
        return False
    keys = gold.get('compare_args')
    if keys is None:
        keys = list(gold.get('arguments', {}).keys())
        if set(call['arguments']) != set(keys):
            return False
    return all(call['arguments'].get(k) == gold['arguments'].get(k) for k in keys)


def diff(call, golds):
    best = None
    for g in golds:
        if g['name'] != call['name']:
            continue
        keys = g.get('compare_args') or list(g.get('arguments', {}).keys())
        d = {k: dict(actual=call['arguments'].get(k), gold=g['arguments'].get(k)) for k in keys if call['arguments'].get(k) != g['arguments'].get(k)}
        if best is None or len(d) < len(best):
            best = d
    return best


def sid(*xs):
    return hashlib.sha256('|'.join(map(str, xs)).encode()).hexdigest()


def pool():
    from experiments.verification_v4.external.render import blocks, render
    from tau2.agent.llm_agent import AGENT_INSTRUCTION
    tel = valid46_telecom_prefixes()
    out, stats = [], Counter()
    for agent, dom, path in files():
        data = json.loads(path.read_text())
        policy = data['info']['environment_info']['policy']
        tools, types = env_info(dom)
        tasks = {str(t['id']): t for t in data['tasks']}
        rel = str(path.relative_to(TAU2))
        for s in data['simulations']:
            tid = str(s['task_id'])
            if excluded(dom, tid, tel):
                stats['excluded_valid46'] += 1
                continue
            golds = [a for a in (tasks[tid]['evaluation_criteria'] or {}).get('actions') or [] if a.get('requestor', 'assistant') == 'assistant']
            reward = (s.get('reward_info') or {}).get('reward')
            bl = blocks(s['messages'])
            first_bad = True
            for b in bl:
                if b['kind'] != 'assistant' or not b['calls']:
                    continue
                writes = [c for c in b['calls'] if types.get(c['name']) == 'WRITE']
                reads = [c for c in b['calls'] if types.get(c['name']) == 'READ']
                base = dict(file=rel, agent=agent, domain=dom, task_id=tid, sim_id=s['id'], trial=s.get('trial'), turn=b['turn'], reward=reward)
                if reward == 0 and writes and first_bad:
                    bad = [(i, c) for i, c in enumerate(b['calls']) if types.get(c['name']) == 'WRITE' and not any(match(c, g) for g in golds)]
                    if bad:
                        first_bad = False
                        i, c = bad[0]
                        d = diff(c, golds)
                        fam = 'wrong_argument' if d else 'unauthorised_action'
                        out.append(dict(base, label=1, family=fam, call_index=i, call=c, diff=d,
                                        gold_same_name=[g for g in golds if g['name'] == c['name']]))
                        stats[f'err_{fam}'] += 1
                elif reward == 1 and writes and all(any(match(c, g) for g in golds) for c in writes):
                    out.append(dict(base, label=0, family='gold_write', call_index=None, call=writes[0]))
                    stats['ok_write'] += 1
                elif reward == 1 and len(reads) >= 2 and not writes:
                    out.append(dict(base, label=0, family='multi_read', call_index=None, call=None))
                    stats['ok_multi'] += 1
        stats['files'] += 1
    for x in out:
        x['pool_id'] = sid(x['file'], x['sim_id'], x['turn'])[:12]
    out.sort(key=lambda x: sid(x['file'], x['sim_id'], x['turn']))
    OUTD.mkdir(parents=True, exist_ok=True)
    (OUTD / 'pool.jsonl').write_text('\n'.join(json.dumps(x, ensure_ascii=False) for x in out) + '\n')
    print(dict(stats), len(out))
    return out


def select(pl):
    per, chosen = Counter(), {'err': [], 'gold_write': [], 'multi_read': []}
    quota = {'err': N_ERR, 'gold_write': N_OK_WRITE, 'multi_read': N_OK_MULTI}
    for x in pl:
        k = 'err' if x['label'] == 1 else x['family']
        if x['pool_id'] in DROPS or rule_drop(x) or len(chosen[k]) >= quota[k] or per[(x['domain'], x['task_id'])] >= 2:
            continue
        if k == 'err' and sum(1 for y in chosen['err'] if y['domain'] == x['domain']) >= 15:
            continue
        chosen[k].append(x)
        per[(x['domain'], x['task_id'])] += 1
    return chosen['err'] + chosen['gold_write'] + chosen['multi_read']


def review_view(pl, n_err=60):
    """Compact view for the manual DROP review: last user turn before the move, the move's call, the oracle diff."""
    from experiments.verification_v4.external.render import blocks
    cache = {}
    for x in [y for y in pl if y['label'] == 1][:n_err]:
        if x['file'] not in cache:
            cache[x['file']] = {s['id']: s for s in json.loads((TAU2 / x['file']).read_text())['simulations']}
        bl = blocks(cache[x['file']][x['sim_id']]['messages'])
        idx = next(i for i, b in enumerate(bl) if b['kind'] == 'assistant' and b['turn'] == x['turn'])
        users = [b['text'] for b in bl[:idx] if b['kind'] == 'user' and b['text'].strip()]
        prose = [b['text'] for b in bl[:idx] if b['kind'] == 'assistant' and b['text'].strip()]
        print(f"## {x['pool_id']} {x['domain']} task {x['task_id']} {x['family']} | call {x['call']['name']} {json.dumps(x['call']['arguments'])[:220]}")
        print('   diff', json.dumps(x['diff'])[:300] if x['diff'] else '-')
        print('   A:', (prose[-1] if prose else '')[-260:].replace('\n', ' '))
        print('   U:', (users[-1] if users else '')[-260:].replace('\n', ' '))


def cause_text(x):
    c = x['call']
    if x['family'] == 'wrong_argument':
        parts = '; '.join(f"{k}: used {json.dumps(v['actual'])}, correct {json.dumps(v['gold'])}" for k, v in x['diff'].items())
        return f"The assistant calls {c['name']} with wrong argument values ({parts}); the correct action per the policy and the conversation differs."
    return f"The assistant executes {c['name']}({json.dumps(c['arguments'], ensure_ascii=False)[:200]}), a state-changing action that is not permitted / not part of the correct resolution of this request under the policy."


def finalize():
    from experiments.verification_v4.external.render import render
    from tau2.agent.llm_agent import AGENT_INSTRUCTION
    from guardian_truth.verification.pipeline import packet_for
    from guardian_truth.source_search.store import SourceStore
    pl = [json.loads(l) for l in (OUTD / 'pool.jsonl').read_text().splitlines()]
    sel = sorted(select(pl), key=lambda x: sid('order', x['pool_id']))   # ids must not reveal the label stratum
    n_rule = Counter(rule_drop(x) for x in pl if rule_drop(x))
    rows, gold, manifest, failed = [], {}, [], Counter()
    cache, envs = {}, {}
    for n, x in enumerate(sel):
        if x['file'] not in cache:
            cache[x['file']] = json.loads((TAU2 / x['file']).read_text())
        data = cache[x['file']]
        if x['domain'] not in envs:
            envs[x['domain']] = env_info(x['domain'])
        tools, _ = envs[x['domain']]
        s = next(s for s in data['simulations'] if s['id'] == x['sim_id'])
        prompt, response, bl, idx = render(AGENT_INSTRUCTION, data['info']['environment_info']['policy'], tools, s['messages'], x['turn'])
        rid = f"ext_{x['domain'][:3]}_{n:03d}"
        row = dict(id=rid, prompt=prompt, response=response)
        try:   # converter validation: SourceStore round-trip + packet + every call of the move is a current target
            st = SourceStore(row)
            assert st.verify_integrity() is not False
            p = packet_for(row, 20000)
            assert p is not None and p['current_targets']
            calls = [t for t in p['current_targets'] if 'TOOL_CALL' in (t['text'] or '')]
            assert len(calls) == len(bl[idx]['calls']), 'call targets'
            tgt = None
            if x['label'] == 1:
                want = f"TOOL_CALL {x['call']['name']}: {json.dumps(x['call']['arguments'], ensure_ascii=False)}"
                hits = [t['source_id'] for t in p['current_targets'] if want in (t['text'] or '')]
                assert hits, 'error call not found among targets'
                tgt = hits[0]
        except Exception as ex:
            failed[type(ex).__name__ + ':' + str(ex)[:40]] += 1
            continue
        rows.append(row)
        gold[rid] = dict(case=x['pool_id'], domain=x['domain'], family=x['family'], label=x['label'], target=tgt,
                         cause=cause_text(x) if x['label'] == 1 else None, n_targets=len(p['current_targets']),
                         later_call=bool(tgt and tgt != p['current_targets'][0]['source_id']), task_id=x['task_id'], agent=x['agent'])
        manifest.append(dict(id=rid, repo='sierra-research/tau2-bench', commit=TAU2_COMMIT, file=x['file'], simulation_id=x['sim_id'],
                             task_id=x['task_id'], trial=x['trial'], turn=x['turn'], reward=x['reward'], pool_id=x['pool_id'],
                             sha256_prompt=hashlib.sha256(prompt.encode()).hexdigest(), sha256_response=hashlib.sha256(response.encode()).hexdigest()))
    (OUTD / 'inputs.jsonl').write_text('\n'.join(json.dumps(r, ensure_ascii=False) for r in rows) + '\n')
    (OUTD / 'GOLD_eval_only.json').write_text(json.dumps(gold, ensure_ascii=False, indent=1))
    strata = dict(label=Counter(g['label'] for g in gold.values()), domain=Counter(f"{g['domain']}:{g['label']}" for g in gold.values()),
                  family=Counter(g['family'] for g in gold.values()), multi_target=Counter(f"{g['n_targets'] >= 2}:{g['label']}" for g in gold.values()),
                  later_call=sum(g['later_call'] for g in gold.values()))
    m = dict(source=dict(repo='https://github.com/sierra-research/tau2-bench', commit=TAU2_COMMIT, license='MIT'), drops=DROPS, rule_drops=dict(rules=RULE_DROPS, pool_counts=dict(n_rule)),
             conversion_failures=dict(failed), n=len(rows), strata={k: dict(v) if isinstance(v, Counter) else v for k, v in strata.items()},
             sha256_inputs=hashlib.sha256((OUTD / 'inputs.jsonl').read_bytes()).hexdigest(),
             sha256_gold=hashlib.sha256((OUTD / 'GOLD_eval_only.json').read_bytes()).hexdigest(), cases=manifest)
    (OUTD / 'MANIFEST.json').write_text(json.dumps(m, ensure_ascii=False, indent=1))
    print(json.dumps({k: v for k, v in m.items() if k != 'cases'}, ensure_ascii=False))


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('stage', choices=['pool', 'review', 'review-selected', 'finalize'])
    a = ap.parse_args()
    if a.stage == 'pool':
        pool()
    elif a.stage == 'review-selected':   # Amendment 2 §5: reproducible view of every selected ERROR candidate
        pl = [json.loads(l) for l in (OUTD / 'pool.jsonl').read_text().splitlines()]
        review_view(select(pl), n_err=10 ** 6)
    elif a.stage == 'review':
        review_view([json.loads(l) for l in (OUTD / 'pool.jsonl').read_text().splitlines()])
    else:
        finalize()
