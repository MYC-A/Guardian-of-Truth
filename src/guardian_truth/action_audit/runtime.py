"""One shared judge request plus error-only table/audit shadow projections."""
from pathlib import Path
import hashlib
import json

from guardian_truth.policy_table.evaluate import load_table, evaluate_table
from guardian_truth.source_search.store import SourceStore
from guardian_truth.source_search.id_contract import id_contract, decode_assessment, registry, native_target_inventory
from guardian_truth.source_search.pipeline import run
from .evaluate import instruction, input_context, evaluate_audit


def validate_modes(config, *, root):
    stages = config.get('stages', {})
    for layer in ('policy_table', 'action_audit'):
        mode = stages.get(layer, {}).get('mode', 'shadow')
        if mode not in ('shadow', 'decisive'): raise ValueError('unsupported V10 mode')
        if mode != 'decisive': continue
        receipt = config.get('promotion_receipt')
        if not isinstance(receipt, dict): raise ValueError('V10 decisive mode requires a measured promotion receipt')
        path = Path(receipt['score_file'])
        if not path.is_absolute(): path = Path(root) / path
        if hashlib.sha256(path.read_bytes()).hexdigest() != receipt['score_sha256']:
            raise ValueError('promotion score seal mismatch')
        score = json.loads(path.read_text(encoding='utf-8'))
        promotion = score.get('promotion', {}); metrics = promotion.get('metrics', {})
        allowed = (promotion.get('approved_layers', {}).get(layer) is True
            and promotion.get('prospective_validation_complete') is True
            and type(metrics.get('public46_fp')) is int and 0 <= metrics['public46_fp'] <= 1
            and 0.79 <= metrics.get('public46_f1', -1) <= 1
            and metrics.get('corrected_cases', 0) >= 3
            and metrics.get('positive_mutations_n', 0) > 0
            and 0.7 <= metrics.get('positive_mutation_recall', -1) <= 1
            and metrics.get('control_n', 0) > 0
            and 0 <= metrics.get('control_decision_change_rate', 1) <= 0.05
            and len(metrics.get('heldout_table_fp', {})) == 4
            and all(type(v) is int and v == 0 for v in metrics.get('heldout_table_fp', {}).values()))
        if not allowed: raise ValueError('V10 promotion gates are not satisfied')


def prepare(store, table_config, *, root):
    directory = Path(table_config['tables_dir'])
    if not directory.is_absolute(): directory = Path(root) / directory
    try:
        table = load_table(store, directory)
        result = evaluate_table(store, table) if table else {'findings': [], 'trace': [], 'emits_no_error': False}
        result['cache_status'] = 'compiled' if table else 'not_compiled'
    except (ValueError, OSError) as exc:
        table = None
        result = {'findings': [], 'trace': [], 'emits_no_error': False, 'cache_status': 'invalid_cache', 'reason': str(exc)}
    native_tools = {c['tool'] for c in native_target_inventory(store)}
    has_text = any(s['document'] == 'response' and s['kind'] == 'text' and s['role'] == 'assistant' for s in store.sources.values())
    applicable = []
    for entry in table.rules if table else ():
        trigger = entry['rule']['trigger']
        if trigger['kind'] == 'TOOL_CALL' and trigger['tool'] in native_tools:
            applicable.append({**entry, 'scope_status': 'CODE_MATCHED_NATIVE_TRIGGER'})
        elif trigger['kind'] == 'SPEECH_ACT' and has_text:
            applicable.append({**entry, 'scope_status': 'SPEECH_ACT_APPLICABILITY_PENDING_MODEL_FRAME'})
    return {'table': table, 'policy_table': result, 'applicable_rules': applicable}


def combine(judge_decision, table_result, audit_result):
    table_hit = any(f.get('compile_agreement_status') == 'DECISIVE' for f in table_result.get('findings', []))
    audit_hit = bool(audit_result.get('findings'))
    return {'judge_shared_request': judge_decision,
        'judge_plus_table': 'ERROR' if table_hit else judge_decision,
        'judge_plus_audit': 'ERROR' if audit_hit else judge_decision,
        'full': 'ERROR' if table_hit or audit_hit else judge_decision}


