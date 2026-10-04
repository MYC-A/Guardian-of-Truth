"""Finite, read-only source exploration. Model gaps remain semantic hypotheses."""
from copy import deepcopy
from guardian_truth.source_search.store import digest


class BoundedRetrieval:
    def __init__(self, store, catalog, target_source_ids, *, max_reads=8, max_rounds=3):
        if type(max_reads) is not int or not 1 <= max_reads <= 8:
            raise ValueError('READ_LIMIT_INVALID')
        if type(max_rounds) is not int or not 1 <= max_rounds <= 4:
            raise ValueError('ROUND_LIMIT_INVALID')
        self.store = store
        self.catalog = {s['source_id']: deepcopy(s) for s in catalog}
        if len(self.catalog) != len(catalog):
            raise ValueError('DUPLICATE_CATALOG_ID')
        self.target_source_ids = list(target_source_ids)
        if not self.target_source_ids:
            raise ValueError('CURRENT_TARGET_REQUIRED')
        for sid in list(self.catalog) + self.target_source_ids:
            store.text(sid)
        self.max_reads, self.max_rounds = max_reads, max_rounds
        self.read_sources, self.gaps, self.traces = {}, {}, []
        self.navigation, self.stop_reason = [], None

    def _ids(self, values, *, targets=False):
        if not isinstance(values, list) or any(not isinstance(v, str) for v in values):
            raise ValueError('GAP_SOURCE_IDS_INVALID')
        allowed = set(self.target_source_ids if targets else self.catalog)
        if any(v not in allowed for v in values):
            raise ValueError('GAP_SOURCE_NAMESPACE_INVALID')
        return list(dict.fromkeys(values))

    def _gap(self, item):
        if not isinstance(item, dict):
            raise ValueError('GAP_INVALID')
        gid = item.get('gap_id')
        if not isinstance(gid, str) or not gid or not isinstance(item.get('question'), str) or not item['question'].strip():
            raise ValueError('GAP_ID_OR_QUESTION_INVALID')
        if not isinstance(item.get('required_fact_type'), str) or not item['required_fact_type']:
            raise ValueError('GAP_FACT_TYPE_INVALID')
        status = item.get('status', 'OPEN')
        if status not in ('OPEN', 'RESOLVED', 'UNRESOLVED'):
            raise ValueError('GAP_STATUS_INVALID')
        result = dict(gap_id=gid, question=item['question'],
            required_fact_type=item['required_fact_type'],
            policy_sources=self._ids(item.get('policy_sources', [])),
            target_sources=self._ids(item.get('target_sources', []), targets=True),
            candidate_source_ids=self._ids(item.get('candidate_source_ids', [])),
            visited_source_ids=self._ids(item.get('visited_source_ids', [])),
            supporting_sources=self._ids(item.get('supporting_sources', [])),
            status=status, unresolved_reason=item.get('unresolved_reason'),
            epistemic_status='MODEL_HYPOTHESIS')
        if result['unresolved_reason'] is not None and not isinstance(result['unresolved_reason'], str):
            raise ValueError('GAP_REASON_INVALID')
        return result

    def context(self):
        return dict(catalog=list(deepcopy(self.catalog).values()),
            target_source_ids=list(self.target_source_ids),
            read_sources=list(deepcopy(self.read_sources).values()),
            gap_ledger=list(deepcopy(self.gaps).values()),
            navigation=deepcopy(self.navigation),
            reads_remaining=self.max_reads-len(self.read_sources),
            rounds_remaining=self.max_rounds-len(self.traces),
            warning='Gap status and sufficiency are semantic hypotheses; search excerpts are navigation, not admitted evidence.')

    def _read(self, sid):
        s = self.store.quotes.get(sid) or self.store.sources.get(sid)
        text = self.store.text(sid)
        windows = []
        for start in range(0, len(text), 8000):
            w = self.store.read_source(sid, start=start, end=min(start+8000, len(text)), limit=8000)
            expected_end = s['start']+min(start+8000,len(text))
            if (w['was_truncated'] or w['document'] != s['document'] or
                    w['start'] != s['start']+start or w['end'] != expected_end or
                    w['source_length'] != len(text) or len(w['text']) != w['end']-w['start']):
                raise ValueError('SOURCE_WINDOW_INTEGRITY_FAILURE')
            windows.append(w)
        if ''.join(w['text'] for w in windows) != text:
            raise ValueError('SOURCE_READ_INCOMPLETE')
        return {**self.catalog[sid], 'source_id': sid, 'document': s['document'],
            'start': s['start'], 'end': s['end'], 'text': text,
            'windows': windows, 'coverage': 'COMPLETE_SELECTED_SOURCE',
            'evidence_status': 'ORIGINAL_SOURCE_NOT_NORMATIVE_PROOF'}

    def step(self, plan):
        if self.stop_reason is not None:
            raise ValueError('CONTROLLER_TERMINAL')
        if len(self.traces) >= self.max_rounds:
            self.stop_reason = 'ROUND_LIMIT'
            raise ValueError('ROUND_LIMIT')
        if not isinstance(plan, dict) or not isinstance(plan.get('operations'), list) or len(plan['operations']) > 8:
            raise ValueError('PLAN_INVALID')
        if type(plan.get('sufficient', False)) is not bool or not isinstance(plan.get('gaps', []), list):
            raise ValueError('PLAN_STATE_INVALID')
        if len(plan.get('gaps', [])) > 16:
            raise ValueError('GAP_LIMIT')
        # Validate the entire round before mutating controller/evidence state.
        gaps = [self._gap(g) for g in plan.get('gaps', [])]
        if len({g['gap_id'] for g in gaps}) != len(gaps):
            raise ValueError('DUPLICATE_GAP_ID')
        ops = deepcopy(plan['operations'])
        for op in ops:
            if not isinstance(op, dict):
                raise ValueError('OPERATION_INVALID')
            if op.get('operation') == 'READ_SOURCE':
                if op.get('source_id') not in self.catalog or op.get('query') is not None:
                    raise ValueError('READ_ARGUMENT_INVALID')
            elif op.get('operation') == 'SEARCH_SOURCES':
                if op.get('source_id') is not None or not isinstance(op.get('query'), str) or not op['query'].strip():
                    raise ValueError('SEARCH_ARGUMENT_INVALID')
            else:
                raise ValueError('OPERATION_NOT_READ_ONLY')
        proposed_reads = set(self.read_sources) | {op['source_id'] for op in ops if op['operation']=='READ_SOURCE'}
        for gap in gaps:
            if not set(gap['visited_source_ids']+gap['supporting_sources']) <= proposed_reads:
                raise ValueError('GAP_EVIDENCE_NOT_COMPLETELY_READ')
            if gap['status']=='RESOLVED' and not gap['supporting_sources']:
                raise ValueError('RESOLVED_GAP_WITHOUT_EVIDENCE')
        before = digest(self.context())
        results, new_reads, new_navigation = [], 0, 0
        for op in ops:
            if op['operation']=='READ_SOURCE':
                sid = op['source_id']
                if sid in self.read_sources:
                    results.append(dict(operation=op, status='ALREADY_READ', new_complete_reads=0))
                elif len(self.read_sources) >= self.max_reads:
                    results.append(dict(operation=op, status='READ_LIMIT', new_complete_reads=0))
                else:
                    value = self._read(sid)
                    self.read_sources[sid] = value
                    new_reads += 1
                    results.append(dict(operation=op, status='COMPLETE_SELECTED_SOURCE', source=value, new_complete_reads=1))
            else:
                hit = self.store.search_sources(op['query'], limit=8)
                hit['admitted_as_evidence'] = False
                hit['catalog_source_ids'] = list(dict.fromkeys(h['source_id'] for h in hit['items'] if h['source_id'] in self.catalog))
                nav = dict(operation=op, result=hit)
                if digest(nav) not in {digest(n) for n in self.navigation}:
                    self.navigation.append(nav)
                    new_navigation += 1
                results.append(dict(operation=op, status='NAVIGATION_ONLY', result=hit, new_complete_reads=0))
        for gap in gaps:
            if not set(gap['visited_source_ids']+gap['supporting_sources']) <= set(self.read_sources):
                gap['status'], gap['unresolved_reason'] = 'UNRESOLVED', 'READ_LIMIT_OR_INCOMPLETE_SOURCE'
                gap['visited_source_ids'] = [sid for sid in gap['visited_source_ids'] if sid in self.read_sources]
                gap['supporting_sources'] = [sid for sid in gap['supporting_sources'] if sid in self.read_sources]
            self.gaps[gap['gap_id']] = gap
        trace = dict(round=len(self.traces)+1, plan=deepcopy(plan), results=results,
            new_complete_reads=new_reads, distinct_complete_reads=len(self.read_sources),
            gap_ledger=list(deepcopy(self.gaps).values()))
        self.traces.append(trace)
        # Stop does not certify a semantic NO_ERROR or discard open questions.
        if plan.get('sufficient', False):
            self.stop_reason = 'MODEL_DECLARED_SUFFICIENT'
        elif len(self.read_sources) >= self.max_reads:
            self.stop_reason = 'READ_LIMIT'
        elif len(self.traces) >= self.max_rounds:
            self.stop_reason = 'ROUND_LIMIT'
        elif not new_reads and not new_navigation:
            self.stop_reason = 'NO_NEW_SOURCE'
        trace['stop_reason'] = self.stop_reason
        trace['state_before_sha256'] = before
        return deepcopy(trace)

    def result(self):
        return dict(stop_reason=self.stop_reason, rounds=len(self.traces),
            distinct_complete_reads=len(self.read_sources),
            read_sources=list(deepcopy(self.read_sources).values()),
            gap_ledger=list(deepcopy(self.gaps).values()), navigation=deepcopy(self.navigation),
            traces=deepcopy(self.traces), completeness_certified=False)

    def run(self, planner):
        while self.stop_reason is None:
            plan = planner(self.context())
            if plan is None:
                self.stop_reason = 'PLANNER_STOP'
                break
            self.step(plan)
        return self.result()
