"""Write docs/integrated_v1/FREEZE.json (refuses to overwrite). No network."""
import hashlib, json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'src')]
from guardian_truth.integrated import reviewer, relations, pipeline

out = ROOT / 'docs/integrated_v1/FREEZE.json'
if out.exists():
    raise SystemExit('FREEZE.json exists; a new freeze needs a new version')
h = lambda p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest()
s = lambda t: hashlib.sha256(t.encode()).hexdigest()
code = ['src/guardian_truth/integrated/' + f for f in ('__init__.py', 'pipeline.py', 'reviewer.py', 'relations.py', 'declarations.py', 'transport.py', 'cli.py')] + [
    'src/guardian_truth/evidence_packer/packer.py', 'src/guardian_truth/parsing.py', 'src/guardian_truth/source_search/store.py',
    'src/guardian_truth/types.py', 'experiments/integrated_v1/run.py', 'experiments/integrated_v1/score.py', 'docs/integrated_v1/EXPERIMENT_PROTOCOL.md']
freeze = dict(
    version='integrated-v1-freeze-1',
    budget_bytes=20000, temperature=0, max_tokens=1700, retry_failed=1,
    families=dict(
        mistral=dict(model='ministral-14b-2512', endpoint='https://api.mistral.ai/v1/chat/completions',
                     schema_mode='json_schema strict + source-ID enums', max_calls=900, max_tokens_total=6_000_000),
        ollama=dict(model='gemma4:31b', endpoint='https://ollama.com/v1/chat/completions',
                    schema_mode='native json_object + same schema text in system prompt (json_schema not honoured: preflight)',
                    max_calls=600, max_tokens_total=4_000_000)),
    judge=dict(model='gpt-oss:120b', endpoint='https://ollama.com/v1/chat/completions', max_calls=600,
               prompt='experiments.evidence_packer_v2.llm_eval.JUDGE_PROMPT (unchanged)'),
    matrix=[
        dict(phase='valid46', provider='mistral', profiles=['baseline', 'integrated'], reps=[1, 2, 3]),
        dict(phase='valid46', provider='ollama', profiles=['baseline', 'integrated'], reps=[1, 2]),
        dict(phase='syn_m1', provider='mistral', profiles=['baseline', 'integrated'], reps=[1, 2, 3]),
        dict(phase='syn_m1', provider='ollama', profiles=['baseline', 'integrated'], reps=[1])],
    arms={'A1_baseline': 'baseline run: corrected U2 20k + I4 direct review',
          'A2_guard': 'baseline run model decision + declaration guard overlay (0 calls)',
          'A3_relations': 'integrated run first review (relation facts + cited spans) + guard',
          'A4_controller': 'integrated run final (A3 + at most one conditional verification pass)'},
    controller_trigger='first review ADMITTED and (UNKNOWN, or NO_ERROR with >=1 decisive relation fact); never on technical failure',
    binary_projection='ERROR->1; NO_ERROR, UNKNOWN, rejected, transport/budget failure, skipped -> 0 (each counted separately)',
    primary='valid46 F1 per family (mean over reps), with TP/FP/FN/TN, cause-correct TPs (judge SAME+PARTIAL), paired row transitions',
    decision_rule=('Integrated (A4 or A3) replaces A1 as default only if, on Mistral valid46 AND Gemma valid46, mean F1 is higher, '
                   'cause-correct TPs are not lower, and the pooled paired row sign test (majority-over-reps correctness) has p<0.1; '
                   'SYN-M1 must not be worse. A2 is adopted independently if it adds no FP on any run. Otherwise A1 stays default.'),
    lockbox=dict(suite='SYN-M1', inputs_sha256=h('outputs/multipacket_v1/suite_syn_m1/inputs.jsonl'),
                 gold_sha256=h('outputs/multipacket_v1/suite_syn_m1/GOLD_eval_only.json'),
                 honesty='authored synthetic suite, previously evaluated in the multipacket phase (seen); derived from valid46 rows; '
                         'CALL_ARG_ID/FACT_NUMBER operators overlap the ARG_VALUE_PROVENANCE / PROSE_VALUE relations by construction'),
    inputs=dict(valid_parquet_sha256=h('valid.parquet')),
    prompts={k: s(v) for k, v in dict(PROMPT=reviewer.PROMPT, LABELS=reviewer.LABELS, CONTRACT=reviewer.CONTRACT,
                                       RELATIONS_ADDENDUM=reviewer.RELATIONS_ADDENDUM, CONTROLLER_ADDENDUM=reviewer.CONTROLLER_ADDENDUM).items()},
    relations=dict(version=relations.VERSION, recent_window=relations.RECENT_WINDOW, max_facts=relations.MAX_FACTS,
                   extra_source_bytes=pipeline.EXTRA_SOURCE_BYTES),
    code_sha256={p: h(p) for p in code})
out.write_text(json.dumps(freeze, indent=1) + '\n')
print('frozen', hashlib.sha256(out.read_bytes()).hexdigest())
