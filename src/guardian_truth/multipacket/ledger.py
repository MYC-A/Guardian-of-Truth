"""Typed evidence memory (minimal graph) shared between packets and controller rounds.

Edge status vocabulary: EXACT (code-verified provenance), SEMANTIC_HYPOTHESIS (model claim),
VERIFIED_SEMANTIC (a second, blinded model pass agreed, still not proof), UNKNOWN, REFUTED.
A model statement never becomes EXACT; only code checks on original spans produce EXACT."""
from dataclasses import dataclass, field

STATUSES = ('EXACT', 'SEMANTIC_HYPOTHESIS', 'VERIFIED_SEMANTIC', 'UNKNOWN', 'REFUTED')
NODE_TYPES = ('Norm', 'Condition', 'Exception', 'Entity', 'Event', 'ToolCall', 'ToolResult', 'CurrentTarget',
              'EvidenceSource', 'Question', 'VerificationResult', 'Claim')


@dataclass
class Node:
    id: str
    type: str
    text: str = ''
    meta: dict = field(default_factory=dict)


@dataclass
class Edge:
    src: str
    dst: str
    type: str
    status: str
    origin: str

    def __post_init__(self):
        if self.status not in STATUSES:
            raise ValueError(self.status)


class Ledger:
    def __init__(self):
        self.nodes, self.edges = {}, []

    def node(self, id, type, text='', **meta):
        if type not in NODE_TYPES:
            raise ValueError(type)
        if id not in self.nodes:
            self.nodes[id] = Node(id, type, text, meta)
        return self.nodes[id]

    def edge(self, src, dst, type, status, origin):
        e = Edge(src, dst, type, status, origin)
        if not any((x.src, x.dst, x.type, x.status, x.origin) == (src, dst, type, status, origin) for x in self.edges):
            self.edges.append(e)
        return e

    def promote(self, src, dst, type, status, origin):
        """Status changes are explicit new edges; the old hypothesis stays visible."""
        if status == 'EXACT':
            raise ValueError('semantic relations cannot be promoted to EXACT')
        return self.edge(src, dst, type, status, origin)

    def has_cycle(self):
        adj = {}
        for e in self.edges:
            adj.setdefault(e.src, []).append(e.dst)
        state = {}

        def visit(n):
            state[n] = 1
            for m in adj.get(n, []):
                if state.get(m) == 1 or (state.get(m) is None and visit(m)):
                    return True
            state[n] = 2
            return False
        return any(state.get(n) is None and visit(n) for n in list(adj))

    def compact(self):
        """Serializable claims for a later pass: model claims are labelled MODEL_HYPOTHESIS."""
        claims = []
        for n in self.nodes.values():
            if n.type != 'Claim':
                continue
            out = [e for e in self.edges if e.src == n.id]
            claims.append(dict(claim_id=n.id, origin=n.meta.get('origin'), status='MODEL_HYPOTHESIS',
                               decision=n.meta.get('decision'), target_id=n.meta.get('target_id'),
                               reason=n.text,
                               norms=[dict(policy_source_id=e.dst, interpretation=self.nodes[e.dst].meta.get('interp', {}).get(n.id))
                                      for e in out if e.type == 'INVOKES'],
                               evidence=[dict(source_id=e.dst, provenance=e.status, fact=self.nodes[e.dst].meta.get('facts', {}).get(n.id))
                                         for e in out if e.type == 'SUPPORTED_BY'],
                               open_questions=[self.nodes[e.dst].text for e in out if e.type == 'RAISES']))
        return claims


def from_reply(ledger, reply, packet, origin):
    """Add one admitted I4 reply; provenance edges are checked against the packet (EXACT/REFUTED)."""
    if not reply:
        return None
    ss = {s['source_id']: s for s in packet['read_sources'] + packet['current_targets'] + packet['declarations']}
    cid = f'claim:{origin}'
    t = reply['regulated_action']['target_id']
    ledger.node(cid, 'Claim', reply.get('reason', ''), origin=origin, decision=reply['decision'], target_id=t)
    ledger.node(t, 'CurrentTarget', ss.get(t, {}).get('text', '')[:200])
    ledger.edge(cid, t, 'REGULATES', 'EXACT' if t in {s['source_id'] for s in packet['current_targets']} else 'REFUTED', origin)
    for n in reply.get('applicable_norms', []):
        node = ledger.node(n['policy_source_id'], 'Norm', ss.get(n['policy_source_id'], {}).get('text', '')[:200])
        node.meta.setdefault('interp', {})[cid] = f"{n['modality']}: {n['interpretation']}"
        ledger.edge(cid, n['policy_source_id'], 'INVOKES', 'SEMANTIC_HYPOTHESIS', origin)
    for e in reply.get('supporting_evidence', []):
        src = ss.get(e['source_id'])
        node = ledger.node(e['source_id'], 'EvidenceSource', (src or {}).get('text', '')[:200])
        node.meta.setdefault('facts', {})[cid] = e['fact']
        ok = src is not None and e['actor'] == src.get('role', 'unknown')
        ledger.edge(cid, e['source_id'], 'SUPPORTED_BY', 'EXACT' if ok else 'REFUTED', origin)
    for i, q in enumerate(reply.get('open_questions', [])):
        ledger.node(f'{cid}:q{i}', 'Question', q)
        ledger.edge(cid, f'{cid}:q{i}', 'RAISES', 'UNKNOWN', origin)
    return cid


def programmatic_check(reply, packet):
    """R1: code-checkable properties of a reason (never semantic correctness)."""
    ss = {s['source_id']: s for s in packet['read_sources'] + packet['current_targets'] + packet['declarations']}
    targets = {s['source_id'] for s in packet['current_targets']}
    ev = reply.get('supporting_evidence', [])
    hist_events = [ss[e['source_id']].get('event') for e in ev if e['source_id'] in ss and ss[e['source_id']].get('category') == 'HISTORY']
    flags = dict(target_valid=reply['regulated_action']['target_id'] in targets,
                 norms_exist=all(n['policy_source_id'] in ss for n in reply.get('applicable_norms', [])),
                 evidence_actor_ok=all(e['source_id'] in ss and e['actor'] == ss[e['source_id']].get('role', 'unknown') for e in ev),
                 cites_current_target=any(e['source_id'] in targets for e in ev),
                 cited_history_events=sorted({h for h in hist_events if h is not None}),
                 has_norm=bool(reply.get('applicable_norms')))
    # an accusation that cites only historical assistant tool calls and never the current move is suspect
    flags['historical_only_accusation'] = (reply['decision'] == 'ERROR' and not flags['cites_current_target'] and bool(ev)
                                           and all(ss.get(e['source_id'], {}).get('role') == 'assistant'
                                                   and ss.get(e['source_id'], {}).get('kind') == 'call' for e in ev))
    flags['r1_pass'] = all(flags[k] for k in ('target_valid', 'norms_exist', 'evidence_actor_ok', 'has_norm')) and not flags['historical_only_accusation']
    return flags
