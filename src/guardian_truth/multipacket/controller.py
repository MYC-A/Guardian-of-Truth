"""Deterministic question-directed source search (Gap Controller G2/G4 tool layer).

Tools operate only on stored original units: retrieve_relevant, read_policy_neighbors,
lookup_entity, find_call_results. Nothing executes business tools. Search order is
BFS, DFS (depth-limited) or PRIORITY (cost-aware); questions are deduplicated, tool
invocations are cycle-checked, and anything left when the budget ends stays UNKNOWN."""
import re
from collections import deque
from dataclasses import dataclass, field

from guardian_truth.evidence_packer import PackerConfig
from guardian_truth.evidence_packer.packer import _qualified_pairs, _terms, bm25, build_units

GAP_TYPES = ('MISSING_POLICY', 'MISSING_FACT', 'MISSING_ENTITY_BINDING', 'MISSING_RECEIPT', 'MISSING_EXCEPTION_CHECK',
             'UNCERTAIN_NORM_SCOPE', 'POSSIBLE_MISSED_OBLIGATION', 'UNVERIFIED_CLAIM')
_ID = re.compile(r'(?<![\w#])#?[A-Za-z]*\d[\w-]{3,}')
_POLICY_WORDS = re.compile(r'\b(polic|rule|allow|permit|must|require|forbid|prohibit|eligib|exception|правил|полит|разреш|запрещ|обязан|исключен)', re.I)
_EXC_WORDS = re.compile(r'\b(exception|unless|except|waiv|исключ|кроме|если не)', re.I)


def norm_q(text):
    return ' '.join(_terms(text))[:200]


@dataclass
class Question:
    text: str
    origin: str
    depth: int = 0
    parent: str | None = None
    kind: str = 'MISSING_FACT'
    linked_norms: list = field(default_factory=list)
    status: str = 'UNKNOWN'
    reads: list = field(default_factory=list)

    @property
    def key(self):
        return norm_q(self.text)


def classify(text):
    if _EXC_WORDS.search(text):
        return 'MISSING_EXCEPTION_CHECK'
    if _ID.search(text):
        return 'MISSING_ENTITY_BINDING'
    if _POLICY_WORDS.search(text):
        return 'MISSING_POLICY'
    return 'MISSING_FACT'


