"""Bounded CCG corrections and minimal semantic counterexamples (§7.D M2).

No Coq is installed and none is installed here (assignment: no gigabyte Coq
on this disk); native HOL inference stays BLOCKED_COQ_NOT_INSTALLED and no
lossy HOL-to-proposition bridge is attempted. Corrections are strictly
bounded lexical operations plus explicitly flagged lexicalized rewrites;
every attempt is journaled before/after. Counterexamples are minimal
meaning-flipping transformations (only-if, unless, negation, modality,
connective scope, inclusive/exclusive boundary, implication direction):
the derived HOL root formula must change. Identical formulas are an
honestly recorded insensitivity; uninterpreted predicates are never read
as verified normative semantics.
"""
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from modular_common import HERE, RESULTS, append, load_input, sha, source_sha, write
from ccg_pilot import THIRD, semparse_compat

FOLDER = RESULTS / 'ccg_bounds'

# Ordered bounded repair cascade. LEXICAL operations never change words;
# LEXICALIZED_SEMANTIC rewrites substitute a fixed surface form and are
# flagged as such in every journal row.
REPAIRS = [
    ('sentence_resplit', 'LEXICAL', lambda t: [s.strip() for s in re.split(r'(?<=[.])\s+', t) if s.strip()]),
    ('semicolon_split', 'LEXICAL', lambda t: [s.strip() for s in t.split(';') if s.strip()]),
    ('boundary_resplit_semicolon', 'LEXICAL', lambda t: [s.strip() for part in re.split(r'(?<=[.])\s+', t) for s in part.split(';') if s.strip()]),
    ('equals_normalize', 'LEXICAL', lambda t: [t.replace('=', ' is ')]),
    ('drop_back', 'LEXICAL', lambda t: [t.replace(' back to ', ' to ')]),
    ('regardless_without_regard', 'LEXICALIZED_SEMANTIC', lambda t: [t.replace('regardless of', 'without regard to')]),
    ('regardless_always', 'LEXICALIZED_SEMANTIC_NARROWING', lambda t: [re.sub(r'\bpermitted regardless of .*$', 'always permitted', t)]),
]

# Minimal meaning-flipping transformations (applied to the key normative
# sentence of each pilot case, one at a time).
TRANSFORMS = [
    ('only_if_to_if', lambda t: t.replace('only if', 'if', 1)),
    ('unless_to_if', lambda t: t.replace('unless', 'if', 1)),
    ('condition_negation', lambda t: (t.replace(' is true', ' is false', 1) if ' is true' in t else
                                       t.replace(' is false', ' is true', 1) if ' is false' in t else
                                       t.replace('=true', '=false', 1))),
    ('modality_flip', lambda t: (t.replace('permitted', 'forbidden', 1) if 'permitted' in t else
                                  t.replace('forbidden', 'permitted', 1) if 'forbidden' in t else
                                  t.replace('may be', 'must not be', 1))),
    ('connective_scope', lambda t: (t.replace(' AND ', ' OR ', 1) if ' AND ' in t else
                                     t.replace(' OR ', ' AND ', 1) if ' OR ' in t else
                                     t.replace(' and ', ' or ', 1) if ' and ' in t else
                                     t.replace(' or ', ' and ', 1))),
    ('boundary_flip', lambda t: t.replace('inclusive', 'exclusive', 1)),
    ('implication_direction', lambda t: ('If verified is true, a is true.' if t == 'If a is true, verified is true.' else None)),
]

KEYWORDS = ('only if', 'unless', 'permitted', 'forbidden', 'requires', 'may be', 'must not', 'deadline', 'exactly when', 'if ')


