"""Offline lexical/exact/graph retrieval; rankings never certify norm meaning."""
from collections import defaultdict
from copy import deepcopy
import json
from pathlib import Path
import re
import time

from guardian_truth.policy_table.evaluate import same
from guardian_truth.source_search.store import entity_key
from experiments.hybrid_mechanisms.runner import coverage_plan
from experiments.telecom_causal_recovery import packets as old_packets
from .corpus import source, scalars

METHODS = ('A','local_bm25','B1','B2','B3','exact_graph','bm25_exact','bm25_exact_graph','rrf','coverage')


def query_variants(corpus):
    tools = ' '.join(t.get('tool') or '' for t in corpus.current_targets if t['kind']=='call')
    operands = ' '.join(json.dumps(o['value'],ensure_ascii=False) for o in corpus.operands)
    call_query = tools.replace('_',' ')+' '+operands
    prose = ' '.join(t['text'] for t in corpus.current_targets if t['kind']=='text')
    declarations = ' '.join(d['text'] for d in corpus.declarations)
    broad = '\n'.join([call_query,prose,declarations])
    # Separate aspects are literal original data, no inferred obligation or gold.
    aspects = [s for s in [tools.replace('_',' '),operands,prose,declarations] if s.strip()]
    return {'B1':[call_query.strip() or prose], 'B2':[broad], 'B3':aspects or [prose]}


def _legacy_bm25(query, texts):
    # Execute the existing function's unchanged AST without importing its old
    # graph scaffolding or global sys.path side effects. The source path/SHA is
    # explicit in traces and code seals include it in the parent protocol.
    import ast
    path = Path(__file__).resolve().parents[1]/'searh_23/evidence_graph_search_probe/ranked_search.py'
    tree = ast.parse(path.read_text(encoding='utf-8'))
    keep = [n for n in tree.body if isinstance(n,(ast.Import,ast.ImportFrom)) and
            (not isinstance(n,ast.ImportFrom) or n.module in ('collections','copy','pathlib'))]
    keep += [n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in ('terms','bm25')]
    namespace = {}
    exec(compile(ast.Module(body=keep,type_ignores=[]),str(path),'exec'),namespace)
    return namespace['bm25'](query,texts)


def _rank(corpus, scores):
    return [corpus.catalog[i]['source_id'] for i in sorted(range(len(scores)),key=lambda i:(-float(scores[i]),i))
            if float(scores[i])>0]


def local_bm25(corpus, queries):
    texts = [s['text'] for s in corpus.catalog]
    return [_rank(corpus,_legacy_bm25(q,texts)) for q in queries]


def bm25s_rank(corpus, queries):
    import bm25s
    # Shared Unicode \w tokenization, including IDs, with no stopword/stemming
    # differences against the existing local baseline.
    docs = [re.findall(r'\w+',s['text'].casefold()) for s in corpus.catalog]
    search = bm25s.BM25(method='lucene',k1=1.5,b=.75)
    search.index(docs,show_progress=False)
    lists = []
    for q in queries:
        tokens = re.findall(r'\w+',q.casefold())
        if not tokens:
            lists.append([]);continue
        indices, scores = search.retrieve([tokens],k=len(docs),show_progress=False)
        ranked = sorted(zip(indices[0],scores[0]),key=lambda x:(-float(x[1]),int(x[0])))
        lists.append([corpus.catalog[int(i)]['source_id'] for i,score in ranked if float(score)>0])
    return lists


