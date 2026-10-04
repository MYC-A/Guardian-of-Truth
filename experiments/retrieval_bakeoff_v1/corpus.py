"""Gold-free corpus of exact SourceStore spans with deterministic window IDs."""
from dataclasses import dataclass
from copy import deepcopy
import re

from guardian_truth.evidence_graph import EvidenceGraph
from guardian_truth.evidence_graph.graph import windows
from guardian_truth.policy_table_v11.provenance import observations
from guardian_truth.source_search.store import SourceStore, digest

WINDOW_CHARS = 4000


def scalars(value, path=()):
    if isinstance(value, dict):
        for key, child in value.items():
            yield from scalars(child, path + (str(key),))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from scalars(child, path + (str(index),))
    else:
        yield path, value


def source(store, sid, *, graph=None, category=None, parent_source_id=None):
    original = store.sources.get(sid) or store.quotes.get(sid) or (graph.refs.get(sid) if graph else None)
    if original is None:
        raise ValueError('SOURCE_NOT_REGISTERED')
    text = store.raw[original['document']][original['start']:original['end']]
    result = {'source_id': sid, **{k: original[k] for k in ('document','start','end','role','kind','tool','event') if k in original},
              'text': text, 'parent_source_id': parent_source_id or sid,
              'category': category or 'HISTORY', 'sha256': digest({'text':text}),
              'evidence_status': 'ORIGINAL_SOURCE_NOT_CURRENT_TRUTH_OR_PERMISSION'}
    return result


def sections(text, max_chars=WINDOW_CHARS):
    """Heading and paragraph boundaries are navigation; partition every char.

    Long sections are explicit bounded windows. No semantic or domain-specific
    policy extraction, title-based exceptions or invisible head/tail dropping.
    """
    cuts = {0, len(text)}
    cuts.update(m.start() for m in re.finditer(r'(?m)^[ \t]*#{1,6}[ \t]+[^\r\n]+', text))
    ordered = sorted(cuts)
    for left, right in zip(ordered, ordered[1:]):
        for start, end in windows(text[left:right], max_chars):
            if start < end:
                yield left+start, left+end


@dataclass
class Corpus:
    row: dict
    store: object
    graph: object
    catalog: list
    sources: dict
    current_targets: list
    declarations: list
    operands: list
    pairs: dict
    receipt_diagnostics: list
    signature: str

    def assert_integrity(self):
        self.graph._assert_integrity()
        if self.row != self.store.raw or self.sources != {s['source_id']:s for s in self.catalog}:
            raise ValueError('CORPUS_ADDRESS_OR_INPUT_CHANGED')
        if self.signature != digest({'raw':self.store.raw,'catalog':self.catalog,
                'targets':self.current_targets,'declarations':self.declarations,
                'operands':self.operands,'pairs':self.pairs,'receipt_diagnostics':self.receipt_diagnostics,
                'recorded_graph_facts':self.store.facts}):
            raise ValueError('CORPUS_CHANGED')
        for item in self.catalog+self.current_targets+self.declarations:
            if self.store.raw[item['document']][item['start']:item['end']] != item['text']:
                raise ValueError('SOURCE_SPAN_CHANGED')


def build_corpus(row):
    """Read prompt/response only, even if the caller passes labels or rationale."""
    original = {key:row[key] for key in ('prompt','response')}
    store = SourceStore(original)
    graph = EvidenceGraph(store)
    targets = [source(store,sid,category='TARGET') for sid,s in store.sources.items()
               if s['document']=='response' and s['kind']!='raw' and s['role']=='assistant']
    declarations = [source(store,sid,graph=graph,category='DECLARATION')
                    for name,sid in graph.declarations.items()
                    if name in {s.get('tool') for s in targets if s['kind']=='call'}]
    # All assistant response text/calls are retained; an empty parsed assistant
    # inventory is an explicit unsupported target, not an automatically clean move.
    operands = []
    for item in targets:
        event = store.target_events[item['event']]
        if event.kind=='call' and event.json_valid:
            operands.extend({'target_source_id':item['source_id'],'field':path[-1] if path else '',
                             'path':list(path),'value':value,'value_type':type(value).__name__}
                            for path,value in scalars(event.value))
    catalog = []
    for sid,s in store.sources.items():
        if s['document']!='prompt' or s['kind']=='raw':
            continue
        category = 'POLICY' if s['role']=='system' else 'HISTORY'
        text = store.text(sid)
        if category=='POLICY' or len(text)>WINDOW_CHARS:
            for start,end in sections(text):
                qid = store.quote_id('prompt',s['start']+start,s['start']+end)
                item = source(store,qid,category=category,parent_source_id=sid)
                item.update(role=s['role'],kind=s['kind'],tool=s.get('tool'),event=s['event'],
                            parent_source_length=len(text),explicit_window=True,
                            parent_coverage='EXACT_WINDOW_NOT_COMPLETE_PARENT')
                catalog.append(item)
        else:
            item = source(store,sid,category=category)
            item.update(parent_source_length=len(text),explicit_window=False,
                        parent_coverage='COMPLETE_PARENT')
            catalog.append(item)
    pairs, diagnostics = {}, []
    events = [('h'+str(i),e) for i,e in enumerate(store.history_events)]
    for tool in sorted({e.name for _,e in events if e.name}):
        for receipt in observations(events,tool):
            diagnostic = {'call_source_id':receipt.call_sid,'result_source_id':receipt.result_sid,
                          'valid':receipt.valid,'reason':receipt.reason,'tool':tool}
            diagnostics.append(diagnostic)
            if receipt.valid:
                pairs[receipt.call_sid]=receipt.result_sid
                pairs[receipt.result_sid]=receipt.call_sid
    ss = {s['source_id']:s for s in catalog}
    signature = digest({'raw':store.raw,'catalog':catalog,'targets':targets,'declarations':declarations,
                        'operands':operands,'pairs':pairs,'receipt_diagnostics':diagnostics,
                        'recorded_graph_facts':store.facts})
    corpus = Corpus(deepcopy(original),store,graph,catalog,ss,targets,declarations,operands,pairs,diagnostics,signature)
    corpus.assert_integrity()
    return corpus