def parse_texts(label, texts):
    """Parse arbitrary sentence texts through EasyCCG -> jigg -> ccg2lambda."""
    import nltk
    from lxml import etree
    out_dir = FOLDER / 'parse' / label
    out_dir.mkdir(parents=True, exist_ok=True)
    tagged = '\n'.join(' '.join(w + '|' + p + '|O' for w, p in nltk.pos_tag(nltk.word_tokenize(t)))
                       for t in texts) + '\n'
    (out_dir / 'tagged.txt').write_text(tagged, encoding='utf-8')
    model = THIRD / 'easyccg/recovered_model/model'
    command = ['java', '-jar', str(THIRD / 'easyccg/easyccg.jar'), '--model', str(model),
               '-i', 'POSandNERtagged', '-o', 'extended', '--nbest', '1']
    parsed = subprocess.run(command, input=tagged, capture_output=True, text=True, timeout=120)
    (out_dir / 'easyccg.txt').write_text(parsed.stdout, encoding='utf-8')
    (out_dir / 'easyccg.stderr.txt').write_text(parsed.stderr, encoding='utf-8')
    results = [{'text': t, 'status': 'PARSE_BLOCKED', 'roots': []} for t in texts]
    xml = out_dir / 'jigg.xml'
    converter = subprocess.run([sys.executable, str(THIRD / 'ccg2lambda/en/easyccg2jigg.py'),
                                str(out_dir / 'easyccg.txt'), str(xml)], capture_output=True, text=True, timeout=60)
    (out_dir / 'converter.log').write_text(converter.stdout + converter.stderr, encoding='utf-8')
    if converter.returncode == 0 and xml.exists():
        sem = out_dir / 'semantics.xml'
        try:
            semparse_compat(xml, sem)
            tree = etree.parse(str(sem))
            sentences = tree.findall('.//sentence')
            for i, sentence in enumerate(sentences[:len(texts)]):
                items = [{'status': s.get('status'),
                          'roots': [span.get('sem') for span in s.findall('span') if span.get('id') == s.get('root')]}
                         for s in sentence.findall('semantics')]
                ok = any(it['status'] == 'success' and it['roots'] for it in items)
                results[i].update(status='success' if ok else ('failed' if items else 'NO_SEMANTICS'),
                                  roots=[r for it in items for r in it['roots'] if r])
        except Exception as exc:
            for r in results:
                r['error_type'] = type(exc).__name__
                r['error'] = str(exc)[:200]
    return results


def normalize_roots(roots):
    return sorted(re.sub(r'\s+', ' ', r).strip() for r in roots if r)


def pilot_state():
    rows = [json.loads(l) for l in (RESULTS / 'ccg_pilot/predictions.jsonl').read_text(encoding='utf-8').splitlines()]
    return {r['id']: r for r in rows}


def prepare():
    state = pilot_state()
    failed = {}
    keys = {}
    for cid, rec in state.items():
        sents = rec['source_sentences']
        bad = []
        for f in rec.get('formulas', []):
            if f.get('status') != 'success':
                bad.append({'sentence_id': f['sentence_id'], 'text': sents[int(f['sentence_id'].lstrip('s'))]['quote']})
        failed[cid] = bad
        key = None
        for f in rec.get('formulas', []):
            idx = int(f['sentence_id'].lstrip('s'))
            text = sents[idx]['quote']
            if f.get('status') == 'success' and any(k in text.lower() for k in KEYWORDS):
                key = {'sentence_id': f['sentence_id'], 'text': text, 'roots': normalize_roots(f.get('roots') or [])}
                break
        keys[cid] = key
    prepared = {'schema': 'ccg-bounds/1', 'status': 'FROZEN_BEFORE_RUN',
        'failed_sentences': failed, 'key_normative_sentences': keys,
        'repair_cascade': [{'name': n, 'kind': k} for n, k, _ in REPAIRS],
        'transformations': [{'name': n} for n, _ in TRANSFORMS],
        'native_inference': 'BLOCKED_COQ_NOT_INSTALLED (not installed here by assignment rule)',
        'bridge': 'NO_LOSSY_HOL_TO_HORN_BRIDGE',
        'formula_comparison': 'normalized root multiset inequality; uninterpreted predicates are lexical, not verified normative semantics',
        'api_cost': 'zero: pure local java/python pipeline'}
    selection = FOLDER / 'selection.json'
    if selection.exists():
        if json.loads(selection.read_text(encoding='utf-8')) != prepared:
            raise ValueError('ccg_bounds_freeze_changed_use_versioned_recovery')
    else:
        write(selection, prepared)
    return prepared


def run_corrections(prepared):
    journal = FOLDER / 'corrections.jsonl'
    done = {r['id'] + '/' + r['sentence_id']: r for r in map(json.loads, journal.read_text(encoding='utf-8').splitlines())} if journal.exists() else {}
    recovered, unrecovered = [], []
    for cid, failures in prepared['failed_sentences'].items():
        for bad in failures:
            key = cid + '/' + bad['sentence_id']
            if key in done:
                row = done[key]
            else:
                row = {'id': cid, 'sentence_id': bad['sentence_id'], 'original': bad['text'], 'attempts': []}
                for name, kind, repair in REPAIRS:
                    candidates = repair(bad['text'])
                    if not candidates or candidates == [bad['text']]:
                        continue
                    label = re.sub(r'[^a-z0-9]+', '_', (cid + '_' + bad['sentence_id'] + '_' + name).lower())
                    parsed = parse_texts(label, candidates)
                    attempt = {'repair': name, 'kind': kind, 'candidates': [
                        {'text': p['text'], 'status': p['status'], 'roots_n': len(p['roots'])} for p in parsed]}
                    row['attempts'].append(attempt)
                    if all(p['status'] == 'success' for p in parsed):
                        attempt['recovered'] = True
                        row['recovered_by'] = name
                        row['recovered_kind'] = kind
                        break
                    attempt['recovered'] = False
                append(journal, row)
            (recovered if row.get('recovered_by') else unrecovered).append(
                {'id': row['id'], 'sentence_id': row['sentence_id'], 'repair': row.get('recovered_by'),
                 'kind': row.get('recovered_kind')})
    return {'failed_n': sum(len(v) for v in prepared['failed_sentences'].values()),
            'recovered': recovered, 'unrecovered': unrecovered}


