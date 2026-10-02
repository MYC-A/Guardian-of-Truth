"""Actual EasyCCG -> author easyccg2jigg -> author ccg2lambda semantics.

Full original automatic sentence inventory, no manually localized/gold spans.
HOL formulas remain HOL. Missing modal/exception semantics are not flattened.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
from modular_common import RESULTS, append, load_input, source_sha, write

THIRD = Path('/workspace/guardian/third_party_modular_20261002')
IDS = [g + '::00' for g in ('dev_necessary', 'dev_unless', 'dev_nested_gate', 'dev_negative_scope',
                           'dev_retry_commit', 'dev_implication', 'dev_inclusive_timezone', 'dev_refusal_inventory')]


def semparse_compat(xml, target):
    # Minimal compatibility shim: PyYAML removed implicit Loader; original
    # plain-data templates safely use SafeLoader. Semantic algorithm unchanged.
    import yaml
    native_load = yaml.load
    yaml.load = lambda stream, Loader=None: native_load(stream, Loader or yaml.SafeLoader)
    scripts = THIRD / 'ccg2lambda/scripts'
    sys.path.insert(0, str(scripts))
    import semparse
    original_args = sys.argv
    sys.argv = [str(scripts / 'semparse.py'), str(xml),
                str(THIRD / 'ccg2lambda/en/semantic_templates_en_emnlp2015.yaml'), str(target), '--ncores', '1']
    try:
        semparse.main()
    finally:
        sys.argv = original_args
        yaml.load = native_load


def run():
    import nltk
    from lxml import etree
    from structural_v02 import parse_case_v02
    out = RESULTS / 'ccg_pilot'
    model = THIRD / 'easyccg/recovered_model/model'
    provenance = json.loads((RESULTS / 'model_setup/ccg_recovery.json').read_text())
    write(out / 'selection.json', {'ids': IDS, 'model_provenance': provenance,
        'parser_revision': 'e42d58e08eb2a86593d52f730c5afe222e939781',
        'semantics_revision': 'a68cb264413791150011c347c64a7b35e2f7270d',
        'semantic_templates': 'en/semantic_templates_en_emnlp2015.yaml',
        'model_authentication': 'community mirror checksum only, not author authenticated',
        'compatibility_changes': ['PyYAML safe Loader selection only'],
        'native_prover': 'Coq; never replace HOL with lossy proposition strings'})
    for resource in ('punkt_tab', 'averaged_perceptron_tagger_eng'):
        nltk.download(resource, quiet=True)
    journal = out / 'predictions.jsonl'
    done = {r['id']: r for r in map(json.loads, journal.read_text().splitlines())} if journal.exists() else {}
    try:
        for row in load_input(ids=IDS):
            if row['id'] in done:
                continue
            ctx = parse_case_v02(row['id'], row['prompt'], row['response'])
            policy = ctx.policy_text
            sentences = nltk.sent_tokenize(policy)
            spans, cursor = [], 0
            for sentence in sentences:
                pos = policy.index(sentence, cursor)
                spans.append({'start': pos, 'end': pos + len(sentence), 'quote': sentence})
                cursor = pos + len(sentence)
            tagged = '\n'.join(' '.join(word + '|' + pos + '|O' for word, pos in nltk.pos_tag(nltk.word_tokenize(sentence))) for sentence in sentences) + '\n'
            case_dir = out / row['id'].replace('::', '_')
            case_dir.mkdir(parents=True, exist_ok=True)
            (case_dir / 'policy.txt').write_text(policy)
            (case_dir / 'tagged.txt').write_text(tagged)
            command = ['java', '-jar', str(THIRD / 'easyccg/easyccg.jar'), '--model', str(model),
                       '-i', 'POSandNERtagged', '-o', 'extended', '--nbest', '1']
            parsed = subprocess.run(command, input=tagged, capture_output=True, text=True, timeout=90)
            (case_dir / 'easyccg.txt').write_text(parsed.stdout)
            (case_dir / 'easyccg.stderr.txt').write_text(parsed.stderr)
            xml = case_dir / 'jigg.xml'
            converter = subprocess.run([sys.executable, str(THIRD / 'ccg2lambda/en/easyccg2jigg.py'),
                                        str(case_dir / 'easyccg.txt'), str(xml)], capture_output=True, text=True, timeout=30)
            (case_dir / 'converter.log').write_text(converter.stdout + converter.stderr)
            rec = {'id': row['id'], 'source_sha256': source_sha(row), 'source_sentences': spans,
                   'tagged_input': tagged, 'parser_command': command,
                   'parser_exit': parsed.returncode, 'converter_exit': converter.returncode,
                   'tree': parsed.stdout, 'formulas': [], 'native_inference': 'UNRUN',
                   'bridge': 'NO_LOSSY_HOL_TO_HORN_BRIDGE', 'semantic_correctness': 'NOT_CERTIFIED'}
            if converter.returncode == 0 and xml.exists():
                sem = case_dir / 'semantics.xml'
                try:
                    semparse_compat(xml, sem)
                    tree = etree.parse(str(sem))
                    rec['formulas'] = [{'sentence_id': sentence.get('id'),
                        'status': s.get('status'),
                        'roots': [span.get('sem') for span in s.findall('span') if span.get('id') == s.get('root')]}
                        for sentence in tree.findall('.//sentence') for s in sentence.findall('semantics')]
                    rec['semantic_execution'] = 'SUCCEEDED'
                except Exception as exc:
                    rec['semantic_execution'] = 'FAILED'
                    rec['semantic_error_type'] = type(exc).__name__
                    rec['semantic_error'] = str(exc)[:300]
            else:
                rec['semantic_execution'] = 'BLOCKED_PARSE_OR_CONVERTER'
            rec['native_inference'] = 'AVAILABLE_BUT_POLICY_MODAL_SEMANTICS_NOT_VALIDATED' if shutil.which('coqtop') else 'BLOCKED_COQ_NOT_INSTALLED'
            append(journal, rec)
            done[row['id']] = rec
        write(out / 'status.json', {'state': 'SUCCEEDED', 'done': len(done), 'total': len(IDS)})
    except Exception as exc:
        write(out / 'status.json', {'state': 'FAILED', 'done': len(done), 'error_type': type(exc).__name__})
        raise


if __name__ == '__main__':
    run()