def exact_rank(corpus):
    scored = defaultdict(float)
    for item in corpus.catalog:
        parent = corpus.store.sources[item['parent_source_id']]
        event = corpus.store.history_events[parent['event']]
        if event.json_valid:
            for path,value in scalars(event.value):
                for operand in corpus.operands:
                    lexeme=json.dumps(value,ensure_ascii=False,separators=(',',':'))
                    # A typed equality in a long parent is not evidence that a
                    # selected early window contains that scalar. Verify raw
                    # field/value spelling in this exact returned window.
                    if path:
                        pattern=re.escape(json.dumps(path[-1],ensure_ascii=False))+r'\s*:\s*'+re.escape(lexeme)+r'(?![\w.])'
                        visible=bool(re.search(pattern,item['text']))
                    else:
                        visible=bool(re.search(r'(?<![\w.])'+re.escape(lexeme)+r'(?![\w.])',item['text']))
                    if same(value,operand['value']) and visible:
                        scored[item['source_id']] += 2 if path and path[-1]==operand['field'] else 1
        # Prose IDs are conservative retrieval hints only: quoted/code literals
        # and numeric operands use exact token boundaries, not string substrings.
        for operand in corpus.operands:
            value = operand['value']
            if isinstance(value,str) and value and re.search(r'(?<![\w.-])'+re.escape(value)+r'(?![\w.-])',item['text']):
                scored[item['source_id']] += .5
    order = {s['source_id']:i for i,s in enumerate(corpus.catalog)}
    return sorted(scored,key=lambda sid:(-scored[sid],order[sid]))


def graph_rank(corpus, exact):
    counts = defaultdict(float)
    parent_to_ids = defaultdict(list)
    for item in corpus.catalog:
        parent_to_ids[item['parent_source_id']].append(item['source_id'])
    # Native unique receipts preserve original actors and chronology. No
    # adjacency-only guess when parallel or USER calls make pairing invalid.
    for rank,sid in enumerate(exact):
        parent = corpus.sources[sid]['parent_source_id']
        paired = corpus.pairs.get(parent)
        for candidate in parent_to_ids.get(paired,[]):
            counts[candidate] += 1/(rank+1)
    for operand in corpus.operands:
        entity = {'field':operand['field'],'value':operand['value']}
        try:
            key = entity_key(entity)
            linked = corpus.store.by_entity.get(key,[])
            neighbors = corpus.store.neighbors(entity,limit=40)['items']
        except (ValueError,KeyError,TypeError):
            continue
        fact_ids = set(linked)
        for neighbor in neighbors:
            fact_ids.update(neighbor['fact_ids'])
        for fid in fact_ids:
            for qid in corpus.store.facts[fid]['source_refs']:
                quote = corpus.store.quotes[qid]
                for item in corpus.catalog:
                    if item['document']==quote['document'] and item['start']<quote['end'] and quote['start']<item['end']:
                        counts[item['source_id']] += .5
    order = {s['source_id']:i for i,s in enumerate(corpus.catalog)}
    return sorted(counts,key=lambda sid:(-counts[sid],order[sid]))


def rrf(rankings, constant=60):
    scores = defaultdict(float)
    first_seen = {}
    for ranking in rankings:
        for rank,sid in enumerate(dict.fromkeys(ranking),1):
            scores[sid] += 1/(constant+rank)
            first_seen.setdefault(sid,len(first_seen))
    return sorted(scores,key=lambda sid:(-scores[sid],first_seen[sid]))


def interleave(rankings):
    """Non-scored fusion control: round-robin independent candidate lists."""
    result=[]
    for index in range(max(map(len,rankings),default=0)):
        for ranking in rankings:
            if index<len(ranking) and ranking[index] not in result:result.append(ranking[index])
    return result


def tokens(text):
    """Conservative UTF8-byte token bound, not a claimed model tokenizer count."""
    return len(text.encode('utf-8'))


def source_cost(sources):
    return len(json.dumps(sources,ensure_ascii=False,separators=(',',':')).encode('utf-8'))


def _related_group(corpus, sid):
    item = corpus.sources[sid]
    paired = corpus.pairs.get(item['parent_source_id'])
    # Selecting a result window groups its unique original call. A long result
    # is not expanded entirely because that would hide a larger read budget.
    if item['kind']=='result' and paired:
        calls = [s['source_id'] for s in corpus.catalog if s['parent_source_id']==paired]
        return list(dict.fromkeys(calls+[sid]))
    return [sid]


