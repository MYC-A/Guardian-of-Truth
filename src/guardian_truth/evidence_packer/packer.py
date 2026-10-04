"""Budgeted evidence packing for verifying one assistant move.

Design principles (domain-agnostic; no tool names, IDs or business rules):

* Units partition the original text exactly (no gaps), so adjacent selected
  units merge into contiguous original spans; every span keeps offsets.
* Normative text is split by its own document structure (headings, tags,
  paragraphs). Headings are tiny parent units pulled in with their children
  (hierarchical context). Root-scope blocks apply globally and are anchored.
* History is split per recorded event; a result depends on its call.
* Mandatory: the whole current move and the declarations of tools it calls.
* Structural anchors of any dialogue turn: the latest user message, the
  latest assistant message, and the first user message (task intent).
* Relevance is a rank fusion (RRF) of independent signals: BM25 lexical,
  optional multilingual dense similarity, rare-identifier overlap with the
  move, and recency (history only). No signal certifies applicability.
* One byte budget (UTF-8 of the serialised source array, the same bound the
  bakeoff uses). Policy gets a reserved share; if the whole policy fits in it,
  it is included whole. Unused share spills over.
* Output records omissions; absence from the packet is never evidence.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field, asdict
import hashlib
import json
import math
import re

from guardian_truth.parsing import parse_events

from .embed import NoEmbedder

HEADING = re.compile(r'^[ \t]*(#{1,6})[ \t]+\S')
TAG_LINE = re.compile(r'^[ \t]*</?[A-Za-z][\w-]*>[ \t]*$')
TOOL_LINE = re.compile(r'^- (?P<name>[\w.-]+)\s+[—–]\s*')
WORD = re.compile(r'\w+', re.UNICODE)
EMPHASIS = re.compile(r'\*\*([^*\n]{2,60})\*\*|`([^`\n]{2,60})`|«([^»\n]{2,60})»|"([^"\n]{2,60})"')
CAPS = re.compile(r'(?<![\w-])[A-Z][A-Z0-9_]{2,}(?![\w-])')
LATIN_RUN = re.compile(r'[A-Za-z][A-Za-z0-9_.-]*(?:[ -][A-Z][A-Za-z0-9_.-]*)*')
IDENT = re.compile(r'(?<![\w@.-])(?:[\w.+-]+@[\w-]+\.[\w.]+|(?=[\w-]*\d)[\w-]{3,})(?![\w-])')
EVIDENCE_STATUS = 'ORIGINAL_SOURCE_NOT_CURRENT_TRUTH_OR_PERMISSION'


@dataclass(frozen=True)
class PackerConfig:
    budget_bytes: int | None = 20000
    max_block_chars: int = 1500
    max_event_chars: int = 3000
    policy_max_share: float = 0.6   # policy gets min(whole policy, this share)
    segment_share: float = 0.5      # of the history allowance for the current segment
    user_share: float = 0.35        # of the remaining allowance for all user utterances
    provenance_share: float = 0.3   # of the allowance for first/latest mention of each identifier
    max_identifiers: int = 8
    rrf_k: int = 10
    weights: dict = field(default_factory=lambda: dict(lexical=1.0, dense=1.0, entity=1.0, recency=1.0))
    anchors: tuple = ('last_user', 'last_assistant', 'first_user', 'entity_provenance',
                      'current_segment', 'user_turns', 'policy_root')
    whole_policy_if_fits: bool = True


# ---------------------------------------------------------------- units

def _lines(text, offset):
    position = 0
    for line in text.splitlines(keepends=True):
        yield offset + position, line
        position += len(line)


def _split_long(start, end, raw, limit):
    """Split [start,end) at line boundaries into pieces <= limit (if possible)."""
    if end - start <= limit:
        return [(start, end)]
    pieces, left, last_cut = [], start, start
    for line_start, line in _lines(raw[start:end], start):
        line_end = line_start + len(line)
        if line_end - left > limit and line_start > left:
            pieces.append((left, line_start)); left = line_start
        last_cut = line_end
    pieces.append((left, end))
    final = []
    for a, b in pieces:  # a single very long line: hard character windows
        while b - a > limit:
            final.append((a, a + limit)); a += limit
        final.append((a, b))
    return final


def _system_units(raw, start, end, cfg):
    """Partition the system event into heading / tag / tool / paragraph blocks."""
    cuts = []  # (offset, kind, level, tool)
    previous_blank = True
    in_tool = False
    for line_start, line in _lines(raw[start:end], start):
        stripped = line.strip()
        if not stripped:
            previous_blank = True
            continue
        heading = HEADING.match(line)
        tool = TOOL_LINE.match(line)
        if heading:
            cuts.append((line_start, 'heading', len(heading.group(1)), None)); in_tool = False
        elif TAG_LINE.match(line):
            cuts.append((line_start, 'tag', None, None)); in_tool = False
        elif tool:
            cuts.append((line_start, 'tool', None, tool.group('name'))); in_tool = True
        elif previous_blank and not (in_tool and line[:1] in ' \t'):
            cuts.append((line_start, 'block', None, None)); in_tool = False
        elif in_tool and line[:1] not in ' \t':
            cuts.append((line_start, 'block', None, None)); in_tool = False
        previous_blank = False
    if not cuts or cuts[0][0] != start:
        cuts.insert(0, (start, 'block', None, None))
    units, stack = [], []  # stack of (level, uid)
    bounds = [c[0] for c in cuts[1:]] + [end]
    for (left, kind, level, tool), right in zip(cuts, bounds):
        if kind == 'heading':
            while stack and stack[-1][0] >= level:
                stack.pop()
        parents = [uid for _, uid in stack]
        category = 'CATALOG' if kind == 'tool' else 'POLICY'
        root = kind != 'tool' and sum(1 for lvl, _ in stack) <= 1 and kind != 'heading'
        pieces = [(left, right)] if kind in ('heading', 'tag') else _split_long(left, right, raw, cfg.max_block_chars)
        for a, b in pieces:
            uid = f'p{a}'
            units.append(dict(uid=uid, document='prompt', start=a, end=b, category=category,
                              role='system', kind=kind, tool=tool, event=0, parents=parents,
                              root_scope=root and kind == 'block', heading_level=level))
        if kind == 'heading':
            stack.append((level, f'p{left}'))
    return units


def build_units(row, cfg=PackerConfig()):
    prompt, response = row['prompt'], row['response']
    raw = {'prompt': prompt, 'response': response}
    history = parse_events(prompt, 'prompt')
    targets = parse_events(response, 'response')
    units, events = [], []
    open_calls = defaultdict(list)
    for index, event in enumerate(history):
        s, e = event.source.start, event.source.end
        if event.role == 'system':
            units.extend(_system_units(prompt, s, e, cfg))
            continue
        event_units = []
        for a, b in _split_long(s, e, prompt, cfg.max_event_chars):
            event_units.append(dict(uid=f'h{index}' + (f'.{a}' if (a, b) != (s, e) else ''),
                                    document='prompt', start=a, end=b, category='HISTORY', role=event.role,
                                    kind=event.kind, tool=event.name, event=index, parents=[], root_scope=False,
                                    heading_level=None))
        key = (event.role, event.name)
        if event.kind == 'call':
            open_calls[key].append([u['uid'] for u in event_units])
        elif event.kind == 'result' and open_calls.get(key):
            call_uids = open_calls[key].pop(0)  # FIFO receipt pairing per actor+tool
            for u in event_units:
                u['parents'] = list(call_uids)
            if len(event_units) == 1:  # a call pulls a complete short receipt
                for uid in call_uids:
                    next(x for x in units + event_units if x['uid'] == uid).setdefault('companions', []).append(event_units[0]['uid'])
        units.extend(event_units)
        events.append(index)
    # partition invariant for the prompt (gaps only outside parsed events)
    target_units = [dict(uid=f't{i}', document='response', start=ev.source.start, end=ev.source.end,
                         category='TARGET', role=ev.role, kind=ev.kind, tool=ev.name, event=i,
                         parents=[], root_scope=False, heading_level=None) for i, ev in enumerate(targets)]
    for u in units + target_units:
        u['text'] = raw[u['document']][u['start']:u['end']]
    return units, target_units, history, targets


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
    q = set(query_terms)  # unique: repeated query words must not reweight
    scores = []
    for t in tokenised:
        length = sum(t.values())
        score = 0.0
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
        elif isinstance(value, bool) or value is None:
            return
        else:
            yield str(value)
    for event in target_events:
        if event.kind == 'call' and event.name:
            found.append(event.name)  # the invoked operation is itself an identifier
        if event.kind == 'call' and event.json_valid:
            found.extend(s for s in scalars(event.value) if len(s) >= 2)
        text = event.text
        found.extend(m.group() for m in IDENT.finditer(text))
        if event.kind == 'text':
            # Typographic named-entity cues, script independent: emphasised or
            # quoted spans, ALLCAPS symbols, and Latin-script runs embedded in
            # non-Latin prose (product/account/plan names in translated dialogue).
            found.extend(next(g for g in m.groups() if g) for m in EMPHASIS.finditer(text))
            found.extend(m.group() for m in CAPS.finditer(text))
            letters = [c for c in text if c.isalpha()]
            if letters and sum(c.isascii() for c in letters) < .5 * len(letters):
                found.extend(m.group() for m in LATIN_RUN.finditer(text) if len(m.group()) >= 3)
    return list(dict.fromkeys(x.strip() for x in found if x.strip()))


def _entity_scores(entities, docs):
    patterns = [(e, re.compile(r'(?<![\w.-])' + re.escape(e) + r'(?![\w-])', re.I)) for e in entities]
    hits = [[bool(p.search(d)) for _, p in patterns] for d in docs]
    n = len(docs) or 1
    df = [sum(h[j] for h in hits) for j in range(len(patterns))]
    weights = [math.log(1 + n / d) if d else 0.0 for d in df]
    return [sum(w for w, hit in zip(weights, h) if hit) for h in hits]


def _ranks(scores):
    order = sorted((i for i, s in enumerate(scores) if s > 0), key=lambda i: (-scores[i], i))
    return {i: r for r, i in enumerate(order, 1)}


def _fuse(signal_scores, weights, k):
    fused = defaultdict(float)
    for name, scores in signal_scores.items():
        for i, rank in _ranks(scores).items():
            fused[i] += weights.get(name, 0) / (k + rank)
    return fused


# ---------------------------------------------------------------- packing

def _record(unit, category=None):
    text = unit['text']
    return {'source_id': unit['uid'], 'document': unit['document'], 'start': unit['start'], 'end': unit['end'],
            'role': unit['role'], 'kind': unit['kind'], 'tool': unit['tool'], 'event': unit['event'],
            'text': text, 'parent_source_id': unit.get('parent_id', unit['uid']),
            'category': category or unit['category'],
            'sha256': hashlib.sha256(text.encode()).hexdigest(), 'evidence_status': EVIDENCE_STATUS}


def _merge(units, raw):
    """Merge selected units into maximal contiguous original spans."""
    ordered = sorted(units, key=lambda u: (u['document'], u['start']))
    spans = []
    for u in ordered:
        last = spans[-1] if spans else None
        if last and last['document'] == u['document'] and last['end'] == u['start'] and last['category'] == u['category']:
            last['end'] = u['end']; last['members'].append(u)
        else:
            spans.append(dict(document=u['document'], start=u['start'], end=u['end'], category=u['category'], members=[u]))
    records = []
    for s in spans:
        first = s['members'][0]
        merged = dict(first, start=s['start'], end=s['end'], text=raw[s['document']][s['start']:s['end']],
                      uid='+'.join(m['uid'] for m in s['members']) if len(s['members']) < 4 else
                      f"{first['uid']}..{s['members'][-1]['uid']}")
        if len(s['members']) > 1:
            merged['kind'] = first['kind'] if all(m['kind'] == first['kind'] for m in s['members']) else 'span'
        records.append(_record(merged))
    return records


def _cost(records):
    return len(json.dumps(records, ensure_ascii=False, separators=(',', ':')).encode('utf-8'))


def pack(row, cfg=PackerConfig(), embedder=None):
    embedder = embedder or NoEmbedder()
    units, target_units, history, targets = build_units(row, cfg)
    raw = {'prompt': row['prompt'], 'response': row['response']}
    by_uid = {u['uid']: u for u in units}
    trace, uncovered = [], []

    # mandatory: whole move + declarations of every tool it calls
    called = {t.name for t in targets if t.kind == 'call' and t.name}
    catalog = [u for u in units if u['category'] == 'CATALOG']
    declared = {u['tool'] for u in catalog}
    declarations = [u for u in catalog if u['tool'] in called]
    undeclared = sorted(called - declared)
    if undeclared and catalog:
        # Showing that a called operation is NOT available requires the complete
        # enumeration, never a ranked subset of it.
        declarations = catalog
        uncovered.append(dict(category='DECLARATION', undeclared_calls=undeclared,
                              reason='CALLED_TOOL_NOT_IN_CATALOG; full catalog attached as evidence'))
    mandatory = [_record(u) for u in target_units] + [_record(u, 'DECLARATION') for u in declarations]
    budget = cfg.budget_bytes
    failure = None
    if budget is not None and _cost(mandatory) > budget:
        failure = 'MANDATORY_CONTEXT_BUDGET_EXCEEDED'

    # query facets (original text only)
    facets = [t.text if t.kind != 'call' else f"{t.name} {t.name.replace('_', ' ')} {t.text}" for t in targets]
    prior = [i for i, ev in enumerate(history) if ev.role != 'system']
    last_user = next((i for i in reversed(prior) if history[i].role == 'user' and history[i].kind == 'text'), None)
    last_asst = next((i for i in reversed(prior) if history[i].role == 'assistant' and history[i].kind == 'text'), None)
    first_user = next((i for i in prior if history[i].role == 'user' and history[i].kind == 'text'), None)
    context = [history[i].text for i in (last_user, last_asst) if i is not None]
    query_terms = _terms(' '.join(facets + context))
    entities = identifiers(targets)

    pool = [u for u in units if u['category'] in ('POLICY', 'HISTORY') and u['kind'] not in ('heading', 'tag')]
    docs = [u['text'] for u in pool]
    heading_text = {u['uid']: u['text'].strip() for u in units if u['kind'] == 'heading'}
    signals = {'lexical': bm25(query_terms, docs), 'entity': _entity_scores(entities, docs)}
    passages = [' '.join(heading_text.get(p, '') for p in u['parents'] if p in heading_text) + '\n' + u['text'] for u in pool]
    q_vec = embedder.encode(facets + context, is_query=True) if facets + context else None
    if q_vec:
        d_vec = embedder.encode(passages, is_query=False)
        signals['dense'] = [max(sum(a * b for a, b in zip(q, d)) for q in q_vec) for d in d_vec]
    last_event = max((u['event'] for u in pool if u['category'] == 'HISTORY'), default=0)
    signals['recency'] = [(1.0 / (1 + last_event - u['event'])) if u['category'] == 'HISTORY' else 0.0 for u in pool]
    fused = _fuse(signals, cfg.weights, cfg.rrf_k)
    ranked = {cat: [pool[i]['uid'] for i in sorted(fused, key=lambda i: (-fused[i], i)) if pool[i]['category'] == cat]
              for cat in ('POLICY', 'HISTORY')}

    selected = []  # uids in selection order

    def closure(uid):
        unit = by_uid[uid]
        group = [p for p in unit['parents'] if p in by_uid] + [uid] + list(unit.get('companions', []))
        return [g for g in dict.fromkeys(group) if g not in selected]

    def current_cost(extra=()):
        return _cost(mandatory + _merge([by_uid[u] for u in selected + list(extra)], raw))

    def try_add(uid, reason, limit=None):
        group = closure(uid)
        if not group:
            return True
        cap = budget if limit is None else limit
        if cap is not None and current_cost(group) > cap:
            trace.append(dict(uid=uid, status='BUDGET_SKIP', reason=reason)); return False
        selected.extend(group); trace.append(dict(uid=uid, status='SELECTED', reason=reason, group=group))
        return True

    if failure is None:
        anchor_events = {'last_user': last_user, 'last_assistant': last_asst, 'first_user': first_user}
        for name in cfg.anchors:
            if name in anchor_events and anchor_events[name] is not None:
                for u in units:
                    if u['category'] == 'HISTORY' and u['event'] == anchor_events[name]:
                        try_add(u['uid'], 'ANCHOR_' + name.upper())
        if 'entity_provenance' in cfg.anchors and entities:
            # For each rare identifier of the move: where it first appears
            # (origin/binding) and where it last appears (latest state).
            here = current_cost()
            prov_cap = None if budget is None else here + int(cfg.provenance_share * (budget - here))
            hist = [u for u in units if u['category'] == 'HISTORY']
            scores = _entity_scores(entities, [u['text'] for u in hist])
            weights = []
            for e in entities:
                hits = [u for u in hist if re.search(r'(?<![\w.-])' + re.escape(e) + r'(?![\w-])', u['text'], re.I)]
                if hits:
                    weights.append((math.log(1 + len(hist) / len(hits)), e, hits))
            for _, e, hits in sorted(weights, key=lambda x: -x[0])[:cfg.max_identifiers]:
                for u in (hits[-1], hits[0]):
                    try_add(u['uid'], 'ANCHOR_ENTITY_PROVENANCE', prov_cap)
        base = current_cost()
        policy_units = [u['uid'] for u in units if u['category'] == 'POLICY']
        whole_policy = current_cost(policy_units)
        if budget is None:
            policy_cap = None
        else:
            policy_cap = min(whole_policy, base + int(cfg.policy_max_share * (budget - base)))
        if cfg.whole_policy_if_fits and (policy_cap is None or whole_policy <= policy_cap):
            for uid in policy_units:
                try_add(uid, 'WHOLE_POLICY_FITS', policy_cap)
        else:
            if 'policy_root' in cfg.anchors:
                for u in units:  # document order: global-scope preambles
                    if u['root_scope']:
                        try_add(u['uid'], 'ANCHOR_POLICY_ROOT_SCOPE', policy_cap)
            for uid in ranked['POLICY']:
                try_add(uid, 'RANKED_POLICY', policy_cap)
        if 'current_segment' in cfg.anchors and last_user is not None:
            # Everything the agent did since the latest user message is what the
            # move reports on or continues; newest first, bounded share.
            here = current_cost()
            segment_cap = None if budget is None else here + int(cfg.segment_share * (budget - here))
            segment = [u for u in units if u['category'] == 'HISTORY' and u['event'] > last_user]
            for u in sorted(segment, key=lambda u: (-u['event'], u['start'])):
                try_add(u['uid'], 'ANCHOR_CURRENT_SEGMENT', segment_cap)
        if 'user_turns' in cfg.anchors:
            # User utterances carry requests, consent and withdrawals; they are
            # short relative to tool output. Newest first, bounded share.
            here = current_cost()
            user_cap = None if budget is None else here + int(cfg.user_share * (budget - here))
            turns = [u for u in units if u['category'] == 'HISTORY' and u['role'] == 'user' and u['kind'] == 'text']
            for u in sorted(turns, key=lambda u: (-u['event'], u['start'])):
                try_add(u['uid'], 'ANCHOR_USER_TURN', user_cap)
        for uid in ranked['HISTORY']:
            try_add(uid, 'RANKED_HISTORY')
        for uid in ranked['POLICY']:  # spill-over of unused history budget
            try_add(uid, 'RANKED_POLICY_SPILLOVER')

    read_sources = _merge([by_uid[u] for u in selected], raw) if failure is None else []
    chosen = set(selected)
    unread_policy = [u['uid'] for u in units if u['category'] == 'POLICY' and u['uid'] not in chosen]
    unread_history = [u['uid'] for u in units if u['category'] == 'HISTORY' and u['uid'] not in chosen]
    if unread_policy:
        uncovered.append(dict(category='POLICY', unread_units=len(unread_policy), reason='NOT_READ_NOT_PROOF_OF_INAPPLICABILITY'))
    if unread_history:
        uncovered.append(dict(category='HISTORY', unread_units=len(unread_history), reason='NOT_READ_NOT_PROOF_OF_ABSENCE'))
    if not targets:
        uncovered.append(dict(category='CURRENT_TARGET', reason='NO_PARSED_ASSISTANT_TARGET'))
    return {'version': 'evidence-packer-v1', 'method': 'U1' + ('+dense' if 'dense' in signals else ''),
            'read_sources': read_sources, 'current_targets': mandatory[:len(target_units)],
            'declarations': mandatory[len(target_units):], 'selected_ids': selected, 'trace': trace,
            'failure': failure, 'budget_bytes': budget,
            'cost': {'source_token_upper_bound': _cost(read_sources + mandatory), 'retrieved_spans': len(read_sources),
                     'retrieved_units': len(selected), 'inference_http': 0, 'embedder': embedder.name},
            'query': {'facets': len(facets), 'context_events': [i for i in (last_user, last_asst) if i is not None],
                      'entities': entities},
            'uncovered': uncovered, 'completeness_certified': False, 'absence_proves_semantic_absence': False}
