"""Budgeted, provenance-safe evidence packing for verifying one assistant move (U2).

Domain-agnostic: no tool names, IDs, business rules or case IDs.

Provenance contract (fixes of the U1 review):
* An evidence record never spans two events, actors, kinds or tools. Policy
  blocks merge only inside the same system event and normative category; the
  merged record lists every member unit with its own offsets and kind.
* Every record carries a native SourceStore reference: the native event id
  (``h<i>``/``t<i>``) when the record is the whole event, otherwise a quote id
  registered with ``SourceStore.quote_id`` for the exact range, plus the native
  parent event id.
* Call/receipt groups come from the existing qualified pairing
  (``policy_table_v11.provenance.observations``): a pair exists only when the
  result has exactly one pending call of the same tool. Same-actor USER pairs
  are recorded as ``UNIQUE_SAME_ACTOR`` (not an assistant receipt). Ambiguous
  results stay unpaired. Group completeness is reported, not assumed.
* "Tool is not declared" is claimed only from the authoritative
  ``parse_catalog`` result when it reports a complete catalog and agrees with
  the structural splitter; otherwise the status is explicitly unverified.
* Required anchors (latest user message by default) that do not fit produce an
  explicit failure; optional anchors report SELECTED / BUDGET_SKIPPED / ABSENT.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
import hashlib
import json
import math
import re

from guardian_truth.parsing import parse_catalog
from guardian_truth.policy_table_v11.provenance import observations
from guardian_truth.source_search.store import SourceStore

from .embed import NoEmbedder

HEADING = re.compile(r'^[ \t]*(#{1,6})[ \t]+\S')
TAG_LINE = re.compile(r'^[ \t]*(?:</?[A-Za-z][\w-]*>|\[[A-Z][A-Z _-]+\])[ \t]*$')
TOOL_LINE = re.compile(r'^- (?P<name>[\w.-]+)\s+[—–]\s*')
WORD = re.compile(r'\w+', re.UNICODE)
IDENT = re.compile(r'(?<![\w@.-])(?:[\w.+-]+@[\w-]+\.[\w.]+|(?=[\w-]*\d)[\w-]{3,})(?![\w-])')
EMPHASIS = re.compile(r'\*\*([^*\n]{2,60})\*\*|`([^`\n]{2,60})`|«([^»\n]{2,60})»|"([^"\n]{2,60})"')
CAPS = re.compile(r'(?<![\w-])[A-Z][A-Z0-9_]{2,}(?![\w-])')
LATIN_RUN = re.compile(r'[A-Za-z][A-Za-z0-9_.-]*(?:[ -][A-Z][A-Za-z0-9_.-]*)*')
EVIDENCE_STATUS = 'ORIGINAL_SOURCE_NOT_CURRENT_TRUTH_OR_PERMISSION'
VERSION = 'evidence-packer-u2'


@dataclass(frozen=True)
class PackerConfig:
    budget_bytes: int | None = 20000
    max_block_chars: int = 1500
    max_event_chars: int = 3000
    policy_max_share: float = 0.6
    segment_share: float = 0.5
    user_share: float = 0.35
    provenance_share: float = 0.3
    max_identifiers: int = 8
    rrf_k: int = 10
    weights: dict = field(default_factory=lambda: dict(lexical=1.0, dense=1.0, entity=1.0, recency=1.0))
    anchors: tuple = ('last_user', 'last_assistant', 'first_user', 'entity_provenance',
                      'current_segment', 'user_turns', 'policy_root')
    required_anchors: tuple = ('last_user',)
    whole_policy_if_fits: bool = True
    # Research hooks (defaults keep U2 behaviour byte-identical):
    extra_queries: tuple = ()          # gap-directed text added to the lexical/dense query
    exclude_uids: frozenset = frozenset()  # units already read elsewhere; never chosen as primary units
    shared_anchors: tuple = ('last_user', 'last_assistant')  # anchors exempt from exclusion


# ---------------------------------------------------------------- units

def _lines(text, offset):
    position = 0
    for line in text.splitlines(keepends=True):
        yield offset + position, line
        position += len(line)


def _split_long(start, end, raw, limit):
    """Gapless split of [start,end) at line boundaries into pieces <= limit."""
    if end - start <= limit:
        return [(start, end)]
    pieces, left = [], start
    for line_start, line in _lines(raw[start:end], start):
        if line_start + len(line) - left > limit and line_start > left:
            pieces.append((left, line_start)); left = line_start
    pieces.append((left, end))
    final = []
    for a, b in pieces:
        while b - a > limit:
            final.append((a, a + limit)); a += limit
        final.append((a, b))
    return final


def _system_units(raw, start, end, cfg, event_index, catalog_source):
    cuts, previous_blank, in_tool, after_marker = [], True, False, False
    for line_start, line in _lines(raw[start:end], start):
        if not line.strip():
            previous_blank = True; continue
        heading, tool = HEADING.match(line), TOOL_LINE.match(line)
        in_catalog = catalog_source is not None and catalog_source.start <= line_start < catalog_source.end
        if heading:
            cuts.append((line_start, 'heading', len(heading.group(1)), None)); in_tool = False
        elif TAG_LINE.match(line):
            cuts.append((line_start, 'tag', None, None)); in_tool = False
        elif tool and in_catalog:
            cuts.append((line_start, 'tool', None, tool.group('name'))); in_tool = True
        elif in_tool and line[:1] in ' \t':
            pass  # continuation of a tool declaration
        elif previous_blank or in_tool or after_marker:
            cuts.append((line_start, 'block', None, None)); in_tool = False
        # Marker lines are context, while their following body is independently
        # rankable even when the author did not insert a blank line.
        after_marker = bool(heading or TAG_LINE.match(line))
        previous_blank = False
    if not cuts or cuts[0][0] != start:
        cuts.insert(0, (start, 'block', None, None))
    units, stack, scope_bodies = [], [], {}
    pending_scope = None
    bounds = [c[0] for c in cuts[1:]] + [end]
    for (left, kind, level, tool), right in zip(cuts, bounds):
        if kind == 'heading':
            while stack and stack[-1][0] >= level:
                stack.pop()
        in_catalog = catalog_source is not None and catalog_source.start <= left < catalog_source.end
        category = 'CATALOG' if in_catalog else 'POLICY'
        parents = [] if in_catalog else [p for _, uid in stack for p in [uid] + scope_bodies.get(uid, [])]
        pieces = [(left, right)] if kind in ('heading', 'tag', 'tool') else _split_long(left, right, raw, cfg.max_block_chars)
        scope_of = pending_scope if category == 'POLICY' and kind == 'block' else None
        for a, b in pieces:
            units.append(dict(uid=f'p{a}', document='prompt', start=a, end=b, category=category,
                              role='system', kind=kind, tool=tool, event=event_index, parents=list(parents),
                              scope_of=scope_of,
                              root_scope=(category == 'POLICY' and kind == 'block' and len(stack) <= 1)))
        if scope_of:
            # The first paragraph can state governing conditions for the rest
            # of the section. Descendants require every chunk of that body.
            scope_bodies[scope_of] = [f'p{a}' for a, _ in pieces]
            pending_scope = None
        if kind == 'heading' and not in_catalog:
            stack.append((level, f'p{left}'))
            pending_scope = f'p{left}'
        elif in_catalog:
            pending_scope = None
    return units


def _qualified_pairs(history):
    """Call/result pairs from the existing unique-receipt logic, per actor."""
    events = [('h' + str(i), e) for i, e in enumerate(history)]
    pairs, diagnostics = {}, []
    for tool in sorted({e.name for _, e in events if e.name}):
        for obs in observations(events, tool):
            call, result = obs.call_sid, obs.result_sid
            if call is None:
                status = 'AMBIGUOUS_UNPAIRED'
            elif obs.reason is None:
                status = 'QUALIFIED_ASSISTANT_RECEIPT'
            elif obs.call.role == obs.result.role and obs.reason in ('call_actor_not_assistant', 'result_actor_not_assistant'):
                status = 'UNIQUE_SAME_ACTOR'
            elif obs.reason == 'call_arguments_invalid' and obs.call.role == obs.result.role:
                status = 'UNIQUE_SAME_ACTOR_INVALID_ARGUMENTS'
            else:
                status = 'ACTOR_MISMATCH_UNPAIRED'
            diagnostics.append(dict(tool=tool, call=call, result=result, status=status, reason=obs.reason))
            if call is not None and status.startswith(('QUALIFIED', 'UNIQUE')):
                pairs[result] = (call, status)
    return pairs, diagnostics


def build_units(row, cfg=PackerConfig(), store=None):
    store = store or SourceStore({'prompt': row['prompt'], 'response': row['response']})
    raw = store.raw
    history, targets = store.history_events, store.target_events
    catalog = parse_catalog(history, raw['prompt'])
    units = []
    for index, event in enumerate(history):
        s, e = event.source.start, event.source.end
        if event.role == 'system':
            units.extend(_system_units(raw['prompt'], s, e, cfg, index, catalog.source))
            continue
        pieces = _split_long(s, e, raw['prompt'], cfg.max_event_chars)
        for a, b in pieces:
            units.append(dict(uid=f'h{index}' + ('' if len(pieces) == 1 else f'@{a}'), document='prompt',
                              start=a, end=b, category='HISTORY', role=event.role, kind=event.kind,
                              tool=event.name, event=index, parents=[], root_scope=False,
                              window_of=None if len(pieces) == 1 else f'h{index}'))
    target_units = [dict(uid=f't{i}', document='response', start=ev.source.start, end=ev.source.end,
                         category='TARGET', role=ev.role, kind=ev.kind, tool=ev.name, event=i,
                         parents=[], root_scope=False, window_of=None) for i, ev in enumerate(targets)]
    for u in units + target_units:
        u['text'] = raw[u['document']][u['start']:u['end']]
    return units, target_units, store, catalog


# ---------------------------------------------------------------- signals

def _terms(text):
    out = []
    for word in WORD.findall(text.casefold()):
        out.append(word)
        if '_' in word:
            out.extend(p for p in word.split('_') if p)
    return out


def bm25(query_terms, docs, k1=1.2, b=0.75):
    tokenised = [Counter(_terms(d)) for d in docs]
    n = len(docs) or 1
    avg = sum(sum(t.values()) for t in tokenised) / n or 1.0
    df = Counter(term for t in tokenised for term in t)
    q = sorted(set(query_terms))  # fixed order: float sums must not depend on PYTHONHASHSEED
    scores = []
    for t in tokenised:
        length, score = sum(t.values()), 0.0
        for term in q:
            f = t.get(term)
            if f:
                idf = math.log(1 + (n - df[term] + .5) / (df[term] + .5))
                score += idf * f * (k1 + 1) / (f + k1 * (1 - b + b * length / avg))
        scores.append(score)
    return scores


def identifiers(target_events):
    found = []

    def scalars(value):
        if isinstance(value, dict):
            for v in value.values(): yield from scalars(v)
        elif isinstance(value, list):
            for v in value: yield from scalars(v)
        elif not (isinstance(value, bool) or value is None):
            yield str(value)
    for event in target_events:
        if event.kind == 'call' and event.name:
            found.append(event.name)
        if event.kind == 'call' and event.json_valid:
            found.extend(s for s in scalars(event.value) if len(s) >= 2)
        text = event.text
        found.extend(m.group() for m in IDENT.finditer(text))
        if event.kind == 'text':
            found.extend(next(g for g in m.groups() if g) for m in EMPHASIS.finditer(text))
            found.extend(m.group() for m in CAPS.finditer(text))
            letters = [c for c in text if c.isalpha()]
            if letters and sum(c.isascii() for c in letters) < .5 * len(letters):
                found.extend(m.group() for m in LATIN_RUN.finditer(text) if len(m.group()) >= 3)
    return list(dict.fromkeys(x.strip() for x in found if x.strip()))


def _pattern(entity):
    return re.compile(r'(?<![\w.-])' + re.escape(entity) + r'(?![\w-])', re.I)


def _entity_scores(entities, docs):
    patterns = [_pattern(e) for e in entities]
    hits = [[bool(p.search(d)) for p in patterns] for d in docs]
    n = len(docs) or 1
    df = [sum(h[j] for h in hits) for j in range(len(patterns))]
    weights = [math.log(1 + n / d) if d else 0.0 for d in df]
    return [sum(w for w, hit in zip(weights, h) if hit) for h in hits]


def _fuse(signal_scores, weights, k):
    fused = defaultdict(float)
    for name, scores in signal_scores.items():
        order = sorted((i for i, s in enumerate(scores) if s > 0), key=lambda i: (-scores[i], i))
        for rank, i in enumerate(order, 1):
            fused[i] += weights.get(name, 0) / (k + rank)
    return fused


# ---------------------------------------------------------------- records

def _native_ref(store, unit_like):
    """Native SourceStore id for an exact range: event id if whole event, else registered quote."""
    for sid, s in store.sources.items():
        if s['kind'] != 'raw' and s['document'] == unit_like['document'] and s['start'] == unit_like['start'] and s['end'] == unit_like['end']:
            return sid, sid
    parent = next((sid for sid, s in store.sources.items() if s['kind'] != 'raw' and s['document'] == unit_like['document']
                   and s['start'] <= unit_like['start'] and unit_like['end'] <= s['end']), None)
    return store.quote_id(unit_like['document'], unit_like['start'], unit_like['end']), parent


def _record(store, members, category=None):
    first = members[0]
    start, end = first['start'], members[-1]['end']
    text = store.raw[first['document']][start:end]
    span = dict(document=first['document'], start=start, end=end)
    source_id, parent = _native_ref(store, span)
    kinds = {m['kind'] for m in members}
    record = {'source_id': source_id, 'document': first['document'], 'start': start, 'end': end,
              'role': first['role'], 'kind': first['kind'] if len(kinds) == 1 else 'policy_span',
              'tool': first['tool'], 'event': first['event'], 'text': text,
              'parent_source_id': parent, 'category': category or first['category'],
              'sha256': hashlib.sha256(text.encode()).hexdigest(), 'evidence_status': EVIDENCE_STATUS}
    return record


def span_members(store, units):
    """Audit sidecar (not sent to the model): member units of every merged record."""
    out = {}
    for group in _groups(units):
        if len(group) > 1:
            out[_record(store, group)['source_id']] = [dict(unit=m['uid'], start=m['start'], end=m['end'], kind=m['kind']) for m in group]
    return out


def _compatible(a, b):
    return (a['document'] == b['document'] and a['end'] == b['start'] and a['category'] == b['category']
            and a['role'] == b['role'] and a['event'] == b['event'] and a['tool'] == b['tool']
            and (a['category'] == 'POLICY' or (a['kind'] == b['kind'] and a.get('window_of') and a.get('window_of') == b.get('window_of'))))


def merge_records(store, units):
    """Contiguous merge ONLY within one event/actor/kind/tool/category."""
    return [_record(store, g) for g in _groups(units)]


def _groups(units):
    groups = []
    for u in sorted(units, key=lambda u: (u['document'], u['start'])):
        if groups and _compatible(groups[-1][-1], u):
            groups[-1].append(u)
        else:
            groups.append([u])
    return groups


def _cost(records):
    return len(json.dumps(records, ensure_ascii=False, separators=(',', ':')).encode('utf-8'))


# ---------------------------------------------------------------- packing

def pack(row, cfg=PackerConfig(), embedder=None):
    embedder = embedder or NoEmbedder()
    units, target_units, store, catalog = build_units(row, cfg)
    history, targets = store.history_events, store.target_events
    by_uid = {u['uid']: u for u in units}
    windows = defaultdict(list)
    scope_bodies = defaultdict(list)
    for u in units:
        if u.get('window_of'):
            windows[u['window_of']].append(u['uid'])
        if u.get('scope_of'):
            scope_bodies[u['scope_of']].append(u['uid'])
    event_uids = defaultdict(list)
    for u in units:
        if u['category'] == 'HISTORY':
            event_uids[f"h{u['event']}"].append(u['uid'])
    trace, uncovered, anchors = [], [], {}

    # ---- receipt groups (qualified pairing only)
    pairs, pair_diagnostics = _qualified_pairs(history)
    partner = {}
    for result_sid, (call_sid, status) in pairs.items():
        partner[result_sid] = (call_sid, status); partner[call_sid] = (result_sid, status)

    # ---- declarations and catalog status
    def declaration(source, kind, tool=None):
        owner = next(i for i, event in enumerate(history)
                     if event.role == 'system' and event.source.start <= source.start
                     and source.end <= event.source.end)
        return dict(uid='catalog' if kind == 'catalog' else f'decl:{tool}', document='prompt',
                    start=source.start, end=source.end, category='DECLARATION',
                    role='system', kind=kind, tool=tool, event=owner)

    called = sorted({t.name for t in targets if t.kind == 'call' and t.name})
    structural_tools = {u['tool'] for u in units if u['category'] == 'CATALOG' and u['kind'] == 'tool'}
    catalog_consistent = bool(catalog.source) and catalog.complete and structural_tools == set(catalog.tools)
    declarations, declaration_status = [], {}
    for name in called:
        if name in catalog.tools:
            spec = catalog.tools[name]
            declarations.append(declaration(spec.source, 'tool', name))
            declaration_status[name] = 'DECLARED'
        else:
            declaration_status[name] = ('UNDECLARED_IN_COMPLETE_PARSED_CATALOG' if catalog_consistent
                                        else 'NOT_FOUND_IN_UNVERIFIED_CATALOG')
    undeclared = [n for n, s in declaration_status.items() if s != 'DECLARED']
    if undeclared and catalog.source:
        # An absence claim needs the complete enumeration, attached as one original span.
        declarations = [declaration(catalog.source, 'catalog')]
    if undeclared:
        uncovered.append(dict(category='DECLARATION', calls={n: declaration_status[n] for n in undeclared},
                              catalog_complete=catalog.complete, catalog_issues=list(catalog.issues),
                              parsers_agree=structural_tools == set(catalog.tools),
                              reason='ABSENCE_CLAIM_VALID_ONLY_IF_STATUS_IS_UNDECLARED_IN_COMPLETE_PARSED_CATALOG'))
    mandatory = [_record(store, [u]) for u in target_units] + [_record(store, [d], 'DECLARATION') for d in declarations]
    budget = cfg.budget_bytes
    failure = 'MANDATORY_CONTEXT_BUDGET_EXCEEDED' if budget is not None and _cost(mandatory) > budget else None

    # ---- query
    facets = [t.text if t.kind != 'call' else f"{t.name} {t.name.replace('_', ' ')} {t.text}" for t in targets]
    prior = [i for i, ev in enumerate(history) if ev.role != 'system']
    last_user = next((i for i in reversed(prior) if history[i].role == 'user' and history[i].kind == 'text'), None)
    last_asst = next((i for i in reversed(prior) if history[i].role == 'assistant' and history[i].kind == 'text'), None)
    first_user = next((i for i in prior if history[i].role == 'user' and history[i].kind == 'text'), None)
    context = [history[i].text for i in (last_user, last_asst) if i is not None] + list(cfg.extra_queries)
    entities = identifiers(targets)
    pool = [u for u in units if u['category'] in ('POLICY', 'HISTORY') and u['kind'] not in ('heading', 'tag')]
    heading_text = {u['uid']: u['text'].strip() for u in units if u['kind'] == 'heading'}
    signals = {'lexical': bm25(_terms(' '.join(facets + context)), [u['text'] for u in pool]),
               'entity': _entity_scores(entities, [u['text'] for u in pool])}
    queries = facets + context
    q_vec = embedder.encode(queries, is_query=True) if queries else None
    if q_vec:
        d_vec = embedder.encode([' '.join(heading_text.get(p, '') for p in u['parents']) + '\n' + u['text'] for u in pool], is_query=False)
        signals['dense'] = [max(sum(a * b for a, b in zip(q, d)) for q in q_vec) for d in d_vec]
    last_event = max((u['event'] for u in pool if u['category'] == 'HISTORY'), default=0)
    signals['recency'] = [1.0 / (1 + last_event - u['event']) if u['category'] == 'HISTORY' else 0.0 for u in pool]
    fused = _fuse(signals, cfg.weights, cfg.rrf_k)
    ranked = {c: [pool[i]['uid'] for i in sorted(fused, key=lambda i: (-fused[i], i)) if pool[i]['category'] == c]
              for c in ('POLICY', 'HISTORY')}

    # ---- selection
    selected = []

    def closure(uid):
        unit = by_uid[uid]
        group = [p for p in unit['parents'] if p in by_uid]
        native = f"h{unit['event']}" if unit['category'] == 'HISTORY' else None
        if native in partner:
            other = partner[native][0]
            # receipt group = every unit of the call event and of the result event
            group += event_uids.get(other, [])
        group += windows.get(unit.get('window_of'), []) if unit.get('window_of') else []
        group += scope_bodies.get(unit.get('scope_of'), []) if unit.get('scope_of') else []
        group.append(uid)
        ordered = list(dict.fromkeys(group))
        return [g for g in ordered if g not in selected], ordered

    def cost(extra=()):
        return _cost(mandatory + merge_records(store, [by_uid[u] for u in dict.fromkeys(selected + list(extra))]))

    def try_add(uid, reason, cap=None):
        """Add the full dependency group; if it does not fit, add the unit alone and mark the group partial."""
        cap = budget if cap is None else cap
        # Required intent anchors override novelty exclusions: re-reading them
        # is mandatory, just as it is for explicitly shared anchors.
        exempt = {'ANCHOR_' + a.upper() for a in cfg.shared_anchors + cfg.required_anchors}
        if uid in cfg.exclude_uids and reason not in exempt:
            return 'EXCLUDED'
        missing, full = closure(uid)
        if not missing:
            return 'ALREADY'
        if cap is None or cost(missing) <= cap:
            selected.extend(missing); trace.append(dict(uid=uid, status='SELECTED', reason=reason, group=full)); return 'SELECTED'
        alone = [g for g in [p for p in by_uid[uid]['parents'] if p in by_uid] + [uid] if g not in selected]
        if cost(alone) <= cap:
            selected.extend(alone)
            trace.append(dict(uid=uid, status='SELECTED_GROUP_PARTIAL', reason=reason, group=full,
                              missing=[g for g in full if g not in selected])); return 'SELECTED_GROUP_PARTIAL'
        trace.append(dict(uid=uid, status='BUDGET_SKIP', reason=reason)); return 'BUDGET_SKIPPED'

    def anchor(name, uids, cap=None):
        if not uids:
            anchors[name] = dict(status='ABSENT'); return
        results = [try_add(u, 'ANCHOR_' + name.upper(), cap) for u in uids]
        present = {'SELECTED', 'ALREADY', 'SELECTED_GROUP_PARTIAL'}
        ok = all(r in present for r in results)
        status = ('SELECTED' if ok else 'PARTIAL' if any(r in present for r in results)
                  else 'EXCLUDED' if all(r == 'EXCLUDED' for r in results) else 'BUDGET_SKIPPED')
        anchors[name] = dict(status=status,
                             units=list(uids))

    def share(fraction):
        here = cost()
        return None if budget is None else here + int(fraction * (budget - here))

    all_units = [u['uid'] for u in units if u['category'] in ('POLICY', 'HISTORY')]
    # FULL_INPUT covers every parsed event span, including unused catalog entries.
    # Parser role markers, outer transport tags and trimmed whitespace are delimiters.
    full_declarations = [declaration(catalog.source, 'catalog')] if catalog.source else declarations
    full_store = reference_store(row, [by_uid[u] for u in all_units], full_declarations + target_units)
    full_mandatory = ([_record(full_store, [u]) for u in target_units]
                      + [_record(full_store, [d], 'DECLARATION') for d in full_declarations])
    full_cost = _cost(full_mandatory + merge_records(full_store, [by_uid[u] for u in all_units]))
    full_input = failure is None and not cfg.exclude_uids and (budget is None or full_cost <= budget)
    if full_input:
        # Select atomically: provisional quote IDs and closure order cannot drop
        # a source after the exact final representation has passed the budget.
        store, declarations, mandatory = full_store, full_declarations, full_mandatory
        selected.extend(all_units)
        trace.extend(dict(uid=uid, status='SELECTED', reason='FULL_INPUT_FITS', group=[uid]) for uid in all_units)
    if failure is None:
        events_of = lambda i: event_uids.get(f'h{i}', []) if i is not None else []
        for name, idx in (('last_user', last_user), ('last_assistant', last_asst), ('first_user', first_user)):
            if name in cfg.anchors or name in cfg.required_anchors:
                anchor(name, events_of(idx))
        missing_required = [n for n in cfg.required_anchors if anchors.get(n, {}).get('status') not in ('SELECTED', 'ABSENT')]
        if missing_required:
            failure = 'REQUIRED_ANCHOR_BUDGET_EXCEEDED'

    if failure is None:
        if 'entity_provenance' in cfg.anchors:
            cap = share(cfg.provenance_share)
            hist = [u for u in units if u['category'] == 'HISTORY']
            weighted = []
            for e in entities:
                p = _pattern(e)
                hits = [u for u in hist if p.search(u['text'])]
                if hits:
                    weighted.append((math.log(1 + len(hist) / len(hits)), e, hits))
            chosen = []
            for _, e, hits in sorted(weighted, key=lambda x: -x[0])[:cfg.max_identifiers]:
                chosen += [hits[-1]['uid'], hits[0]['uid']]
            anchor('entity_provenance', list(dict.fromkeys(chosen)), cap)
        base = cost()
        policy_units = [u['uid'] for u in units if u['category'] == 'POLICY']
        whole = cost(policy_units)
        policy_cap = None if budget is None else min(whole, base + int(cfg.policy_max_share * (budget - base)))
        policy_mode = 'WHOLE'
        if cfg.whole_policy_if_fits and (policy_cap is None or whole <= policy_cap):
            for uid in policy_units:
                try_add(uid, 'WHOLE_POLICY_FITS', policy_cap)
        else:
            policy_mode = 'RANKED'
            if 'policy_root' in cfg.anchors:
                anchor('policy_root', [u['uid'] for u in units if u['root_scope']], policy_cap)
            for uid in ranked['POLICY']:
                try_add(uid, 'RANKED_POLICY', policy_cap)
        if 'current_segment' in cfg.anchors:
            segment = [u for u in units if u['category'] == 'HISTORY' and last_user is not None and u['event'] > last_user]
            anchor('current_segment', [u['uid'] for u in sorted(segment, key=lambda u: (-u['event'], u['start']))],
                   share(cfg.segment_share))
        if 'user_turns' in cfg.anchors:
            turns = [u for u in units if u['category'] == 'HISTORY' and u['role'] == 'user' and u['kind'] == 'text']
            anchor('user_turns', [u['uid'] for u in sorted(turns, key=lambda u: (-u['event'], u['start']))],
                   share(cfg.user_share))
        for uid in ranked['HISTORY']:
            try_add(uid, 'RANKED_HISTORY')
        for uid in ranked['POLICY']:
            try_add(uid, 'RANKED_POLICY_SPILLOVER')
    else:
        policy_mode = None

    # Final references: a fresh store with non-native spans registered in sorted
    # order, so quote ids are deterministic and reproducible by resolve().
    store = reference_store(row, [by_uid[u] for u in selected] if failure is None else [], declarations + target_units)
    mandatory = [_record(store, [u]) for u in target_units] + [_record(store, [d], 'DECLARATION') for d in declarations]
    read_sources = merge_records(store, [by_uid[u] for u in selected]) if failure is None else []
    chosen = set(selected)
    # group completeness over native call/result pairs touched by the packet
    groups = []
    for result_sid, (call_sid, status) in pairs.items():
        members = event_uids.get(call_sid, []) + event_uids.get(result_sid, [])
        present = [m for m in members if m in chosen]
        if present:
            groups.append(dict(call=call_sid, result=result_sid, pairing=status,
                               completeness='COMPLETE' if len(present) == len(members) else 'PARTIAL',
                               missing_units=[m for m in members if m not in chosen]))
    policy_scopes = []
    for heading, members in scope_bodies.items():
        if any(m in chosen for m in members):
            missing = [m for m in members if m not in chosen]
            policy_scopes.append(dict(heading=heading, completeness='PARTIAL' if missing else 'COMPLETE',
                                      missing_units=missing))
    if any(g['completeness'] == 'PARTIAL' for g in policy_scopes):
        uncovered.append(dict(category='POLICY', partial_scope_bodies=[g['heading'] for g in policy_scopes
                                                                      if g['completeness'] == 'PARTIAL'],
                              reason='GOVERNING_BODY_NOT_ALL_READ'))
    unread_policy = sum(1 for u in units if u['category'] == 'POLICY' and u['uid'] not in chosen)
    unread_history = sum(1 for u in units if u['category'] == 'HISTORY' and u['uid'] not in chosen)
    if unread_policy:
        uncovered.append(dict(category='POLICY', unread_units=unread_policy, reason='NOT_READ_NOT_PROOF_OF_INAPPLICABILITY'))
    if unread_history:
        uncovered.append(dict(category='HISTORY', unread_units=unread_history, reason='NOT_READ_NOT_PROOF_OF_ABSENCE'))
    if any(g['completeness'] == 'PARTIAL' for g in groups):
        uncovered.append(dict(category='RECEIPT_GROUP', partial=[g['result'] for g in groups if g['completeness'] == 'PARTIAL'],
                              reason='CALL_OR_RESULT_UNITS_NOT_ALL_READ'))
    if not targets:
        uncovered.append(dict(category='CURRENT_TARGET', reason='NO_PARSED_ASSISTANT_TARGET'))
    return {'version': VERSION, 'method': 'U2' + ('+dense' if 'dense' in signals else ''),
            'source_sha256': store.source_sha256,
            'read_sources': read_sources, 'current_targets': mandatory[:len(target_units)],
            'declarations': mandatory[len(target_units):], 'declaration_status': declaration_status,
            'catalog': dict(present=bool(catalog.source), complete=catalog.complete, issues=list(catalog.issues),
                            parsers_agree=structural_tools == set(catalog.tools)),
            'span_members': span_members(store, [by_uid[u] for u in selected]) if failure is None else {},
            'anchors': anchors, 'receipt_groups': groups, 'pair_diagnostics': pair_diagnostics,
            'policy_scope_groups': policy_scopes,
            'policy_mode': policy_mode, 'mode': 'FULL_INPUT' if full_input and failure is None else 'SELECTED',
            'full_input_scope': 'ALL_PARSED_EVENT_SPANS_INCLUDING_ORIGINAL_CATALOG',
            'selected_units': selected, 'trace': trace, 'failure': failure,
            'budget_bytes': budget,
            'cost': {'source_token_upper_bound': _cost(read_sources + mandatory), 'retrieved_records': len(read_sources),
                     'retrieved_units': len(selected), 'inference_http': 0, 'embedder': embedder.name},
            'query': {'facets': len(facets), 'context_events': [i for i in (last_user, last_asst) if i is not None],
                      'entities': entities},
            'uncovered': uncovered, 'completeness_certified': False, 'absence_proves_semantic_absence': False}


def reference_store(row, selected_units, mandatory_units):
    store = SourceStore({'prompt': row['prompt'], 'response': row['response']})
    native = {(v['document'], v['start'], v['end']) for v in store.sources.values() if v['kind'] != 'raw'}
    spans = {(g[0]['document'], g[0]['start'], g[-1]['end']) for g in _groups(selected_units)}
    spans |= {(u['document'], u['start'], u['end']) for u in mandatory_units}
    for span in sorted(spans - native):
        store.quote_id(*span)
    return store


def resolve(packet, row):
    """Check original spans and structural provenance, never semantic truth.

    FULL_INPUT means coverage of every parsed event span, including the original
    catalog. Transport delimiters and whitespace trimmed by parse_events are not
    evidence events and are outside that claim.
    """
    records = packet['read_sources'] + packet['current_targets'] + packet['declarations']
    store = SourceStore({'prompt': row['prompt'], 'response': row['response']})
    # Structural boundaries do not depend on a caller's chunk-size setting.
    structural, _, _, catalog = build_units(row, PackerConfig(max_block_chars=max(1, len(row['prompt']))), store)
    native = {(v['document'], v['start'], v['end']) for v in store.sources.values() if v['kind'] != 'raw'}
    for span in sorted({(r['document'], r['start'], r['end']) for r in records} - native):
        store.quote_id(*span)
    if packet['source_sha256'] != store.source_sha256:
        raise ValueError('SOURCE_HASH_CHANGED')
    for container, allowed in (('read_sources', {'POLICY', 'HISTORY'}),
                               ('current_targets', {'TARGET'}), ('declarations', {'DECLARATION'})):
        if any(r['category'] not in allowed for r in packet[container]):
            raise ValueError('SOURCE_CATEGORY_INVALID')
    for record in records:
        if store.raw[record['document']][record['start']:record['end']] != record['text']:
            raise ValueError('SOURCE_SPAN_CHANGED')
        native, parent = _native_ref(store, record)
        if native != record['source_id']:
            raise ValueError('SOURCE_ID_NOT_NATIVE')
        if parent is None or record.get('parent_source_id') != parent:
            raise ValueError('SOURCE_PARENT_INVALID')
        event = store.sources[parent]
        if record['role'] != event['role'] or record['event'] != event['event']:
            raise ValueError('ACTOR_OR_EVENT_PROVENANCE_MISMATCH')
        category = record['category']
        if category == 'TARGET':
            valid = record['document'] == 'response' and native == parent
            kind, tool = event['kind'], event['tool']
        elif category == 'HISTORY':
            valid = record['document'] == 'prompt' and event['role'] != 'system'
            kind, tool = event['kind'], event['tool']
        elif category == 'POLICY':
            touched = [u for u in structural if u['start'] < record['end'] and record['start'] < u['end']]
            valid = (record['document'] == 'prompt' and event['role'] == 'system' and bool(touched)
                     and all(u['category'] == 'POLICY' and u['event'] == event['event'] for u in touched))
            kinds = {u['kind'] for u in touched}
            kind, tool = (next(iter(kinds)) if len(kinds) == 1 else 'policy_span'), None
        else:  # DECLARATION: only exact authoritative parser ranges.
            span = (record['start'], record['end'])
            is_catalog = catalog.source is not None and span == (catalog.source.start, catalog.source.end)
            spec = catalog.tools.get(record.get('tool'))
            is_tool = spec is not None and span == (spec.source.start, spec.source.end)
            kind, tool = ('catalog', None) if record['kind'] == 'catalog' else ('tool', record.get('tool'))
            valid = (record['document'] == 'prompt' and event['role'] == 'system'
                     and (is_catalog if record['kind'] == 'catalog' else is_tool))
        if not valid:
            raise ValueError('SOURCE_CATEGORY_PROVENANCE_MISMATCH')
        if record['kind'] != kind or record.get('tool') != tool:
            raise ValueError('SOURCE_KIND_OR_TOOL_MISMATCH')
        if record.get('sha256') != hashlib.sha256(record['text'].encode()).hexdigest():
            raise ValueError('SOURCE_RECORD_HASH_CHANGED')
    # Exact native inventory: unique, complete, same count, same order-independent
    # membership and same span metadata (set equality would admit duplicates).
    native_targets = sorted((sid, s['start'], s['end']) for sid, s in store.sources.items()
                            if s['kind'] != 'raw' and s['document'] == 'response')
    packed_targets = sorted((r['source_id'], r['start'], r['end']) for r in packet['current_targets'])
    if len({r['source_id'] for r in packet['current_targets']}) != len(packet['current_targets']):
        raise ValueError('CURRENT_TARGET_DUPLICATED')
    if packed_targets != native_targets:
        raise ValueError('CURRENT_TARGET_INVENTORY_CHANGED')
    ids = [r['source_id'] for r in records]
    if len(set(ids)) != len(ids):
        raise ValueError('SOURCE_RECORD_DUPLICATED')
    if packet.get('mode') == 'FULL_INPUT':
        if packet.get('failure'):
            raise ValueError('FULL_INPUT_WITH_FAILURE')
        for source in store.sources.values():
            if source['kind'] == 'raw':
                continue
            cursor = source['start']
            for record in sorted((r for r in records if r['document'] == source['document']
                                  and source['start'] <= r['start'] < r['end'] <= source['end']),
                                 key=lambda r: r['start']):
                if record['start'] > cursor:
                    break
                cursor = max(cursor, record['end'])
            if cursor != source['end']:
                raise ValueError('FULL_INPUT_COVERAGE_INCOMPLETE')
    return True
