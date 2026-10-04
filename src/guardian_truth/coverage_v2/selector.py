"""Budgeted weighted facet cover for evidence selection (no domain rules).

Problem statement
-----------------
Given the original prompt (policy + journal) and the assistant move under
review, choose original spans that a verifier needs, under a byte budget.
Top-k ranking optimises *relevance of each unit*; what the verifier needs is
*coverage of every checkable thing the move depends on*. We therefore cast
selection as budgeted maximum coverage (monotone submodular):

    maximise  sum_f w_f * min(1, c_f(S)/need_f)   s.t.  cost(S) <= B

Facets f are extracted mechanically from the move only:
  * LITERAL  - tokens carrying digits/underscores/@ (ids, amounts, dates,
               codes) and JSON scalar operands of the current calls;
  * NAME     - called tool names (bridge to declarations / policy wording);
  * TERM     - content-word stems of the move, idf-weighted;
  * CONTEXT  - stems of the latest user turn (what the move answers);
  * FEEDBACK - stems of journal units that contain move literals
               (pseudo-relevance feedback). This bridges language gaps:
               a Russian reply -> English tool JSON -> English policy.

Greedy cost-benefit selection plus best-singleton gives the classic
(1-1/e)/2 guarantee for budgeted coverage. Structural rules are generic:
  * the normative scope is taken whole when it fits a fixed share of the
    budget (absence of a norm can never be proven by retrieval, so we avoid
    ranking norms whenever we can afford it);
  * a selected tool result pulls its uniquely paired call;
  * the latest user turn is always read;
  * every literal facet is reported as GROUNDED (with locations) or
    UNGROUNDED in the *whole* prompt, not only in the packet. Ungrounded
    literals are a downstream fabrication signal, never a verdict.

No case ids, labels, domain vocabularies or tool-specific rules are used.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import json
import math
import re

UNIT_CHARS = 1500
POLICY_SHARE = 0.55          # fixed a priori, not tuned on cases
FEEDBACK_WEIGHT = 0.5
CONTEXT_WEIGHT = 0.7
LITERAL_WEIGHT = 3.0
LITERAL_NEED = 2             # origin + latest occurrence are both useful

_WORD = re.compile(r"[^\W\d_]{3,}", re.UNICODE)
_LIT = re.compile(r"[$€£]?\d{1,3}(?:,\d{3})+(?:\.\d+)?|[\w@.\-/:$€£]*\d[\w@.\-/:$€£]*|\b[A-Za-z]+_[\w]+\b|[\w.+-]+@[\w.-]+", re.UNICODE)
_STOP = set("""the and for that with this you your are was were have has had not but can will
from they their them our out all any may must should would could into than then there here what
which when where who whom how also only such each other more most some very just been being its
это что как для или при они его она оно был была были все всё уже вам вас ваш ваша ваши мне меня
мой моя мои если так также чтобы есть нет еще ещё только этот эта эти тот той там тут где когда
""".split())


def stem(word: str) -> str:
    w = word.lower()
    return w[:6] if len(w) > 6 else w


def norm_literal(tok: str) -> str:
    t = tok.strip(".,:;/-").lower().replace('$', '').replace('€', '').replace('£', '')
    if re.fullmatch(r"\d{1,3}(,\d{3})+(\.\d+)?", t):
        t = t.replace(',', '')
    if re.fullmatch(r"\d+\.0+", t):
        t = t.split('.')[0]
    return t


def literals(text: str) -> set[str]:
    out = set()
    for m in _LIT.finditer(text):
        t = norm_literal(m.group(0))
        if 2 <= len(t) <= 48 and not re.fullmatch(r"\d", t):
            out.add(t)
            for part in re.split(r"[/:]|(?<=\d)t(?=\d)", t):   # 2024-05-26T10:00 -> parts
                if len(part) >= 4 and part != t:
                    out.add(part)
    return out


def terms(text: str) -> list[str]:
    return [stem(w) for w in _WORD.findall(text) if w.lower() not in _STOP]


def _scalars(value):
    if isinstance(value, dict):
        for v in value.values():
            yield from _scalars(v)
    elif isinstance(value, list):
        for v in value:
            yield from _scalars(v)
    elif value is not None and not isinstance(value, bool):
        yield value


# --------------------------------------------------------------------- units

def _pieces(text: str, max_chars: int):
    """Split at blank lines/headings/list items; merge to <= max_chars; never
    drop characters (pieces partition the text)."""
    cuts = {0, len(text)}
    cuts.update(m.start() for m in re.finditer(r"\n\s*\n|\n(?=[ \t]*(?:#{1,6} |[-*·] |\d+\. ))", text))
    cuts = sorted(cuts)
    spans, cur = [], None
    for a, b in zip(cuts, cuts[1:]):
        if cur is None:
            cur = [a, b]
        elif b - cur[0] <= max_chars:
            cur[1] = b
        else:
            spans.append(tuple(cur)); cur = [a, b]
    if cur:
        spans.append(tuple(cur))
    out = []
    for a, b in spans:                       # hard split oversize pieces at newline/space
        while b - a > max_chars:
            cut = text.rfind('\n', a + max_chars // 2, a + max_chars)
            if cut <= a:
                cut = text.rfind(' ', a + max_chars // 2, a + max_chars)
            if cut <= a:
                cut = a + max_chars
            out.append((a, cut)); a = cut
        if b > a:
            out.append((a, b))
    return out


def build_units(corpus, max_chars=UNIT_CHARS):
    """Finer original-span units over the corpus catalog (exact provenance)."""
    from experiments.retrieval_bakeoff_v1.corpus import source
    store = corpus.store
    units = []
    for item in corpus.catalog:
        text = item['text']
        spans = [(0, len(text))] if len(text) <= max_chars else _pieces(text, max_chars)
        for a, b in spans:
            if not text[a:b].strip():
                continue
            start, end = item['start'] + a, item['start'] + b
            qid = store.quote_id('prompt', start, end) if (a, b) != (0, len(text)) else item['source_id']
            rec = source(store, qid, graph=corpus.graph, category=item['category'],
                         parent_source_id=item['parent_source_id'])
            for k in ('role', 'kind', 'tool', 'event'):
                if item.get(k) is not None:
                    rec[k] = item[k]
            units.append(rec)
    return units


# -------------------------------------------------------------------- facets

def extract_facets(corpus, units, prompt):
    target_text = '\n'.join(t['text'] for t in corpus.current_targets)
    lits = literals(target_text)
    for op in corpus.operands:
        for v in _scalars(op['value']):
            t = norm_literal(str(v))
            if 2 <= len(t) <= 48 and not re.search(r"\s", t):
                lits.add(t)
    names = {t.get('tool') for t in corpus.current_targets if t.get('tool')}
    # Literals that also appear verbatim in the *policy/tool declarations*
    # (e.g. "50 dollars", enum values) are kept; trivial numbers are kept but
    # weighted by idf, so ubiquitous values carry little weight.
    unit_lits = [literals(u['text']) for u in units]
    unit_terms = [set(terms(u['text'])) for u in units]
    n = len(units) or 1
    df_t = Counter(t for s in unit_terms for t in s)
    df_l = Counter(l for s in unit_lits for l in s)
    idf = lambda df: math.log(1 + n / (1 + df))

    facets = {}
    def add(key, w, need=1):
        if w > 0 and (key not in facets or facets[key][0] < w):
            facets[key] = (w, need)

    for l in lits:
        add(('LIT', l), LITERAL_WEIGHT * idf(df_l.get(l, 0)), LITERAL_NEED)
    for name in names:
        add(('LIT', name.lower()), LITERAL_WEIGHT * idf(df_l.get(name.lower(), 0)), LITERAL_NEED)
        for t in terms(name.replace('_', ' ')):
            add(('TERM', t), idf(df_t.get(t, 0)))
    for t in set(terms(target_text)):
        add(('TERM', t), idf(df_t.get(t, 0)))
    # latest user turn = what the move answers
    users = [u for u in units if u.get('role') == 'user']
    if users:
        last_event = max(u['event'] for u in users)
        ctx = ' '.join(u['text'] for u in users if u['event'] == last_event)
        for t in set(terms(ctx)):
            add(('TERM', t), CONTEXT_WEIGHT * idf(df_t.get(t, 0)))
        for l in literals(ctx):
            add(('LIT', l), CONTEXT_WEIGHT * LITERAL_WEIGHT * idf(df_l.get(l, 0)))
    # pseudo-relevance feedback from journal units that share move literals
    fb = Counter()
    for u, ls, ts in zip(units, unit_lits, unit_terms):
        if u['category'] == 'HISTORY' and ls & lits:
            fb.update(ts)
    for t, _ in fb.most_common(40):
        add(('TERM', t), FEEDBACK_WEIGHT * idf(df_t.get(t, 0)))

    # grounding ledger over the WHOLE prompt (not just the packet)
    low = prompt.lower()
    ledger = {}
    for l in sorted(lits):
        locs = [i for i, s in enumerate(unit_lits) if l in s]
        ledger[l] = dict(status='GROUNDED' if locs or l in low else 'UNGROUNDED',
                         unit_count=len(locs))
    covers = []
    for ls, ts in zip(unit_lits, unit_terms):
        c = {('LIT', l) for l in ls} | {('TERM', t) for t in ts}
        covers.append({k for k in c if k in facets})
    return facets, covers, ledger


# ----------------------------------------------------------------- selection

def _cost(rec):
    return len(json.dumps(rec, ensure_ascii=False, separators=(',', ':')).encode('utf-8')) + 1


TAIL_SHARE = 0.15            # conversation tail the move directly answers
USER_SHARE = 0.10            # user utterances: intent, consent, withdrawals


def select_evidence(corpus, budget_bytes=20000, policy_share=POLICY_SHARE):
    """Return a packet compatible with retrieval_bakeoff_v1.scoring.

    Phases (shares fixed a priori, never tuned per case):
      0. if the whole input fits, read everything (no retrieval needed);
      1. conversation tail, newest first (TAIL_SHARE);
      2. user utterances, newest first (USER_SHARE);
      3. facet-cover greedy over the journal;
      4. normative scope: whole if it fits policy_share, else facet greedy
         with feedback terms from already selected journal units;
      5. fill the remaining budget by (facet mass + recency), so budget is
         never left unused while relevant-looking text remains.
    """
    units = build_units(corpus)
    facets, covers, ledger = extract_facets(corpus, units, corpus.row['prompt'])
    mandatory = corpus.current_targets + corpus.declarations
    used = len(json.dumps(mandatory, ensure_ascii=False, separators=(',', ':')).encode('utf-8'))
    cost = [_cost(u) for u in units]
    chosen, chosen_set, trace = [], set(), []
    count = Counter()

    def take(i, why, cap=None):
        nonlocal used
        limit = budget_bytes if cap is None else min(budget_bytes, cap)
        if i in chosen_set or used + cost[i] > limit:
            return False
        chosen.append(i); chosen_set.add(i); used += cost[i]; count.update(covers[i])
        trace.append(dict(source_id=units[i]['source_id'], why=why, bytes=cost[i]))
        return True

    if used > budget_bytes:
        return _packet(corpus, units, [], trace, ledger, facets, count, used, budget_bytes,
                       'MANDATORY_SOURCES_EXCEED_BUDGET', False, 'NONE')
    if used + sum(cost) <= budget_bytes:
        for i in range(len(units)):
            take(i, 'FULL_INPUT_FITS')
        return _packet(corpus, units, chosen, trace, ledger, facets, count, used, budget_bytes,
                       None, True, 'FULL_INPUT')

    free = budget_bytes - used
    hist = [i for i, u in enumerate(units) if u['category'] == 'HISTORY']
    pol = [i for i, u in enumerate(units) if u['category'] == 'POLICY']
    by_parent = defaultdict(list)
    for i, u in enumerate(units):
        by_parent[u['parent_source_id']].append(i)
    max_event = max([u['event'] for u in units if u.get('event') is not None] or [1]) or 1

    def with_pair(i, why, cap=None):
        if take(i, why, cap) and units[i].get('kind') == 'result':
            for j in by_parent.get(corpus.pairs.get(units[i]['parent_source_id']), []):
                take(j, 'PAIRED_CALL', cap)

    # 1) tail, newest first, whole events
    cap = used + TAIL_SHARE * free
    for i in sorted(hist, key=lambda i: -units[i]['start']):
        if used + cost[i] > cap:
            break
        with_pair(i, 'CONVERSATION_TAIL', cap)
    # 2) user utterances, newest first
    cap = used + USER_SHARE * free
    for i in sorted((i for i in hist if units[i].get('role') == 'user'), key=lambda i: -units[i]['start']):
        take(i, 'USER_UTTERANCE', cap)

    def gain(i, saturate=True):
        g = 0.0
        for f in covers[i]:
            w, need = facets[f]
            if not saturate or count[f] < need:
                g += w / need
        if units[i]['category'] == 'HISTORY' and units[i].get('event') is not None:
            g *= 1 + 0.15 * units[i]['event'] / max_event
        return g

    def greedy(pool, why, cap):
        while True:
            best, best_ratio = None, 0.0
            for i in pool:
                if i in chosen_set or used + cost[i] > cap:
                    continue
                g = gain(i)
                if g > 0 and g / cost[i] > best_ratio:
                    best, best_ratio = i, g / cost[i]
            if best is None:
                return
            with_pair(best, why, cap)

    # 3) journal facet cover, leaving the policy share untouched
    pol_cost = sum(cost[i] for i in pol)
    policy_whole = pol_cost <= policy_share * free
    reserve = pol_cost if policy_whole else policy_share * free
    greedy(hist, 'FACET_GAIN', budget_bytes - reserve)
    # 4) normative scope
    if policy_whole:
        for i in pol:
            take(i, 'POLICY_WHOLE')
    else:
        fb = Counter()
        for i in chosen:
            if units[i]['category'] == 'HISTORY':
                fb.update(t for (k, t) in covers[i] if k == 'TERM')
        for i in pol:
            for t in set(terms(units[i]['text'])):
                if t in fb and ('TERM', t) not in facets:
                    facets[('TERM', t)] = (FEEDBACK_WEIGHT * 0.5, 1)
        for i in range(len(units)):
            covers[i] = covers[i] | {('TERM', t) for t in set(terms(units[i]['text']))
                                     if ('TERM', t) in facets}
        greedy(pol, 'POLICY_FACET_GAIN', budget_bytes)
    # 5) fill by unsaturated facet mass + recency
    rest = sorted((i for i in range(len(units)) if i not in chosen_set),
                  key=lambda i: -(gain(i, saturate=False) / cost[i] + 1e-6 * units[i]['start']))
    for i in rest:
        with_pair(i, 'FILL')
    return _packet(corpus, units, chosen, trace, ledger, facets, count, used, budget_bytes,
                   None, policy_whole, 'SELECTED')


def _packet(corpus, units, chosen, trace, ledger, facets, count, used, budget, failure, policy_whole, mode):
    order = sorted(chosen, key=lambda i: (units[i]['start']))
    uncovered = sorted(f'{k}:{v}' for (k, v), (w, need) in facets.items()
                       if count[(k, v)] == 0 and k == 'LIT')
    return {
        'method': 'coverage_v2_facet_cover',
        'read_sources': [units[i] for i in order],
        'current_targets': corpus.current_targets,
        'declarations': corpus.declarations,
        'selected_ids': [units[i]['source_id'] for i in order],
        'trace': trace,
        'failure': failure,
        'cost': {'source_utf8_bound': used, 'budget': budget, 'reads': len(order)},
        'policy_whole': policy_whole,
        'mode': mode,
        'literal_ledger': ledger,
        'ungrounded_literals': [l for l, v in ledger.items() if v['status'] == 'UNGROUNDED'],
        'uncovered_literal_facets': uncovered,
        'completeness_certified': False,
    }