def _select(corpus,ranking,read_limit,token_limit,diverse):
    selected, trace = [], []
    mandatory_sources = corpus.current_targets+corpus.declarations
    mandatory_tokens = source_cost(mandatory_sources)
    charged = mandatory_tokens
    seen_categories, seen_tools, seen_actors = set(),set(),set()
    remaining = list(dict.fromkeys(ranking))
    ordinal = {sid:i for i,sid in enumerate(remaining)}
    while remaining:
        def utility(sid):
            item = corpus.sources[sid]
            score = 1/(ordinal[sid]+1)
            if diverse:
                score += 1.0*(item['category'] not in seen_categories)
                score += .35*(item['role'] not in seen_actors)
                score += .2*(item.get('tool') not in seen_tools)
                # Raw exception markers are navigation, not applicability or
                # trusted semantic evidence. No domain or business tool rules.
                if re.search(r'\b(?:unless|except|however|override)\b',item['text'],re.I):
                    score += .25
            return score
        sid = max(remaining,key=lambda s:(utility(s),-ordinal[s]))
        remaining.remove(sid)
        group = [s for s in _related_group(corpus,sid) if s not in selected]
        # Charge the exact final serialized source array. Summing independent
        # array costs adds repeated brackets and made the same seed fit or fail
        # depending on whether call/result were selected together or separately.
        proposed_sources=mandatory_sources+[corpus.sources[s] for s in selected+group]
        proposed_cost=source_cost(proposed_sources)
        extra=proposed_cost-charged
        if len(selected)+len(group)>read_limit:
            trace.append({'source_id':sid,'status':'READ_BUDGET_SKIP','dependency_group':group});continue
        if token_limit is not None and proposed_cost>token_limit:
            trace.append({'source_id':sid,'status':'TOKEN_BUDGET_SKIP','dependency_group':group,'required_token_bound':extra});continue
        selected.extend(group);charged=proposed_cost
        for chosen in group:
            item=corpus.sources[chosen]
            seen_categories.add(item['category']);seen_tools.add(item.get('tool'));seen_actors.add(item['role'])
        trace.append({'source_id':sid,'status':'SELECTED','dependency_group':group,'token_bound':extra})
    return selected,trace,mandatory_tokens,charged


def _packet(corpus, selected, read_sources, method, elapsed, trace, read_limit, token_limit, failure=None):
    mandatory = corpus.current_targets+corpus.declarations
    chars = sum(len(s['text']) for s in read_sources+mandatory)
    charged = source_cost(read_sources+mandatory)
    categories = {s['category'] for s in read_sources}
    uncovered = [{'category':c,'reason':'NO_SELECTED_SOURCE_NOT_PROOF_OF_ABSENCE'}
                 for c in ('POLICY','HISTORY') if c not in categories]
    if any(s['explicit_window'] for s in read_sources if 'explicit_window' in s):
        uncovered.append({'category':'PARENT_SOURCE_COMPLETENESS','reason':'EXPLICIT_SOURCE_WINDOWS_ONLY; all original parents remain accessible'})
    if not corpus.current_targets:
        uncovered.append({'category':'CURRENT_TARGET','reason':'NO_PARSED_ASSISTANT_TARGET'})
    selected_parents={s.get('parent_source_id',s['source_id']) for s in read_sources}
    for item in read_sources:
        if item.get('kind')!='result':continue
        parent=item.get('parent_source_id',item['source_id'])
        pair=corpus.pairs.get(parent)
        if pair is None:
            uncovered.append({'category':'QUALIFIED_RESULT_RECEIPT','source_id':item['source_id'],
                              'reason':'NO_UNIQUE_ORIGINAL_ASSISTANT_RECEIPT; result remains recorded raw observation'})
        elif pair not in selected_parents:
            uncovered.append({'category':'CALL_RESULT_DEPENDENCY','source_id':item['source_id'],
                              'missing_source_id':pair,'reason':'RELATED_CALL_NOT_SELECTED'})
    if token_limit is not None and source_cost(mandatory)>token_limit:
        failure='MANDATORY_CONTEXT_BUDGET_EXCEEDED'
    packet = {'version':'retrieval-bakeoff-v1','method':method,'source_sha256':corpus.store.source_sha256,
              'read_sources':deepcopy(read_sources),'current_targets':deepcopy(corpus.current_targets),
              'declarations':deepcopy(corpus.declarations),'selected_ids':list(selected),
              'trace':trace,'seconds':elapsed,'failure':failure,'read_limit':read_limit,'token_limit':token_limit,
              'cost':{'retrieved_reads':len(read_sources),'mandatory_targets':len(corpus.current_targets),
                      'mandatory_declarations':len(corpus.declarations),'source_chars':chars,
                      'source_token_upper_bound':charged,'token_estimator':'FULL_UTF8_BYTES_CONSERVATIVE_BOUND_NOT_PROVIDER_USAGE',
                      'inference_http':0},'uncovered':uncovered,'completeness_certified':False,
              'absence_proves_semantic_absence':False,'evidence_contract':'Original recorded sources and explicit windows only. Raw matching and graph links are candidate retrieval, not entity/ownership/permission/current-state proof. Absence from this subset never establishes missing process events in the full log.'}
    return packet


