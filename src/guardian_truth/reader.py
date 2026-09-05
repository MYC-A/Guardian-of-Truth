"""Read-only, bounded evidence environment for graph-guided recursive reading.

The model requests data, never executable Python, shell commands or external tools.
Chunk IDs point to exact original spans. Graph edges prioritize reading; they do
not become independent evidence for the text they summarize.
"""

from dataclasses import dataclass
import json
import re

from .provenance import value_key
from .types import Source


@dataclass(frozen=True)
class Chunk:
    id: str
    event: int
    role: str
    kind: str
    tool: str | None
    source: Source
    text: str


class EvidenceReader:
    def __init__(self, context, *, chunk_chars=1800, max_evidence_chars=24000, rolling=False):
        if (type(chunk_chars) is not int or type(max_evidence_chars) is not int
                or chunk_chars < 100 or max_evidence_chars < chunk_chars):
            raise ValueError('Invalid evidence limits')
        self.context = context
        self.rolling = rolling
        self.max_chars = max_evidence_chars
        self.chunks = {}
        self.selected = []
        self.used_chars = 0
        self.facts = {f.id: f for f in context.graph.facts}
        self.neighbors = {f.id: set(f.previous) for f in context.graph.facts}
        for fact in context.graph.facts:
            for previous in fact.previous:
                self.neighbors.setdefault(previous, set()).add(fact.id)
        for event_index, event in enumerate(context.history):
            for start in range(event.source.start, event.source.end, chunk_chars):
                end = min(start + chunk_chars, event.source.end)
                key = f'p{len(self.chunks)}'
                self.chunks[key] = Chunk(key, event_index, event.role, event.kind, event.name,
                                        Source('prompt', start, end), context.prompt[start:end])

    def read(self, ids):
        ids = list(dict.fromkeys(ids))
        protected = set(ids) & set(self.selected)
        added = []
        for key in ids:
            chunk = self.chunks.get(key)
            if chunk is None or key in self.selected:
                continue
            if self.used_chars + len(chunk.text) > self.max_chars:
                if not self.rolling:
                    continue
                removable = [old for old in self.selected if old not in protected and old not in added]
                reclaimable = sum(len(self.chunks[old].text) for old in removable)
                if self.used_chars - reclaimable + len(chunk.text) > self.max_chars:
                    continue
                for old in removable:
                    if self.used_chars + len(chunk.text) <= self.max_chars:
                        break
                    self.selected.remove(old)
                    self.used_chars -= len(self.chunks[old].text)
            self.selected.append(key)
            self.used_chars += len(chunk.text)
            added.append(key)
        return added

    def search(self, query, limit=4):
        words = set(re.findall(r'[\w#@.-]{2,}', query.casefold()))
        ranked = []
        for chunk in self.chunks.values():
            overlap = words & set(re.findall(r'[\w#@.-]{2,}', chunk.text.casefold()))
            if overlap:
                ranked.append((len(overlap), chunk.event, chunk.id))
        ranked.sort(reverse=True)
        return [item[2] for item in ranked if item[2] not in self.selected][:limit]

    def graph_chunks(self, fact_ids, hops=1, limit=8):
        frontier = list(dict.fromkeys(fid for fid in fact_ids if fid in self.facts))
        visited = set(frontier)
        for _ in range(min(max(hops, 0), 2)):
            new = set()
            for fid in frontier:
                new.update(self.neighbors.get(fid, ()))
            new -= visited
            visited.update(new)
            frontier = sorted(new)
        sources = [s for fid in sorted(visited) for s in self.facts[fid].sources]
        return [c.id for c in self.chunks.values() if c.id not in self.selected and any(
            c.source.document == s.document and c.source.start < s.end and c.source.end > s.start
            for s in sources)][:limit]

    def entity_chunks(self, field, value, limit=8):
        ids = [f.id for f in self.facts.values() if any(
            e.field == field and value_key(e.value) == value_key(value) for e in f.entities)]
        return self.graph_chunks(ids, limit=limit)

    def response_entity_chunks(self, limit=2):
        """Read exact opaque-identity mentions before broad lexical matches.

        This only ranks sources. It neither equates differently named fields nor
        concludes ownership, correctness or absence from a failed lookup.
        """
        values = {e.value for f in self.facts.values() for e in f.entities
                  if (e.field.endswith('_id') or e.field.endswith('_number'))
                  and isinstance(e.value,str) and len(e.value)>=3
                  and re.search(r'(?<!\w)'+re.escape(e.value)+r'(?!\w)',self.context.response)}
        if not values:
            return []
        relevant = [f for f in self.facts.values() if any(e.value in values for e in f.entities
                     if isinstance(e.value,str))]
        sources = [f.sources[0] for f in relevant if f.sources]
        chunks = [c for c in self.chunks.values() if c.kind=='result' and any(
            c.source.start < s.end and c.source.end > s.start for s in sources)]
        # Prioritize a chunk actually containing the identity over other chunks
        # belonging to the same possibly very large JSON result.
        chunks.sort(key=lambda c:(any(value in c.text for value in values),c.event),reverse=True)
        return [c.id for c in chunks if c.id not in self.selected][:limit]

    def initialize(self, max_initial_chars=12000):
        rolling = self.rolling
        self.rolling = False  # Initial ranking is unchanged by the experiment.
        old_limit = self.max_chars
        self.max_chars = min(old_limit, max_initial_chars)
        # One policy anchor, then the actual entity's observations. Broad lexical
        # matches must not crowd out a direct source with an opaque identity.
        policy = [c.id for c in self.chunks.values() if c.role == 'system']
        self.read(policy[:1])
        entity_chunks = self.response_entity_chunks()
        self.read(entity_chunks)
        if not entity_chunks:
            results = [c for c in self.chunks.values() if c.kind=='result']
            if results:
                last_event = results[-1].event
                self.read([c.id for c in results if c.event==last_event][:2])
        users = [c for c in self.chunks.values() if c.role == 'user' and c.kind == 'text']
        if users:
            last_event = users[-1].event
            self.read([c.id for c in users if c.event == last_event])
        ids = [key for trace in self.context.graph.arguments
               for key in (trace.alternatives + trace.supporting)[:4]]
        self.read(self.graph_chunks(ids, limit=4))
        self.read(self.search(self.context.response, limit=6))
        self.read(policy[1:])
        self.max_chars = old_limit
        self.rolling = rolling

    def request(self, request):
        if not isinstance(request, dict):
            return {'status': 'invalid_request', 'added': []}
        action = request.get('action')
        if action == 'read' and isinstance(request.get('ids'), list):
            ids = [x for x in request['ids'][:8] if isinstance(x, str)]
        elif action == 'search' and isinstance(request.get('query'), str):
            ids = self.search(request['query'][:300])
        elif action == 'graph' and isinstance(request.get('fact_ids'), list):
            ids = self.graph_chunks([x for x in request['fact_ids'][:8] if isinstance(x, str)])
        elif action == 'entity' and isinstance(request.get('field'), str):
            value = request.get('value')
            if type(value) not in (str, int):
                return {'status':'invalid_request','added':[]}
            ids = self.entity_chunks(request['field'], value)
        else:
            return {'status': 'invalid_request', 'added': []}
        previous = list(self.selected)
        added = self.read(ids)
        return {'status': 'ok' if added else 'no_new_evidence', 'added': added,
                'evicted': [key for key in previous if key not in self.selected]}

    def packet(self):
        return [{'id': key, 'role': self.chunks[key].role, 'kind': self.chunks[key].kind,
                 'tool': self.chunks[key].tool, 'start': self.chunks[key].source.start,
                 'end': self.chunks[key].source.end, 'text': self.chunks[key].text}
                for key in self.selected]

    def catalog(self, limit=160):
        # Metadata is explicitly not a source citation. Unseen text stays unread.
        items = list(self.chunks.values())
        return {'total_chunks': len(items), 'truncated':len(items) > limit,
                'chunks':[{'id':c.id,'role':c.role,'kind':c.kind,'tool':c.tool}
                          for c in items[:limit]]}

    def metadata(self):
        """Metadata must not crowd out the original evidence it points to.

        Bound serialized character size independently of fact count: one result
        can contain large scalar values and repeated entity bindings. Truncation
        remains explicit; search/read still address the full local history.
        """
        cap = max(900, min(6000, self.max_chars // 2))
        catalog_limit, graph_limit = 160, 40
        catalog, graph = self.catalog(catalog_limit), self.graph_summary(graph_limit)
        while True:
            catalog_size = len(json.dumps(catalog,ensure_ascii=False))
            graph_size = len(json.dumps(graph,ensure_ascii=False))
            if catalog_size + graph_size <= cap or not (catalog_limit or graph_limit):
                return {'catalog':catalog,'graph':graph}
            if catalog_limit and (catalog_size >= graph_size or not graph_limit):
                catalog_limit //= 2
                catalog = self.catalog(catalog_limit)
            else:
                graph_limit //= 2
                graph = self.graph_summary(graph_limit)

    def graph_summary(self, limit=40):
        keys = list(dict.fromkeys(key for t in self.context.graph.arguments
                                 for key in (t.alternatives + t.supporting)[:4]))[:limit]
        # Text-only answers have no argument traces. Make the graph useful for
        # them too, via observations linked to the retrieved evidence. Recent
        # observations are reading priorities, not assertions of current truth.
        selected_sources = [self.chunks[key].source for key in self.selected]
        related = [f.id for f in reversed(list(self.facts.values())) if any(
            s.start < chosen.end and s.end > chosen.start and s.document == chosen.document
            for s in f.sources for chosen in selected_sources)]
        keys = list(dict.fromkeys(keys + related))[:limit]
        return {
            'warning': 'Structural candidates, not proof of correctness, ownership or current state.',
            'facts':[{'id':f.id,'event':f.event,'field':f.field,'value':f.value,
                      'entities':[{ 'field':e.field,'value':e.value} for e in f.entities],
                      'previous':f.previous} for key in keys if (f := self.facts.get(key))],
            'arguments':[{'path':t.path,'value':t.value,'status':t.status,
                          'supporting':t.supporting[:4],'alternatives':t.alternatives[:4]}
                         for t in self.context.graph.arguments[:limit]],
            'truncated': len(self.context.graph.arguments) > limit or len(self.facts) > len(keys),
        }

    def citation(self, key):
        if key == 'response':
            return Source('response', 0, len(self.context.response)) if self.context.response else None
        if key not in self.selected:
            return None
        return self.chunks[key].source