def run_counterexamples(prepared, state):
    journal = FOLDER / 'counterexamples.jsonl'
    done = {r['id'] + '/' + r['sentence_id'] + '/' + r['transform']: r
            for r in map(json.loads, journal.read_text(encoding='utf-8').splitlines())} if journal.exists() else {}
    classes = {}
    for cid, rec in state.items():
        sents = rec['source_sentences']
        keys = []
        for f in rec.get('formulas', []):
            if f.get('status') != 'success':
                continue
            text = sents[int(f['sentence_id'].lstrip('s'))]['quote']
            if any(k in text.lower() for k in KEYWORDS):
                keys.append({'sentence_id': f['sentence_id'], 'text': text, 'roots': normalize_roots(f.get('roots') or [])})
        classes[cid] = {}
        pending = []  # (sentence_key, transform_name, transformed_text)
        for key in keys:
            for name, transform in TRANSFORMS:
                tag = cid + '/' + key['sentence_id'] + '/' + name
                if tag in done:
                    classes[cid][key['sentence_id'] + '/' + name] = done[tag]['class']
                    continue
                text = transform(key['text'])
                if text is None or text == key['text']:
                    continue  # transform not applicable to this sentence
                pending.append((key, name, text, tag))
        if not pending:
            continue
        # one batched EasyCCG run per case for all transformed texts
        parsed = parse_texts(re.sub(r'[^a-z0-9]+', '_', cid.lower()) + '_transforms', [p[2] for p in pending])
        for (key, name, text, tag), result in zip(pending, parsed):
            row = {'id': cid, 'sentence_id': key['sentence_id'], 'transform': name,
                   'original': key['text'], 'transformed': text,
                   'original_status': 'success', 'transformed_status': result['status'],
                   'original_roots': key['roots'], 'transformed_roots': normalize_roots(result['roots'])}
            if result['status'] != 'success':
                row['class'] = 'COVERAGE_GAP_TRANSFORMED_UNPARSEABLE'
            elif row['transformed_roots'] == key['roots']:
                row['class'] = 'INSENSITIVE_IDENTICAL_FORMULA'
            else:
                row['class'] = 'DISTINGUISHED_FORMULA_CHANGED'
            append(journal, row)
            classes[cid][key['sentence_id'] + '/' + name] = row['class']
    flat = [c for per in classes.values() for c in per.values()]
    tally = {}
    for value in flat:
        tally[value] = tally.get(value, 0) + 1
    return {'per_case': classes, 'tally': tally}


def run():
    prepared = prepare()
    state = pilot_state()
    began = time.monotonic()
    corrections = run_corrections(prepared)
    counterexamples = run_counterexamples(prepared, state)
    write(FOLDER / 'summary.json', {
        'schema': 'ccg-bounds-summary/1',
        'corrections': {'failed_n': corrections['failed_n'],
                        'recovered_n': len(corrections['recovered']),
                        'recovered_by_kind': {k: sum(1 for r in corrections['recovered'] if r.get('kind') == k)
                                              for k in ('LEXICAL', 'LEXICALIZED_SEMANTIC', 'LEXICALIZED_SEMANTIC_NARROWING')},
                        'unrecovered_n': len(corrections['unrecovered']),
                        'unrecovered': corrections['unrecovered']},
        'counterexamples': counterexamples['tally'],
        'counterexamples_per_case': counterexamples['per_case'],
        'native_inference': 'BLOCKED_COQ_NOT_INSTALLED; no lossy bridge attempted',
        'limits': ['Corrections are bounded surface operations; a recovered parse is not a semantics certificate.',
                   'DISTINGUISHED only shows the lexical HOL formula changed under a meaning flip; predicates remain uninterpreted.',
                   'coqtop absent: no native inference claim of any kind.'],
        'elapsed_seconds': time.monotonic() - began})
    write(FOLDER / 'status.json', {'state': 'SUCCEEDED'})
    print(json.dumps({'corrections_recovered': len(corrections['recovered']),
                      'corrections_unrecovered': len(corrections['unrecovered']),
                      'counterexample_tally': counterexamples['tally']}))


if __name__ == '__main__':
    run()