def retrieve(corpus, method, read_limit=8, token_limit=None):
    if method not in METHODS:raise ValueError('METHOD_UNKNOWN')
    if type(read_limit) is not int or read_limit not in (8,12):raise ValueError('READ_LIMIT_MUST_BE_8_OR_12')
    if token_limit is not None and (type(token_limit) is not int or token_limit<1):raise ValueError('TOKEN_LIMIT_INVALID')
    corpus.assert_integrity();started=time.perf_counter()
    if method=='A':
        try:
            # Exactly the inherited selector. Its intrinsic eight-read cap is
            # unchanged even when the comparison's advertised cap is twelve.
            plan=coverage_plan(corpus.row,None)
            g,_,norms=old_packets.extract(corpus.row)
            normmap={n['source_id']:n for n in norms}
            selected=[o['source_id'] for o in plan['operations']]
            reads=[normmap[sid] if sid in normmap else old_packets.source(g,sid) for sid in selected]
            for s in reads:s['category']='POLICY' if s['source_id'] in normmap else 'HISTORY'
            total=source_cost(reads+corpus.current_targets+corpus.declarations)
            failure='BASELINE_PACKET_EXCEEDS_TOKEN_BUDGET' if token_limit is not None and total>token_limit else None
            return _packet(corpus,selected,reads,method,time.perf_counter()-started,
                           {'algorithm':'UNCHANGED_IMPORTED_COVERAGE_PLAN','plan':plan,'intrinsic_read_limit':8,
                            'common_catalog_used':False,'budget_semantics':'No pruning or porting of original baseline'},read_limit,token_limit,failure)
        except (ValueError,KeyError,AssertionError) as error:
            return _packet(corpus,[],[],method,time.perf_counter()-started,
                           {'algorithm':'UNCHANGED_IMPORTED_COVERAGE_PLAN','error_type':type(error).__name__,'error':str(error)},
                           read_limit,token_limit,'UNSUPPORTED_BASELINE_CASE')
    queries=query_variants(corpus)
    exact=exact_rank(corpus);graph=graph_rank(corpus,exact)
    lexical=[]
    try:
        if method=='local_bm25':lexical=local_bm25(corpus,queries['B2'])
        elif method not in ('exact_graph',):lexical=bm25s_rank(corpus,queries[method] if method in ('B1','B2','B3') else queries['B3'])
    except ImportError:
        return _packet(corpus,[],[],method,time.perf_counter()-started,{'failure':'BM25S_UNAVAILABLE'},read_limit,token_limit,'DEPENDENCY_UNAVAILABLE')
    rankings=lexical
    if method=='exact_graph':rankings=[exact,graph]
    elif method=='bm25_exact':rankings=lexical+[exact]
    elif method in ('bm25_exact_graph','rrf','coverage'):rankings=lexical+[exact,graph]
    ranking=interleave(rankings) if method in ('exact_graph','bm25_exact','bm25_exact_graph') else rrf(rankings)
    selected,selection,mandatory,charged=_select(corpus,ranking,read_limit,token_limit,method=='coverage')
    corpus.assert_integrity()
    return _packet(corpus,selected,[corpus.sources[s] for s in selected],method,time.perf_counter()-started,
                   {'queries':queries[method] if method in ('B1','B2','B3') else queries['B3'] if method!='local_bm25' else queries['B2'],
                    'rankings':rankings,'fused_ranking':ranking,'selection':selection,
                    'fusion':'ROUND_ROBIN' if method in ('exact_graph','bm25_exact','bm25_exact_graph') else 'RRF_K60',
                    'graph_assurance':'UNIQUE_ORIGINAL_RECEIPTS_AND_CO_RECORDED_CANDIDATES_NOT_SEMANTIC_IDENTITY',
                    'common_catalog_used':True},read_limit,token_limit)