def run_joint(row, ask, *, store=None, prepared=None, root, table_config, audit_config, **options):
    store = store or SourceStore(row)
    prepared = prepared or prepare(store, table_config, root=root)
    table_result = prepared['policy_table']
    table_decisive = table_config.get('mode', 'shadow') == 'decisive'
    audit_decisive = audit_config.get('mode', 'shadow') == 'decisive'
    if table_decisive and any(f.get('compile_agreement_status') == 'DECISIVE' for f in table_result['findings']):
        return {'decision': 'ERROR', 'decision_basis': 'policy_table', 'degraded': False,
            'assessment': {'findings': table_result['findings']}, 'trace': [], 'material_query_gaps': [],
            'coverage': {'source_index_complete': True}, 'stop_reason': 'decisive_policy_table', 'sources': store.snapshot(),
            'v10': {'policy_table': table_result, 'action_audit': {'status': 'NOT_RUN_TABLE_SHORT_CIRCUIT'},
                'variants': {'judge_shared_request': 'NOT_RUN', 'judge_plus_table': 'ERROR', 'judge_plus_audit': 'NOT_RUN', 'full': 'ERROR'},
                'comparison_scope': 'MISSING_JUDGE_COUNTERFACTUAL_ON_SHORT_CIRCUIT'}}
    captured = {}
    def decoder(current_store, vote):
        captured['vote'] = vote
        return decode_assessment(current_store, vote)
    context = {'source_registry': registry(store), 'native_target_calls': native_target_inventory(store),
        'policy_rules_for_current_move': prepared['applicable_rules'],
        'action_audit_inputs': input_context(store)}
    result = run(row, ask, source_store=store, policy_first=True, initial_context=context,
        contract_builder=lambda phase: id_contract(phase, checks_mode=options.get('checks_mode', 'diagnostic')),
        assessment_decoder=decoder, system_extension=instruction(), **options)
    vote = captured.get('vote', {})
    audited = evaluate_audit(store, vote.get('action_audit'), judge_findings=vote.get('findings', []),
        table_findings=table_result['findings'])
    if prepared['table'] and audited.get('target_acts'):
        mapping = {'REFUSE': 'REFUSE', 'TRANSFER': 'TRANSFER', 'ASK_CLARIFY': 'ASK_USER',
            'ASK_USER_ACTION': 'ASK_USER', 'ASK_CONFIRM': 'ASK_USER', 'ASSERT_DONE': 'ASSERT_DONE', 'ASSERT_FACT': 'ASSERT_FACT'}
        targets = [{'source_id': a['target_source_id'], 'act': mapping[a['act']], 'arguments': a['entity_arguments']}
            for a in audited['target_acts'] if a['act'] in mapping]
        speech = evaluate_table(store, prepared['table'], targets=targets)
        table_result = {**table_result, 'findings': table_result['findings'] + speech['findings'],
            'trace': table_result['trace'] + speech['trace']}
    variants = combine(result['decision'], table_result, audited)
    selected = 'full' if table_decisive and audit_decisive else 'judge_plus_table' if table_decisive else 'judge_plus_audit' if audit_decisive else 'judge_shared_request'
    judge_decision = result['decision']
    result['decision'] = variants[selected]
    if result['decision'] == 'ERROR' and judge_decision != 'ERROR':
        findings = ([f for f in table_result['findings'] if f.get('compile_agreement_status') == 'DECISIVE'] if table_decisive else [])
        findings += audited['findings'] if audit_decisive else []
        result['assessment'] = {**(result.get('assessment') or {}), 'findings': findings}
        result.update(decision_basis='error_only_added_layer', degraded=False)
    result['v10'] = {'policy_table': table_result, 'action_audit': audited, 'variants': variants,
        'judge_decision': judge_decision, 'selected_projection': selected,
        'comparison_scope': 'SAME_MODEL_REQUEST_WITH_RAW_POLICY_AND_AUDIT_SLOTS; NOT_A_CLEAN_A1_A2_COUNTERFACTUAL',
        'raw_policy_retained': True, 'online_policy_compilation': False}
    result['sources'] = store.snapshot()
    return result