class Controller:
    def __init__(self, row, read_units=(), order='PRIORITY', max_hops=4, max_chars=8000, max_depth=2, per_query=2):
        self.units, _, store, _ = build_units(row, PackerConfig())
        self.by = {u['uid']: u for u in self.units}
        self.pool = [u for u in self.units if u['category'] in ('POLICY', 'HISTORY') and u['kind'] not in ('heading', 'tag')]
        pairs, _ = _qualified_pairs(store.history_events)
        self.partner = {}
        for r, (c, _) in pairs.items():
            self.partner[r] = c; self.partner[c] = r
        self.read = set(read_units)
        self.order, self.max_hops, self.max_chars, self.max_depth, self.per_query = order, max_hops, max_chars, max_depth, per_query
        self.seen_q, self.visited, self.trace, self.selected = set(), set(), [], []
        self.hops = self.chars = 0
        self.stop = None

    # ---- tools (pure functions of the stored row)
    def retrieve_relevant(self, text, category=None):
        cand = [u for u in self.pool if u['uid'] not in self.read and (category is None or u['category'] == category)]
        if not cand:
            return []
        scores = bm25(_terms(text), [u['text'] for u in cand])
        best = sorted(range(len(cand)), key=lambda i: (-scores[i], i))
        return [cand[i]['uid'] for i in best[:self.per_query] if scores[i] > 0]

    def read_policy_neighbors(self, uid):
        u = self.by[uid]
        if u['category'] != 'POLICY' or not u['parents']:
            return []
        par = u['parents'][-1]
        return [x['uid'] for x in self.pool if x['category'] == 'POLICY' and x['parents'] and x['parents'][-1] == par
                and x['uid'] not in self.read][:3]

    def lookup_entity(self, ident):
        p = re.compile(r'(?<![\w])' + re.escape(ident.lstrip('#')) + r'(?![\w])')
        hits = [u['uid'] for u in self.pool if u['category'] == 'HISTORY' and u['uid'] not in self.read and p.search(u['text'])]
        return hits[-1:] + hits[:1] if hits else []

    def find_call_results(self, uid):
        u = self.by[uid]
        if u['category'] != 'HISTORY':
            return []
        other = self.partner.get(f"h{u['event']}")
        return [x['uid'] for x in self.pool if other and f"h{x['event']}" == other and x['uid'] not in self.read]

    # ---- traversal
    def _invoke(self, tool, arg, q):
        if (tool, arg) in self.visited:
            self.trace.append(dict(q=q.text[:80], tool=tool, arg=str(arg)[:60], result='CYCLE_SKIPPED')); return []
        if self.hops >= self.max_hops:
            self.stop = self.stop or 'HOP_BUDGET'; return []
        self.visited.add((tool, arg)); self.hops += 1
        got = []
        for uid in getattr(self, tool)(arg):
            size = self.by[uid]['end'] - self.by[uid]['start']
            if uid in self.read or self.chars + size > self.max_chars:
                continue
            self.read.add(uid); self.selected.append(uid); self.chars += size; got.append(uid)
        self.trace.append(dict(q=q.text[:80], kind=q.kind, depth=q.depth, tool=tool, arg=str(arg)[:60], new_units=got))
        return got

    def _priority(self, q):
        return (-(2 if q.linked_norms else 0) - (1 if q.kind in ('MISSING_ENTITY_BINDING', 'MISSING_EXCEPTION_CHECK') else 0) + q.depth, len(q.text))

    def explore(self, questions):
        """Answer-free evidence gathering for a set of questions; returns per-question reads."""
        frontier = []
        for q in questions:
            if q.key and q.key not in self.seen_q:
                self.seen_q.add(q.key)
                frontier.append(q)
        if self.order == 'BFS':
            dq = deque(frontier); pop = dq.popleft; push = dq.append; has = lambda: bool(dq)
        elif self.order == 'DFS':
            st = list(reversed(frontier)); pop = st.pop; push = st.append; has = lambda: bool(st)
        else:
            frontier.sort(key=self._priority); pl = frontier; pop = lambda: pl.pop(0); push = lambda x: (pl.append(x), pl.sort(key=self._priority)); has = lambda: bool(pl)
        while has():
            if self.hops >= self.max_hops or self.chars >= self.max_chars:
                self.stop = 'BUDGET_EXHAUSTED'; break
            q = pop()
            if q.depth > self.max_depth:
                continue
            cat = 'POLICY' if q.kind in ('MISSING_POLICY', 'MISSING_EXCEPTION_CHECK', 'UNCERTAIN_NORM_SCOPE', 'POSSIBLE_MISSED_OBLIGATION') else None
            got = self._invoke('retrieve_relevant', q.text, q) if cat is None else self._invoke_cat(q, cat)
            for ident in sorted(set(_ID.findall(q.text)))[:2]:
                got += self._invoke('lookup_entity', ident, q)
            for uid in list(got):
                if self.by[uid]['category'] == 'POLICY' and q.kind == 'MISSING_EXCEPTION_CHECK':
                    got += self._invoke('read_policy_neighbors', uid, q)
                if self.by[uid]['category'] == 'HISTORY':
                    got += self._invoke('find_call_results', uid, q)
            q.reads += got
            q.status = 'EVIDENCE_GATHERED' if got else 'NO_NEW_EVIDENCE'
            if self.order == 'DFS' and got and q.depth < self.max_depth:
                # bounded deepening: entities in the newest read become child questions
                for ident in sorted(set(_ID.findall(' '.join(self.by[u]['text'] for u in got[:1]))))[:1]:
                    child = Question(f'binding of {ident}', q.origin, q.depth + 1, q.key, 'MISSING_ENTITY_BINDING')
                    if child.key not in self.seen_q:
                        self.seen_q.add(child.key); push(child)
        if not self.stop:
            self.stop = 'NO_OPEN_QUESTIONS'
        return questions

    def _invoke_cat(self, q, cat):
        key = ('retrieve_relevant', (q.text, cat))
        if key in self.visited:
            self.trace.append(dict(q=q.text[:80], tool='retrieve_relevant', result='CYCLE_SKIPPED')); return []
        if self.hops >= self.max_hops:
            return []
        self.visited.add(key); self.hops += 1
        got = []
        for uid in self.retrieve_relevant(q.text, cat) + self.retrieve_relevant(q.text, 'HISTORY')[:1]:
            size = self.by[uid]['end'] - self.by[uid]['start']
            if uid in self.read or self.chars + size > self.max_chars:
                continue
            self.read.add(uid); self.selected.append(uid); self.chars += size; got.append(uid)
        self.trace.append(dict(q=q.text[:80], kind=q.kind, depth=q.depth, tool='retrieve_relevant', arg=cat, new_units=got))
        return got

    def summary(self):
        return dict(order=self.order, hops=self.hops, chars=self.chars, stop=self.stop, questions=len(self.seen_q),
                    selected_units=list(self.selected), loops_prevented=sum(1 for t in self.trace if t.get('result') == 'CYCLE_SKIPPED'))