def rank_queries(corpus, queries):
    """BM25S/RRF addressed search over the SAME immutable source catalog."""
    corpus.assert_integrity()
    if not isinstance(queries,list) or any(not isinstance(q,str) or not q.strip() for q in queries):
        raise ValueError('QUERY_LIST_INVALID')
    return rrf(bm25s_rank(corpus,queries)) if queries else []


def assemble(corpus, selected_ids, read_limit=8, token_limit=None, method='ADDRESSED_SOURCE_SELECTION'):
    """Read original addressed candidates, dependency groups and bounded costs.

    Unknown library IDs are rejected. Call/result grouping uses only uniquely
    qualified original assistant receipts. All omissions remain explicit.
    """
    if type(read_limit) is not int or read_limit not in (8,12):raise ValueError('READ_LIMIT_MUST_BE_8_OR_12')
    if token_limit is not None and (type(token_limit) is not int or token_limit<1):raise ValueError('TOKEN_LIMIT_INVALID')
    if not isinstance(selected_ids,list) or any(not isinstance(s,str) or s not in corpus.sources for s in selected_ids):
        raise ValueError('SOURCE_NAMESPACE_INVALID')
    corpus.assert_integrity();started=time.perf_counter()
    selected,trace,_,_=_select(corpus,selected_ids,read_limit,token_limit,False)
    return _packet(corpus,selected,[corpus.sources[s] for s in selected],method,time.perf_counter()-started,
                   {'selection':trace,'input_ids':selected_ids,'common_catalog_used':True},read_limit,token_limit)


def deterministic_extension(corpus, starting_ids, read_limit=12, token_limit=None):
    """Retain starting candidates, then expose receipt/entity neighbors.

    This resolves only mechanical candidate dependencies; no missing normative
    condition or absence is inferred. No reference source lists are consulted.
    """
    exact=exact_rank(corpus)
    graph=graph_rank(corpus,starting_ids+exact)
    dependencies=[]
    for sid in starting_ids:
        parent=corpus.sources[sid]['parent_source_id']
        pair=corpus.pairs.get(parent)
        dependencies += [s['source_id'] for s in corpus.catalog if s['parent_source_id']==pair]
    packet=assemble(corpus,list(dict.fromkeys(starting_ids+dependencies+graph+exact)),read_limit,token_limit,
                    method='S1_DETERMINISTIC_RELATION_EXTENSION')
    missing=[sid for sid in dict.fromkeys(starting_ids) if sid not in packet['selected_ids']]
    if missing:
        packet['failure']='SEED_RETENTION_BUDGET_STOP'
        packet['uncovered'].append({'category':'SEED_EVIDENCE','missing_source_ids':missing,
                                   'reason':'Extension cannot preserve supplied seed within budget; no semantic judgment is eligible.'})
    return packet
